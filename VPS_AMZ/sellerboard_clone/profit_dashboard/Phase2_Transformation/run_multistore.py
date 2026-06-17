"""Phase 2 — Multi-tenant runner (Physical Sharding: mỗi store 1 Supabase project).

Đọc danh sách store từ `stores.json` (cùng thư mục, KHÔNG commit — chứa key):
{
  "MORY": {"SUPABASE_URL": "https://xxx.supabase.co", "SUPABASE_SERVICE_KEY": "..."},
  "LLH":  {"SUPABASE_URL": "https://yyy.supabase.co", "SUPABASE_SERVICE_KEY": "..."}
}

Chạy:
  python run_multistore.py --date 2026-06-10                 # 1 ngày, mọi store
  python run_multistore.py --date 2026-06-10 --calibrate     # học fee cache trước
  python run_multistore.py --date 2026-06-10 --store MORY    # chỉ 1 store
  python run_multistore.py --date 2026-06-10 --no-write      # chỉ tính

1 store lỗi KHÔNG chặn store sau (isolation) — exit code != 0 nếu có store lỗi.
"""
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transform_engine import run_transformation

STORES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stores.json")


def load_stores() -> dict[str, dict]:
    if not os.path.exists(STORES_FILE):
        raise FileNotFoundError(
            f"Thiếu {STORES_FILE} — tạo theo mẫu trong docstring (không commit).")
    with open(STORES_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 2 multi-store (loop run_transformation)")
    ap.add_argument("--date", required=True, help="Ngày YYYY-MM-DD (Pacific)")
    ap.add_argument("--days", type=int, help="Cửa sổ N ngày kết thúc tại --date")
    ap.add_argument("--store", help="Chỉ chạy 1 store (mặc định: tất cả trong stores.json)")
    ap.add_argument("--calibrate", action="store_true", help="Học Profit_Phase1_fee_cache trước transform")
    ap.add_argument("--fresh", action="store_true", help="Xóa 3 bảng Master trước khi ghi")
    ap.add_argument("--no-write", action="store_true", help="Chỉ tính, không ghi")
    args = ap.parse_args()

    from supabase import create_client
    stores = load_stores()
    if args.store:
        if args.store not in stores:
            ap.error(f"Store '{args.store}' không có trong stores.json ({list(stores)})")
        stores = {args.store: stores[args.store]}

    failed = []
    for name, conf in stores.items():
        print(f"\n{'=' * 60}\n🏬 STORE: {name}\n{'=' * 60}")
        try:
            client = create_client(conf["SUPABASE_URL"], conf["SUPABASE_SERVICE_KEY"])
            result = run_transformation(
                client, args.date, days=args.days, write=not args.no_write,
                fresh=args.fresh, calibrate=args.calibrate)
            t = result["totals"]
            w = result.get("written", {})
            print(f"✅ {name}: {t.get('orders', 0)} đơn, sales ${t.get('sales', 0):,.2f}, "
                  f"net ${t.get('net_profit', 0):,.2f}"
                  + (f" — ghi {w}" if w else " (no-write)"))
        except Exception as exc:                       # noqa: BLE001 — isolation per store
            failed.append(name)
            print(f"❌ {name} LỖI: {exc}")
            traceback.print_exc()
    if failed:
        print(f"\n⚠️  Store lỗi: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except Exception:                          # noqa: BLE001
                pass
    sys.exit(main())
