"""PPC Phase 1 — Main entry point: ingest tất cả PPC data -> Supabase PPC_*.

Chạy:
    python run_ppc_ingest.py --all --date 2026-06-15
    python run_ppc_ingest.py --all --from 2026-06-01 --to 2026-06-15
    python run_ppc_ingest.py --reports --date 2026-06-15          # chỉ report metrics
    python run_ppc_ingest.py --mgmt                               # chỉ snapshot mgmt data
    python run_ppc_ingest.py --bid-recs                           # chỉ bid recommendations

Nguồn dữ liệu:
  --reports   : 5 report types (campaigns/adgroups/keywords/targets/searchterms) + placement
  --mgmt      : snapshot campaigns/adgroups/keywords/targets/portfolios từ Mgmt API
  --bid-recs  : bid recommendations cho tất cả enabled keywords

Bảng Supabase đích (prefix PPC_*):
  PPC_Phase1_portfolios, PPC_Phase1_campaigns_raw, PPC_Phase1_adgroups_raw,
  PPC_Phase1_keywords_raw, PPC_Phase1_targets_raw,
  PPC_Phase1_campaigns_daily, PPC_Phase1_adgroups_daily, PPC_Phase1_keywords_daily,
  PPC_Phase1_targets_daily, PPC_Phase1_searchterms_daily, PPC_Phase1_placement_daily,
  PPC_Phase1_bid_recommendations
"""
import argparse
import gc
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from shared.amz_auth import get_ads_token
from shared.supabase_client import get_supabase_client
from shared.timeutils import date_range_pacific, yesterday_pacific

import amz_ads_ppc_client as api
import db_writer as db

REQUEST_GAP = float(os.getenv("ADS_REQUEST_GAP_SECONDS", "20"))


# ── Report pipeline (daily metrics) ───────────────────────────────────────────

REPORT_JOBS = [
    ("SP-Campaigns",    api.make_sp_campaigns_config(),         db.write_campaigns_daily),
    ("SP-AdGroups",     api.make_sp_adgroups_config(),          db.write_adgroups_daily),
    ("SP-Keywords",     api.make_sp_keywords_config(),          db.write_keywords_daily),
    ("SP-Targets",      api.make_sp_targets_config(),           db.write_targets_daily),
    ("SP-SearchTerms",  api.make_sp_searchterm_config(),        db.write_searchterms_daily),
    ("SP-Placement",    api.make_sp_campaigns_config("placement"), db.write_placement_daily),
]


def run_reports(client, lwa_ads: str, report_dates: list[str]) -> dict:
    print(f"\n=== PPC REPORTS: {len(report_dates)} ngày ===")
    totals: dict = {}

    for date_str in report_dates:
        print(f"\n--- {date_str} ---")
        report_ids = []

        for name, config, _ in REPORT_JOBS:
            try:
                rid = api.request_report(lwa_ads, config, name, date_str)
            except Exception as exc:
                print(f"  ⚠️  {name}: {exc} — bỏ qua")
                rid = ""
            report_ids.append((name, rid))
            time.sleep(REQUEST_GAP)

        for (name, rid), (_, _, write_fn) in zip(report_ids, REPORT_JOBS):
            if not rid:
                continue
            url = api.poll_until_done(lwa_ads, rid, name)
            if not url:
                continue
            data = api.download_report(url)
            print(f"  [ADS] {name}: {len(data)} rows")
            n = write_fn(client, data, date_str)
            totals[f"{date_str}/{name}"] = n
            del data
            gc.collect()

    print(f"✅ PPC Reports xong: {sum(totals.values())} rows tổng")
    return totals


# ── Management API snapshot ────────────────────────────────────────────────────

