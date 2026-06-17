"""Phase 1 phụ — Lấy ảnh sản phẩm từ SP-API Catalog Items -> products.image_url.

Quy trình:
  1. Quét DISTINCT asin từ Profit_Phase1_sp_order_items (+ asin trong products còn thiếu ảnh).
  2. Gọi searchCatalogItems (catalog 2022-04-01) theo LÔ 20 ASIN/request,
     includedData=images -> lấy link ảnh MAIN.
  3. UPDATE products.image_url theo asin (KHÔNG insert dòng mới — products là
     bảng SỐNG của web app, chỉ điền thêm cột ảnh).

Chạy:
  python fetch_product_images.py            # chỉ điền ASIN chưa có ảnh
  python fetch_product_images.py --refresh  # ghi đè ảnh cho TẤT CẢ ASIN tìm được

Rate limit Catalog Items: 2 req/s (burst 2) — giãn cách CATALOG_DELAY (mặc định 0.6s).
"""
import argparse
import sys
import time

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from amz_spapi_client import MARKETPLACE_ID, auth_session, spapi_get
from direct_stream_pipeline import get_supabase_client

CATALOG_PATH = "/catalog/2022-04-01/items"
BATCH = 20                       # searchCatalogItems nhận tối đa 20 identifiers
CATALOG_DELAY = 0.6


def _pick_main_link(item: dict) -> str | None:
    """images[0].link theo nghĩa 'ảnh MAIN, bản to nhất'."""
    for by_marketplace in item.get("images", []):
        imgs = by_marketplace.get("images", [])
        main = [i for i in imgs if i.get("variant") == "MAIN"] or imgs
        if main:
            return max(main, key=lambda i: i.get("height", 0)).get("link")
    return None


def collect_asins(sb, refresh: bool) -> list[str]:
    asins: set[str] = set()
    for r in sb.table("Profit_Phase1_sp_order_items").select("asin").execute().data:
        if r.get("asin"):
            asins.add(r["asin"])
    # ASIN có trong products nhưng chưa có ảnh (phủ luôn SKU cũ không nằm trong đơn gần đây)
    for r in sb.table("products").select("asin,image_url").execute().data:
        if r.get("asin") and (refresh or not r.get("image_url")):
            asins.add(r["asin"])
    if not refresh:
        done = {r["asin"] for r in sb.table("products")
                .select("asin,image_url").not_.is_("image_url", "null").execute().data}
        asins -= done
    return sorted(asins)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                    help="Ghi đè image_url kể cả ASIN đã có ảnh")
    args = ap.parse_args()

    sb = get_supabase_client()
    asins = collect_asins(sb, args.refresh)
    if not asins:
        print("✅ Không có ASIN nào cần lấy ảnh.")
        return 0
    print(f"Cần lấy ảnh cho {len(asins)} ASIN ({(len(asins) + BATCH - 1) // BATCH} request)...")

    session = auth_session()
    lwa, sk, ss, st = session
    found: dict[str, str] = {}
    for i in range(0, len(asins), BATCH):
        chunk = asins[i: i + BATCH]
        resp = spapi_get(CATALOG_PATH, {
            "identifiers": ",".join(chunk),
            "identifiersType": "ASIN",
            "marketplaceIds": MARKETPLACE_ID,
            "includedData": "images",
            "pageSize": BATCH,
        }, lwa, sk, ss, st)
        for item in resp.get("items", []):
            link = _pick_main_link(item)
            if link:
                found[item.get("asin", "")] = link
        print(f"  [Catalog] {i + len(chunk)}/{len(asins)} ASIN — có ảnh: {len(found)}")
        time.sleep(CATALOG_DELAY)

    updated = 0
    for asin, link in found.items():
        r = sb.table("products").update({"image_url": link}).eq("asin", asin).execute()
        updated += len(r.data or [])
    missing = [a for a in asins if a not in found]
    print(f"\n✅ Cập nhật image_url cho {updated} dòng products ({len(found)} ASIN có ảnh).")
    if missing:
        print(f"⚠️  {len(missing)} ASIN không tìm thấy ảnh: {', '.join(missing[:10])}"
              + (" ..." if len(missing) > 10 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
