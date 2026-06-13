"""Phase 3 — Aggregator cho Dashboard (đọc 100% từ SQLite/Postgres local qua SQLAlchemy).

Cung cấp các hàm dùng cho route GET /api/analytics/dashboard/summary:
  get_dashboard_kpis(db, owner_id, start_date, end_date, compare_start, compare_end)
      -> Thẻ KPI (Sales/Net Profit/Units/Refunds/Fees/Ads/COGS) cho kỳ hiện tại (CP)
         và kỳ so sánh (PP), kèm delta_pct chuẩn hoá theo "Daily Average Normalization".
  get_sku_performance(db, owner_id, start_date, end_date)
      -> Bảng "Products": GROUP BY (asin, sku) từ NEW_summary_products.
  get_order_items_details(db, owner_id, start_date, end_date)
      -> Bảng "Orders": ledger giao dịch thô từ NEW_summary_order_items.

KHÔNG còn bất kỳ lệnh gọi Supabase nào trong module này — toàn bộ dữ liệu đã
được đồng bộ về DB cục bộ qua Phase3_Application/data_bridge/supabase_to_app_db.py.

Quy ước dấu (xem aggregation_models.py): doanh thu DƯƠNG; phí/ads/COGS/promo/
refund_cost lưu ÂM.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PHASE3_DIR = Path(__file__).resolve().parent          # .../sellerboard_clone/Phase3_Application/data_bridge
_ROOT_DIR = _PHASE3_DIR.parent.parent                  # .../sellerboard_clone
_BACKEND_DIR = _ROOT_DIR / "backend"


# ══════════════════════════════════════════════════════════════════════════════
# Timezone helpers — ưu tiên dùng app.timeutils của backend; nếu chạy độc lập
# ngoài backend thì fallback bản nội bộ tương đương.
# ══════════════════════════════════════════════════════════════════════════════
try:
    if str(_BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(_BACKEND_DIR))
    from app.timeutils import (MARKETPLACE_TZ, now_marketplace,   # type: ignore
                               to_marketplace_local)
except Exception:                                    # noqa: BLE001 — chạy standalone
    from zoneinfo import ZoneInfo

    MARKETPLACE_TZ = ZoneInfo(os.getenv("SELLER_TIMEZONE", "America/Los_Angeles"))

    def to_marketplace_local(dt: datetime) -> datetime:
        """UTC (naive/aware) -> giờ địa phương marketplace, trả về naive."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MARKETPLACE_TZ).replace(tzinfo=None)

    def now_marketplace() -> datetime:
        return to_marketplace_local(datetime.now(timezone.utc))


def marketplace_local_to_utc(local_dt: datetime) -> datetime:
    """Nghịch đảo của to_marketplace_local: mốc giờ local (naive) -> UTC naive,
    dùng để lọc các cột TIMESTAMPTZ lưu theo UTC (purchase_date, posted_date)."""
    return (local_dt.replace(tzinfo=MARKETPLACE_TZ)
            .astimezone(timezone.utc).replace(tzinfo=None))


def calculate_trend(cp_val: float, pp_val: float, cp_days: int, pp_days: int) -> float:
    """% thay đổi chuẩn hoá theo trung bình/ngày (Daily Average Normalization) —
    tránh lệch khi so sánh 2 kỳ có số ngày khác nhau (vd 28 ngày vs 31 ngày)."""
    if cp_days == 0 or pp_days == 0:
        return 0.00
    cp_daily_avg = cp_val / cp_days
    pp_daily_avg = pp_val / pp_days
    if pp_daily_avg == 0:
        return 100.00 if cp_daily_avg > 0 else 0.00
    trend_pct = ((cp_daily_avg - pp_daily_avg) / abs(pp_daily_avg)) * 100
    return round(trend_pct, 2)


