"""Phase1_Fetch — Ảnh sản phẩm từ SP-API Catalog Items (theo ASIN).

Quét ASIN từ các file orders local đã fetch (data/YYYY/MM/DD/orders.jsonl.gz),
gọi searchCatalogItems (catalog 2022-04-01) lấy ảnh MAIN, lưu MAP TÍCH LUỸ:
  data/_persistent/product_images.json.gz   {asin: {image_url, updated_at}}

Ảnh đổi rất chậm → mặc định CHỈ lấy ASIN chưa có ảnh trong map. --refresh để lấy lại hết.
KHÔNG ghi Supabase (đó là việc của Phase1_Upload/upload_images.py).

Chạy:
    python fetch_images.py                       # quét ASIN từ TẤT CẢ orders local
    python fetch_images.py --from 2026-06-01 --to 2026-06-16
    python fetch_images.py --refresh
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import requests
from shared.amz_auth import get_lwa_token
from shared.config import SP_BASE, MARKETPLACE_ID
from Phase1_Fetch.paths import (orders_file, product_images_file, read_jsonl_gz,
                                read_json_gz, write_json_gz, iter_days, DATA_DIR)

CATALOG_PATH  = "/catalog/2022-04-01/items"
BATCH         = 20
CATALOG_DELAY = 0.6


def _catalog_get(params, lwa, retries=5):
    headers = {"x-amz-access-token": lwa, "content-type": "application/json"}
    for attempt in range(retries):
        r = requests.get(f"{SP_BASE}{CATALOG_PATH}", params=params, headers=headers, timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            wait = max(float(r.headers.get("Retry-After", 2.0)), 2.0) + attempt
            print(f"    ⚠️  429 catalog → đợi {wait:.0f}s"); time.sleep(wait); continue
        if not r.ok:
            print(f"    ❌ {r.status_code} catalog: {r.text[:200]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Hết retry catalog")


def _pick_main_link(item: dict) -> str | None:
    for by_mp in item.get("images", []):
        imgs = by_mp.get("images", [])
        main = [i for i in imgs if i.get("variant") == "MAIN"] or imgs
        if main:
            return max(main, key=lambda i: i.get("height", 0)).get("link")
    return None


def _collect_asins_from_orders(days: list[str] | None) -> set[str]:
    """ASIN từ orders local. days=None → quét TẤT CẢ file orders trong data/."""
    asins: set[str] = set()
    if days:
        files = [orders_file(d) for d in days]
    else:
        files = list(DATA_DIR.glob("**/orders.jsonl.gz"))
    for path in files:
        for order in read_jsonl_gz(path):
            for it in order.get("_items") or []:
                a = it.get("ASIN")
                if a:
                    asins.add(a)
    return asins


def main():
    ap = argparse.ArgumentParser(description="Fetch product images → data/_persistent/")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    ap.add_argument("--refresh", action="store_true", help="Lấy lại ảnh kể cả ASIN đã có")
    args = ap.parse_args()

    days = None
    if args.from_date:
        days = list(iter_days(args.from_date, args.to_date or args.from_date))

    img_path = product_images_file()
    existing = read_json_gz(img_path)
    img_map = existing if isinstance(existing, dict) else {}

    asins = _collect_asins_from_orders(days)
    if not args.refresh:
        asins = {a for a in asins if a not in img_map}
    asins = sorted(asins)
    if not asins:
        print("✅ Không có ASIN nào cần lấy ảnh (map đã đủ)."); return 0

    print(f"Cần ảnh cho {len(asins)} ASIN ({(len(asins)+BATCH-1)//BATCH} request)...")
    lwa = get_lwa_token(cache_key="spapi")
    now = datetime.now(timezone.utc).isoformat()
    found = 0
    for i in range(0, len(asins), BATCH):
        chunk = asins[i:i+BATCH]
        resp = _catalog_get({
            "identifiers": ",".join(chunk), "identifiersType": "ASIN",
            "marketplaceIds": MARKETPLACE_ID, "includedData": "images", "pageSize": BATCH,
        }, lwa)
        for item in resp.get("items", []):
            link = _pick_main_link(item)
            asin = item.get("asin", "")
            if link and asin:
                img_map[asin] = {"image_url": link, "updated_at": now}
                found += 1
        print(f"  [Catalog] {min(i+BATCH,len(asins))}/{len(asins)} — tổng có ảnh: {found}")
        time.sleep(CATALOG_DELAY)

    write_json_gz(img_path, img_map)
    print(f"\n✅ Ảnh: +{found} ASIN → {img_path} (tổng map {len(img_map)})")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main() or 0)
