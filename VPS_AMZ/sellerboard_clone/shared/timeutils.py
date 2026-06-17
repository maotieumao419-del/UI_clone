"""Shared — Pacific timezone utilities (chuẩn Sellerboard).

Quy tắc:
  - Phase 1 lưu nguyên UTC từ Amazon, KHÔNG quy đổi lúc ghi.
  - Phase 2 group-by ngày: ép UTC -> America/Los_Angeles TRƯỚC khi .date().
  - Ads report_date ĐÃ là Pacific — không quy đổi lần 2.
  - DST tự động (UTC-7 hè / UTC-8 đông) — không hardcode offset.

Import:
    from shared.timeutils import pacific_date, utc_window_for_date, date_range_pacific
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_date(dt_utc: datetime) -> date:
    """Chuyển datetime UTC -> date Pacific (tự động DST)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(PACIFIC).date()


def utc_window_for_date(d: date) -> tuple[datetime, datetime]:
    """Trả (start_utc, end_utc_exclusive) cho đúng 1 ngày Pacific d.

    start = 00:00:00 Pacific ngày d quy đổi sang UTC
    end   = 00:00:00 Pacific ngày d+1 quy đổi sang UTC (exclusive)
    """
    start_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=PACIFIC)
    end_local   = datetime(d.year, d.month, d.day + 1, 0, 0, 0, tzinfo=PACIFIC) \
        if d.day < _days_in_month(d.year, d.month) \
        else datetime(d.year + (d.month // 12), (d.month % 12) + 1, 1, 0, 0, 0, tzinfo=PACIFIC)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _days_in_month(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]


def date_range_pacific(start_str: str, end_str: str) -> list[date]:
    """Trả list date Pacific trong [start_str, end_str] (YYYY-MM-DD, cả 2 đầu)."""
    s = date.fromisoformat(start_str)
    e = date.fromisoformat(end_str)
    result = []
    cur = s
    while cur <= e:
        result.append(cur)
        cur += timedelta(days=1)
    return result


def today_pacific() -> date:
    return datetime.now(timezone.utc).astimezone(PACIFIC).date()


def yesterday_pacific() -> date:
    return today_pacific() - timedelta(days=1)


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
