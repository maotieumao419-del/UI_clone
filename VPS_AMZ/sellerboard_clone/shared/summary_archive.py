"""Shared — Archive & Hydrate bảng summary Phase2 giữa Supabase ↔ local gz.

Vì Supabase chỉ giữ cửa sổ ~62 ngày, summary cũ hơn được lưu ở local
(data/YYYY/MM/DD/summary_<table>.json.gz). Khi UI chọn khoảng cũ → hydrate từ
local lên Supabase (KHÔNG transform lại) → xem xong → evict.

  archive_days : Supabase → local gz  (chạy sau Phase2 transform, trước prune)
  hydrate_days : local gz → Supabase   (khi xem khoảng ngoài cửa sổ)
  evict_days   : xóa khoảng đã hydrate khỏi Supabase (sau khi xem)

Chỉ áp cho bảng SUMMARY (đã tính toán). Raw KHÔNG cần — đã có sẵn trong file
fetch local (orders/finances/ads gz), tái upload được.

Mỗi spec: {"table", "day_col", "period" (bool), "conflict"}.
  period=True  → bản ghi NGÀY có period_start==period_end==day (profit summary).
  period=False → lọc thẳng day_col == day (ppc report_date, order_date).

path_fn(day, table) -> Path do caller truyền (thường Phase1_Fetch.paths.summary_file)
để shared/ không phụ thuộc cứng vào layout thư mục.
"""
import gzip
import json

from shared.supabase_client import fetch_all, upsert_chunks


def _read_day(client, table: str, spec: dict, day: str) -> list[dict]:
    def q():
        sel = client.table(table).select("*")
        if spec.get("period"):
            return sel.eq("period_start", day).eq("period_end", day)
        return sel.eq(spec["day_col"], day)
    return fetch_all(q)


def _write_gz(path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)


def _read_gz(path) -> list:
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def archive_days(client, days: list[str], specs: list[dict], path_fn) -> dict:
    """Supabase → local gz cho từng (ngày, bảng summary)."""
    totals = {}
    for day in days:
        for spec in specs:
            table = spec["table"]
            rows = _read_day(client, table, spec, day)
            if not rows:
                continue
            _write_gz(path_fn(day, table), rows)
            totals[table] = totals.get(table, 0) + len(rows)
            print(f"  📦 archive {table} {day}: {len(rows)} rows")
    return totals


def hydrate_days(client, days: list[str], specs: list[dict], path_fn) -> dict:
    """local gz → Supabase (upsert) cho khoảng cũ muốn xem."""
    totals = {}
    for day in days:
        for spec in specs:
            table = spec["table"]
            rows = _read_gz(path_fn(day, table))
            if not rows:
                continue
            n = upsert_chunks(client, table, rows, spec["conflict"])
            totals[table] = totals.get(table, 0) + n
            print(f"  💧 hydrate {table} {day}: +{n}")
    return totals


def evict_days(client, days: list[str], specs: list[dict]) -> dict:
    """Xóa khoảng đã hydrate khỏi Supabase (giải phóng sau khi xem)."""
    totals = {}
    for day in days:
        for spec in specs:
            table = spec["table"]
            try:
                if spec.get("period"):
                    client.table(table).delete().eq("period_start", day).eq("period_end", day).execute()
                else:
                    client.table(table).delete().eq(spec["day_col"], day).execute()
                totals[table] = totals.get(table, 0) + 1
            except Exception as exc:                   # noqa: BLE001
                print(f"  ⚠️  evict {table} {day} lỗi: {exc}")
    return totals
