"""Settlement Report sync — Phase 1 data pipeline.

Luồng:
  1. Yêu cầu Amazon tạo GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE
  2. Poll đến khi DONE (tối đa MAX_POLL_MINUTES phút)
  3. Tải TSV về, parse từng dòng → SettlementEntry
  4. Upsert vào DB (idempotent theo settlement_id + dòng)
  5. Tính lại AggregatedDaily cho các ngày bị ảnh hưởng

Tại sao cần Settlement Report thay vì ước tính phí?
  - Phí FBA, referral fee, storage fee thay đổi thường xuyên theo size/weight.
  - Settlement Report là nguồn chân lý duy nhất Amazon công nhận cho thanh toán.
  - Không có nó, PnL sẽ lệch 10-30% so với thực tế.
"""
import csv
import io
import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from ..models import AggregatedDaily, Order, OrderItem, SettlementEntry, User

logger = logging.getLogger(__name__)

MAX_POLL_MINUTES = 15
POLL_INTERVAL_SECONDS = 30

# Cột TSV của GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE
_COL_SETTLEMENT_ID   = "settlement-id"
_COL_TXN_TYPE        = "transaction-type"
_COL_ORDER_ID        = "order-id"
_COL_SKU             = "sku"
_COL_QTY             = "quantity-purchased"
_COL_POSTED_DATE     = "posted-date"
_COL_SHIP_FEE_TYPE   = "shipment-fee-type"
_COL_SHIP_FEE_AMT    = "shipment-fee-amount"
_COL_ORDER_FEE_TYPE  = "order-fee-type"
_COL_ORDER_FEE_AMT   = "order-fee-amount"
_COL_ITEM_FEE_TYPE   = "item-related-fee-type"
_COL_ITEM_FEE_AMT    = "item-related-fee-amount"
_COL_PRICE_TYPE      = "price-type"
_COL_PRICE_AMT       = "price-amount"
_COL_OTHER_AMT       = "other-amount"
_COL_MISC_AMT        = "misc-fee-amount"


def _safe_float(val: str) -> float:
    try:
        return float(str(val).strip().replace(",", "")) if val and val.strip() else 0.0
    except ValueError:
        return 0.0


def _safe_int(val: str) -> int:
    try:
        return int(str(val).strip()) if val and val.strip() else 0
    except ValueError:
        return 0


