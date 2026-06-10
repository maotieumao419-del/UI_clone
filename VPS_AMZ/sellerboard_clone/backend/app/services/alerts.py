"""Mô-đun 3: Trung tâm Cảnh báo & Khôi phục Doanh thu.

- Giám sát Listing 24/7: so sánh 2 snapshot gần nhất -> phát hiện thay đổi tiêu
  đề, ảnh chính, kích thước, phí giới thiệu, mất Buy Box, xuất hiện hijacker.
- Báo cáo Bồi thường: quét hàng mất/hư & hoàn tiền không trả hàng.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, ListingSnapshot, Order, OrderItem, Product, ReimbursementCase

# Các trường được theo dõi và mức độ nghiêm trọng
_WATCHED = {
    "title": ("title_changed", "warning", "Tiêu đề listing bị thay đổi"),
    "main_image": ("image_changed", "warning", "Hình ảnh chính bị thay đổi"),
    "dimensions": ("dimensions_changed", "warning", "Kích thước sản phẩm thay đổi (ảnh hưởng phí FBA)"),
    "referral_fee_pct": ("fee_changed", "critical", "Phí giới thiệu thay đổi"),
    "buybox_owner": ("buybox_lost", "critical", "Mất Buy Box"),
}


def scan_listing_changes(db: Session, owner_id: int) -> list[Alert]:
    """So sánh snapshot mới nhất với snapshot trước đó cho từng sản phẩm."""
    products = db.scalars(select(Product).where(Product.owner_id == owner_id)).all()
    new_alerts: list[Alert] = []

    for p in products:
        snaps = db.scalars(
            select(ListingSnapshot)
            .where(ListingSnapshot.product_id == p.id)
            .order_by(ListingSnapshot.captured_at.desc())
            .limit(2)
        ).all()
        if len(snaps) < 2:
            continue
        latest, prev = snaps[0].data, snaps[1].data

        for field, (atype, sev, label) in _WATCHED.items():
            if latest.get(field) != prev.get(field):
                if field == "buybox_owner" and latest.get(field) == p.sku:
                    continue  # mình vẫn giữ buy box
                msg = f"{label} [{p.asin}]: '{prev.get(field)}' → '{latest.get(field)}'"
                new_alerts.append(Alert(owner_id=owner_id, product_id=p.id, type=atype, severity=sev, message=msg))

        # Phát hiện hijacker: người bán lạ chen vào danh sách seller
        prev_sellers = set(prev.get("sellers", []))
        new_sellers = set(latest.get("sellers", [])) - prev_sellers - {p.sku}
        for s in new_sellers:
            new_alerts.append(Alert(
                owner_id=owner_id, product_id=p.id, type="hijacker", severity="critical",
                message=f"Phát hiện người bán lạ (hijacker) trên ASIN {p.asin}: {s}",
            ))

    # Lưu, tránh trùng lặp với alert chưa đọc cùng nội dung
    existing = {
        (a.product_id, a.type, a.message)
        for a in db.scalars(select(Alert).where(Alert.owner_id == owner_id, Alert.is_read.is_(False))).all()
    }
    saved = []
    for a in new_alerts:
        if (a.product_id, a.type, a.message) in existing:
            continue
        db.add(a)
        saved.append(a)
    db.commit()
    return saved


def build_reimbursement_report(db: Session, owner_id: int) -> list[ReimbursementCase]:
    """Tạo hồ sơ bồi thường cho đơn hoàn tiền nhưng KHÔNG trả lại hàng."""
    refunded_no_return = db.execute(
        select(Order.id, OrderItem.product_id, OrderItem.quantity, OrderItem.unit_price)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.owner_id == owner_id, Order.is_refunded.is_(True), Order.refund_returned.is_(False))
    ).all()

    existing_orders = {
        c.detected_at for c in db.scalars(
            select(ReimbursementCase).where(ReimbursementCase.owner_id == owner_id)
        ).all()
    }
    new_cases = []
    for order_id, product_id, qty, price in refunded_no_return:
        case = ReimbursementCase(
            owner_id=owner_id, product_id=product_id, reason="refund_no_return",
            quantity=qty, estimated_amount=round(price * qty, 2), status="open",
        )
        db.add(case)
        new_cases.append(case)
    db.commit()
    return new_cases
