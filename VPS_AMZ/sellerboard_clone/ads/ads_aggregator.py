"""Module ADS — aggregator chỉ số quảng cáo (đọc 100% từ DB qua SQLAlchemy session).

Bắt chước Phase3_Application/data_bridge/analytics_aggregator.py nhưng cho ADS:
  get_ads_overview(db, start, end, window)        -> thẻ KPI tổng: spend/ad_sales/orders
       + ACOS/ROAS/TACOS/CTR/CVR/CPC cho khoảng [start, end].
  get_campaign_performance(db, start, end, window) -> bảng theo campaign (LEFT JOIN
       entity tree NEW_ad_campaigns lấy state/budget/targeting nếu đã áp migration 0003).
  get_sku_ads_performance(db, start, end, window)  -> bảng theo SKU/ASIN (LEFT JOIN
       NEW_products lấy title nếu có).

Nguồn dữ liệu (đã được pipeline xử lý sẵn, KHÔNG gọi Amazon ở đây):
  - "NEW_ads_campaigns_daily"  perf/ngày cấp campaign — cost & sales lưu số DƯƠNG.
  - "NEW_ads_sp_asin_daily"    perf/ngày cấp SKU/ASIN (chỉ có cửa sổ _1d/_7d).
  - "NEW_summary_products"     tổng doanh thu (organic+ad) cho mẫu số TACOS.
  - "NEW_ad_campaigns"/"NEW_products" (tùy chọn, từ migration 0003) — enrich.

Quy ước: KPI quảng cáo dùng spend/sales DƯƠNG (khác cây P&L lưu ads ÂM). Tỉ lệ
trả None khi mẫu số = 0 (frontend hiển thị "—") để không bịa số.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, text

# Cửa sổ attribution hợp lệ (whitelist — chặn SQL injection vào tên cột f-string)
_WINDOWS = ("1d", "7d", "14d")
_DEFAULT_WINDOW = "7d"

T_CAMP_DAILY = '"NEW_ads_campaigns_daily"'
T_ASIN_DAILY = '"NEW_ads_sp_asin_daily"'
T_SUMMARY = '"NEW_summary_products"'
T_ENTITY_CAMP = "NEW_ad_campaigns"
T_PRODUCTS = "NEW_products"


# ── Helpers ──────────────────────────────────────────────────────────────────
def _win(window: str) -> str:
    """Chuẩn hoá + validate cửa sổ attribution; mặc định 7d."""
    w = (window or _DEFAULT_WINDOW).lower().strip()
    return w if w in _WINDOWS else _DEFAULT_WINDOW


def _f(v) -> float:
    """Decimal/None -> float (SUM trên cột NUMERIC trả Decimal)."""
    return float(v or 0.0)


def _ratio(num, den):
    """Tỉ lệ an toàn: None nếu mẫu số ~ 0 (tránh chia 0 / bịa số)."""
    num = _f(num)
    den = _f(den)
    if den == 0:
        return None
    return round(num / den, 4)


def _table_exists(db, name: str) -> bool:
    """True nếu bảng tồn tại (entity tree 0003 có thể chưa áp). Dùng SQLAlchemy
    inspector → chạy được cả Postgres (prod) lẫn SQLite (dev), không phụ thuộc
    hàm to_regclass riêng của Postgres."""
    try:
        return sa_inspect(db.get_bind()).has_table(name)
    except Exception:                                  # noqa: BLE001
        return False


def _kpis(spend, ad_sales, orders, impressions, clicks, total_sales=None) -> dict:
    """Gói KPI suy ra từ các tổng thô. Tỉ lệ None khi mẫu số 0."""
    spend, ad_sales = _f(spend), _f(ad_sales)
    orders, impressions, clicks = _f(orders), _f(impressions), _f(clicks)
    return {
        "spend": round(spend, 2),
        "ad_sales": round(ad_sales, 2),
        "orders": int(orders),
        "impressions": int(impressions),
        "clicks": int(clicks),
        "acos": _ratio(spend, ad_sales),          # spend / ad_sales
        "roas": _ratio(ad_sales, spend),          # ad_sales / spend
        "tacos": _ratio(spend, total_sales) if total_sales is not None else None,
        "ctr": _ratio(clicks, impressions),       # clicks / impressions
        "cpc": _ratio(spend, clicks),             # spend / clicks
        "cvr": _ratio(orders, clicks),            # orders / clicks
    }


def _total_sales(db, start_date, end_date, owner_id=None):
    """Tổng doanh thu (organic+ad) từ NEW_summary_products (chỉ bản ghi NGÀY) cho
    mẫu số TACOS. owner_id=None -> không lọc (pipeline single-seller). None nếu
    bảng/dữ liệu chưa có (TACOS sẽ là None)."""
    if not _table_exists(db, "NEW_summary_products"):
        return None
    sql = (f"SELECT COALESCE(SUM(sales), 0) FROM {T_SUMMARY} "
           "WHERE period_start = period_end "
           "AND period_start >= :lo AND period_start <= :hi")
    params = {"lo": start_date, "hi": end_date}
    if owner_id is not None:
        sql += " AND owner_id = :oid"
        params["oid"] = owner_id
    val = db.execute(text(sql), params).scalar()
    return _f(val)


# ── A. Overview — thẻ KPI tổng ────────────────────────────────────────────────
def get_ads_overview(db, start_date, end_date, window=_DEFAULT_WINDOW, owner_id=None) -> dict:
    """Tổng spend/ad_sales/orders/impr/clicks từ NEW_ads_campaigns_daily +
    ACOS/ROAS/TACOS/CTR/CVR/CPC cho [start_date, end_date]."""
    w = _win(window)
    row = db.execute(text(
        f"SELECT COALESCE(SUM(impressions),0) AS impressions, "
        f"       COALESCE(SUM(clicks),0)      AS clicks, "
        f"       COALESCE(SUM(cost),0)        AS spend, "
        f"       COALESCE(SUM(sales_{w}),0)   AS ad_sales, "
        f"       COALESCE(SUM(purchases_{w}),0) AS orders "
        f"FROM {T_CAMP_DAILY} WHERE report_date >= :lo AND report_date <= :hi"
    ), {"lo": start_date, "hi": end_date}).first()

    total_sales = _total_sales(db, start_date, end_date, owner_id)
    kpis = _kpis(
        spend=row.spend if row else 0, ad_sales=row.ad_sales if row else 0,
        orders=row.orders if row else 0, impressions=row.impressions if row else 0,
        clicks=row.clicks if row else 0, total_sales=total_sales,
    )
    return {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "window": w,
        "total_sales": round(total_sales, 2) if total_sales is not None else None,
        "kpis": kpis,
    }


# ── B. Campaign performance ───────────────────────────────────────────────────
def get_campaign_performance(db, start_date, end_date, window=_DEFAULT_WINDOW) -> list[dict]:
    """GROUP BY campaign từ NEW_ads_campaigns_daily; LEFT JOIN entity tree
    NEW_ad_campaigns (state/budget/targeting/strategy) nếu migration 0003 đã áp.
    Sắp theo spend giảm dần."""
    w = _win(window)
    has_entity = _table_exists(db, T_ENTITY_CAMP)

    if has_entity:
        sql = (
            f"SELECT d.campaign_id, MAX(d.campaign_name) AS campaign_name, d.ad_product, "
            f"       COALESCE(SUM(d.impressions),0) AS impressions, "
            f"       COALESCE(SUM(d.clicks),0)      AS clicks, "
            f"       COALESCE(SUM(d.cost),0)        AS spend, "
            f"       COALESCE(SUM(d.sales_{w}),0)   AS ad_sales, "
            f"       COALESCE(SUM(d.purchases_{w}),0) AS orders, "
            f"       MAX(c.state) AS state, MAX(c.targeting_type) AS targeting_type, "
            f"       MAX(c.budget_amount) AS budget_amount, MAX(c.bidding_strategy) AS bidding_strategy, "
            f"       MAX(c.advertised_asin) AS advertised_asin "
            f"FROM {T_CAMP_DAILY} d "
            f'LEFT JOIN "{T_ENTITY_CAMP}" c ON c.campaign_id = d.campaign_id '
            f"WHERE d.report_date >= :lo AND d.report_date <= :hi "
            f"GROUP BY d.campaign_id, d.ad_product ORDER BY spend DESC"
        )
    else:
        sql = (
            f"SELECT d.campaign_id, MAX(d.campaign_name) AS campaign_name, d.ad_product, "
            f"       COALESCE(SUM(d.impressions),0) AS impressions, "
            f"       COALESCE(SUM(d.clicks),0)      AS clicks, "
            f"       COALESCE(SUM(d.cost),0)        AS spend, "
            f"       COALESCE(SUM(d.sales_{w}),0)   AS ad_sales, "
            f"       COALESCE(SUM(d.purchases_{w}),0) AS orders "
            f"FROM {T_CAMP_DAILY} d "
            f"WHERE d.report_date >= :lo AND d.report_date <= :hi "
            f"GROUP BY d.campaign_id, d.ad_product ORDER BY spend DESC"
        )

    rows = db.execute(text(sql), {"lo": start_date, "hi": end_date}).mappings().all()
    out = []
    for r in rows:
        item = {
            "campaign_id": r["campaign_id"],
            "campaign_name": r["campaign_name"],
            "ad_product": r["ad_product"],
            **_kpis(r["spend"], r["ad_sales"], r["orders"], r["impressions"], r["clicks"]),
        }
        if has_entity:
            item.update({
                "state": r.get("state"),
                "targeting_type": r.get("targeting_type"),
                "budget_amount": _f(r.get("budget_amount")) if r.get("budget_amount") is not None else None,
                "bidding_strategy": r.get("bidding_strategy"),
                "advertised_asin": r.get("advertised_asin"),
            })
        out.append(item)
    return out


# ── C. SKU/ASIN performance ───────────────────────────────────────────────────
def get_sku_ads_performance(db, start_date, end_date, window=_DEFAULT_WINDOW) -> list[dict]:
    """GROUP BY (advertised_sku, advertised_asin) từ NEW_ads_sp_asin_daily; LEFT JOIN
    NEW_products lấy title nếu có. Bảng này chỉ có cửa sổ _1d/_7d (14d -> 7d)."""
    w = _win(window)
    if w == "14d":
        w = "7d"
    has_products = _table_exists(db, T_PRODUCTS)

    title_sel = "MAX(p.title) AS title" if has_products else "NULL AS title"
    join = f'LEFT JOIN "{T_PRODUCTS}" p ON p.sku = d.advertised_sku ' if has_products else ""
    sql = (
        f"SELECT d.advertised_sku, MAX(d.advertised_asin) AS advertised_asin, {title_sel}, "
        f"       COALESCE(SUM(d.impressions),0) AS impressions, "
        f"       COALESCE(SUM(d.clicks),0)      AS clicks, "
        f"       COALESCE(SUM(d.cost),0)        AS spend, "
        f"       COALESCE(SUM(d.sales_{w}),0)   AS ad_sales, "
        f"       COALESCE(SUM(d.purchases_{w}),0) AS orders "
        f"FROM {T_ASIN_DAILY} d {join}"
        f"WHERE d.report_date >= :lo AND d.report_date <= :hi "
        f"GROUP BY d.advertised_sku ORDER BY spend DESC"
    )
    rows = db.execute(text(sql), {"lo": start_date, "hi": end_date}).mappings().all()
    return [{
        "sku": r["advertised_sku"],
        "asin": r["advertised_asin"],
        "title": r["title"],
        **_kpis(r["spend"], r["ad_sales"], r["orders"], r["impressions"], r["clicks"]),
    } for r in rows]


# ── CLI standalone (verify nhanh, giống analytics_aggregator) ──────────────────
if __name__ == "__main__":
    import argparse
    import json

    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except Exception:                          # noqa: BLE001
                pass

    ap = argparse.ArgumentParser(description="In thử KPI ADS cho 1 khoảng ngày")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--window", default=_DEFAULT_WINDOW, choices=_WINDOWS)
    args = ap.parse_args()

    # backend trên sys.path để dùng app.database.SessionLocal (giống analytics_aggregator)
    _BACKEND = Path(__file__).resolve().parent.parent / "backend"
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))
    try:
        from app.database import SessionLocal           # type: ignore
        try:
            from app.timeutils import now_marketplace   # type: ignore
            end_d = now_marketplace().date()
        except Exception:                                # noqa: BLE001
            end_d = datetime.now(timezone.utc).date()
        start_d = end_d - timedelta(days=args.days - 1)

        db = SessionLocal()
        ov = get_ads_overview(db, start_d, end_d, args.window)
        print("=== OVERVIEW ===")
        print(json.dumps(ov, indent=2, ensure_ascii=False))
        camps = get_campaign_performance(db, start_d, end_d, args.window)
        print(f"=== CAMPAIGNS: {len(camps)} ===")
        for c in camps[:5]:
            print(f"  {c['campaign_name']!r:40.40} spend={c['spend']:>8} "
                  f"acos={c['acos']} roas={c['roas']}")
        skus = get_sku_ads_performance(db, start_d, end_d, args.window)
        print(f"=== SKUS: {len(skus)} ===")
        db.close()
    except Exception as exc:                             # noqa: BLE001
        print(f"LỖI: {exc}", file=sys.stderr)
        sys.exit(1)
