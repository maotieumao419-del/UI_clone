"""Tiện ích thời gian: dùng UTC nhất quán dạng *naive* để khớp với cách SQLite
lưu cột DateTime (không kèm tzinfo). Tránh lỗi so sánh aware/naive."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    """Thời điểm hiện tại theo UTC, bỏ tzinfo (naive) để so sánh với DB."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Múi giờ của marketplace Amazon đang kết nối (US = ATVPDKIKX0DER -> Pacific Time).
# Amazon Seller Central / Sellerboard hiển thị "ngày" theo múi giờ NÀY chứ không phải
# UTC - cần quy đổi để "Hôm nay/Hôm qua/Tháng này" trên dashboard khớp với số liệu thật.
MARKETPLACE_TZ = ZoneInfo("America/Los_Angeles")


def to_marketplace_local(dt: datetime) -> datetime:
    """Quy đổi 1 thời điểm UTC (naive) sang giờ địa phương của marketplace, trả về dạng
    naive (để dễ so sánh / gom nhóm theo ngày) - dùng để tính đúng "ngày mua hàng"
    giống cách Amazon Seller Central hiển thị (tự động xử lý giờ mùa hè/đông - DST)."""
    return dt.replace(tzinfo=timezone.utc).astimezone(MARKETPLACE_TZ).replace(tzinfo=None)


def now_marketplace() -> datetime:
    """Thời điểm hiện tại theo giờ địa phương của marketplace (vd: Pacific Time cho US)."""
    return to_marketplace_local(now_utc())

