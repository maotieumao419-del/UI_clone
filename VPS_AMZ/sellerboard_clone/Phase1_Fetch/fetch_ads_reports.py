"""Phase1_Fetch — Ads Reports API v3: TẤT CẢ report types, gọi 1 lần/ngày.

Lưu mỗi report type 1 file:
  data/ads_reports/YYYY-MM-DD_<file_key>.json.gz   (vd 2026-06-15_sp_campaigns.json.gz)

spCampaigns dùng chung cho cả profit + ppc → chỉ tải 1 lần, 2 upload script đọc
cùng file. KHÔNG ghi Supabase, KHÔNG transform — lưu nguyên list rows Amazon trả.

Giãn cách REQUEST_GAP giữa các lần POST tạo report (throttle Ads API rất chặt).
Replay: file đã tồn tại → skip (dùng --force để ghi đè).

Chạy:
    python fetch_ads_reports.py --date 2026-06-15
    python fetch_ads_reports.py --from 2026-06-01 --to 2026-06-15
    python fetch_ads_reports.py --date 2026-06-15 --only sp_campaigns,sp_keywords
    python fetch_ads_reports.py --date 2026-06-15 --consumer ppc   # chỉ report ppc cần
"""
import argparse
import gc
import gzip
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from shared.amz_auth import get_ads_token
from shared.config import REQUEST_GAP
from shared.ads_api import request_report, poll_until_done, download_report
from shared.timeutils import yesterday_pacific
from Phase1_Fetch.paths import ads_report_file, write_json_gz, iter_days

from ads_report_configs import REPORT_JOBS


def fetch_reports_for_date(lwa_ads: str, date_str: str, jobs: list, force=False) -> dict:
    """Tạo tất cả report cho 1 ngày (POST đồng loạt giãn cách), rồi poll + download.
    Lưu vào data/YYYY/MM/DD/ads_<file_key>.json.gz"""
    print(f"\n--- Ads reports {date_str} ---")
    totals = {}

    # B1: POST tạo tất cả report (giãn cách REQUEST_GAP)
    pending = []   # (file_key, name, report_id)
    for file_key, name, config, _consumers in jobs:
        out_path = ads_report_file(date_str, file_key)
        if out_path.exists() and not force:
            print(f"  [{name}] Đã có {out_path.name} — skip")
            continue
        try:
            rid = request_report(lwa_ads, config, name, date_str)
        except Exception as exc:
            print(f"  ⚠️  {name}: tạo report lỗi: {exc} — bỏ qua")
            rid = ""
        pending.append((file_key, name, rid))
        time.sleep(REQUEST_GAP)

    # B2: Poll + download từng report
    for file_key, name, rid in pending:
        if not rid:
            continue
        url = poll_until_done(lwa_ads, rid, name)
        if not url:
            continue
        rows = download_report(url)
        write_json_gz(ads_report_file(date_str, file_key), rows)
        print(f"  ✅ {name}: {len(rows)} rows → ads_{file_key}.json.gz")
        totals[file_key] = len(rows)
        del rows
        gc.collect()

    return totals


def main():
    ap = argparse.ArgumentParser(description="Fetch Ads Reports → data/ads_reports/")
    ap.add_argument("--date",  help="Đúng 1 ngày YYYY-MM-DD (Pacific)")
    ap.add_argument("--from",  dest="from_date")
    ap.add_argument("--to",    dest="to_date")
    ap.add_argument("--force", action="store_true", help="Ghi đè file đã có")
    ap.add_argument("--only",  help="Chỉ fetch các file_key này (phân tách dấu phẩy)")
    ap.add_argument("--consumer", choices=["profit", "ppc"],
                    help="Chỉ fetch report mà dashboard này cần")
    args = ap.parse_args()

    # Lọc danh sách jobs
    jobs = REPORT_JOBS
    if args.consumer:
        jobs = [j for j in jobs if args.consumer in j[3]]
    if args.only:
        keys = {k.strip() for k in args.only.split(",")}
        jobs = [j for j in jobs if j[0] in keys]
    if not jobs:
        print("Không có report nào khớp filter."); return 1

    # Khoảng ngày
    if args.date:
        dates = [args.date]
    elif args.from_date:
        dates = list(iter_days(args.from_date, args.to_date or args.from_date))
    else:
        dates = [str(yesterday_pacific())]

    lwa_ads = get_ads_token()
    print(f"\n=== FETCH ADS REPORTS: {len(dates)} ngày, {len(jobs)} report types ===")
    grand = {}
    for d in dates:
        result = fetch_reports_for_date(lwa_ads, d, jobs, force=args.force)
        for k, v in result.items():
            grand[k] = grand.get(k, 0) + v
    print(f"\n✅ Ads reports fetch hoàn tất: {grand}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main() or 0)
