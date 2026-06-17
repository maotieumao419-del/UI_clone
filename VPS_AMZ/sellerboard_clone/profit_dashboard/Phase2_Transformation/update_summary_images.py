"""Phase 2 (profit) — Điền cột image_url cho bảng summary theo asin.

TÁCH RIÊNG khỏi transform_engine (giữ lõi transform đang chạy ổn định) — chạy SAU
transform. Join Profit_Phase1_product_images (asin → image_url) vào:
  Profit_Phase2_summary_products.image_url
  Profit_Phase2_summary_order_items.image_url

Idempotent: chạy lại chỉ ghi đè cùng giá trị.

Chạy:
    python update_summary_images.py                       # toàn bộ
    python update_summary_images.py --from 2026-06-01 --to 2026-06-16   # giới hạn kỳ
"""
import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / "profit_dashboard" / "Phase1_Upload" / ".env")

from shared.supabase_client import get_supabase_client, fetch_all

T_IMAGES   = "Profit_Phase1_product_images"
T_PRODUCTS = "Profit_Phase2_summary_products"
T_ITEMS    = "Profit_Phase2_summary_order_items"


def _image_map(client) -> dict[str, str]:
    rows = fetch_all(lambda: client.table(T_IMAGES).select("asin,image_url"))
    return {r["asin"]: r["image_url"] for r in rows if r.get("asin") and r.get("image_url")}


def update_images(client, from_date: str = None, to_date: str = None) -> dict:
    imgs = _image_map(client)
    if not imgs:
        print("  ⚠️  Bảng ảnh trống — chạy fetch_images.py + upload_images.py trước")
        return {}
    print(f"  {len(imgs)} ASIN có ảnh")

    totals = {T_PRODUCTS: 0, T_ITEMS: 0}
    for asin, url in imgs.items():
        # Products: lọc theo period_start nếu có khoảng
        q = client.table(T_PRODUCTS).update({"image_url": url}).eq("asin", asin)
        if from_date:
            q = q.gte("period_start", from_date)
        if to_date:
            q = q.lte("period_end", to_date)
        r = q.execute()
        totals[T_PRODUCTS] += len(r.data or [])

        q = client.table(T_ITEMS).update({"image_url": url}).eq("asin", asin)
        if from_date:
            q = q.gte("order_date", from_date)
        if to_date:
            q = q.lte("order_date", to_date)
        r = q.execute()
        totals[T_ITEMS] += len(r.data or [])

    print(f"  ✅ cập nhật image_url: {totals}")
    return totals


def main():
    ap = argparse.ArgumentParser(description="Điền image_url cho summary (profit)")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    args = ap.parse_args()
    client = get_supabase_client()
    print("\n=== Update summary images (join asin) ===")
    update_images(client, args.from_date, args.to_date)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
