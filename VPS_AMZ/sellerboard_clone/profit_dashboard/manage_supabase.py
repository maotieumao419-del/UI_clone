"""Profit dashboard — quản lý vòng đời dữ liệu Supabase (archive / hydrate / prune).

Lớp MỎNG: chỉ khai báo registry tên bảng Profit_*; logic chung ở shared/.

Lệnh:
    # Sau Phase2 transform — lưu summary ra local archive:
    python manage_supabase.py archive --from 2026-06-01 --to 2026-06-15

    # Dọn Supabase về cửa sổ 62 ngày (raw + summary), chạy định kỳ:
    python manage_supabase.py prune

    # Xem khoảng cũ (ngoài 62 ngày) — nạp tạm từ local lên Supabase:
    python manage_supabase.py hydrate --from 2026-01-01 --to 2026-01-31

    # Xem xong, giải phóng:
    python manage_supabase.py evict --from 2026-01-01 --to 2026-01-31

Bảng PERSISTENT (KHÔNG prune): Profit_Phase1_product_price / _product_cogs /
_fee_cache — dữ liệu tích lũy, không theo ngày.
"""
import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]            # sellerboard_clone
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / "Phase1_Upload" / ".env")

from shared.supabase_client import get_supabase_client
from shared.retention import prune_tables, WINDOW_DAYS, RAW_WINDOW_DAYS
from shared.summary_archive import archive_days, hydrate_days, evict_days
from Phase1_Fetch.paths import summary_file, iter_days

# ── Registry: bảng SUMMARY để archive/hydrate ─────────────────────────────────
ARCHIVE_SPECS = [
    {"table": "Profit_Phase2_summary_products",       "period": True,
     "conflict": "owner_id,period_start,period_end,asin,sku"},
    {"table": "Profit_Phase2_summary_order_items",    "day_col": "order_date",
     "conflict": "owner_id,order_number,asin,sku,row_type"},
    {"table": "Profit_Phase2_summary_campaigns",      "period": True,
     "conflict": "period_start,period_end,campaign_id"},
    {"table": "Profit_Phase2_summary_reimbursements", "period": True,
     "conflict": "owner_id,period_start,period_end,adjustment_type,asin,sku"},
]

# ── Registry: bảng RAW (prune theo cửa sổ raw) ────────────────────────────────
PRUNE_RAW = [
    {"table": "Profit_Phase1_sp_orders",          "date_col": "purchase_date"},
    {"table": "Profit_Phase1_sp_order_items",     "date_col": "synced_at"},
    {"table": "Profit_Phase1_fin_item_fees",      "date_col": "posted_date"},
    {"table": "Profit_Phase1_fin_refunds",        "date_col": "posted_date"},
    {"table": "Profit_Phase1_fin_adjustments",    "date_col": "posted_date"},
    {"table": "Profit_Phase1_ads_campaigns_daily", "date_col": "report_date"},
    {"table": "Profit_Phase1_ads_sp_asin_daily",  "date_col": "report_date"},
]

# ── Registry: bảng SUMMARY (prune theo cửa sổ summary) ────────────────────────
PRUNE_SUMMARY = [
    {"table": "Profit_Phase2_summary_products",       "date_col": "period_end"},
    {"table": "Profit_Phase2_summary_order_items",    "date_col": "order_date"},
    {"table": "Profit_Phase2_summary_campaigns",      "date_col": "period_end"},
    {"table": "Profit_Phase2_summary_reimbursements", "date_col": "period_end"},
]


def _days(args) -> list[str]:
    if args.date:
        return [args.date]
    if args.from_date:
        return list(iter_days(args.from_date, args.to_date or args.from_date))
    raise SystemExit("Cần --date hoặc --from/--to")


def main():
    ap = argparse.ArgumentParser(description="Profit — quản lý dữ liệu Supabase")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("archive", "hydrate", "evict"):
        p = sub.add_parser(name)
        p.add_argument("--date"); p.add_argument("--from", dest="from_date")
        p.add_argument("--to", dest="to_date")
    pp = sub.add_parser("prune")
    pp.add_argument("--window", type=int, help=f"Ghi đè cửa sổ summary (mặc định {WINDOW_DAYS})")
    pp.add_argument("--raw-window", type=int, help=f"Ghi đè cửa sổ raw (mặc định {RAW_WINDOW_DAYS})")
    args = ap.parse_args()

    client = get_supabase_client()

    if args.cmd == "archive":
        print(f"\n=== ARCHIVE summary → local ({len(_days(args))} ngày) ===")
        print(archive_days(client, _days(args), ARCHIVE_SPECS, summary_file))
    elif args.cmd == "hydrate":
        print(f"\n=== HYDRATE local → Supabase ({len(_days(args))} ngày) ===")
        print(hydrate_days(client, _days(args), ARCHIVE_SPECS, summary_file))
    elif args.cmd == "evict":
        print(f"\n=== EVICT khỏi Supabase ({len(_days(args))} ngày) ===")
        print(evict_days(client, _days(args), ARCHIVE_SPECS))
    elif args.cmd == "prune":
        sw = args.window or WINDOW_DAYS
        rw = args.raw_window or RAW_WINDOW_DAYS
        print(f"\n=== PRUNE: raw>{rw}d, summary>{sw}d ===")
        prune_tables(client, PRUNE_RAW, rw)
        prune_tables(client, PRUNE_SUMMARY, sw)
        print("✅ Prune xong — Supabase đã về cửa sổ. Dữ liệu cũ vẫn ở archive local.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
