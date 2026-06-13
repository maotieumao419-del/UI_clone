"""Mô-đun 1: Phân tích Tài chính Tiên tiến (Advanced Profit Analytics).

Dùng Pandas/NumPy để bóc tách doanh thu - phí Amazon - COGS (FIFO) - PPC -> lợi
nhuận ròng, biên lợi nhuận, ROI. Cung cấp dữ liệu cho Dashboard, LTV và BSR.
"""
import calendar
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (BsrSnapshot, InventoryBatch, ListingSnapshot, Order,
                      OrderItem, Product, SettlementEntry)
from ..timeutils import (MARKETPLACE_TZ, now_utc, now_marketplace,
                         to_marketplace_local)

logger = logging.getLogger(__name__)

# Bảng đệm báo cáo quảng cáo trên Supabase (Phase 3) — mỗi dòng là 1 bản ghi
# report (SP/SB/SD) theo ngày, chứa raw_json gốc từ Advertising API.
_ADS_REPORTS_TABLE = "raw_amazon_campaign_reports"


def _fifo_cogs_by_product(db: Session, owner_id: int) -> dict[int, list[float]]:
    """Phân bổ giá vốn theo FIFO cho TỪNG đơn vị đã bán của mỗi sản phẩm.

    Trả về: {product_id: [unit_cost cho đơn vị bán thứ 0, thứ 1, ...]} theo thứ
    tự thời gian bán. Người gọi sẽ tiêu thụ tuần tự danh sách này.
    """
    # Hàng đợi lô nhập (FIFO) theo product
    batches = db.scalars(
        select(InventoryBatch)
        .join(Product, Product.id == InventoryBatch.product_id)
        .where(Product.owner_id == owner_id)
        .order_by(InventoryBatch.received_at.asc())
    ).all()
    queues: dict[int, deque] = defaultdict(deque)
    for b in batches:
        queues[b.product_id].append([b.quantity, b.unit_cost])

    # Tất cả đơn vị đã bán, theo thứ tự thời gian
    rows = db.execute(
        select(OrderItem.product_id, OrderItem.quantity, Order.purchased_at)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.owner_id == owner_id, Order.is_refunded.is_(False))
        .order_by(Order.purchased_at.asc())
    ).all()

    result: dict[int, list[float]] = defaultdict(list)
    for product_id, qty, _ in rows:
        q = queues[product_id]
        for _ in range(qty):
            if not q:
                # Hết lô nhập -> dùng giá vốn của lô cuối cùng đã biết (hoặc 0)
                result[product_id].append(result[product_id][-1] if result[product_id] else 0.0)
                continue
            batch = q[0]
            result[product_id].append(batch[1])
            batch[0] -= 1
            if batch[0] <= 0:
                q.popleft()
    return result


def calculate_cogs_fifo(db: Session, owner_id: int) -> dict:
    """Hàm wrapper: khởi chạy bộ tính giá vốn COGS theo FIFO và tổng hợp biên
    lợi nhuận P&L cho TOÀN BỘ tài khoản `owner_id`.

    Được gọi đúng MỘT LẦN sau khi giai đoạn xử lý nội bộ (Supabase -> SQLite)
    đã duyệt và commit xong toàn bộ các trang dữ liệu — tránh tính lặp lại
    COGS giữa chừng khi đơn hàng/lô nhập còn đang được ghi dở.
    """
    cogs_map = _fifo_cogs_by_product(db, owner_id)
    overview = period_overview(db, owner_id)
    return {
        "owner_id": owner_id,
        "products_costed": len(cogs_map),
        "units_costed": sum(len(unit_costs) for unit_costs in cogs_map.values()),
        "periods": overview.get("periods", []),
    }


