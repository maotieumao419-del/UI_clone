"""
Đọc dữ liệu thô từ Supabase (raw_amazon_orders) — không gọi Amazon API.
Mục đích: xem cấu trúc JSON thực tế Amazon trả về để thiết kế schema DB.

Chạy: python inspect_raw_data.py
Output: raw_data/orders_sample.json  — 5 đơn mẫu đầy đủ field
        raw_data/fields_report.txt   — danh sách tất cả field xuất hiện
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SELLER_ID    = os.getenv("SELLER_ID", "musemory@sellervision.io")

OUT_DIR = Path("raw_data")
OUT_DIR.mkdir(exist_ok=True)


def flatten_keys(obj, prefix="") -> set:
    """Đệ quy lấy tất cả key trong JSON lồng nhau."""
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            keys.add(full_key)
            keys |= flatten_keys(v, full_key)
    elif isinstance(obj, list) and obj:
        keys |= flatten_keys(obj[0], prefix + "[]")
    return keys


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Thiếu SUPABASE_URL hoặc SUPABASE_KEY trong .env")
        return

    print(f"Kết nối Supabase: {SUPABASE_URL[:40]}...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # ── Lấy 5 đơn mẫu để xem cấu trúc ──
    print(f"Đọc raw_amazon_orders (seller: {SELLER_ID})...")
    resp = (
        client.table("raw_amazon_orders")
        .select("*")
        .eq("seller_id", SELLER_ID)
        .order("purchase_date", desc=True)
        .limit(5)
        .execute()
    )

    records = resp.data or []
    if not records:
        print("❌ Không có dữ liệu trong raw_amazon_orders")
        return

    print(f"✅ Lấy được {len(records)} đơn mẫu")

    # ── Lưu 5 đơn đầy đủ ra file ──
    sample_file = OUT_DIR / "orders_sample.json"
    with open(sample_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)
    print(f"→ Đã lưu: {sample_file}")

    # ── Phân tích tất cả field trong raw_json ──
    all_order_keys = set()
    all_item_keys  = set()

    for r in records:
        raw = r.get("raw_json") or {}
        if isinstance(raw, str):
            raw = json.loads(raw)

        all_order_keys |= flatten_keys(raw)

        for item in raw.get("order_items", []):
            all_item_keys |= flatten_keys(item)

    # ── In report ──
    report_file = OUT_DIR / "fields_report.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("=== ORDER FIELDS (từ Amazon SP-API) ===\n")
        for k in sorted(all_order_keys):
            f.write(f"  {k}\n")
        f.write("\n=== ORDER ITEM FIELDS ===\n")
        for k in sorted(all_item_keys):
            f.write(f"  {k}\n")

    print(f"→ Đã lưu: {report_file}")

    # In nhanh ra màn hình
    print("\n─── ORDER FIELDS ───")
    for k in sorted(all_order_keys):
        print(f"  {k}")

    print("\n─── ORDER ITEM FIELDS ───")
    for k in sorted(all_item_keys):
        print(f"  {k}")

    # ── Tổng số đơn trong DB ──
    count_resp = (
        client.table("raw_amazon_orders")
        .select("amazon_order_id", count="exact")
        .eq("seller_id", SELLER_ID)
        .execute()
    )
    print(f"\nTổng số đơn trong raw_amazon_orders: {count_resp.count}")


if __name__ == "__main__":
    main()
