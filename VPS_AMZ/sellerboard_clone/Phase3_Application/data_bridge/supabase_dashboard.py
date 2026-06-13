"""Phase 3 / data_bridge — Dashboard API hoàn toàn từ Supabase.

Mục tiêu (theo yêu cầu): web app sellerboard_clone CHỈ còn render giao diện;
MỌI số liệu của Dashboard lấy từ bảng đệm Supabase NEW_* (KHÔNG đụng SQLite).

Cung cấp 2 payload đúng shape mà frontend/app.js đang đọc:

  build_dashboard(days) -> GET /api/analytics/dashboard?days=N
      {kpis, timeseries, top_products, marketplace_breakdown, totals, range, status}
  build_periods()       -> GET /api/analytics/periods
      {periods: [today, yesterday, mtd, forecast, last_month]}

Nguyên tắc tính (chuẩn Sellerboard, cash-basis theo ngày sự kiện, giờ Pacific):
  - Sales / Units / Orders / Promo  : gom theo NGÀY MUA (purchase_date) local.
  - Amazon fees                     : gom theo NGÀY POST (posted_date) local —
                                      phí hiển thị đúng ngày Amazon ghi nhận,
                                      KHÔNG cần khớp order (tránh lỗi orphan).
  - Refunds / Refund cost           : gom theo posted_date local.
  - Ads (PPC/SB/SD)                 : gom theo report_date (Ads API trả sẵn theo
                                      timezone tài khoản = Pacific) — không đổi.
  - COGS (FIFO)                     : theo ngày mua, dùng NEW_product_cogs.
  Quy ước dấu: doanh thu DƯƠNG, mọi chi phí ÂM; ads lưu DƯƠNG nên TRỪ khi tính.

  Net_profit  = Sales + Promo + Amazon_fees + Refund_cost + COGS - Ads_cost
  Est_payout  = Sales + Promo + Amazon_fees + Refund_cost - Ads_cost   (không trừ COGS)

top_products tái dùng Phase3/analytics_aggregator (đã tính per-SKU + COGS FIFO +
phân bổ ads 3 tầng), nên render_performance.js hoạt động như cũ.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]            # .../sellerboard_clone
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Phase3.analytics_aggregator import (  # noqa: E402  — sau khi chỉnh sys.path
    MARKETPLACE_TZ, _float, _load_cogs, _unit_cogs, aggregate_product_performance,
    fetch_all, get_supabase_client, marketplace_local_to_utc, now_marketplace,
    parse_iso, to_marketplace_local)

logger = logging.getLogger(__name__)

T_ORDERS  = "NEW_sp_orders"
T_ITEMS   = "NEW_sp_order_items"
T_FEES    = "NEW_fin_item_fees"
T_REFUNDS = "NEW_fin_refunds"
T_ADS     = "NEW_ads_campaigns_daily"
_IN_CHUNK = 150
_CANCELED = ("Canceled", "Cancelled")


def _delta_pct(now_v: float, before_v: float):
    """% thay đổi so kỳ trước; None nếu kỳ trước = 0 (không có cơ sở)."""
    if not before_v:
        return None
    return round((now_v - before_v) / abs(before_v) * 100, 1)


def _new_day() -> dict:
    return {"sales": 0.0, "units": 0, "orders": set(), "promo": 0.0,
            "fees": 0.0, "refunds": 0, "refund_cost": 0.0, "ads": 0.0, "cogs": 0.0}


# ══════════════════════════════════════════════════════════════════════════════
# Lõi: gom metrics theo NGÀY LOCAL (Pacific) cho khoảng [start_d, end_d]
# ══════════════════════════════════════════════════════════════════════════════
def _daily_metrics(sb, start_d: date, end_d: date) -> dict[str, dict]:
    start_utc = marketplace_local_to_utc(datetime.combine(start_d, time.min))
    end_utc = marketplace_local_to_utc(datetime.combine(end_d, time.max))
    days: dict[str, dict] = {}

    def bucket(d_iso: str) -> dict:
        return days.setdefault(d_iso, _new_day())

    # ── Orders -> ngày mua local ──────────────────────────────────────────────
    orders = fetch_all(lambda: (
        sb.table(T_ORDERS).select("order_id,purchase_date,order_status")
        .gte("purchase_date", start_utc.isoformat() + "Z")
        .lte("purchase_date", end_utc.isoformat() + "Z")
        .not_.in_("order_status", list(_CANCELED))
    ))
    order_day: dict[str, str] = {}
    for o in orders:
        dt = parse_iso(o.get("purchase_date"))
        if o.get("order_id") and dt:
            order_day[o["order_id"]] = to_marketplace_local(dt).date().isoformat()

    # ── Items -> Sales/Units/Promo/COGS theo ngày mua ────────────────────────
    cogs_map = _load_cogs(sb)
    ids = list(order_day)
    for i in range(0, len(ids), _IN_CHUNK):
        chunk = ids[i: i + _IN_CHUNK]
        items = fetch_all(lambda c=chunk: (
            sb.table(T_ITEMS)
            .select("order_id,sku,quantity_ordered,item_price,promotion_discount")
            .in_("order_id", c)
        ))
        for it in items:
            d_iso = order_day.get(it.get("order_id") or "")
            if not d_iso:
                continue
            b = bucket(d_iso)
            qty = int(it.get("quantity_ordered") or 0)
            b["orders"].add(it["order_id"])
            b["units"] += qty
            b["sales"] += _float(it.get("item_price"))
            b["promo"] += -abs(_float(it.get("promotion_discount")))
            b["cogs"] += -_unit_cogs(cogs_map, it.get("sku") or "",
                                     datetime.fromisoformat(d_iso)) * qty

    # ── Fees theo posted_date local (số âm) ──────────────────────────────────
    try:
        fees = fetch_all(lambda: (
            sb.table(T_FEES).select("posted_date,amount")
            .gte("posted_date", start_utc.isoformat() + "Z")
            .lte("posted_date", end_utc.isoformat() + "Z")
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Dashboard] fees lỗi: %s", exc)
        fees = []
    for f in fees:
        dt = parse_iso(f.get("posted_date"))
        if dt:
            bucket(to_marketplace_local(dt).date().isoformat())["fees"] += _float(f.get("amount"))

    # ── Refunds theo posted_date local ───────────────────────────────────────
    try:
        refs = fetch_all(lambda: (
            sb.table(T_REFUNDS)
            .select("posted_date,quantity_returned,refund_principal,"
                    "refund_commission,refunded_referral_fee")
            .gte("posted_date", start_utc.isoformat() + "Z")
            .lte("posted_date", end_utc.isoformat() + "Z")
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Dashboard] refunds lỗi: %s", exc)
        refs = []
    for r in refs:
        dt = parse_iso(r.get("posted_date"))
        if dt:
            b = bucket(to_marketplace_local(dt).date().isoformat())
            b["refunds"] += int(r.get("quantity_returned") or 1)
            b["refund_cost"] += (_float(r.get("refund_principal"))
                                 + _float(r.get("refund_commission"))
                                 + _float(r.get("refunded_referral_fee")))

    # ── Ads theo report_date (đã là ngày Pacific) ────────────────────────────
    try:
        ads = fetch_all(lambda: (
            sb.table(T_ADS).select("report_date,cost")
            .gte("report_date", start_d.isoformat())
            .lte("report_date", end_d.isoformat())
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Dashboard] ads lỗi: %s", exc)
        ads = []
    for a in ads:
        rd = a.get("report_date")
        if rd:
            bucket(str(rd)[:10])["ads"] += _float(a.get("cost"))

    return days


def _derive(day: dict) -> dict:
    """Bổ sung net_profit / est_payout cho 1 ngày (orders set -> count)."""
    sales, promo = day["sales"], day["promo"]
    fees, refund_cost = day["fees"], day["refund_cost"]
    ads, cogs = day["ads"], day["cogs"]
    est_payout = sales + promo + fees + refund_cost - ads
    return {
        "sales": sales, "units": day["units"], "orders": len(day["orders"]),
        "promo": promo, "fees": fees, "refunds": day["refunds"],
        "refund_cost": refund_cost, "ads": ads, "cogs": cogs,
        "est_payout": est_payout, "net_profit": est_payout + cogs,
    }


def _sum_range(days: dict[str, dict], lo: date, hi: date) -> dict:
    """Cộng dồn các ngày trong [lo, hi]. orders = tổng order/ngày (mỗi order 1 ngày)."""
    acc = {"sales": 0.0, "units": 0, "orders": 0, "promo": 0.0, "fees": 0.0,
           "refunds": 0, "refund_cost": 0.0, "ads": 0.0, "cogs": 0.0}
    lo_s, hi_s = lo.isoformat(), hi.isoformat()
    for d_iso, day in days.items():
        if lo_s <= d_iso <= hi_s:
            der = _derive(day)
            for k in ("sales", "promo", "fees", "refund_cost", "ads", "cogs"):
                acc[k] += der[k]
            acc["units"] += der["units"]
            acc["orders"] += der["orders"]
            acc["refunds"] += der["refunds"]
    acc["est_payout"] = acc["sales"] + acc["promo"] + acc["fees"] + acc["refund_cost"] - acc["ads"]
    acc["net_profit"] = acc["est_payout"] + acc["cogs"]
    return acc


# ══════════════════════════════════════════════════════════════════════════════
# /api/analytics/periods — 5 thẻ kỳ
# ══════════════════════════════════════════════════════════════════════════════
def _shift_month(d: date, months: int) -> date:
    y, m = d.year, d.month + months
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return d.replace(year=y, month=m, day=1)


def build_periods() -> dict:
    now = now_marketplace()
    today = now.date()
    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)
    next_month_start = _shift_month(month_start, 1)
    prev_month_start = _shift_month(month_start, -1)
    prev_month_end = month_start - timedelta(days=1)
    prev_prev_month_start = _shift_month(month_start, -2)
    prev_prev_month_end = prev_month_start - timedelta(days=1)
    days_in_month = (next_month_start - month_start).days
    days_elapsed = (today - month_start).days + 1

    sb = get_supabase_client()
    days = _daily_metrics(sb, prev_prev_month_start, today)

    fmt = lambda d: d.strftime("%d/%m/%Y")  # noqa: E731

    def card(key, label, range_label, na, ca=None):
        return {
            "key": key, "label": label, "range_label": range_label,
            "sales": round(na["sales"], 2),
            "sales_delta_pct": _delta_pct(na["sales"], ca["sales"]) if ca else None,
            "orders": int(na["orders"]), "units": int(na["units"]),
            "refunds": int(na["refunds"]),
            "adv_cost": -round(na["ads"], 2),              # âm để hiển thị "-$x"
            "est_payout": round(na["est_payout"], 2),
            "net_profit": round(na["net_profit"], 2),
            "net_profit_delta_pct": _delta_pct(na["net_profit"], ca["net_profit"]) if ca else None,
        }

    today_a = _sum_range(days, today, today)
    yest_a = _sum_range(days, yesterday, yesterday)
    mtd_a = _sum_range(days, month_start, today)
    last_a = _sum_range(days, prev_month_start, prev_month_end)
    pprev_a = _sum_range(days, prev_prev_month_start, prev_prev_month_end)
    mtd_cmp_end = min(prev_month_end, prev_month_start + timedelta(days=days_elapsed - 1))
    mtd_cmp_a = _sum_range(days, prev_month_start, mtd_cmp_end)

    factor = (days_in_month / days_elapsed) if days_elapsed else 0.0
    forecast_a = {k: (mtd_a[k] * factor) for k in mtd_a}
    forecast_a["orders"] = round(mtd_a["orders"] * factor)
    forecast_a["units"] = round(mtd_a["units"] * factor)
    forecast_a["refunds"] = round(mtd_a["refunds"] * factor)

    periods = [
        card("today", "Hôm nay", fmt(today), today_a),
        card("yesterday", "Hôm qua", fmt(yesterday), yest_a),
        card("mtd", "Từ đầu tháng", f"{fmt(month_start)} – {fmt(today)}", mtd_a, mtd_cmp_a),
        card("forecast", "Dự báo cả tháng",
             f"{fmt(month_start)} – {fmt(next_month_start - timedelta(days=1))}",
             forecast_a, last_a),
        card("last_month", "Tháng trước",
             f"{fmt(prev_month_start)} – {fmt(prev_month_end)}", last_a, pprev_a),
    ]
    return {"periods": periods}


# ══════════════════════════════════════════════════════════════════════════════
# /api/analytics/dashboard?days=N — kpis + timeseries + top_products + breakdown
# ══════════════════════════════════════════════════════════════════════════════
def build_dashboard(days: int = 30) -> dict:
    end = now_marketplace().date()
    start = end - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    sb = get_supabase_client()
    daily = _daily_metrics(sb, prev_start, end)
    cur = _sum_range(daily, start, end)
    prev = _sum_range(daily, prev_start, start - timedelta(days=1))

    margin = (cur["net_profit"] / cur["sales"] * 100) if cur["sales"] else 0.0
    kpis = [
        {"label": "Doanh thu", "value": round(cur["sales"], 2), "unit": "$",
         "delta_pct": _delta_pct(cur["sales"], prev["sales"])},
        {"label": "Lợi nhuận ròng", "value": round(cur["net_profit"], 2), "unit": "$",
         "delta_pct": _delta_pct(cur["net_profit"], prev["net_profit"])},
        {"label": "Biên LN", "value": round(margin, 1), "unit": "%", "delta_pct": None},
        {"label": "Số đơn vị", "value": int(cur["units"]), "unit": "",
         "delta_pct": _delta_pct(cur["units"], prev["units"])},
        {"label": "Phí Amazon", "value": round(cur["fees"], 2), "unit": "$",
         "delta_pct": _delta_pct(cur["fees"], prev["fees"])},
        {"label": "Chi phí PPC", "value": -round(cur["ads"], 2), "unit": "$",
         "delta_pct": _delta_pct(cur["ads"], prev["ads"])},
        {"label": "Giá vốn (COGS)", "value": round(cur["cogs"], 2), "unit": "$",
         "delta_pct": None},
        {"label": "Đơn hoàn", "value": int(cur["refunds"]), "unit": "", "delta_pct": None},
    ]

    timeseries = []
    for d_iso in sorted(daily):
        if start.isoformat() <= d_iso <= end.isoformat():
            der = _derive(daily[d_iso])
            timeseries.append({"date": d_iso, "sales": round(der["sales"], 2),
                               "profit": round(der["net_profit"], 2),
                               "units": int(der["units"])})

    # top_products + totals + range: tái dùng aggregator per-SKU (COGS FIFO + ads 3 tầng)
    try:
        agg = aggregate_product_performance(days=days)
        top_products = agg.get("top_products", [])
        totals = agg.get("totals", {})
        rng = agg.get("range", {})
    except Exception as exc:                            # noqa: BLE001
        logger.warning("[Dashboard] aggregator top_products lỗi: %s", exc)
        top_products, totals, rng = [], {}, {}

    return {
        "status": "success",
        "period_days": days,
        "range": rng or {"start": start.isoformat(), "end": end.isoformat(),
                         "timezone": str(MARKETPLACE_TZ)},
        "kpis": kpis,
        "timeseries": timeseries,
        "marketplace_breakdown": {"amazon": round(cur["sales"], 2)} if cur["sales"] else {},
        "totals": totals,
        "top_products": top_products,
    }


# ── CLI test: python Phase3_Application/data_bridge/supabase_dashboard.py ─────
if __name__ == "__main__":
    import argparse
    import json

    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except Exception:                          # noqa: BLE001
                pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--what", choices=["dashboard", "periods", "both"], default="both")
    args = ap.parse_args()

    if args.what in ("periods", "both"):
        print("=== PERIODS ===")
        print(json.dumps(build_periods(), indent=2, ensure_ascii=False))
    if args.what in ("dashboard", "both"):
        print("=== DASHBOARD ===")
        d = build_dashboard(days=args.days)
        d_print = dict(d)
        d_print["top_products"] = f"<{len(d['top_products'])} SKU>"
        print(json.dumps(d_print, indent=2, ensure_ascii=False))