def _marketplace_local_to_utc(local_dt: datetime) -> datetime:
    """Nghịch đảo của `to_marketplace_local`: quy đổi mốc giờ địa phương của
    marketplace (naive, Pacific Time) về UTC naive — dùng để lọc các cột DB
    lưu theo UTC (vd SettlementEntry.posted_date)."""
    return local_dt.replace(tzinfo=MARKETPLACE_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _settlement_fees_by_sku(db: Session, owner_id: int,
                            start_local: datetime, end_local: datetime) -> dict[str, dict]:
    """Tổng hợp phí THẬT theo SKU từ Settlement Report trong khoảng kỳ.

    Trả về {sku: {commission, fba, promo, other, has_fees}}:
      - commission : Referral fee / Commission (lấy trị tuyệt đối)
      - fba        : các phí hoàn thiện đơn FBA*/Fulfillment (trị tuyệt đối)
      - promo      : chiết khấu khuyến mãi (Promotion*, trị tuyệt đối)
      - other      : các phí/điều chỉnh khác, GIỮ NGUYÊN DẤU (+/- Other_Fees)
      - has_fees   : SKU có dữ liệu phí thật hay chưa (nếu chưa -> nơi gọi
                     fallback về phí ước tính referral_fee_pct/fba_fee_per_unit)
    """
    start_utc = _marketplace_local_to_utc(start_local)
    end_utc = _marketplace_local_to_utc(end_local)
    rows = db.execute(
        select(SettlementEntry.sku, SettlementEntry.amount_type,
               SettlementEntry.amount_description, func.sum(SettlementEntry.amount))
        .where(SettlementEntry.owner_id == owner_id,
               SettlementEntry.sku != "",
               SettlementEntry.posted_date >= start_utc,
               SettlementEntry.posted_date <= end_utc)
        .group_by(SettlementEntry.sku, SettlementEntry.amount_type,
                  SettlementEntry.amount_description)
    ).all()

    out: dict[str, dict] = defaultdict(
        lambda: {"commission": 0.0, "fba": 0.0, "promo": 0.0, "other": 0.0, "has_fees": False})
    for sku, amount_type, desc, amount in rows:
        d = (desc or "").lower()
        amt = float(amount or 0.0)
        bucket = out[sku]
        if "commission" in d or "referral" in d:
            bucket["commission"] += abs(amt)
            bucket["has_fees"] = True
        elif d.startswith("fba") or "fulfillment" in d:
            bucket["fba"] += abs(amt)
            bucket["has_fees"] = True
        elif "promo" in d:
            bucket["promo"] += abs(amt)
        elif amount_type == "ItemPrice":
            continue  # Principal/Shipping/Tax = doanh thu, đã có sẵn trong Orders
        else:
            bucket["other"] += amt  # giữ dấu gốc: bồi thường (+) / phí khác (-)
    return dict(out)


def _ads_spend_by_sku(sales_by_sku: dict[str, float],
                      start_local: datetime, end_local: datetime) -> dict[str, float]:
    """Phân bổ chi phí quảng cáo xuống từng SKU từ bảng đệm Supabase
    `raw_amazon_campaign_reports` trong khoảng kỳ (theo ngày local marketplace —
    Ads API vốn đã trả report theo timezone tài khoản quảng cáo).

    Chiến lược phân bổ 3 tầng:
      1) Bản ghi cấp SKU/ASIN (report SP theo advertisedSku) -> gán thẳng.
      2) Bản ghi cấp campaign: nếu tên campaign chứa SKU -> gán cho SKU đó.
      3) Phần spend còn lại không khớp -> phân bổ theo tỉ trọng doanh thu.

    Bọc try-except toàn phần: Supabase lỗi/chưa có bảng -> trả {} để nơi gọi
    fallback về Order.ppc_cost, KHÔNG làm sập dashboard.
    """
    try:
        from .supabase_client import get_supabase_client
        supabase = get_supabase_client()
        resp = (supabase.table(_ADS_REPORTS_TABLE)
                .select("*")
                .gte("report_date", start_local.date().isoformat())
                .lte("report_date", end_local.date().isoformat())
                .execute())
        rows = resp.data or []
    except Exception as exc:
        logger.warning("[AdsAlloc] Khong doc duoc %s tu Supabase (%s) — fallback ppc_cost.",
                       _ADS_REPORTS_TABLE, exc)
        return {}

    allocated: dict[str, float] = defaultdict(float)
    unmatched = 0.0
    skus_upper = {s.upper(): s for s in sales_by_sku if s}

    for r in rows:
        raw = r.get("raw_json") if isinstance(r.get("raw_json"), dict) else r
        cost = 0.0
        for key in ("cost", "spend", "ad_spend"):
            if raw.get(key) is not None:
                try:
                    cost = float(raw.get(key) or 0.0)
                except (TypeError, ValueError):
                    cost = 0.0
                break
        if not cost:
            continue
        # Tầng 1: bản ghi cấp SKU/ASIN
        sku = raw.get("advertisedSku") or raw.get("advertised_sku") or ""
        if sku in sales_by_sku:
            allocated[sku] += cost
            continue
        # Tầng 2: dò SKU trong tên campaign (quy ước đặt tên campaign theo SKU)
        name = str(raw.get("campaignName") or raw.get("campaign_name") or "").upper()
        hit = next((orig for up, orig in skus_upper.items() if up and up in name), None)
        if hit:
            allocated[hit] += cost
        else:
            unmatched += cost

    # Tầng 3: phân bổ phần không khớp theo tỉ trọng doanh thu từng SKU
    total_sales = sum(v for v in sales_by_sku.values() if v > 0)
    if unmatched > 0 and total_sales > 0:
        for sku, s in sales_by_sku.items():
            if s > 0:
                allocated[sku] += unmatched * (s / total_sales)
    return dict(allocated)


def _latest_image_by_product(db: Session, product_ids: list[int]) -> dict[int, str | None]:
    """Ảnh thumbnail mới nhất của từng sản phẩm (từ ListingSnapshot.data.main_image)."""
    if not product_ids:
        return {}
    img_map: dict[int, str | None] = {}
    for pid, data in db.execute(
        select(ListingSnapshot.product_id, ListingSnapshot.data)
        .where(ListingSnapshot.product_id.in_(product_ids))
        .order_by(ListingSnapshot.product_id, ListingSnapshot.captured_at.desc())
    ).all():
        img_map.setdefault(pid, (data or {}).get("main_image"))
    return img_map


def _build_dataframe(db: Session, owner_id: int, start: datetime, end: datetime) -> pd.DataFrame:
    """Bảng dữ liệu dòng (1 dòng = 1 order item) đã gắn COGS FIFO + phí."""
    cogs_map = _fifo_cogs_by_product(db, owner_id)
    cogs_cursor: dict[int, int] = defaultdict(int)  # con trỏ tiêu thụ FIFO

    rows = db.execute(
        select(
            OrderItem.product_id,
            OrderItem.quantity,
            OrderItem.unit_price,
            Order.id,
            Order.purchased_at,
            Order.ppc_cost,
            Order.is_refunded,
            Order.marketplace,
            Product.asin,
            Product.sku,
            Product.title,
            Product.referral_fee_pct,
            Product.fba_fee_per_unit,
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Order.owner_id == owner_id)
        .order_by(Order.purchased_at.asc())
    ).all()

    records = []
    for r in rows:
        (pid, qty, price, order_id, purchased_at, ppc, refunded, market, asin, sku, title, ref_pct, fba) = r
        # Quy doi gio mua hang tu UTC sang gio dia phuong cua marketplace (vd: Pacific
        # Time cho US) - de "ngay mua hang" tinh giong cach Amazon Seller Central /
        # Sellerboard hien thi (tranh lech "Hom nay/Hom qua" do khac mui gio voi UTC).
        local_dt = to_marketplace_local(purchased_at)
        # Tiêu thụ COGS theo FIFO kể cả đơn ngoài khoảng (để con trỏ đúng vị trí)
        unit_costs = cogs_map.get(pid, [])
        cogs = 0.0
        if not refunded:
            for _ in range(qty):
                idx = cogs_cursor[pid]
                if idx < len(unit_costs):
                    cogs += unit_costs[idx]
                cogs_cursor[pid] += 1

        if not (start <= local_dt <= end):
            continue

        sales = 0.0 if refunded else price * qty
        referral_fee = sales * ref_pct
        fba_fee = 0.0 if refunded else fba * qty
        amazon_fees = referral_fee + fba_fee
        net = sales - amazon_fees - cogs - (ppc or 0.0)
        records.append(
            {
                "product_id": pid,
                "asin": asin,
                "sku": sku,
                "title": title,
                "ref_pct": ref_pct,
                "fba_per_unit": fba,
                "order_id": order_id,
                "date": local_dt.date().isoformat(),
                "marketplace": market,
                "units": 0 if refunded else qty,
                "sales": sales,
                "fees": amazon_fees,
                "cogs": cogs,
                "ppc": ppc or 0.0,
                "net_profit": net,
                "refunded": bool(refunded),
            }
        )

    cols = ["product_id", "asin", "sku", "title", "ref_pct", "fba_per_unit", "order_id",
            "date", "marketplace", "units", "sales", "fees", "cogs", "ppc", "net_profit", "refunded"]
    return pd.DataFrame(records, columns=cols)


def _delta_pct(now_v: float, before_v: float) -> float | None:
    """% thay đổi so với kỳ trước; None nếu kỳ trước = 0 (không có cơ sở so sánh)."""
    if before_v == 0:
        return None
    return round((now_v - before_v) / abs(before_v) * 100, 1)


def dashboard(db: Session, owner_id: int, days: int = 30) -> dict:
    end = now_marketplace()
    start = end - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    df_all = _build_dataframe(db, owner_id, prev_start, end)
    if df_all.empty:
        return {"kpis": [], "timeseries": [], "top_products": [], "marketplace_breakdown": {}}

    df_all["date_dt"] = pd.to_datetime(df_all["date"])
    cur = df_all[df_all["date_dt"] >= pd.Timestamp(start.date())]
    prev = df_all[df_all["date_dt"] < pd.Timestamp(start.date())]

    def _agg(d: pd.DataFrame) -> dict:
        return {
            "sales": float(d["sales"].sum()),
            "units": int(d["units"].sum()),
            "profit": float(d["net_profit"].sum()),
            "fees": float(d["fees"].sum()),
            "cogs": float(d["cogs"].sum()),
            "ppc": float(d["ppc"].sum()),
            "refunds": int(d["refunded"].sum()),
        }

    c, p = _agg(cur), _agg(prev)

    margin = (c["profit"] / c["sales"] * 100) if c["sales"] else 0.0
    kpis = [
        {"label": "Doanh thu", "value": round(c["sales"], 2), "unit": "$", "delta_pct": _delta_pct(c["sales"], p["sales"])},
        {"label": "Lợi nhuận ròng", "value": round(c["profit"], 2), "unit": "$", "delta_pct": _delta_pct(c["profit"], p["profit"])},
        {"label": "Biên LN", "value": round(margin, 1), "unit": "%", "delta_pct": None},
        {"label": "Số đơn vị", "value": c["units"], "unit": "", "delta_pct": _delta_pct(c["units"], p["units"])},
        {"label": "Phí Amazon", "value": round(c["fees"], 2), "unit": "$", "delta_pct": _delta_pct(c["fees"], p["fees"])},
        {"label": "Chi phí PPC", "value": round(c["ppc"], 2), "unit": "$", "delta_pct": _delta_pct(c["ppc"], p["ppc"])},
        {"label": "Giá vốn (COGS)", "value": round(c["cogs"], 2), "unit": "$", "delta_pct": None},
        {"label": "Đơn hoàn", "value": c["refunds"], "unit": "", "delta_pct": None},
    ]

    # Time series theo ngày
    ts = (
        cur.groupby("date")
        .agg(sales=("sales", "sum"), profit=("net_profit", "sum"), units=("units", "sum"))
        .reset_index()
        .sort_values("date")
    )
    timeseries = [
        {"date": row["date"], "sales": round(float(row["sales"]), 2),
         "profit": round(float(row["profit"]), 2), "units": int(row["units"])}
        for _, row in ts.iterrows()
    ]

    # Top sản phẩm theo lợi nhuận (bảng chi tiết kiểu Sellerboard)
    grp = (
        cur.groupby(["product_id", "asin", "title"])
        .agg(units=("units", "sum"), refunds=("refunded", "sum"), sales=("sales", "sum"),
             cogs=("cogs", "sum"), fees=("fees", "sum"), ppc=("ppc", "sum"), net_profit=("net_profit", "sum"))
        .reset_index()
        .sort_values("net_profit", ascending=False)
        .head(10)
    )
    # BSR hiện tại (snapshot mới nhất) cho từng sản phẩm trong bảng
    bsr_map: dict[int, int] = {}
    product_ids = [int(pid) for pid in grp["product_id"].tolist()]
    if product_ids:
        for pid, bsr in db.execute(
            select(BsrSnapshot.product_id, BsrSnapshot.bsr)
            .where(BsrSnapshot.product_id.in_(product_ids))
            .order_by(BsrSnapshot.product_id, BsrSnapshot.captured_at.desc())
        ).all():
            bsr_map.setdefault(pid, bsr)  # dòng đầu mỗi product_id (đã sort theo captured_at desc) = mới nhất

    top_products = []
    for _, row in grp.iterrows():
        s = float(row["sales"])
        units = int(row["units"])
        cogs = float(row["cogs"])
        net_profit = float(row["net_profit"])
        gross_profit = s - cogs
        pid = int(row["product_id"])
        top_products.append({
            "product_id": pid,
            "asin": row["asin"],
            "title": row["title"],
            "units": units,
            "refunds": int(row["refunds"]),
            "sales": round(s, 2),
            "avg_selling_price": round(s / units, 2) if units else 0.0,
            "cogs": round(cogs, 2),
            "fees": round(float(row["fees"]), 2),
            "ppc": round(float(row["ppc"]), 2),
            "gross_profit": round(gross_profit, 2),
            "net_profit": round(net_profit, 2),
            "margin_pct": round(net_profit / s * 100, 1) if s else 0.0,
            "roi_pct": round(net_profit / cogs * 100, 1) if cogs else 0.0,
            "bsr": bsr_map.get(pid),
        })

    breakdown = cur.groupby("marketplace")["sales"].sum().round(2).to_dict()

    return {
        "kpis": kpis,
        "timeseries": timeseries,
        "top_products": top_products,
        "marketplace_breakdown": {k: float(v) for k, v in breakdown.items()},
    }


def _shift_month(d, months: int):
    """Lùi/tiến `months` tháng, luôn trả về ngày-1 của tháng đích."""
    y, m = d.year, d.month + months
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return d.replace(year=y, month=m, day=1)


def _supabase_select_all(build_query) -> list[dict]:
    """Lấy hết kết quả 1 query Supabase, phân trang 1000 dòng/lần (giới hạn
    mặc định của PostgREST). `build_query` là callable trả về 1 query builder
    MỚI mỗi lần gọi (vì `.range()` phải áp lên builder chưa execute)."""
    rows: list[dict] = []
    page = 1000
    offset = 0
    while True:
        batch = build_query().range(offset, offset + page - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def period_overview(db: Session, owner_id: int) -> dict:
    """5 thẻ tổng quan kiểu Sellerboard: Hôm nay / Hôm qua / Từ đầu tháng /
    Dự báo cả tháng / Tháng trước — mỗi thẻ gồm Sales, Orders/Units, Refunds,
    Adv. cost, Est. payout, Net profit (kèm % so với kỳ tham chiếu).

    Đọc trực tiếp từ NEW_summary_order_items / NEW_summary_campaigns trên
    Supabase — đây là dữ liệu Phase 2 đã hiệu chỉnh (phí Amazon thực/ước theo
    từng SKU, COGS thực, ads phân bổ 3 tầng), thay cho local DB
    (Product.referral_fee_pct/fba_fee_per_unit mặc định + Order.ppc_cost luôn
    = 0 vốn cho ra lợi nhuận ảo cao hơn thực tế nhiều).

    LƯU Ý: NEW_summary_* hiện KHÔNG có owner_id (single-tenant per Supabase
    project) — `owner_id` chỉ được giữ lại để tương thích chữ ký hàm/route.

    'Est. payout' xấp xỉ = Doanh thu - Phí Amazon - Chi phí PPC: số tiền thực
    về tài khoản người bán (Amazon Ads cũng trừ tiền trực tiếp từ tài khoản).
    """
    from .supabase_client import get_supabase_client

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

    def agg(lo, hi):
        lo_s, hi_s = lo.isoformat(), hi.isoformat()
        items = _supabase_select_all(lambda: sb.table("NEW_summary_order_items")
            .select("order_number,units,sales,amazon_fees,refunds,net_profit")
            .gte("order_date", lo_s).lte("order_date", hi_s))
        camps = _supabase_select_all(lambda: sb.table("NEW_summary_campaigns")
            .select("ad_spend")
            .gte("period_start", lo_s).lte("period_end", hi_s))

        # ad_spend lưu âm (chi phí); amazon_fees cũng lưu âm (đã trừ vào gross).
        ad_spend = sum(r.get("ad_spend") or 0 for r in camps)
        item_net = sum(r.get("net_profit") or 0 for r in items)  # chưa gồm ads

        return {
            "sales": round(sum(r.get("sales") or 0 for r in items), 2),
            "orders": len({r["order_number"] for r in items if r.get("order_number")}),
            "units": sum(int(r.get("units") or 0) for r in items),
            "refunds": sum(int(r.get("refunds") or 0) for r in items),
            "fees": round(-sum(r.get("amazon_fees") or 0 for r in items), 2),
            "ppc": round(-ad_spend, 2),
            "net_profit": round(item_net + ad_spend, 2),
        }

    fmt = lambda d: d.strftime("%d/%m/%Y")

    def card(key, label, range_label, now_agg, compare_agg=None):
        return {
            "key": key, "label": label, "range_label": range_label,
            "sales": round(now_agg["sales"], 2),
            "sales_delta_pct": _delta_pct(now_agg["sales"], compare_agg["sales"]) if compare_agg else None,
            "orders": now_agg["orders"], "units": now_agg["units"], "refunds": now_agg["refunds"],
            "adv_cost": round(now_agg["ppc"], 2),
            "est_payout": round(now_agg["sales"] - now_agg["fees"] - now_agg["ppc"], 2),
            "net_profit": round(now_agg["net_profit"], 2),
            "net_profit_delta_pct": _delta_pct(now_agg["net_profit"], compare_agg["net_profit"]) if compare_agg else None,
        }

    today_agg = agg(today, today)
    yesterday_agg = agg(yesterday, yesterday)
    mtd_agg = agg(month_start, today)
    last_month_agg = agg(prev_month_start, prev_month_end)
    prev_prev_month_agg = agg(prev_prev_month_start, prev_prev_month_end)

    if not any(a["sales"] or a["orders"] or a["units"]
               for a in (today_agg, yesterday_agg, mtd_agg, last_month_agg, prev_prev_month_agg)):
        return {"periods": []}

    # So MTD với cùng số ngày đầu của tháng trước
    mtd_compare_end = min(prev_month_end, prev_month_start + timedelta(days=days_elapsed - 1))
    mtd_compare_agg = agg(prev_month_start, mtd_compare_end)

    # Dự báo cả tháng = ngoại suy tuyến tính theo tốc độ hiện tại, so với tháng trước
    factor = (days_in_month / days_elapsed) if days_elapsed else 0.0
    forecast_agg = {
        "sales": mtd_agg["sales"] * factor, "orders": round(mtd_agg["orders"] * factor),
        "units": round(mtd_agg["units"] * factor), "refunds": round(mtd_agg["refunds"] * factor),
        "fees": mtd_agg["fees"] * factor, "ppc": mtd_agg["ppc"] * factor,
        "net_profit": mtd_agg["net_profit"] * factor,
    }

    periods = [
        card("today", "Hôm nay", fmt(today), today_agg),
        card("yesterday", "Hôm qua", fmt(yesterday), yesterday_agg),
        card("mtd", "Từ đầu tháng", f"{fmt(month_start)} – {fmt(today)}", mtd_agg, mtd_compare_agg),
        card("forecast", "Dự báo cả tháng", f"{fmt(month_start)} – {fmt(next_month_start - timedelta(days=1))}",
             forecast_agg, last_month_agg),
        card("last_month", "Tháng trước", f"{fmt(prev_month_start)} – {fmt(prev_month_end)}",
             last_month_agg, prev_prev_month_agg),
    ]
    return {"periods": periods}


def customer_ltv(db: Session, owner_id: int) -> dict:
    """LTV Dashboard: giá trị trọn đời trung bình của khách hàng."""
    rows = db.execute(
        select(Order.customer_ref, OrderItem.unit_price, OrderItem.quantity, Order.ppc_cost)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.owner_id == owner_id, Order.is_refunded.is_(False), Order.customer_ref != "")
    ).all()
    if not rows:
        return {"avg_ltv": 0, "avg_orders_per_customer": 0, "customers": 0, "repeat_rate_pct": 0}

    df = pd.DataFrame(rows, columns=["customer_ref", "unit_price", "quantity", "ppc"])
    df["revenue"] = df["unit_price"] * df["quantity"]
    by_cust = df.groupby("customer_ref").agg(revenue=("revenue", "sum"), ppc=("ppc", "sum"))
    # số đơn riêng biệt
    order_counts = (
        db.execute(
            select(Order.customer_ref, Order.id)
            .where(Order.owner_id == owner_id, Order.is_refunded.is_(False), Order.customer_ref != "")
        ).all()
    )
    oc = pd.DataFrame(order_counts, columns=["customer_ref", "order_id"]).groupby("customer_ref")["order_id"].nunique()
    customers = len(by_cust)
    repeat = int((oc > 1).sum())
    return {
        "avg_ltv": round(float(by_cust["revenue"].mean()), 2),
        "avg_orders_per_customer": round(float(oc.mean()), 2),
        "customers": customers,
        "repeat_rate_pct": round(repeat / customers * 100, 1) if customers else 0,
    }


def bsr_monitor(db: Session, owner_id: int) -> list[dict]:
    """So sánh BSR hiện tại với trung bình 7 ngày & 30 ngày."""
    products = db.scalars(select(Product).where(Product.owner_id == owner_id)).all()
    now = now_utc()
    out = []
    for p in products:
        snaps = db.scalars(
            select(BsrSnapshot).where(BsrSnapshot.product_id == p.id).order_by(BsrSnapshot.captured_at.desc())
        ).all()
        if not snaps:
            continue
        current = snaps[0].bsr
        wk = [s.bsr for s in snaps if s.captured_at >= now - timedelta(days=7)]
        mo = [s.bsr for s in snaps if s.captured_at >= now - timedelta(days=30)]
        avg_wk = sum(wk) / len(wk) if wk else current
        avg_mo = sum(mo) / len(mo) if mo else current
        # BSR thấp hơn = tốt hơn; %thay đổi dương nghĩa là cải thiện
        out.append({
            "product_id": p.id,
            "asin": p.asin,
            "title": p.title,
            "current_bsr": current,
            "avg_week": round(avg_wk),
            "avg_month": round(avg_mo),
            "vs_week_pct": round((avg_wk - current) / avg_wk * 100, 1) if avg_wk else 0,
            "vs_month_pct": round((avg_mo - current) / avg_mo * 100, 1) if avg_mo else 0,
        })
    return out
