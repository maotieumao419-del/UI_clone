"""Phase 2 — Seed/override giá vào Profit_Phase1_product_price từ file "Products" của Sellerboard.

Bảng Profit_Phase1_product_price tự tích lũy giá từ đơn Shipped (Phase 1). Nhưng SKU mới
CHƯA TỪNG ship (vd chỉ có đơn Pending) thì chưa có giá → impute fail. Dùng
importer này seed giá list (Average Sales Price) cho các SKU đó từ báo cáo
Products của Sellerboard. source='manual' — đơn Shipped thật sau này sẽ ghi đè.

Chạy:
    python import_price_from_csv.py "<Sellerboard Products CSV>"
    python import_price_from_csv.py "<csv>" --only SKU1,SKU2   # chỉ seed vài SKU
    python import_price_from_csv.py "<csv>" --dry-run
"""
import argparse
import csv
import os
import sys

from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

T_PRICE = "Profit_Phase1_product_price"


def get_supabase_client():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise ValueError("Thiếu SUPABASE_URL / SUPABASE_SERVICE_KEY trong .env")
    from supabase import create_client
    return create_client(url, key)


def _num(v) -> float:
    s = str(v or "").strip().replace("$", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_rows(path: str, only: set | None) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        rows = []
        for r in reader:
            keys = {k.strip().lower(): k for k in r}
            sku = (r.get(keys.get("sku", "")) or "").strip()
            if not sku or (only and sku not in only):
                continue
            # ưu tiên Average Sales Price; fallback Sales/Units
            price = _num(r.get(keys.get("average sales price", "")))
            if price <= 0:
                sales = _num(r.get(keys.get("sales", "")))
                units = _num(r.get(keys.get("units", "")))
                price = round(sales / units, 2) if units > 0 else 0.0
            if price > 0:
                rows.append({"sku": sku, "unit_price": round(price, 2), "source": "manual"})
    # dedupe theo sku (giữ dòng đầu)
    seen, out = set(), []
    for r in rows:
        if r["sku"] not in seen:
            seen.add(r["sku"])
            out.append(r)
    return out


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", help="Sellerboard Products CSV (có cột Average Sales Price)")
    ap.add_argument("--only", help="Chỉ seed các SKU này (phẩy ngăn cách)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    only = set(s.strip() for s in args.only.split(",")) if args.only else None
    rows = parse_rows(args.csv_path, only)
    print(f"Đọc được {len(rows)} SKU có giá từ {os.path.basename(args.csv_path)}:")
    for r in rows:
        print(f"  {r['sku']:<26} ${r['unit_price']}")
    if not rows or args.dry_run:
        print("\n[DRY-RUN] Không ghi." if args.dry_run else "Không có dòng hợp lệ.")
        return 0
    get_supabase_client().table(T_PRICE).upsert(rows, on_conflict="sku").execute()
    print(f"\n✅ Đã upsert {len(rows)} giá vào {T_PRICE} (source=manual).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
