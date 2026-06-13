"""
Module dùng chung: xác định khoảng thời gian lấy dữ liệu cho fetch_24h_*.py.

── Vấn đề timezone ────────────────────────────────────────────────────────────
- SP-API (PurchaseDate, PostedDate) trả về UTC (suffix "Z").
- Ads API trả "date" theo TIMEZONE CỦA TÀI KHOẢN QUẢNG CÁO (marketplace US
  thường là America/Los_Angeles, tự xử lý DST PDT/PST).
- Sellerboard tính "1 ngày" theo timezone cấu hình trong
  Settings → General → Time Zone (mặc định/khuyến nghị US: America/Los_Angeles).

→ SELLER_TIMEZONE (.env, mặc định "America/Los_Angeles") = timezone Sellerboard
  đang dùng. Khi bạn chọn "ngày 2026-06-08":
    - Orders/Finances: quy đổi thành [2026-06-08 00:00, 2026-06-09 00:00) giờ
      SELLER_TIMEZONE → UTC, dùng làm CreatedAfter/CreatedBefore, PostedAfter/PostedBefore.
    - Ads: dùng thẳng "2026-06-08" làm startDate/endDate (Ads API đã đúng timezone).

── Cách dùng trong mỗi script ──────────────────────────────────────────────────
  import _time_range as tr
  start_utc, end_utc, day_label = tr.maybe_prompt()
  # start_utc/end_utc: chuỗi ISO "YYYY-MM-DDTHH:MM:SSZ" hoặc None nếu dùng mặc định
  # day_label: "YYYY-MM-DD" (giờ SELLER_TIMEZONE) hoặc None

maybe_prompt() chỉ hỏi khi:
  - KHÔNG có biến .env override liên quan đã được set (script tự kiểm tra trước khi gọi)
  - đang chạy ở terminal tương tác (sys.stdin.isatty())
Nếu không thoả 1 trong 2 → trả về (None, None, None) → script dùng mặc định
(LOOKBACK_HOURS / hôm qua) như cũ.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 (hiếm)
    ZoneInfo = None

SELLER_TZ_NAME = os.getenv("SELLER_TIMEZONE", "America/Los_Angeles")


def _seller_tz():
    if ZoneInfo is None:
        raise RuntimeError("Cần Python >= 3.9 để dùng zoneinfo, hoặc cài 'tzdata'")
    return ZoneInfo(SELLER_TZ_NAME)


def is_interactive() -> bool:
    return sys.stdin.isatty()


def day_to_utc_range(date_str: str):
    """'YYYY-MM-DD' (giờ SELLER_TIMEZONE) → (start_utc_iso, end_utc_iso) bao trọn 1 ngày."""
    tz = _seller_tz()
    day = datetime.strptime(date_str.strip(), "%Y-%m-%d").replace(tzinfo=tz)
    start_utc = day.astimezone(timezone.utc)
    end_utc   = (day + timedelta(days=1)).astimezone(timezone.utc)
    return (start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))


def range_to_utc(from_str: str, to_str: str = None):
    """KHOẢNG '[from, to]' (giờ SELLER_TIMEZONE, gồm cả 2 đầu) →
    (start_utc_iso, end_utc_iso, [danh sách ngày YYYY-MM-DD cho ads]).
    to_str trống = bằng from_str (lấy đúng 1 ngày)."""
    tz = _seller_tz()
    to_str = (to_str or from_str).strip()
    d0 = datetime.strptime(from_str.strip(), "%Y-%m-%d").replace(tzinfo=tz)
    d1 = datetime.strptime(to_str, "%Y-%m-%d").replace(tzinfo=tz)
    if d1.date() < d0.date():
        d0, d1 = d1, d0                                  # tự đảo nếu nhập ngược
    start_utc = d0.astimezone(timezone.utc)
    end_utc = (d1 + timedelta(days=1)).astimezone(timezone.utc)
    days, cur = [], d0
    while cur.date() <= d1.date():
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return (start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), days)


def maybe_prompt():
    """Hỏi user chọn '24h gần nhất' hay 'một KHOẢNG ngày cụ thể (từ → đến)'.

    Trả về:
      (None, None, None)                              → dùng mặc định (24h / hôm qua)
      (start_utc_iso, end_utc_iso, [YYYY-MM-DD, ...]) → khoảng UTC + danh sách ngày
                                                         (giờ SELLER_TIMEZONE)
    """
    if not is_interactive():
        return None, None, None

    print(f"\n── Khoảng thời gian lấy dữ liệu (giờ Seller Central = {SELLER_TZ_NAME}) ──")
    print("  1. 24h gần nhất / hôm qua (mặc định)")
    print("  2. Một khoảng ngày cụ thể (từ ngày → đến ngày — khớp Sellerboard)")
    choice = input("  Lựa chọn (1/2, Enter = 1): ").strip()
    if choice != "2":
        return None, None, None

    def _ask(prompt, allow_blank=False):
        while True:
            s = input(prompt).strip()
            if allow_blank and not s:
                return ""
            try:
                datetime.strptime(s, "%Y-%m-%d")
                return s
            except ValueError:
                print("  ⚠️  Sai định dạng, cần YYYY-MM-DD (vd 2026-06-08). Thử lại.")

    from_str = _ask("  Từ ngày (YYYY-MM-DD): ")
    to_str = _ask("  Đến ngày (YYYY-MM-DD, Enter = cùng ngày): ", allow_blank=True) or from_str
    start_utc, end_utc, days = range_to_utc(from_str, to_str)
    print(f"  → {from_str} → {to_str} ({SELLER_TZ_NAME}) = UTC [{start_utc} .. {end_utc})"
          f"  ({len(days)} ngày)")
    return start_utc, end_utc, days


def env_overrides_present(*names) -> bool:
    """True nếu bất kỳ biến env nào trong danh sách đã được điền (không rỗng)."""
    return any(os.getenv(n, "").strip() for n in names)
