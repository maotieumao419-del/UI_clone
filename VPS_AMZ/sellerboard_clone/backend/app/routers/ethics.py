"""Lớp Đạo đức Dữ liệu (điểm khác biệt cốt lõi - Privacy by Design).

- Transparency portal: tóm tắt loại dữ liệu thu thập + mục đích.
- Meaningful choice: cập nhật đồng ý (consent) theo từng mục.
- Data minimization: xoá dữ liệu thô quá hạn lưu trữ.
- Quyền truy xuất/xoá dữ liệu cá nhân (GDPR-like).
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import BsrSnapshot, ListingSnapshot, Product, User
from ..timeutils import now_utc

router = APIRouter(prefix="/api/ethics", tags=["ethics"])

# Cổng minh bạch: mô tả dễ hiểu thay cho chính sách dài dòng
DATA_TRANSPARENCY = [
    {"category": "Thông tin tài khoản", "data": "Email, tên", "purpose": "Đăng nhập & liên hệ",
     "retention": "Đến khi bạn xoá tài khoản", "required": True},
    {"category": "Dữ liệu đơn hàng", "data": "Doanh thu, phí, đơn vị bán",
     "purpose": "Tính lợi nhuận & phân tích", "retention": f"{settings.DATA_RETENTION_DAYS} ngày (thô)", "required": True},
    {"category": "Nhật ký listing", "data": "Ảnh chụp tiêu đề/ảnh/giá",
     "purpose": "Cảnh báo thay đổi 24/7", "retention": f"{settings.DATA_RETENTION_DAYS} ngày", "required": False},
    {"category": "Tiếp thị", "data": "Hành vi sử dụng app",
     "purpose": "Cải thiện sản phẩm (tuỳ chọn)", "retention": "Theo đồng ý của bạn", "required": False},
]


@router.get("/transparency")
def transparency():
    """Tóm tắt rõ ràng rủi ro/lợi ích của việc chia sẻ dữ liệu."""
    return {
        "principle": "Data Minimization + Privacy by Design",
        "summary": "Chúng tôi chỉ thu thập dữ liệu cần thiết để cung cấp dịch vụ và "
                   "không bao giờ bán dữ liệu của bạn cho bên thứ ba.",
        "data_catalog": DATA_TRANSPARENCY,
        "retention_days": settings.DATA_RETENTION_DAYS,
    }


@router.get("/consent")
def get_consent(current: User = Depends(get_current_user)):
    return current.consent or {}


@router.put("/consent")
def update_consent(consent: dict, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """Lựa chọn có ý nghĩa: bật/tắt từng mục đồng ý."""
    allowed = {"analytics", "marketing", "data_sharing"}
    current.consent = {k: bool(v) for k, v in consent.items() if k in allowed}
    db.commit()
    db.refresh(current)
    return current.consent


@router.post("/minimize")
def run_minimization(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """Xoá dữ liệu thô (listing/BSR snapshot) vượt quá thời hạn lưu trữ."""
    cutoff = now_utc() - timedelta(days=settings.DATA_RETENTION_DAYS)
    pids = [p.id for p in db.scalars(select(Product).where(Product.owner_id == current.id)).all()]
    deleted = 0
    if pids:
        r1 = db.execute(delete(ListingSnapshot).where(
            ListingSnapshot.product_id.in_(pids), ListingSnapshot.captured_at < cutoff))
        r2 = db.execute(delete(BsrSnapshot).where(
            BsrSnapshot.product_id.in_(pids), BsrSnapshot.captured_at < cutoff))
        deleted = (r1.rowcount or 0) + (r2.rowcount or 0)
        db.commit()
    return {"deleted_records": deleted, "cutoff": cutoff.isoformat()}
