"""Shared — Retention / prune: giữ Supabase ở cửa sổ trượt cố định.

Mô hình (đã thống nhất): Supabase chỉ giữ ~WINDOW_DAYS ngày gần nhất của CẢ raw
lẫn summary; dữ liệu cũ hơn vẫn còn trong archive local (Phase1_Fetch/data/ +
summary_*.json.gz). Job prune chạy định kỳ xóa phần rơi ra ngoài cửa sổ → dung
lượng Supabase ĐỨNG YÊN bất kể chạy bao lâu (chống tràn 500MB free tier).

Config qua .env:
  SUPABASE_WINDOW_DAYS=62     # cửa sổ chung (mặc định 2 tháng)
  SUPABASE_RAW_WINDOW_DAYS=   # ghi đè riêng cho raw nếu search terms phình to

Import:
    from shared.retention import cutoff_date, prune_tables
"""
import os
from datetime import timedelta

from shared.timeutils import today_pacific

WINDOW_DAYS     = int(os.getenv("SUPABASE_WINDOW_DAYS", "62"))
RAW_WINDOW_DAYS = int(os.getenv("SUPABASE_RAW_WINDOW_DAYS", str(WINDOW_DAYS)))


def cutoff_date(window_days: int) -> str:
    """Ngày ranh giới (ISO) — bản ghi có date_col < ngày này sẽ bị xóa."""
    return (today_pacific() - timedelta(days=window_days)).isoformat()


def prune_tables(client, specs: list[dict], window_days: int) -> dict:
    """Xóa rows cũ hơn cửa sổ.

    specs: list {"table": str, "date_col": str}. Bảng persistent (price/cogs/
    fee_cache) hoặc snapshot bounded (mgmt raw) KHÔNG đưa vào đây.

    Trả {table: cutoff} đã prune. PostgREST so ISO được cho cả DATE lẫn TIMESTAMPTZ.
    """
    cutoff = cutoff_date(window_days)
    result = {}
    for spec in specs:
        table, date_col = spec["table"], spec["date_col"]
        try:
            client.table(table).delete().lt(date_col, cutoff).execute()
            result[table] = cutoff
            print(f"  🧹 prune {table}: xóa {date_col} < {cutoff}")
        except Exception as exc:                       # noqa: BLE001 — 1 bảng lỗi không chặn cả batch
            print(f"  ⚠️  prune {table} lỗi: {exc}")
    return result
