"""Phase1_Upload (profit) — đọc data/_persistent/product_images.json.gz
→ Profit_Phase1_product_images (asin PK, persistent).

Bảng ảnh là PERSISTENT (giống product_price/cogs) — KHÔNG bị prune theo ngày.
Phase 2 / Phase 3 join theo asin để hiện ảnh cho SKU/ASIN.

Chạy:
    python upload_images.py
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from shared.supabase_client import get_supabase_client, upsert_chunks
from Phase1_Fetch.paths import product_images_file, read_json_gz

T_IMAGES = "Profit_Phase1_product_images"


def upload_images(client) -> int:
    img_map = read_json_gz(product_images_file())
    if not isinstance(img_map, dict) or not img_map:
        print("  ⚠️  Chưa có product_images.json.gz — chạy Phase1_Fetch/fetch_images.py trước")
        return 0
    rows = [{"asin": asin, "image_url": v.get("image_url"), "updated_at": v.get("updated_at")}
            for asin, v in img_map.items() if asin and v.get("image_url")]
    n = upsert_chunks(client, T_IMAGES, rows, "asin")
    print(f"  ✅ {T_IMAGES}: +{n} ASIN có ảnh")
    return n


def main():
    client = get_supabase_client()
    print("\n=== Upload product images → Profit_Phase1_product_images ===")
    upload_images(client)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