# ══════════════════════════════════════════════════════════════════════════════
# A. get_dashboard_kpis — thẻ KPI tổng hợp + so sánh kỳ trước
# ══════════════════════════════════════════════════════════════════════════════
def get_dashboard_kpis(db, owner_id: int, start_date, end_date,
                       compare_start=None, compare_end=None) -> dict:
    """Tổng SUM(Sales/Net Profit/Units/Refunds/Fees/Ads/COGS) từ NEW_summary_products
    (chỉ các bản ghi NGÀY: period_start == period_end) cho kỳ hiện tại (CP) và kỳ
    so sánh (PP). Nếu không truyền compare_start/compare_end, PP = khoảng liền
    trước CP, cùng số ngày."""
    from sqlalchemy import func, select
    from app.models import SummaryProduct

    if compare_start is None or compare_end is None:
        period_len = (end_date - start_date).days + 1
        compare_end = start_date - timedelta(days=1)
        compare_start = compare_end - timedelta(days=period_len - 1)

    def _agg(lo, hi) -> dict:
        row = db.execute(
            select(
                func.sum(SummaryProduct.sales),
                func.sum(SummaryProduct.net_profit),
                func.sum(SummaryProduct.units),
                func.sum(SummaryProduct.refunds),
                func.sum(SummaryProduct.amazon_fees),
                func.sum(SummaryProduct.ads),
                func.sum(SummaryProduct.cost_of_goods),
            ).where(
                SummaryProduct.owner_id == owner_id,
                SummaryProduct.period_start == SummaryProduct.period_end,
                SummaryProduct.period_start >= lo,
                SummaryProduct.period_start <= hi,
            )
        ).first()
        sales, net_profit, units, refunds, fees, ads, cogs = row or (None,) * 7
        return {
            "sales": float(sales or 0.0),
            "net_profit": float(net_profit or 0.0),
            "units": int(units or 0),
            "refunds": int(refunds or 0),
            "fees": float(fees or 0.0),
            "ads": float(ads or 0.0),
            "cogs": float(cogs or 0.0),
        }

    cp = _agg(start_date, end_date)
    pp = _agg(compare_start, compare_end)
    cp_days = (end_date - start_date).days + 1
    pp_days = (compare_end - compare_start).days + 1

    kpis = {}
    for key, cp_val in cp.items():
        pp_val = pp[key]
        kpis[key] = {
            "value": round(cp_val, 2),
            "compare_value": round(pp_val, 2),
            "delta_pct": calculate_trend(cp_val, pp_val, cp_days, pp_days),
        }

    return {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "compare_period": {"start": compare_start.isoformat(), "end": compare_end.isoformat()},
        "kpis": kpis,
    }


