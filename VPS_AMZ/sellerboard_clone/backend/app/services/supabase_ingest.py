"""Module đồng bộ dữ liệu 2 giai đoạn qua tầng đệm Supabase (Data Buffer).

Pipeline:
  Giai đoạn 1 (Inbound Streaming) : Amazon SP-API -> FastAPI -> Supabase (raw_amazon_orders)
  Giai đoạn 2 (Processing)        : Supabase -> FastAPI -> SQLite local (sellervision.db)

Tách biệt 2 giai đoạn để loại bỏ luồng đồng bộ inline/blocking cũ — vốn giữ
toàn bộ dữ liệu trong RAM của Gunicorn worker trong lúc gọi HTTP tới Amazon,
gây OOM Killer sập worker và lỗi 504 Gateway Timeout.
"""
from __future__ import annotations

import gc
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Order, OrderItem, Product, User
from ..timeutils import now_utc
from .profit import calculate_cogs_fifo
from .supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

_RAW_ORDERS_TABLE = "raw_amazon_orders"
_PAGE_SIZE = 100


# ─────────────────────────────────────────────────────────────────────────────
# Helper: ánh xạ Seller ID -> Owner ID (User.id) — KHÔNG cho phép Fallback
# ─────────────────────────────────────────────────────────────────────────────

def get_owner_id_from_seller_id(db: Session, seller_id: str) -> int:
    """Xác thực và ánh xạ `seller_id` (định danh gian hàng Amazon) sang
    `User.id` nội bộ (owner_id).

    Thứ tự thử khớp:
      1) `seller_id` là số nguyên -> tra theo User.id (phục vụ môi trường test)
      2) `seller_id` khớp với User.email

    QUY TẮC BẢO MẬT TUYỆT ĐỐI (Strict Mapping):
    Nghiêm cấm Fallback về User đầu tiên trong DB khi không tìm thấy. Nếu
    không khớp -> log CRITICAL + ném ValueError để dừng tiến trình ngay lập
    tức, cách ly hoàn toàn dữ liệu tài chính giữa các Seller.
    """
    # 1) Thử khớp theo User.id (số nguyên) — phục vụ môi trường test
    try:
        candidate_id = int(seller_id)
    except (TypeError, ValueError):
        candidate_id = None

    if candidate_id is not None:
        user = db.scalar(select(User).where(User.id == candidate_id))
        if user is not None:
            return user.id

    # 2) Thử khớp theo User.email
    user = db.scalar(select(User).where(User.email == seller_id))
    if user is not None:
        return user.id

    # 3) KHÔNG TÌM THẤY -> nghiêm cấm Fallback, dừng tiến trình ngay lập tức
    logger.critical(
        "CRITICAL: Unmapped Seller ID '%s' — khong tim thay User tuong ung trong he "
        "thong. Tu choi Fallback ve User mac dinh de bao ve tinh cach ly du lieu tai "
        "chinh giua cac Seller. Dung tien trinh dong bo ngay lap tuc.", seller_id,
    )
    raise ValueError("CRITICAL: Unmapped Seller ID")


# ─────────────────────────────────────────────────────────────────────────────
# Giai đoạn 1: Thu thập dữ liệu thô — Amazon SP-API -> Supabase (raw_amazon_orders)
# ─────────────────────────────────────────────────────────────────────────────

