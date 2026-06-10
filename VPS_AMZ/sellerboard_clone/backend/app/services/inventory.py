"""Mô-đun 2: Tự động hoá Vận hành & Phân tích Chuỗi Cung ứng.

Vận tốc bán hàng có trọng số theo thời gian + yếu tố mùa vụ/tăng trưởng + đệm an
toàn & lead time -> điểm đặt hàng lại (reorder point) và số lượng nên nhập.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Order, OrderItem, Product
from ..timeutils import now_utc

# Trọng số tầm quan trọng: 3 ngày gần nhất > 7 ngày > 30 ngày (loại nhiễu)
DEFAULT_WEIGHTS = {3: 0.5, 7: 0.3, 30: 0.2}


def _weighted_velocity(daily_units: pd.Series, weights: dict[int, float], end: datetime) -> float:
    """Vận tốc bán/ngày = tổng có trọng số của trung bình các cửa sổ thời gian."""
    velocity = 0.0
    for window, w in weights.items():
        start = pd.Timestamp((end - timedelta(days=window)).date())
        sub = daily_units[daily_units.index >= start]
        avg = sub.sum() / window if window else 0.0
        velocity += w * avg
    return velocity


def _seasonality_factor(month: int) -> float:
    """Hệ số mùa vụ đơn giản (Q4 cao điểm). Production: học từ dữ liệu lịch sử."""
    table = {1: 0.85, 2: 0.85, 3: 0.95, 4: 1.0, 5: 1.0, 6: 1.0,
             7: 1.0, 8: 1.05, 9: 1.1, 10: 1.2, 11: 1.5, 12: 1.6}
    return table.get(month, 1.0)


def restock_suggestions(db: Session, owner_id: int,
                        monthly_growth_target: float = 0.05,
                        weights: dict[int, float] | None = None) -> list[dict]:
    weights = weights or DEFAULT_WEIGHTS
    end = now_utc()

    products = db.scalars(select(Product).where(Product.owner_id == owner_id)).all()
    rows = db.execute(
        select(OrderItem.product_id, OrderItem.quantity, Order.purchased_at)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.owner_id == owner_id, Order.is_refunded.is_(False),
               Order.purchased_at >= end - timedelta(days=45))
    ).all()
    df = pd.DataFrame(rows, columns=["product_id", "quantity", "purchased_at"])
    if not df.empty:
        df["day"] = pd.to_datetime(df["purchased_at"]).dt.normalize()

    suggestions = []
    for p in products:
        if df.empty:
            daily = pd.Series(dtype=float)
        else:
            sub = df[df["product_id"] == p.id]
            daily = sub.groupby("day")["quantity"].sum() if not sub.empty else pd.Series(dtype=float)

        base_velocity = _weighted_velocity(daily, weights, end) if not daily.empty else 0.0
        # Áp mùa vụ + tăng trưởng mục tiêu
        season = _seasonality_factor(end.month)
        growth = 1 + monthly_growth_target
        velocity = base_velocity * season * growth

        lead_time = (p.lead_time_manufacture_days + p.lead_time_shipping_days + p.lead_time_prep_days)
        days_cover = lead_time + p.safety_stock_days

        available = p.current_stock + p.inbound_stock
        days_of_stock = (available / velocity) if velocity > 0 else float("inf")
        reorder_point = int(np.ceil(velocity * days_cover))

        # Nhập đủ để phủ 1 chu kỳ lead time + đệm, trừ tồn hiện có
        target_units = velocity * (days_cover + 30)  # +30 ngày bán sau khi hàng về
        suggested = int(max(0, np.ceil(target_units - available)))

        if days_of_stock == float("inf"):
            stockout_date, urgency = None, "ổn định"
        else:
            stockout_date = (end + timedelta(days=days_of_stock)).date().isoformat()
            if days_of_stock <= lead_time:
                urgency = "khẩn cấp"          # sẽ hết hàng trước khi hàng mới về
            elif days_of_stock <= days_cover:
                urgency = "cần đặt ngay"
            elif days_of_stock <= days_cover + 21:
                urgency = "theo dõi"
            else:
                urgency = "ổn định"

        suggestions.append({
            "product_id": p.id,
            "asin": p.asin,
            "title": p.title,
            "daily_velocity": round(velocity, 2),
            "current_stock": p.current_stock,
            "inbound_stock": p.inbound_stock,
            "days_of_stock": round(days_of_stock, 1) if days_of_stock != float("inf") else 9999,
            "reorder_point": reorder_point,
            "suggested_order_qty": suggested if available <= reorder_point else 0,
            "stockout_date": stockout_date,
            "urgency": urgency,
        })

    order = {"khẩn cấp": 0, "cần đặt ngay": 1, "theo dõi": 2, "ổn định": 3}
    suggestions.sort(key=lambda s: (order.get(s["urgency"], 9), s["days_of_stock"]))
    return suggestions