def _parse_date(val: str) -> datetime:
    val = (val or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(val, fmt)
            return dt.replace(tzinfo=None)  # lưu naive UTC
        except ValueError:
            continue
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_tsv_to_entries(owner_id: int, tsv_text: str) -> list[dict]:
    """Parse nội dung TSV thành list dict để insert vào SettlementEntry."""
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    entries = []

    for row in reader:
        settlement_id = row.get(_COL_SETTLEMENT_ID, "").strip()
        if not settlement_id:
            continue

        order_id     = row.get(_COL_ORDER_ID, "").strip()
        txn_type     = row.get(_COL_TXN_TYPE, "").strip()
        sku          = row.get(_COL_SKU, "").strip()
        qty          = _safe_int(row.get(_COL_QTY, "0"))
        posted_date  = _parse_date(row.get(_COL_POSTED_DATE, ""))

        # Mỗi dòng TSV có thể chứa nhiều loại phí — tách thành entry riêng
        fee_pairs = [
            (row.get(_COL_SHIP_FEE_TYPE, ""),  row.get(_COL_SHIP_FEE_AMT, "0"),  "ItemFees"),
            (row.get(_COL_ORDER_FEE_TYPE, ""), row.get(_COL_ORDER_FEE_AMT, "0"), "ItemFees"),
            (row.get(_COL_ITEM_FEE_TYPE, ""),  row.get(_COL_ITEM_FEE_AMT, "0"),  "ItemFees"),
            (row.get(_COL_PRICE_TYPE, ""),     row.get(_COL_PRICE_AMT, "0"),     "ItemPrice"),
        ]
        # Other/misc fees gộp chung
        other = _safe_float(row.get(_COL_OTHER_AMT, "0")) + _safe_float(row.get(_COL_MISC_AMT, "0"))
        if other:
            fee_pairs.append(("OtherFee", str(other), "ItemFees"))

        for desc, amt_str, amt_type in fee_pairs:
            amt = _safe_float(amt_str)
            if not desc and not amt:
                continue
            entries.append({
                "owner_id":           owner_id,
                "settlement_id":      settlement_id,
                "order_id":           order_id,
                "transaction_type":   txn_type,
                "amount_type":        amt_type,
                "amount_description": desc,
                "amount":             amt,
                "posted_date":        posted_date,
                "sku":                sku,
                "quantity":           qty,
            })

    return entries


def _upsert_entries(db: Session, owner_id: int, entries: list[dict]) -> int:
    """Xóa entries cũ theo settlement_id rồi insert lại — idempotent."""
    if not entries:
        return 0

    settlement_ids = {e["settlement_id"] for e in entries}
    for sid in settlement_ids:
        db.execute(
            delete(SettlementEntry).where(
                SettlementEntry.owner_id == owner_id,
                SettlementEntry.settlement_id == sid,
            )
        )

    for e in entries:
        db.add(SettlementEntry(**e))

    return len(entries)


def _rebuild_aggregated_daily(db: Session, owner_id: int) -> int:
    """Tính lại toàn bộ AggregatedDaily cho owner từ Orders + SettlementEntry.

    Chiến lược: xóa và tính lại (đơn giản, chính xác; chấp nhận được vì chạy
    sau sync chứ không phải mỗi request). Với dữ liệu lớn hơn có thể tối ưu
    thêm bằng cách chỉ rebuild các ngày bị ảnh hưởng.
    """
    # Xóa toàn bộ aggregated_daily của owner này
    db.execute(delete(AggregatedDaily).where(AggregatedDaily.owner_id == owner_id))

    # Lấy tất cả orders có items
    orders = db.scalars(
        select(Order).where(Order.owner_id == owner_id)
    ).all()

    daily: dict[str, dict] = {}  # key = "YYYY-MM-DD"

    for o in orders:
        day_key = o.purchased_at.strftime("%Y-%m-%d") if o.purchased_at else None
        if not day_key:
            continue
        if day_key not in daily:
            daily[day_key] = {
                "gross_revenue": 0.0, "units_sold": 0, "orders_count": 0,
                "refunds_amount": 0.0, "refunds_count": 0,
                "cogs": 0.0, "ppc_cost": 0.0,
            }
        d = daily[day_key]
        if o.is_refunded:
            d["refunds_count"] += 1
            for item in o.items:
                d["refunds_amount"] += item.unit_price * item.quantity
        else:
            d["orders_count"] += 1
            for item in o.items:
                d["gross_revenue"] += item.unit_price * item.quantity
                d["units_sold"] += item.quantity
        d["ppc_cost"] += o.ppc_cost or 0.0

    # Phí Amazon từ SettlementEntry (chỉ lấy ItemFees — loại trừ ItemPrice vì đã có trong orders)
    fee_entries = db.scalars(
        select(SettlementEntry).where(
            SettlementEntry.owner_id == owner_id,
            SettlementEntry.amount_type == "ItemFees",
        )
    ).all()
    for fe in fee_entries:
        day_key = fe.posted_date.strftime("%Y-%m-%d") if fe.posted_date else None
        if not day_key or day_key not in daily:
            continue
        # Phí Amazon là số âm trong settlement (Amazon trừ ra) → lấy abs
        daily[day_key]["amazon_fees"] = daily[day_key].get("amazon_fees", 0.0) + abs(fe.amount)

    rows_created = 0
    for day_key, d in daily.items():
        gross    = d["gross_revenue"]
        refunds  = d["refunds_amount"]
        fees     = d.get("amazon_fees", 0.0)
        cogs     = d["cogs"]
        ppc      = d["ppc_cost"]
        net_rev  = gross - refunds - fees
        net_prof = net_rev - cogs - ppc

        db.add(AggregatedDaily(
            owner_id=owner_id,
            date=datetime.strptime(day_key, "%Y-%m-%d"),
            gross_revenue=gross,
            units_sold=d["units_sold"],
            orders_count=d["orders_count"],
            refunds_amount=refunds,
            refunds_count=d["refunds_count"],
            amazon_fees=fees,
            cogs=cogs,
            ppc_cost=ppc,
            net_revenue=net_rev,
            net_profit=net_prof,
        ))
        rows_created += 1

    return rows_created


def sync_settlement_reports(db: Session, client, owner_id: int) -> dict:
    """Orchestrate toàn bộ luồng Settlement Report sync cho một seller.

    Returns dict: {"entries_saved": int, "daily_rows": int, "errors": list}
    """
    result = {"entries_saved": 0, "daily_rows": 0, "errors": []}

    # ── Bước 1: Lấy documentId của report mới nhất đã có sẵn ────────────────
    # Settlement reports do Amazon tự sinh theo chu kỳ 2 tuần — không tạo on-demand.
    try:
        document_id = client.get_latest_settlement_report_document_id()
        if not document_id:
            result["errors"].append("settlement: khong co report nao DONE tren SP-API")
            return result
        logger.info("[Settlement][owner=%s] Found documentId: %s", owner_id, document_id)
    except Exception as exc:
        result["errors"].append(f"get_settlement_report: {exc}")
        return result

    # ── Bước 2: Tải file TSV ─────────────────────────────────────────────────
    try:
        url = client.get_report_document_url(document_id)
        tsv_text = client.download_report_text(url)
        logger.info("[Settlement][owner=%s] Downloaded %d bytes", owner_id, len(tsv_text))
    except Exception as exc:
        result["errors"].append(f"download: {exc}")
        return result

    # ── Bước 4: Parse + Upsert ───────────────────────────────────────────────
    try:
        entries = _parse_tsv_to_entries(owner_id, tsv_text)
        saved = _upsert_entries(db, owner_id, entries)
        db.commit()
        result["entries_saved"] = saved
        logger.info("[Settlement][owner=%s] Saved %d entries", owner_id, saved)
    except Exception as exc:
        db.rollback()
        result["errors"].append(f"upsert: {exc}")
        return result

    # ── Bước 5: Rebuild AggregatedDaily ─────────────────────────────────────
    try:
        daily_rows = _rebuild_aggregated_daily(db, owner_id)
        db.commit()
        result["daily_rows"] = daily_rows
        logger.info("[Settlement][owner=%s] AggregatedDaily: %d rows", owner_id, daily_rows)
    except Exception as exc:
        db.rollback()
        result["errors"].append(f"aggregated_daily: {exc}")

    return result
