"""Phase1_Fetch — Bid Recommendations cho tất cả enabled keywords.

Đọc keyword_id từ snapshot mgmt (data/ads_mgmt/<date>_keywords_raw.json.gz),
batch 100 ids/lần gọi POST /sp/keywords/bidRecommendations, lưu:
  data/ads_mgmt/<snapshot_date>_bid_recommendations.json.gz

CẦN chạy fetch_ads_mgmt.py TRƯỚC (để có keywords_raw). Chỉ PPC dashboard dùng.

Chạy:
    python fetch_bid_recs.py                    # dùng snapshot hôm nay
    python fetch_bid_recs.py --date 2026-06-16
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
from shared.ads_api import ads_post
from shared.timeutils import today_pacific
from Phase1_Fetch.paths import ads_mgmt_file, read_json_gz, write_json_gz


def _load_keyword_ids(snapshot_date: str) -> list[str]:
    path = ads_mgmt_file(snapshot_date, "keywords_raw")
    if not path.exists():
        raise FileNotFoundError(
            f"Chưa có {path.name} — chạy fetch_ads_mgmt.py --date {snapshot_date} trước.")
    keywords = read_json_gz(path)
    return [str(kw.get("keywordId", "")) for kw in keywords
            if kw.get("state") == "enabled" and kw.get("keywordId")]


def fetch_bid_recs(lwa, snapshot_date: str, force=False) -> int:
    out_path = ads_mgmt_file(snapshot_date, "bid_recommendations")
    if out_path.exists() and not force:
        print(f"  Đã có {out_path.name} — skip")
        return 0

    keyword_ids = _load_keyword_ids(snapshot_date)
    print(f"  {len(keyword_ids)} enabled keywords")

    all_recs = []
    for i in range(0, len(keyword_ids), 100):
        batch = keyword_ids[i: i + 100]
        try:
            resp = ads_post("/sp/keywords/bidRecommendations", lwa,
                            {"keywordIds": batch})
            recs = resp.get("bidRecommendationsSuccess", []) if isinstance(resp, dict) else []
            all_recs.extend(recs)
        except Exception as exc:
            print(f"    ⚠️  batch {i//100}: {exc}")
        time.sleep(2)

    write_json_gz(out_path, all_recs)
    print(f"  ✅ Bid recs: {len(all_recs)} → {out_path.name}")
    return len(all_recs)


def main():
    ap = argparse.ArgumentParser(description="Fetch Bid Recommendations → data/ads_mgmt/")
    ap.add_argument("--date", help="Snapshot date (YYYY-MM-DD). Mặc định = hôm nay.")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    snapshot_date = args.date or str(today_pacific())
    lwa = get_ads_token()
    print(f"\n=== FETCH BID RECOMMENDATIONS: {snapshot_date} ===")
    fetch_bid_recs(lwa, snapshot_date, force=args.force)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main() or 0)
