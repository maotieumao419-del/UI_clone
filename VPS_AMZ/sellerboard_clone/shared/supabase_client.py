"""Shared — Supabase client singleton + bulk upsert helper.

Import:
    from shared.supabase_client import get_supabase_client, upsert_chunks, fetch_all
"""
import os

from dotenv import load_dotenv

load_dotenv()

_client = None


def get_supabase_client():
    global _client
    if _client is not None:
        return _client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise ValueError("Thiếu SUPABASE_URL / SUPABASE_SERVICE_KEY trong .env")
    from supabase import create_client
    _client = create_client(url, key)
    return _client


def upsert_chunks(client, table: str, rows: list, conflict: str, chunk_size: int = 100) -> int:
    """Bulk upsert rows theo từng chunk <=chunk_size. Trả về tổng số dòng đã gửi."""
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i: i + chunk_size]
        client.table(table).upsert(chunk, on_conflict=conflict).execute()
        total += len(chunk)
    return total


def fetch_all(make_query, page_size: int = 1000) -> list[dict]:
    """Đọc toàn bộ rows qua phân trang .range() (PostgREST giới hạn 1000/lần)."""
    rows: list[dict] = []
    offset = 0
    while True:
        resp = make_query().range(offset, offset + page_size - 1).execute()
        page = resp.data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size
