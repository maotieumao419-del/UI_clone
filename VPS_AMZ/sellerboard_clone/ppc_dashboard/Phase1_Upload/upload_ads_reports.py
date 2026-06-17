"""Phase1_Upload (ppc) — đọc data/ads_reports/*.json.gz → PPC_Phase1_*_daily.

Đọc raw report do Phase1_Fetch lưu (KHÔNG gọi API), map sang bảng PPC_Phase1_*
qua db_writer. Ads report lưu theo TỪNG NGÀY → upload lặp ngày.

  sp_campaigns  → PPC_Phase1_campaigns_daily
  sp_adgroups   → PPC_Phase1_adgroups_daily
  sp_keywords   → PPC_Phase1_keywords_daily
  sp_targeting  → PPC_Phase1_targets_daily
  sp_searchterm → PPC_Phase1_searchterms_daily
  sp_placement  → PPC_Phase1_placement_daily

Chạy:
    python upload_ads_reports.py --date 2026-06-15
    python upload_ads_reports.py --from 2026-06-01 --to 2026-06-15
"""
import argparse
import gc
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]   # sellerboard_clone
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# Cho phép `import db_writer` (cùng thư mục) khi gọi qua subprocess/orchestrator
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from shared.supabase_client import get_supabase_client
from shared.timeutils import date_range_pacific, yesterday_pacific
from Phase1_Fetch.paths import ads_report_file, read_json_gz

import db_writer as db

# file_key → hàm write tương ứng (đều nhận (client, data, report_date))
REPORT_MAP = [
    ("sp_campaigns",  db.write_campaigns_daily),
    ("sp_adgroups",   db.write_adgroups_daily),
    ("sp_keywords",   db.write_keywords_daily),
    ("sp_targeting",  db.write_targets_daily),
    ("sp_searchterm", db.write_searchterms_daily),
    ("sp_placement",  db.write_placement_daily),
]


def upload_for_date(client, date_str: str) -> dict:
    totals = {}
    for file_key, write_fn in REPORT_MAP:
        path = ads_report_file(date_str, file_key)
        data = read_json_gz(path)
        if not data:
            continue
        n = write_fn(client, data, date_str)
        totals[file_key] = n
        del data
        gc.collect()
    return totals


def main():
    ap = argparse.ArgumentParser(description="Upload ads reports → PPC_Phase1_*_daily")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    args = ap.parse_args()

    if args.date:
        dates = [args.date]
    elif args.from_date:
        end = args.to_date or args.from_date
        dates = [str(d) for d in date_range_pacific(args.from_date, end)]
    else:
        dates = [str(yesterday_pacific())]

    client = get_supabase_client()
    for d in dates:
        print(f"\n--- PPC ads reports {d} ---")
        upload_for_date(client, d)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
