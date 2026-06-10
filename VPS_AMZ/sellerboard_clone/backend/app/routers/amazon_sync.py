"""Sync SP-API orders (qua tầng đệm Supabase) + FBA inventory -> SQLite, Ads API campaigns."""
import logging, threading, time
from datetime import datetime, timedelta, timezone

from ..timeutils import now_marketplace, MARKETPLACE_TZ
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import Order, Product, User
from ..services import sync_state
from ..services.amazon_spapi_client import get_spapi_client
from ..services.settlement_sync import sync_settlement_reports
from ..services.supabase_ingest import (
    get_owner_id_from_seller_id,
    sync_orders_to_supabase_streaming,
    sync_staging_to_db,
)

router = APIRouter(prefix="/api/amazon", tags=["amazon"])
logger = logging.getLogger(__name__)


def _do_sync(db_session: Session, client, seller_id: str, days: int, on_progress=None) -> dict:
    """Điều phối luồng đồng bộ Orders theo mô hình Pipeline 2 giai đoạn qua
    tầng đệm Supabase, sau đó đồng bộ tồn kho FBA độc lập:

      Giai đoạn 1: Amazon SP-API -> Supabase (raw_amazon_orders)   [sync_orders_to_supabase_streaming]
      Giai đoạn 2: Supabase -> Supabase ORM (main DB) + COGS/P&L   [sync_staging_to_db]
      Giai đoạn 3: Settlement Reports -> SettlementEntry + AggregatedDaily
      Giai đoạn 4: FBA Inventory (độc lập, giữ nguyên luồng cũ)
    """
    result = {"orders_synced": 0, "products_created": 0, "inventory_updated": 0, "errors": []}
    created_after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Giai đoạn 1: Inbound Streaming — Amazon SP-API -> Supabase ──
    if on_progress:
        sync_state.write_progress({
            "seller_id": seller_id, "days": days, "status": "ingesting",
            "processed": 0, "total": 0,
            "message": f"Dang thu thap Orders tu Amazon SP-API (created_after={created_after})",
        })
    try:
        stage1 = sync_orders_to_supabase_streaming(client, seller_id, created_after)
        result["errors"].extend(stage1.get("errors", []))
    except Exception as e:
        logger.error("[_do_sync][seller=%s] Loi Giai doan 1 (Inbound Streaming): %s", seller_id, e)
        result["errors"].append(f"stage1 sync_orders_to_supabase_streaming: {e}")

    # ── Giai đoạn 2: Processing — Supabase -> SQLite local + COGS/P&L ──
    try:
        stage2 = sync_staging_to_db(db_session, seller_id)
        result["orders_synced"] = stage2.get("orders_created", 0) + stage2.get("orders_updated", 0)
        result["products_created"] += stage2.get("products_created", 0)
        result["errors"].extend(stage2.get("errors", []))
        if on_progress:
            on_progress(stage2.get("orders_processed", 0), stage2.get("orders_processed", 0))
    except Exception as e:
        logger.error("[_do_sync][seller=%s] Loi Giai doan 2 (Processing): %s", seller_id, e)
        result["errors"].append(f"stage2 sync_staging_to_db: {e}")

    # ── Giai đoạn 3: Settlement Reports — phí Amazon thật → AggregatedDaily ──
    try:
        owner_id_for_settle = get_owner_id_from_seller_id(db_session, seller_id)
        stage3 = sync_settlement_reports(db_session, client, owner_id_for_settle)
        result["errors"].extend(stage3.get("errors", []))
        logger.info(
            "[_do_sync][seller=%s] Settlement: %d entries, %d daily rows",
            seller_id, stage3.get("entries_saved", 0), stage3.get("daily_rows", 0),
        )
    except Exception as e:
        logger.error("[_do_sync][seller=%s] Loi Giai doan 3 (Settlement): %s", seller_id, e)
        result["errors"].append(f"stage3 settlement: {e}")

    # ── Giai đoạn 4: FBA Inventory — luồng độc lập, giữ nguyên ──
    try:
        owner_id = get_owner_id_from_seller_id(db_session, seller_id)
        inv = client.get_inventory()  # noqa: reuse owner_id from stage 3 when available
        for item in inv.get("payload", {}).get("inventorySummaries", []):
            asin = item.get("asin", "")
            qty  = item.get("totalQuantity", 0)
            fn   = item.get("productName", "")
            p = db_session.scalar(select(Product).where(
                Product.owner_id == owner_id, Product.asin == asin))
            if p:
                p.current_stock = qty
                if fn and not p.title:
                    p.title = fn[:512]
            elif asin:
                db_session.add(Product(owner_id=owner_id, asin=asin, sku=asin,
                                       title=(fn or asin)[:512], current_stock=qty))
                result["products_created"] += 1
            result["inventory_updated"] += 1
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error("[_do_sync][seller=%s] Loi Giai doan 3 (FBA Inventory): %s", seller_id, e)
        result["errors"].append(f"inventory: {e}")

    return result


# ── Chay sync nen: tranh request HTTP phai cho het tien trinh (gay 504 Gateway Timeout) ──

def _sync_job_runner(seller_id: str, days: int):
    """Chay trong thread rieng: tu mo session DB + client SP-API, ghi tien do ra file
    de moi worker doc duoc, luon nha lock khi xong (du thanh cong hay loi)."""
    db = SessionLocal()
    started_at = datetime.now(timezone.utc).isoformat()
    base = {"seller_id": seller_id, "days": days, "started_at": started_at}
    try:
        sync_state.write_progress({**base, "status": "running", "processed": 0, "total": 0})

        def _on_progress(processed, total):
            sync_state.write_progress({**base, "status": "running", "processed": processed, "total": total})

        client = get_spapi_client()
        result = _do_sync(db, client, seller_id, days, on_progress=_on_progress)
        sync_state.write_progress({
            **base, "status": "done",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            **result,
        })
    except Exception as e:
        logger.error("[_sync_job_runner][seller=%s] Job nen that bai: %s", seller_id, e)
        sync_state.write_progress({
            **base, "status": "error",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "errors": [str(e)],
        })
    finally:
        db.close()
        sync_state.release_lock()


