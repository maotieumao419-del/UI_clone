"""Phase1_Fetch — Ads Campaign Management API: snapshot trạng thái HIỆN TẠI.

Lưu snapshot (không theo ngày — là trạng thái tại thời điểm chạy):
  data/ads_mgmt/<snapshot_date>_portfolios.json.gz
  data/ads_mgmt/<snapshot_date>_campaigns_raw.json.gz
  data/ads_mgmt/<snapshot_date>_adgroups_raw.json.gz
  data/ads_mgmt/<snapshot_date>_keywords_raw.json.gz
  data/ads_mgmt/<snapshot_date>_targets_raw.json.gz

Chủ yếu PPC dashboard dùng (status, daily_budget, bid, bidding_strategy,
portfolio_id) — những field report metrics KHÔNG có. Profit dashboard không cần.

Chạy:
    python fetch_ads_mgmt.py                      # snapshot hôm nay
    python fetch_ads_mgmt.py --date 2026-06-16    # gắn nhãn ngày cụ thể
    python fetch_ads_mgmt.py --force
"""
import argparse
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
from shared.ads_api import ads_get
from shared.timeutils import today_pacific
from Phase1_Fetch.paths import ads_mgmt_file, write_json_gz

STATE_FILTER = "enabled,paused,archived"


def _paginate(lwa, path, base_params, label) -> list:
    """GET phân trang count/startIndex cho mgmt endpoints v2-style."""
    out, start = [], 0
    while True:
        params = dict(base_params, count=100, startIndex=start)
        page = ads_get(path, lwa, params=params)
        page = page if isinstance(page, list) else []
        out.extend(page)
        print(f"  [{label}] +{len(page)} (tổng {len(out)})")
        if len(page) < 100:
            break
        start += 100
        time.sleep(0.5)
    return out


def fetch_mgmt(lwa, snapshot_date: str, force=False) -> dict:
    totals = {}

    def _do(file_key, fetch_fn):
        out_path = ads_mgmt_file(snapshot_date, file_key)
        if out_path.exists() and not force:
            print(f"  [{file_key}] Đã có {out_path.name} — skip")
            return
        rows = fetch_fn()
        write_json_gz(out_path, rows)
        print(f"  ✅ {file_key}: {len(rows)} → mgmt_{file_key}.json.gz")
        totals[file_key] = len(rows)

    # Portfolios
    def _portfolios():
        resp = ads_get("/portfolios", lwa)
        return resp if isinstance(resp, list) else resp.get("portfolios", [])
    _do("portfolios", _portfolios)
    time.sleep(2)

    # Campaigns
    _do("campaigns_raw",
        lambda: _paginate(lwa, "/sp/campaigns", {"stateFilter": STATE_FILTER}, "campaigns"))
    time.sleep(2)

    # Ad Groups
    _do("adgroups_raw",
        lambda: _paginate(lwa, "/sp/adGroups", {"stateFilter": STATE_FILTER}, "adgroups"))
    time.sleep(2)

    # Keywords
    _do("keywords_raw",
        lambda: _paginate(lwa, "/sp/keywords", {"stateFilter": STATE_FILTER}, "keywords"))
    time.sleep(2)

    # Targets
    _do("targets_raw",
        lambda: _paginate(lwa, "/sp/targets", {"stateFilter": STATE_FILTER}, "targets"))

    return totals


def main():
    ap = argparse.ArgumentParser(description="Fetch Ads Management snapshot → data/ads_mgmt/")
    ap.add_argument("--date", help="Gắn nhãn snapshot (YYYY-MM-DD). Mặc định = hôm nay Pacific.")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    snapshot_date = args.date or str(today_pacific())
    lwa = get_ads_token()
    print(f"\n=== FETCH ADS MGMT SNAPSHOT: {snapshot_date} ===")
    totals = fetch_mgmt(lwa, snapshot_date, force=args.force)
    print(f"\n✅ Mgmt snapshot hoàn tất: {totals}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main() or 0)
