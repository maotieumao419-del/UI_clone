"""Mô-đun 1: Phân tích Tài chính Tiên tiến (Advanced Profit Analytics).

Dùng Pandas/NumPy để bóc tách doanh thu - phí Amazon - COGS (FIFO) - PPC -> lợi
nhuận ròng, biên lợi nhuận, ROI. Cung cấp dữ liệu cho Dashboard, LTV và BSR.
"""
import logging
from collections import defaultdict, deque
from datetime import timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (BsrSnapshot, InventoryBatch, Order, OrderItem, Product,
                      SummaryOrderItem, SummaryProduct)
from ..timeutils import now_utc, now_marketplace

logger = logging.getLogger(__name__)


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


def _delta_pct(now_v: float, before_v: float) -> float | None:
    """% thay đổi so với kỳ trước; None nếu kỳ trước = 0 (không có cơ sở so sánh)."""
    if before_v == 0:
        return None
    return round((now_v - before_v) / abs(before_v) * 100, 1)


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


def period_overview(db: Session, owner_id: int) -> dict:
    """5 thẻ tổng quan kiểu Sellerboard: Hôm nay / Hôm qua / Từ đầu tháng /
    Dự báo cả tháng / Tháng trước — mỗi thẻ gồm Sales, Orders/Units, Refunds,
    Adv. cost, Est. payout, Net profit (kèm % so với kỳ tham chiếu).

    Đọc từ NEW_summary_order_items / NEW_summary_products đã đồng bộ về
    DB cục bộ (SQLite/Postgres) — dữ liệu Phase 2 đã hiệu chỉnh (phí Amazon
    thực/ước theo từng SKU, COGS thực, ads phân bổ 3 tầng), thay cho local DB
    (Product.referral_fee_pct/fba_fee_per_unit mặc định + Order.ppc_cost luôn
    = 0 vốn cho ra lợi nhuận ảo cao hơn thực tế nhiều).

    'Est. payout' xấp xỉ = Doanh thu - Phí Amazon - Chi phí PPC: số tiền thực
    về tài khoản người bán (Amazon Ads cũng trừ tiền trực tiếp từ tài khoản).
    """
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

    def agg(lo, hi):
        row = db.execute(
            select(
                func.sum(SummaryOrderItem.sales),
                func.sum(SummaryOrderItem.net_profit),
                func.sum(SummaryOrderItem.units),
                func.sum(SummaryOrderItem.refunds),
                func.sum(SummaryOrderItem.amazon_fees),
                func.count(func.distinct(SummaryOrderItem.order_number)),
            ).where(
                SummaryOrderItem.owner_id == owner_id,
                SummaryOrderItem.order_date >= lo,
                SummaryOrderItem.order_date <= hi,
            )
        ).first()
        sales, item_net, units, refunds, amazon_fees, orders = (
            float(row[0] or 0), float(row[1] or 0), int(row[2] or 0),
            int(row[3] or 0), float(row[4] or 0), int(row[5] or 0))

        # ads lưu âm (chi phí); amazon_fees cũng lưu âm (đã trừ vào gross).
        ad_spend = float(db.scalar(
            select(func.sum(SummaryProduct.ads)).where(
                SummaryProduct.owner_id == owner_id,
                SummaryProduct.period_start == SummaryProduct.period_end,
                SummaryProduct.period_start >= lo,
                SummaryProduct.period_start <= hi,
            )
        ) or 0.0)

        return {
            "sales": round(sales, 2),
            "orders": orders,
            "units": units,
            "refunds": refunds,
            "fees": round(-amazon_fees, 2),
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