def run_management_snapshot(client, lwa_ads: str) -> dict:
    """Lấy toàn bộ campaigns/adgroups/keywords/targets/portfolios (không phân theo ngày)."""
    print("\n=== PPC MANAGEMENT SNAPSHOT ===")
    totals: dict = {}

    # Portfolios
    portfolios = api.list_portfolios(lwa_ads)
    totals["portfolios"] = db.write_portfolios(client, portfolios)
    time.sleep(2)

    # Campaigns (phân trang thủ công)
    all_campaigns = []
    start = 0
    while True:
        page = api.list_sp_campaigns(lwa_ads, count=100, start_index=start)
        if not page:
            break
        all_campaigns.extend(page)
        if len(page) < 100:
            break
        start += 100
        time.sleep(1)
    totals["campaigns"] = db.write_campaigns_raw(client, all_campaigns)
    campaign_ids = [str(c.get("campaignId", "")) for c in all_campaigns]
    del all_campaigns
    gc.collect()
    time.sleep(2)

    # Ad Groups
    all_adgroups = []
    for cid in campaign_ids:
        start = 0
        while True:
            page = api.list_sp_adgroups(lwa_ads, campaign_id_filter=cid, count=100, start_index=start)
            if not page:
                break
            all_adgroups.extend(page)
            if len(page) < 100:
                break
            start += 100
            time.sleep(0.5)
    totals["adgroups"] = db.write_adgroups_raw(client, all_adgroups)
    adgroup_ids = [str(ag.get("adGroupId", "")) for ag in all_adgroups]
    del all_adgroups
    gc.collect()
    time.sleep(2)

    # Keywords
    all_keywords = []
    for agid in adgroup_ids:
        start = 0
        while True:
            page = api.list_sp_keywords(lwa_ads, ad_group_id_filter=agid, count=100, start_index=start)
            if not page:
                break
            all_keywords.extend(page)
            if len(page) < 100:
                break
            start += 100
            time.sleep(0.3)
    totals["keywords"] = db.write_keywords_raw(client, all_keywords)
    del all_keywords
    gc.collect()
    time.sleep(2)

    # Targets (product/ASIN targeting)
    all_targets = []
    for agid in adgroup_ids:
        start = 0
        while True:
            page = api.list_sp_targets(lwa_ads, ad_group_id_filter=agid, count=100, start_index=start)
            if not page:
                break
            all_targets.extend(page)
            if len(page) < 100:
                break
            start += 100
            time.sleep(0.3)
    totals["targets"] = db.write_targets_raw(client, all_targets)
    del all_targets
    gc.collect()

    print(f"✅ Management snapshot: {totals}")
    return totals


# ── Bid recommendations ────────────────────────────────────────────────────────

def run_bid_recommendations(client, lwa_ads: str, snapshot_date: str) -> dict:
    """Lấy tất cả enabled keywords -> batch bid recommendations."""
    from shared.supabase_client import fetch_all
    print("\n=== PPC BID RECOMMENDATIONS ===")

    # Đọc keyword_id từ PPC_Phase1_keywords_raw (state=enabled)
    rows = fetch_all(lambda: (
        client.table(db.T_KEYWORDS_RAW)
        .select("keyword_id")
        .eq("state", "enabled")
    ))
    keyword_ids = [r["keyword_id"] for r in rows if r.get("keyword_id")]
    print(f"  {len(keyword_ids)} enabled keywords")

    all_recs = []
    # Batch 100 ids mỗi lần (giới hạn API)
    for i in range(0, len(keyword_ids), 100):
        batch = keyword_ids[i: i + 100]
        recs = api.get_bid_recommendations(lwa_ads, batch)
        all_recs.extend(recs)
        time.sleep(2)

    n = db.write_bid_recommendations(client, all_recs, snapshot_date)
    print(f"✅ Bid recommendations: {n} rows")
    return {"bid_recommendations": n}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="PPC Phase 1 — Ingestion")
    ap.add_argument("--all",       action="store_true", help="Chạy tất cả: reports + mgmt + bid-recs")
    ap.add_argument("--reports",   action="store_true", help="Chỉ kéo daily report metrics")
    ap.add_argument("--mgmt",      action="store_true", help="Chỉ snapshot management data")
    ap.add_argument("--bid-recs",  action="store_true", help="Chỉ lấy bid recommendations")
    ap.add_argument("--date",  help="Đúng 1 ngày YYYY-MM-DD (Pacific). Mặc định = hôm qua.")
    ap.add_argument("--from",  dest="from_date", help="Ngày bắt đầu khoảng (Pacific)")
    ap.add_argument("--to",    dest="to_date",   help="Ngày kết thúc khoảng (Pacific)")
    args = ap.parse_args()

    do_reports  = args.all or args.reports
    do_mgmt     = args.all or args.mgmt
    do_bid_recs = args.all or getattr(args, "bid_recs", False)

    if not (do_reports or do_mgmt or do_bid_recs):
        ap.error("Chọn ít nhất 1 nguồn: --reports / --mgmt / --bid-recs / --all")

    # Xác định khoảng ngày cho reports
    if args.date:
        report_dates = [args.date]
    elif args.from_date:
        end = args.to_date or args.from_date
        report_dates = [str(d) for d in date_range_pacific(args.from_date, end)]
    else:
        report_dates = [str(yesterday_pacific())]

    snapshot_date = report_dates[-1]

    client  = get_supabase_client()
    lwa_ads = get_ads_token()

    if do_reports:
        run_reports(client, lwa_ads, report_dates)
    if do_mgmt:
        run_management_snapshot(client, lwa_ads)
    if do_bid_recs:
        run_bid_recommendations(client, lwa_ads, snapshot_date)

    print("\n✅ PPC Phase 1 hoàn tất — dữ liệu đã ở bảng Supabase PPC_*.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