# ══════════════════════════════════════════════════════════════════════════════
# B. get_sku_performance — bảng "Products" (GROUP BY asin, sku)
# ══════════════════════════════════════════════════════════════════════════════
def get_sku_performance(db, owner_id: int, start_date, end_date) -> list[dict]:
    """SUM(NEW_summary_products) GROUP BY (asin, sku) cho khoảng [start_date, end_date]
    (chỉ các bản ghi NGÀY: period_start == period_end). Trả về list dict cho tab Products."""
    from sqlalchemy import func, select
    from app.models import SummaryProduct

    rows = db.execute(
        select(
            SummaryProduct.asin,
            SummaryProduct.sku,
            func.max(SummaryProduct.product).label("product"),
            func.sum(SummaryProduct.units).label("units"),
            func.sum(SummaryProduct.refunds).label("refunds"),
            func.sum(SummaryProduct.sales).label("sales"),
            func.sum(SummaryProduct.promo).label("promo"),
            func.sum(SummaryProduct.ads).label("ads"),
            func.sum(SummaryProduct.refund_cost).label("refund_cost"),
            func.sum(SummaryProduct.amazon_fees).label("amazon_fees"),
            func.sum(SummaryProduct.cost_of_goods).label("cost_of_goods"),
            func.sum(SummaryProduct.shipping).label("shipping"),
            func.sum(SummaryProduct.gross_profit).label("gross_profit"),
            func.sum(SummaryProduct.net_profit).label("net_profit"),
            func.sum(SummaryProduct.estimated_payout).label("estimated_payout"),
            func.sum(SummaryProduct.expenses).label("expenses"),
            func.max(SummaryProduct.bsr).label("bsr"),
        )
        .where(
            SummaryProduct.owner_id == owner_id,
            SummaryProduct.period_start == SummaryProduct.period_end,
            SummaryProduct.period_start >= start_date,
            SummaryProduct.period_start <= end_date,
        )
        .group_by(SummaryProduct.asin, SummaryProduct.sku)
        .order_by(func.sum(SummaryProduct.net_profit).desc())
    ).all()

    out: list[dict] = []
    for r in rows:
        units = int(r.units or 0)
        sales = float(r.sales or 0.0)
        net_profit = float(r.net_profit or 0.0)
        cogs = float(r.cost_of_goods or 0.0)
        out.append({
            "asin": r.asin,
            "sku": r.sku,
            "product": r.product or r.sku,
            "units": units,
            "refunds": int(r.refunds or 0),
            "sales": round(sales, 2),
            "promo": round(float(r.promo or 0.0), 2),
            "ads": round(float(r.ads or 0.0), 2),
            "refund_cost": round(float(r.refund_cost or 0.0), 2),
            "amazon_fees": round(float(r.amazon_fees or 0.0), 2),
            "cost_of_goods": round(cogs, 2),
            "shipping": round(float(r.shipping or 0.0), 2),
            "gross_profit": round(float(r.gross_profit or 0.0), 2),
            "net_profit": round(net_profit, 2),
            "estimated_payout": round(float(r.estimated_payout or 0.0), 2),
            "expenses": round(float(r.expenses or 0.0), 2),
            "average_sales_price": round(sales / units, 2) if units else 0.0,
            "margin_pct": round(net_profit / sales * 100, 1) if sales else 0.0,
            "roi_pct": round(net_profit / abs(cogs) * 100, 1) if cogs else 0.0,
            "bsr": r.bsr,
        })
    return out


# ══════════════════════════════════════════════════════════════════════════════
# C. get_order_items_details — bảng "Orders" (ledger thô, không group)
# ══════════════════════════════════════════════════════════════════════════════
def get_order_items_details(db, owner_id: int, start_date, end_date) -> list[dict]:
    """NEW_summary_order_items trong khoảng [start_date, end_date], mới nhất trước,
    tối đa 1000 dòng — cho tab Orders."""
    from sqlalchemy import select
    from app.models import SummaryOrderItem

    rows = db.scalars(
        select(SummaryOrderItem)
        .where(
            SummaryOrderItem.owner_id == owner_id,
            SummaryOrderItem.order_date >= start_date,
            SummaryOrderItem.order_date <= end_date,
        )
        .order_by(SummaryOrderItem.order_date.desc())
        .limit(1000)
    ).all()
    return [row.to_dict() for row in rows]


# ── CLI test: python Phase3_Application/data_bridge/analytics_aggregator.py ───
if __name__ == "__main__":
    import argparse
    import json

    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except Exception:                          # noqa: BLE001
                pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--owner-id", type=int, default=1)
    args = ap.parse_args()

    try:
        from app.database import SessionLocal
        db = SessionLocal()
        end_d = now_marketplace().date()
        start_d = end_d - timedelta(days=args.days - 1)
        print("=== KPIS ===")
        print(json.dumps(get_dashboard_kpis(db, args.owner_id, start_d, end_d), indent=2, ensure_ascii=False))
        print("=== PRODUCTS ===")
        products = get_sku_performance(db, args.owner_id, start_d, end_d)
        print(f"<{len(products)} SKU>")
        print("=== ORDERS ===")
        orders = get_order_items_details(db, args.owner_id, start_d, end_d)
        print(f"<{len(orders)} rows>")
        db.close()
    except Exception as exc:                          # noqa: BLE001
        print(f"LỖI: {exc}", file=sys.stderr)
        sys.exit(1)
