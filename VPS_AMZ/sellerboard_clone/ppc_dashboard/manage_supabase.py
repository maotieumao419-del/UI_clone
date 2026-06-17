"""PPC dashboard — quản lý vòng đời dữ liệu Supabase (archive / hydrate / prune).

Lớp MỎNG: registry tên bảng PPC_*; logic chung ở shared/. Xem profit_dashboard/
manage_supabase.py cho ý nghĩa lệnh — giống hệt, chỉ khác bảng.

Lệnh:
    python manage_supabase.py archive --from 2026-06-01 --to 2026-06-15
    python manage_supabase.py prune
    python manage_supabase.py hydrate --from 2026-01-01 --to 2026-01-31
    python manage_supabase.py evict   --from 2026-01-01 --to 2026-01-31

Snapshot mgmt (PPC_Phase1_portfolios/campaigns_raw/adgroups_raw/keywords_raw/
targets_raw) KHÔNG prune theo ngày — bị ghi đè mỗi lần fetch (PK = id thực thể),
dung lượng bounded theo số thực thể. bid_recommendations prune theo snapshot_date.
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

# ── Registry: bảng SUMMARY (archive/hydrate) — tất cả theo report_date ─────────
ARCHIVE_SPECS = [
    {"table": "PPC_Phase2_summary_campaigns",   "day_col": "report_date",
     "conflict": "report_date,campaign_id"},
    {"table": "PPC_Phase2_summary_adgroups",    "day_col": "report_date",
     "conflict": "report_date,adgroup_id"},
    {"table": "PPC_Phase2_summary_keywords",    "day_col": "report_date",
     "conflict": "report_date,keyword_id"},
    {"table": "PPC_Phase2_summary_searchterms", "day_col": "report_date",
     "conflict": "report_date,campaign_id,adgroup_id,keyword_id,query"},
    {"table": "PPC_Phase2_summary_portfolios",  "day_col": "report_date",
     "conflict": "report_date,portfolio_id"},
]

# ── Registry: RAW daily (prune theo cửa sổ raw) ───────────────────────────────
PRUNE_RAW = [
    {"table": "PPC_Phase1_campaigns_daily",   "date_col": "report_date"},
    {"table": "PPC_Phase1_adgroups_daily",    "date_col": "report_date"},
    {"table": "PPC_Phase1_keywords_daily",    "date_col": "report_date"},
    {"table": "PPC_Phase1_targets_daily",     "date_col": "report_date"},
    {"table": "PPC_Phase1_searchterms_daily", "date_col": "report_date"},
    {"table": "PPC_Phase1_placement_daily",   "date_col": "report_date"},
    {"table": "PPC_Phase1_bid_recommendations", "date_col": "snapshot_date"},
]

# ── Registry: SUMMARY (prune theo cửa sổ summary) ─────────────────────────────
PRUNE_SUMMARY = [
    {"table": "PPC_Phase2_summary_campaigns",   "date_col": "report_date"},
    {"table": "PPC_Phase2_summary_adgroups",    "date_col": "report_date"},
    {"table": "PPC_Phase2_summary_keywords",    "date_col": "report_date"},
    {"table": "PPC_Phase2_summary_searchterms", "date_col": "report_date"},
    {"table": "PPC_Phase2_summary_portfolios",  "date_col": "report_date"},
    {"table": "PPC_Phase2_bulk_sp",             "date_col": "period_end"},
]


def _days(args) -> list[str]:
    if args.date:
        return [args.date]
    if args.from_date:
        return list(iter_days(args.from_date, args.to_date or args.from_date))
    raise SystemExit("Cần --date hoặc --from/--to")


def main():
    ap = argparse.ArgumentParser(description="PPC — quản lý dữ liệu Supabase")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("archive", "hydrate", "evict"):
        p = sub.add_parser(name)
        p.add_argument("--date"); p.add_argument("--from", dest="from_date")
        p.add_argument("--to", dest="to_date")
    pp = sub.add_parser("prune")
    pp.add_argument("--window", type=int)
    pp.add_argument("--raw-window", type=int)
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
        print("✅ Prune xong. Snapshot mgmt không prune (bounded). Dữ liệu cũ ở archive local.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