def _try_start_sync(seller_id: str, days: int) -> bool:
    """True neu vua khoi dong job nen moi; False neu da co job khac dang chay (lock dang giu)."""
    if not sync_state.acquire_lock():
        return False
    threading.Thread(target=_sync_job_runner, args=(seller_id, days), daemon=True).start()
    return True


def _next_scheduled_run(now: datetime, schedule_hours: list[int]) -> datetime:
    """Tính thời điểm chạy tiếp theo dựa trên danh sách giờ cố định trong ngày
    (naive datetime, cùng timezone với `now` — marketplace TZ).

    Ví dụ: now=02:30, hours=[1,7,13,19] -> target=07:00 hôm nay.
            now=20:00, hours=[1,7,13,19] -> target=01:00 ngày mai.
    """
    for h in sorted(schedule_hours):
        candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if candidate > now:
            return candidate
    # Tất cả giờ hôm nay đã qua -> giờ đầu tiên của ngày mai
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=min(schedule_hours), minute=0, second=0, microsecond=0)


def start_auto_sync_thread():
    """Vòng lặp nền chạy sync theo lịch giờ cố định trong ngày (cron-style), tính
    theo giờ của marketplace (Pacific Time cho Amazon US).

    Mặc định: 01:00, 07:00, 13:00, 19:00 (cách nhau 6 tiếng).
    Cấu hình qua: AMAZON_AUTO_SYNC_SCHEDULE_HOURS=1,7,13,19 trong .env.

    File-lock atomic đảm bảo chỉ 1 Gunicorn worker thực sự chạy job mỗi lần,
    dù nhiều worker cùng khởi động thread này khi app start.
    """
    schedule_hours = settings.AMAZON_AUTO_SYNC_SCHEDULE_HOURS or [1, 7, 13, 19]

    def _loop():
        while True:
            try:
                now = now_marketplace()
                target = _next_scheduled_run(now, schedule_hours)
                wait_secs = (target - now).total_seconds()

                logger.info(
                    "[AutoSync] Lich dong bo tiep theo: %s (gio %s) — con %.0f phut (%.1f gio)",
                    target.strftime("%Y-%m-%d %H:%M"),
                    MARKETPLACE_TZ.key,
                    wait_secs / 60,
                    wait_secs / 3600,
                )

                # Ngủ từng đoạn 60s — tránh drift khi hệ thống bị tạm treo hoặc
                # đồng hồ hệ thống bị điều chỉnh (NTP leap second, DST change).
                while now_marketplace() < target:
                    remaining = (target - now_marketplace()).total_seconds()
                    time.sleep(min(60.0, max(1.0, remaining)))

                # Bỏ qua nếu job khác đang giữ lock (worker khác đã đi trước)
                if sync_state.read_progress().get("status") == "running":
                    logger.info(
                        "[AutoSync] Bo qua lich %s — job sync dang chay o worker khac.",
                        target.strftime("%H:%M"),
                    )
                    # Chờ job kia xong rồi tính lại lịch tiếp
                    while sync_state.read_progress().get("status") == "running":
                        time.sleep(10)
                    time.sleep(120)
                    continue

                # Kích hoạt sync tuần tự cho từng User active
                db = SessionLocal()
                try:
                    owners = db.scalars(select(User).where(User.is_active == True)).all()
                finally:
                    db.close()

                for u in owners:
                    logger.info("[AutoSync] Khoi dong sync cho seller: %s", u.email)
                    if not _try_start_sync(u.email, settings.AMAZON_AUTO_SYNC_DAYS):
                        logger.warning(
                            "[AutoSync] Khong the lay lock cho %s — bo qua, sang User tiep theo.", u.email
                        )
                        continue
                    # Chờ job hoàn thành trước khi sang User tiếp theo
                    while sync_state.read_progress().get("status") == "running":
                        time.sleep(5)

                # Buffer 2 phút sau khi sync xong — tránh trigger lại trong cùng 1 giờ
                time.sleep(120)

            except Exception as exc:
                logger.error("[AutoSync] Loi bat ngo trong vong lap lich: %s", exc)
                time.sleep(60)

    threading.Thread(target=_loop, daemon=True).start()


@router.post("/sync")
def sync_amazon(days: int = 7, current: User = Depends(get_current_user)):
    if not settings.AMAZON_SPI_CLIENT_ID:
        raise HTTPException(503, "SP-API chua duoc cau hinh")
    started = _try_start_sync(current.email, days)
    return {"ok": True, "status": "started" if started else "already_running", **sync_state.read_progress()}


@router.get("/sync/progress")
def sync_progress(current: User = Depends(get_current_user)):
    return sync_state.read_progress()


@router.get("/sync/status")
def sync_status(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    orders  = db.scalar(select(func.count()).select_from(Order).where(Order.owner_id == current.id))
    products = db.scalar(select(func.count()).select_from(Product).where(Product.owner_id == current.id))
    return {
        "orders_in_db": orders,
        "products_in_db": products,
        "ads_api": bool(settings.AMAZON_ADS_CLIENT_ID),
        "spapi": bool(settings.AMAZON_SPI_CLIENT_ID),
    }
