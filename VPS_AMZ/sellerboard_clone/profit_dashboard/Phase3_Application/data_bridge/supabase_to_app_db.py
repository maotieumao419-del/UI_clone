"""Phase 3 / data_bridge — Đồng bộ Supabase (NEW_*) -> SQLite của Web App.

Tầng INTERNAL của pipeline: đọc dữ liệu đã nằm sẵn trên bảng đệm Supabase
(KHÔNG chạm mạng Amazon), ghi vào cơ sở dữ liệu hiển thị của Web Application
(sellervision.db: users / products / orders / order_items).

Kỷ luật an toàn:
  - Đọc theo cụm .range(offset, offset + 99) — 100 dòng/lần, không nạp cả bảng.
  - Mỗi ĐƠN HÀNG bọc trong db.begin_nested() (Savepoint): 1 đơn lỗi chỉ
    rollback riêng đơn đó, luồng tổng không chết.
  - Strict Mapping seller -> User: không khớp -> raise ValueError, TUYỆT ĐỐI
    không fallback về user mặc định (cách ly dữ liệu tài chính giữa các seller).
  - Sau mỗi cụm: del + gc.collect(). Kết thúc toàn bộ mới gọi
    calculate_cogs_fifo() đúng 1 lần.

Chạy (trên VPS, từ thư mục gốc sellerboard_clone):
    python Phase3_Application/data_bridge/supabase_to_app_db.py --seller <email|user_id>
    python Phase3_Application/data_bridge/supabase_to_app_db.py --seller 1 --days 30
"""
import argparse
import gc
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent             # .../Phase3_Application/data_bridge
_ROOT = _THIS_DIR.parents[1]                            # .../sellerboard_clone
_BACKEND = _ROOT / "backend"
for p in (str(_BACKEND), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger(__name__)

T_ORDERS = "Profit_Phase1_sp_orders"
T_ITEMS  = "Profit_Phase1_sp_order_items"
T_SUMMARY = "Profit_Phase2_summary_products"
T_SUMMARY_ITEMS = "Profit_Phase2_summary_order_items"
PAGE = 100


def _get_supabase():
    try:
        from app.services.supabase_client import get_supabase_client
        return get_supabase_client()
    except Exception:                                    # noqa: BLE001 — fallback .env
        import os
        from dotenv import load_dotenv
        load_dotenv(_BACKEND / ".env")
        load_dotenv(_THIS_DIR / ".env")
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            raise ValueError("Thiếu SUPABASE_URL / SUPABASE_SERVICE_KEY")
        from supabase import create_client
        return create_client(url, key)


def get_owner_id(db, seller_id: str) -> int:
    """Strict Mapping: seller_id -> User.id (thử int id rồi email).
    Không khớp -> ValueError, KHÔNG fallback."""
    from sqlalchemy import select
    from app.models import User
    try:
        candidate = int(seller_id)
    except (TypeError, ValueError):
        candidate = None
    if candidate is not None:
        user = db.scalar(select(User).where(User.id == candidate))
        if user is not None:
            return user.id
    user = db.scalar(select(User).where(User.email == seller_id))
    if user is not None:
        return user.id
    logger.critical("CRITICAL: Unmapped Seller ID '%s' — từ chối fallback, dừng đồng bộ.",
                    seller_id)
    raise ValueError("CRITICAL: Unmapped Seller ID")


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _get_or_create_product(db, owner_id: int, asin: str, sku: str,
                           title: str, price: float):
    from sqlalchemy import select
    from app.models import Product
    product = db.scalar(select(Product).where(
        Product.owner_id == owner_id, Product.sku == sku, Product.asin == asin))
    if product is None:
        product = Product(owner_id=owner_id, asin=asin, sku=sku,
                          title=(title or "")[:512], price=price)
        db.add(product)
        db.flush()
    return product


def sync_orders(db, sb, owner_id: int, since_utc: datetime) -> dict:
    """Supabase Profit_Phase1_sp_orders/Profit_Phase1_sp_order_items -> SQLite Order/OrderItem/Product.
    Mỗi đơn 1 Savepoint; mỗi cụm 100 đơn commit 1 lần + giải phóng RAM."""
    from sqlalchemy import select
    from app.models import Order, OrderItem

    stats = {"orders": 0, "items": 0, "skipped": 0, "errors": 0}
    offset = 0
    while True:
        resp = (sb.table(T_ORDERS)
                .select("order_id,purchase_date,order_status")
                .gte("purchase_date", since_utc.isoformat() + "Z")
                .not_.in_("order_status", ["Canceled", "Cancelled"])
                .order("purchase_date")
                .range(offset, offset + PAGE - 1).execute())
        orders_page = resp.data or []
        if not orders_page:
            break

        order_ids = [o["order_id"] for o in orders_page if o.get("order_id")]
        items_by_order: dict[str, list] = {}
        i_resp = (sb.table(T_ITEMS)
                  .select("order_id,asin,sku,title,quantity_ordered,unit_price,"
                          "item_price,promotion_discount")
                  .in_("order_id", order_ids).execute())
        for it in i_resp.data or []:
            items_by_order.setdefault(it["order_id"], []).append(it)

        for o in orders_page:
            oid = o.get("order_id") or ""
            purchased = _parse_dt(o.get("purchase_date"))
            if not oid or purchased is None:
                stats["skipped"] += 1
                continue
            try:
                with db.begin_nested():               # Savepoint: lỗi 1 đơn không chết luồng
                    existing = db.scalar(select(Order).where(
                        Order.owner_id == owner_id, Order.external_id == oid))
                    if existing is not None:
                        db.query(OrderItem).filter(OrderItem.order_id == existing.id).delete()
                        order = existing
                        order.purchased_at = purchased
                        order.status = "shipped"
                    else:
                        order = Order(owner_id=owner_id, external_id=oid,
                                      purchased_at=purchased, status="shipped")
                        db.add(order)
                        db.flush()
                    promo_total = 0.0
                    for it in items_by_order.get(oid, []):
                        qty = int(it.get("quantity_ordered") or 0)
                        unit_price = float(it.get("unit_price") or 0)
                        promo_total += abs(float(it.get("promotion_discount") or 0))
                        product = _get_or_create_product(
                            db, owner_id, it.get("asin") or "", it.get("sku") or "",
                            it.get("title") or "", unit_price)
                        db.add(OrderItem(order_id=order.id, product_id=product.id,
                                         quantity=qty, unit_price=unit_price))
                        stats["items"] += 1
                    order.promo_discount = round(promo_total, 2)
                stats["orders"] += 1
            except Exception as exc:                  # noqa: BLE001 — savepoint đã rollback
                stats["errors"] += 1
                logger.warning("[Bridge] Lỗi đơn %s: %s — rollback riêng đơn này.", oid, exc)

        db.commit()
        print(f"  [Bridge] offset {offset}: +{len(orders_page)} đơn "
              f"(tổng {stats['orders']} OK / {stats['errors']} lỗi)")
        offset += PAGE
        del orders_page, items_by_order
        gc.collect()
    return stats


def sync_summary_products(db, sb, owner_id: int, since_utc: datetime) -> dict:
    """Supabase Profit_Phase2_summary_products -> SQLite Profit_Phase2_summary_products.
    Sử dụng ON CONFLICT (owner_id, period_start, period_end, asin, sku) DO UPDATE SET."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from app.models import SummaryProduct
    from app.database import Base
    
    # Đảm bảo bảng tồn tại ở SQLite
    Base.metadata.create_all(bind=db.bind)

    stats = {"inserted_or_updated": 0, "skipped": 0, "errors": 0}
    offset = 0
    
    # Lấy các cột cần update khi có conflict
    cols_to_update = [
        c.name for c in SummaryProduct.__table__.columns 
        if c.name not in ('owner_id', 'period_start', 'period_end', 'asin', 'sku')
    ]

    since_date_str = since_utc.date().isoformat()
    
    while True:
        resp = (sb.table(T_SUMMARY)
                .select("*")
                .eq("owner_id", owner_id)
                .gte("period_start", since_date_str)
                .order("period_start")
                .range(offset, offset + PAGE - 1).execute())
        
        rows = resp.data or []
        if not rows:
            break

        try:
            with db.begin_nested():
                for row in rows:
                    p_start = date.fromisoformat(row["period_start"])
                    p_end = date.fromisoformat(row["period_end"])
                    
                    row_dict = {
                        "owner_id": owner_id,
                        "period_start": p_start,
                        "period_end": p_end,
                        "product": row.get("product"),
                        "asin": row.get("asin") or "",
                        "sku": row.get("sku") or "",
                        "units": row.get("units") or 0,
                        "refunds": row.get("refunds") or 0,
                        "sales": row.get("sales") or 0.0,
                        "promo": row.get("promo") or 0.0,
                        "ads": row.get("ads") or 0.0,
                        "sponsored_products": row.get("sponsored_products") or 0.0,
                        "sponsored_display": row.get("sponsored_display") or 0.0,
                        "sponsored_brands": row.get("sponsored_brands") or 0.0,
                        "sponsored_brands_video": row.get("sponsored_brands_video") or 0.0,
                        "google_ads": row.get("google_ads") or 0.0,
                        "facebook_ads": row.get("facebook_ads") or 0.0,
                        "refunds_pct": row.get("refunds_pct"),
                        "sellable_quota": row.get("sellable_quota"),
                        "refund_cost": row.get("refund_cost") or 0.0,
                        "amazon_fees": row.get("amazon_fees") or 0.0,
                        "cost_of_goods": row.get("cost_of_goods") or 0.0,
                        "shipping": row.get("shipping") or 0.0,
                        "gross_profit": row.get("gross_profit") or 0.0,
                        "net_profit": row.get("net_profit") or 0.0,
                        "estimated_payout": row.get("estimated_payout") or 0.0,
                        "expenses": row.get("expenses") or 0.0,
                        "margin": row.get("margin"),
                        "roi": row.get("roi"),
                        "bsr": row.get("bsr"),
                        "real_acos": row.get("real_acos"),
                        "sessions": row.get("sessions"),
                        "unit_session_pct": row.get("unit_session_pct"),
                        "average_sales_price": row.get("average_sales_price") or 0.0,
                        "fee_state": row.get("fee_state") or 'NONE',
                        "updated_at": _parse_dt(row.get("updated_at")) or datetime.utcnow()
                    }
                    
                    stmt = sqlite_insert(SummaryProduct).values(row_dict)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['owner_id', 'period_start', 'period_end', 'asin', 'sku'],
                        set_={col: stmt.excluded[col] for col in cols_to_update}
                    )
                    db.execute(stmt)
                    stats["inserted_or_updated"] += 1
            db.commit()
            print(f"  [Bridge] Summary products offset {offset}: +{len(rows)} rows OK")
        except Exception as exc:
            stats["errors"] += 1
            db.rollback()
            logger.warning("[Bridge] Lỗi trang summary products offset %s: %s — rollback.", offset, exc)
            
        offset += PAGE
        del rows
        gc.collect()

    return stats


def sync_summary_order_items(db, sb, owner_id: int, since_utc: datetime) -> dict:
    """Supabase Profit_Phase2_summary_order_items -> SQLite Profit_Phase2_summary_order_items.
    Sử dụng ON CONFLICT (owner_id, order_number, sku, asin, row_type) DO UPDATE SET."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from app.models import SummaryOrderItem
    from app.database import Base

    # Đảm bảo bảng tồn tại ở SQLite
    Base.metadata.create_all(bind=db.bind)

    stats = {"inserted_or_updated": 0, "skipped": 0, "errors": 0}
    offset = 0

    cols_to_update = [
        c.name for c in SummaryOrderItem.__table__.columns
        if c.name not in ('owner_id', 'order_number', 'sku', 'asin', 'row_type')
    ]

    since_date_str = since_utc.date().isoformat()

    while True:
        resp = (sb.table(T_SUMMARY_ITEMS)
                .select("*")
                .eq("owner_id", owner_id)
                .gte("order_date", since_date_str)
                .order("order_date")
                .range(offset, offset + PAGE - 1).execute())

        rows = resp.data or []
        if not rows:
            break

        try:
            with db.begin_nested():
                for row in rows:
                    order_date = date.fromisoformat(row["order_date"])

                    row_dict = {
                        "owner_id": owner_id,
                        "order_number": row.get("order_number") or "",
                        "sku": row.get("sku") or "",
                        "asin": row.get("asin") or "",
                        "row_type": row.get("row_type") or "normal",
                        "order_date": order_date,
                        "product": row.get("product"),
                        "units": row.get("units") or 0,
                        "refunds": row.get("refunds") or 0,
                        "sales": row.get("sales") or 0.0,
                        "promo": row.get("promo") or 0.0,
                        "sellable_quota": row.get("sellable_quota"),
                        "refund_cost": row.get("refund_cost") or 0.0,
                        "amazon_fees": row.get("amazon_fees") or 0.0,
                        "cost_of_goods": row.get("cost_of_goods") or 0.0,
                        "shipping": row.get("shipping") or 0.0,
                        "gross_profit": row.get("gross_profit") or 0.0,
                        "expenses": row.get("expenses") or 0.0,
                        "net_profit": row.get("net_profit") or 0.0,
                        "margin": row.get("margin"),
                        "roi": row.get("roi"),
                        "coupon": row.get("coupon") or 0.0,
                        "order_status": row.get("order_status") or "",
                        "price_source": row.get("price_source") or "ACTUAL",
                        "fee_state": row.get("fee_state") or "NONE",
                    }

                    stmt = sqlite_insert(SummaryOrderItem).values(row_dict)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['owner_id', 'order_number', 'sku', 'asin', 'row_type'],
                        set_={col: stmt.excluded[col] for col in cols_to_update}
                    )
                    db.execute(stmt)
                    stats["inserted_or_updated"] += 1
            db.commit()
            print(f"  [Bridge] Summary order items offset {offset}: +{len(rows)} rows OK")
        except Exception as exc:
            stats["errors"] += 1
            db.rollback()
            logger.warning("[Bridge] Lỗi trang summary order items offset %s: %s — rollback.", offset, exc)

        offset += PAGE
        del rows
        gc.collect()

    return stats