def sync_orders_to_supabase_streaming(client, seller_id: str, created_after: str) -> dict:
    """Kéo đơn hàng từ Amazon SP-API (`/orders/v0/orders`) theo từng trang nhỏ
    (MaxResultsPerPage=100, đã khống chế sẵn trong `client.get_orders`), nhúng
    Order Items (`/orders/v0/orders/{id}/orderItems`) vào từng đơn để tạo
    payload tự chứa (self-contained JSONB), rồi Bulk Upsert lên bảng
    `raw_amazon_orders` của Supabase.

    Đây là giai đoạn DUY NHẤT gọi HTTP tới Amazon — giai đoạn xử lý nội bộ
    (sync_staging_to_db) sẽ không chạm mạng nữa.
    """
    supabase = get_supabase_client()
    result = {"pages": 0, "orders_fetched": 0, "orders_upserted": 0, "errors": []}

    next_token = None
    page = 0

    logger.info(
        "[Stage1][seller=%s] Bat dau thu thap Orders tu SP-API -> Supabase "
        "(created_after=%s, MaxResultsPerPage=%s)", seller_id, created_after, _PAGE_SIZE,
    )

    while True:
        page += 1
        try:
            resp = client.get_orders(created_after=created_after, next_token=next_token)
            payload = resp.get("payload", {})
            orders = payload.get("Orders", [])
            next_token = payload.get("NextToken")
        except Exception as exc:
            logger.error("[Stage1][seller=%s] Loi goi get_orders (trang %s): %s", seller_id, page, exc)
            result["errors"].append(f"get_orders page {page}: {exc}")
            break

        result["pages"] = page
        total_in_page = len(orders)
        logger.info(
            "[Stage1][seller=%s] Trang %s: nhan %s don hang tu Amazon (con NextToken: %s)",
            seller_id, page, total_in_page, bool(next_token),
        )

        upsert_rows = []
        for idx, order in enumerate(orders, start=1):
            amazon_order_id = order.get("AmazonOrderId")
            if not amazon_order_id:
                continue

            # ── Goi API phu lay chi tiet Order Items (chong nghen I/O) ──
            try:
                items_resp = client._request(
                    "GET", f"/orders/v0/orders/{amazon_order_id}/orderItems"
                ).json()
                items_data = items_resp.get("payload", {}).get("OrderItems", [])
            except Exception as exc:
                logger.error(
                    "[Stage1][seller=%s] Loi lay OrderItems cho don %s: %s",
                    seller_id, amazon_order_id, exc,
                )
                result["errors"].append(f"orderItems {amazon_order_id}: {exc}")
                items_data = []

            # Đóng gói: nhúng mảng Order Items vào chính đối tượng đơn hàng
            order["order_items"] = items_data
            upsert_rows.append({
                "seller_id": seller_id,
                "amazon_order_id": amazon_order_id,
                "order_status": order.get("OrderStatus"),
                "purchase_date": order.get("PurchaseDate"),
                "raw_json": order,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            result["orders_fetched"] += 1

            # Giãn cách 0.15s giữa các đơn — kiểm soát tần suất, chống lỗi 429
            time.sleep(0.15)

            pct = (idx / total_in_page * 100) if total_in_page else 100.0
            logger.info(
                "[Stage1][seller=%s] Trang %s — tien do %s/%s (%.1f%%): don %s da nhung %s order_items",
                seller_id, page, idx, total_in_page, pct, amazon_order_id, len(items_data),
            )

        # ── Bulk Upsert mang don hang tu chua (Self-contained JSONB) ──
        if upsert_rows:
            try:
                supabase.table(_RAW_ORDERS_TABLE) \
                    .upsert(upsert_rows, on_conflict="seller_id,amazon_order_id") \
                    .execute()
                result["orders_upserted"] += len(upsert_rows)
                logger.info(
                    "[Stage1][seller=%s] Upsert thanh cong %s don len Supabase.%s "
                    "(luy ke: %s)", seller_id, len(upsert_rows), _RAW_ORDERS_TABLE,
                    result["orders_upserted"],
                )
            except Exception as exc:
                logger.error(
                    "[Stage1][seller=%s] Loi Bulk Upsert Supabase (trang %s): %s",
                    seller_id, page, exc,
                )
                result["errors"].append(f"supabase upsert page {page}: {exc}")

        # ── QUAN LY RAM TOI THUONG: giai phong RAM cuoi moi trang ──
        del orders, payload, upsert_rows
        gc.collect()
        logger.info(
            "[Stage1][seller=%s] Da kich hoat gc.collect() — giai phong RAM sau trang %s",
            seller_id, page,
        )

        if not next_token:
            break

    logger.info(
        "[Stage1][seller=%s] HOAN TAT Giai doan 1: %s trang, %s don thu thap, "
        "%s don upsert, %s loi", seller_id, result["pages"], result["orders_fetched"],
        result["orders_upserted"], len(result["errors"]),
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Giai đoạn 2: Xử lý & đồng bộ nội bộ — Supabase -> SQLite local
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_purchase_date(raw_value: str | None) -> datetime:
    """Chuẩn hoá chuỗi `PurchaseDate` (vd '2024-05-01T12:34:56Z' hoặc có hậu tố
    múi giờ '+00:00') về dạng *naive* datetime UTC — tương thích với cột
    DateTime (không tzinfo) của SQLite, tránh lỗi so sánh aware/naive.
    """
    if not raw_value:
        return now_utc()

    s = raw_value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    dt = None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(raw_value, fmt)
                break
            except ValueError:
                continue

    if dt is None:
        return now_utc()

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _anonymize_buyer(buyer_email: str) -> str:
    import hashlib
    return hashlib.sha256(buyer_email.encode()).hexdigest()[:16]


def _apply_raw_order_to_sqlite(db: Session, owner_id: int, record: dict) -> tuple[str, int]:
    """Ánh xạ 1 bản ghi `raw_amazon_orders` -> Order/OrderItem/Product trong
    SQLite. Cập nhật OrderStatus nếu đơn đã tồn tại, chèn mới nếu chưa có.

    Hàm này được gọi BÊN TRONG một SAVEPOINT (`db.begin_nested()`) — nếu ném
    ngoại lệ, savepoint tự rollback riêng lẻ mà không ảnh hưởng các đơn khác.
    Trả về `("updated"|"created", số_product_mới_tạo)` để nơi gọi thống kê.
    """
    amazon_order_id = record["amazon_order_id"]
    raw_order = record.get("raw_json") or {}
    order_status = record.get("order_status") or raw_order.get("OrderStatus") or "Shipped"
    purchased_at = _normalize_purchase_date(record.get("purchase_date") or raw_order.get("PurchaseDate"))
    buyer_email = (raw_order.get("BuyerInfo") or {}).get("BuyerEmail", "")
    is_refunded = order_status in ("Canceled", "Cancelled")
    items_data = raw_order.get("order_items") or []

    existing = db.scalar(
        select(Order).where(Order.owner_id == owner_id, Order.external_id == amazon_order_id)
    )
    if existing is not None:
        existing.status = order_status.lower()
        existing.is_refunded = is_refunded
        existing.purchased_at = purchased_at
        return "updated", 0

    db_order = Order(
        owner_id=owner_id,
        external_id=amazon_order_id,
        marketplace="amazon",
        customer_ref=_anonymize_buyer(buyer_email) if buyer_email else "",
        purchased_at=purchased_at,
        status=order_status.lower(),
        is_refunded=is_refunded,
    )
    db.add(db_order)
    db.flush()

    products_created = 0
    for item in items_data:
        asin = item.get("ASIN", "")
        sku = item.get("SellerSKU") or asin
        title = (item.get("Title") or asin)[:512]
        qty = int(item.get("QuantityOrdered", 1) or 1)
        price_amount = float((item.get("ItemPrice") or {}).get("Amount", 0) or 0)
        shipping_amount = float((item.get("ShippingPrice") or {}).get("Amount", 0) or 0)
        unit_price = ((price_amount + shipping_amount) / qty) if qty else 0.0

        product = db.scalar(
            select(Product).where(Product.owner_id == owner_id, Product.asin == asin)
        )
        if product is None:
            product = Product(
                owner_id=owner_id, asin=asin, sku=sku, title=title,
                marketplace="amazon", price=unit_price,
            )
            db.add(product)
            db.flush()
            products_created += 1

        db.add(OrderItem(order_id=db_order.id, product_id=product.id, quantity=qty, unit_price=unit_price))

    return "created", products_created


def sync_staging_to_db(db: Session, seller_id: str) -> dict:
    """Đọc dữ liệu sạch từ Supabase (`raw_amazon_orders`) theo từng cụm nhỏ
    (limit/offset chunking, KHÔNG bao giờ load toàn bộ lên RAM) rồi ghi vào
    Supabase PostgreSQL (main DB) thông qua SQLAlchemy ORM.

    Xử lý biệt lập 100%: KHÔNG gọi thêm bất kỳ HTTP Request nào tới Amazon —
    triệt tiêu hoàn toàn rủi ro nghẽn I/O mạng ở giai đoạn này.
    """
    owner_id = get_owner_id_from_seller_id(db, seller_id)
    supabase = get_supabase_client()

    result = {
        "owner_id": owner_id, "pages": 0,
        "orders_processed": 0, "orders_created": 0, "orders_updated": 0,
        "orders_failed": 0, "products_created": 0, "errors": [],
    }

    try:
        count_resp = supabase.table(_RAW_ORDERS_TABLE) \
            .select("amazon_order_id", count="exact") \
            .eq("seller_id", seller_id) \
            .execute()
        total_records = count_resp.count or 0
    except Exception as exc:
        logger.error("[Stage2][seller=%s] Loi dem so ban ghi tren Supabase: %s", seller_id, exc)
        result["errors"].append(f"supabase count error: {exc}")
        total_records = 0

    logger.info(
        "[Stage2][seller=%s] Bat dau xu ly noi bo Supabase -> SQLite "
        "(owner_id=%s, tong uoc tinh=%s, limit/trang=%s)",
        seller_id, owner_id, total_records, _PAGE_SIZE,
    )

    offset = 0
    page = 0
    while True:
        page += 1
        try:
            resp = supabase.table(_RAW_ORDERS_TABLE) \
                .select("seller_id, amazon_order_id, order_status, purchase_date, raw_json") \
                .eq("seller_id", seller_id) \
                .order("purchase_date", desc=True) \
                .range(offset, offset + _PAGE_SIZE - 1) \
                .execute()
            records = resp.data or []
        except Exception as exc:
            logger.error("[Stage2][seller=%s] Loi keo du lieu Supabase (trang %s): %s", seller_id, page, exc)
            result["errors"].append(f"supabase fetch page {page}: {exc}")
            break

        if not records:
            break

        result["pages"] = page
        logger.info(
            "[Stage2][seller=%s] Trang %s: keo %s ban ghi tu Supabase (offset=%s)",
            seller_id, page, len(records), offset,
        )

        for record in records:
            amazon_order_id = record.get("amazon_order_id", "?")
            result["orders_processed"] += 1
            try:
                # SAVEPOINT: 1 don loi -> rollback rieng le, khong giet ca tien trinh
                with db.begin_nested():
                    outcome, new_products = _apply_raw_order_to_sqlite(db, owner_id, record)
                result["products_created"] += new_products
                if outcome == "created":
                    result["orders_created"] += 1
                else:
                    result["orders_updated"] += 1
            except Exception as exc:
                result["orders_failed"] += 1
                logger.error(
                    "[Stage2][seller=%s] SAVEPOINT ROLLBACK rieng le cho don %s: %s — bo qua, tiep tuc trang.",
                    seller_id, amazon_order_id, exc,
                )
                result["errors"].append(f"order {amazon_order_id}: {exc}")
                continue

            pct = (result["orders_processed"] / total_records * 100) if total_records else 100.0
            logger.info(
                "[Stage2][seller=%s] Tien do ghi nhan: %s/%s (%.1f%%) — don %s -> %s",
                seller_id, result["orders_processed"], total_records, pct, amazon_order_id, outcome,
            )

        db.commit()

        # ── QUAN LY RAM TIEP DIEN: giai phong RAM cuoi moi trang 100 ban ghi ──
        del records
        gc.collect()
        logger.info(
            "[Stage2][seller=%s] Da kich hoat gc.collect() — giai phong RAM sau trang %s",
            seller_id, page,
        )

        offset += _PAGE_SIZE

    logger.info(
        "[Stage2][seller=%s] HOAN TAT Giai doan 2: %s don da duyet, %s tao moi, "
        "%s cap nhat, %s loi/bo qua", seller_id, result["orders_processed"],
        result["orders_created"], result["orders_updated"], result["orders_failed"],
    )

    # ── KICH HOAT TINH TOAN TAI CHINH: chi goi 1 LAN sau khi toan bo trang da commit ──
    try:
        cogs_summary = calculate_cogs_fifo(db, owner_id)
        result["cogs_fifo"] = cogs_summary
        logger.info(
            "[Stage2][seller=%s] Da khoi chay calculate_cogs_fifo cho owner_id=%s: %s",
            seller_id, owner_id, cogs_summary,
        )
    except Exception as exc:
        logger.error(
            "[Stage2][seller=%s] Loi khi tinh COGS (FIFO) / P&L cho owner_id=%s: %s",
            seller_id, owner_id, exc,
        )
        result["errors"].append(f"calculate_cogs_fifo: {exc}")

    return result
