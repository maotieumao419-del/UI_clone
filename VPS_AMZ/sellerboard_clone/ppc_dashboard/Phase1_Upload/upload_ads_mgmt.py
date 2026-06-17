"""Phase1_Upload (ppc) — đọc data/ads_mgmt/*.json.gz → PPC_Phase1_*_raw + bid recs.

Đọc snapshot management do Phase1_Fetch/fetch_ads_mgmt.py + fetch_bid_recs.py lưu.
Snapshot KHÔNG theo ngày metric — gắn nhãn snapshot_date (mặc định hôm nay).

  portfolios            → PPC_Phase1_portfolios
  campaigns_raw         → PPC_Phase1_campaigns_raw
  adgroups_raw          → PPC_Phase1_adgroups_raw
  keywords_raw          → PPC_Phase1_keywords_raw
  targets_raw           → PPC_Phase1_targets_raw
  bid_recommendations   → PPC_Phase1_bid_recommendations

Chạy:
    python upload_ads_mgmt.py                    # snapshot hôm nay
    python upload_ads_mgmt.py --date 2026-06-16
"""
import argparse
import gc
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from shared.supabase_client import get_supabase_client
from shared.timeutils import today_pacific
from Phase1_Fetch.paths import ads_mgmt_file, read_json_gz

import db_writer as db


def upload_mgmt(client, snapshot_date: str) -> dict:
    totals = {}

    # Snapshot (không cần report_date)
    snapshots = [
        ("portfolios",    db.write_portfolios),
        ("campaigns_raw", db.write_campaigns_raw),
        ("adgroups_raw",  db.write_adgroups_raw),
        ("keywords_raw",  db.write_keywords_raw),
        ("targets_raw",   db.write_targets_raw),
    ]
    for file_key, write_fn in snapshots:
        data = read_json_gz(ads_mgmt_file(snapshot_date, file_key))
        if not data:
            print(f"  ⚠️  không có {file_key} snapshot {snapshot_date} — bỏ qua")
            continue
        n = write_fn(client, data)
        totals[file_key] = n
        del data
        gc.collect()

    # Bid recommendations (cần snapshot_date)
    recs = read_json_gz(ads_mgmt_file(snapshot_date, "bid_recommendations"))
    if recs:
        n = db.write_bid_recommendations(client, recs, snapshot_date)
        totals["bid_recommendations"] = n
        del recs
        gc.collect()

    return totals


def main():
    ap = argparse.ArgumentParser(description="Upload ads mgmt snapshot → PPC_Phase1_*_raw")
    ap.add_argument("--date", help="Snapshot date (YYYY-MM-DD). Mặc định = hôm nay.")
    args = ap.parse_args()

    snapshot_date = args.date or str(today_pacific())
    client = get_supabase_client()
    print(f"\n=== Upload PPC mgmt snapshot {snapshot_date} ===")
    totals = upload_mgmt(client, snapshot_date)
    print(f"✅ Mgmt upload xong: {totals}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