def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="data_bridge: Supabase NEW_* -> SQLite app")
    ap.add_argument("--seller", required=True,
                    help="Seller ID: User.id (số) hoặc User.email trong sellervision.db")
    ap.add_argument("--days", type=int, default=30, help="Đồng bộ N ngày gần nhất (mặc định 30)")
    args = ap.parse_args()

    from app.database import SessionLocal, Base
    from sqlalchemy import select
    from app.models import User
    
    sb = _get_supabase()
    db = SessionLocal()
    try:
        # Ensure tables exist
        Base.metadata.create_all(bind=db.bind)
        
        # Seed demo user if no users exist
        if db.scalar(select(User).limit(1)) is None:
            from app.core.security import hash_password
            demo_user = User(
                id=1,
                email="demo@sellervision.io",
                full_name="Người bán Demo",
                hashed_password=hash_password("demo1234"),
                consent={"analytics": True, "marketing": False, "data_sharing": False},
            )
            db.add(demo_user)
            db.commit()
            print("[Bridge] Empty database detected. Seeded demo user 'demo@sellervision.io' with ID 1.")
            
        owner_id = get_owner_id(db, args.seller)      # Strict Mapping — lỗi là dừng
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=args.days)
        print(f"[Bridge] Seller '{args.seller}' -> owner_id={owner_id}; từ {since:%Y-%m-%d}")
        print(f"[Bridge] Bắt đầu đồng bộ Order...")
        order_stats = sync_orders(db, sb, owner_id, since)
        print(f"[Bridge] Đồng bộ Order hoàn tất: {order_stats}")

        print(f"[Bridge] Bắt đầu đồng bộ Profit_Phase2_summary_products...")
        summary_stats = sync_summary_products(db, sb, owner_id, since)
        print(f"[Bridge] Đồng bộ Profit_Phase2_summary_products hoàn tất: {summary_stats}")

        print(f"[Bridge] Bắt đầu đồng bộ Profit_Phase2_summary_order_items...")
        summary_items_stats = sync_summary_order_items(db, sb, owner_id, since)
        print(f"[Bridge] Đồng bộ Profit_Phase2_summary_order_items hoàn tất: {summary_items_stats}")

        # Tính COGS FIFO đúng 1 lần SAU khi commit xong toàn bộ
        try:
            from app.services.profit import calculate_cogs_fifo
            summary = calculate_cogs_fifo(db, owner_id)
            print(f"[Bridge] COGS FIFO: {summary.get('products_costed', '?')} sản phẩm đã tính giá vốn.")
        except Exception as exc:                      # noqa: BLE001
            logger.warning("[Bridge] calculate_cogs_fifo lỗi (không chặn): %s", exc)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:                              # noqa: BLE001
            pass
    sys.exit(main())
