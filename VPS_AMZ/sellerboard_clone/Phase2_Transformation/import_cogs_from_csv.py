"""Phase 2 — Nhập COGS từ file CSV "Products" export của Sellerboard.

Sellerboard Products CSV (phân tách bằng ';') có cột "Cost of Goods" là TỔNG
giá vốn của kỳ (số âm) và "Units". Per-unit COGS = |Cost of Goods| / Units.
Nạp vào NEW_product_cogs (sku, cog_per_unit, effective_date) để transform_engine
/ aggregator áp COGS FIFO.

effective_date mặc định '2000-01-01' = áp cho MỌI ngày mua (giá vốn phẳng).
Đổi qua --effective-date nếu giá vốn chỉ hiệu lực từ 1 mốc.

Chạy:
    python import_cogs_from_csv.py "<đường dẫn Products CSV>"
    python import_cogs_from_csv.py "<csv>" --effective-date 2026-06-01 --dry-run
"""
import argparse
import csv
import os
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

T_COGS = "NEW_product_cogs"


def get_supabase_client():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise ValueError("Thiếu SUPABASE_URL / SUPABASE_SERVICE_KEY trong .env")
    from supabase import create_client
    return create_client(url, key)


def _num(val) -> float:
    """'-12,5' / '-12.5' / '' -> float."""
    s = str(val or "").strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_rows(path: str, effective_date: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        rows = []
        for r in reader:
            keys = {k.strip().lower(): k for k in r}
            sku = (r.get(keys.get("sku", "")) or "").strip()
            if not sku:
                continue

            cost_key = keys.get("cost")
            cogs_key = keys.get("cost of goods")
            units_key = keys.get("units")

            if cost_key:
                # Cấu trúc file mới: có cột "Cost" trực tiếp
                cog_val = _num(r[cost_key])
                if cog_val <= 0:
                    continue
                # Xác định ngày hiệu lực
                row_date = (r.get(keys.get("costperiodstartdate", "")) or "").strip()
                if row_date:
                    try:
                        from datetime import datetime
                        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y"):
                            try:
                                parsed_dt = datetime.strptime(row_date, fmt)
                                row_date = parsed_dt.date().isoformat()
                                break
                            except ValueError:
                                continue
                    except Exception:
                        row_date = ""
                eff_date = row_date if row_date else effective_date
                rows.append({
                    "sku": sku,
                    "cog_per_unit": round(cog_val, 2),
                    "effective_date": eff_date,
                    "notes": f"import CSV {os.path.basename(path)}",
                })
            elif cogs_key and units_key:
                # Cấu trúc file cũ: "Cost of Goods" và "Units"
                cogs_total = abs(_num(r[cogs_key]))
                units = int(_num(r[units_key]))
                if cogs_total == 0 or units <= 0:
                    continue
                rows.append({
                    "sku": sku,
                    "cog_per_unit": round(cogs_total / units, 2),
                    "effective_date": effective_date,
                    "notes": f"import CSV {os.path.basename(path)}",
                })
    return rows



def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", help="Đường dẫn file Products CSV của Sellerboard")
    ap.add_argument("--effective-date", default="2000-01-01",
                    help="Ngày hiệu lực giá vốn (YYYY-MM-DD), mặc định 2000-01-01")
    ap.add_argument("--dry-run", action="store_true", help="Chỉ in, không ghi Supabase")
    args = ap.parse_args()

    date.fromisoformat(args.effective_date)  # validate
    rows = parse_rows(args.csv_path, args.effective_date)
    print(f"Đọc được {len(rows)} SKU có COGS từ {os.path.basename(args.csv_path)}:")
    for r in rows:
        print(f"  {r['sku']:<24} ${r['cog_per_unit']}/unit  (eff {r['effective_date']})")
    if not rows:
        print("Không có dòng COGS hợp lệ.")
        return 0
    if args.dry_run:
        print("\n[DRY-RUN] Không ghi Supabase.")
        return 0

    sb = get_supabase_client()
    sb.table(T_COGS).upsert(rows, on_conflict="sku,effective_date").execute()
    print(f"\n✅ Đã upsert {len(rows)} dòng vào {T_COGS}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
