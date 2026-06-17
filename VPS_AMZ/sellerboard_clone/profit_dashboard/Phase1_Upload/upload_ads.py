"""Phase1_Upload (profit) — đọc data/ads_reports/*.json.gz → Profit_Phase1_ads_*.

Profit dashboard dùng:
  sp_campaigns, sb_campaigns, sd_campaigns → Profit_Phase1_ads_campaigns_daily
  sp_advertised_product                    → Profit_Phase1_ads_sp_asin_daily (Tầng 1)

Ads report luôn lưu theo TỪNG NGÀY (fetch lặp từng ngày) → upload cũng lặp ngày.
Logic port từ direct_stream_pipeline.ingest_ads_campaign_report / sp_asin_report.

Chạy:
    python upload_ads.py --date 2026-06-15
    python upload_ads.py --from 2026-06-01 --to 2026-06-15
"""
import argparse
import gc
import sys
from pathlib import Path

from _common import (T_ADS, T_ADS_SKU, f_, i_, now_iso)

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.supabase_client import get_supabase_client, upsert_chunks
from shared.timeutils import date_range_pacific, yesterday_pacific
from Phase1_Fetch.paths import ads_report_file, read_json_gz

# (file_key, ad_product) cho các campaign-level report
CAMPAIGN_REPORTS = [
    ("sp_campaigns", "SPONSORED_PRODUCTS"),
    ("sb_campaigns", "SPONSORED_BRANDS"),
    ("sd_campaigns", "SPONSORED_DISPLAY"),
]


def _ingest_campaign_report(client, data: list, ad_product: str, report_date: str) -> int:
    rows = []
    ts = now_iso()
    for row in data:
        base = {
            "report_date": report_date,
            "campaign_id": str(row.get("campaignId", "")),
            "campaign_name": row.get("campaignName", ""),
            "ad_product": ad_product,
            "impressions": i_(row.get("impressions")),
            "clicks": i_(row.get("clicks")),
            "cost": round(f_(row.get("cost")), 2),
            "synced_at": ts,
        }
        if ad_product == "SPONSORED_PRODUCTS":
            base.update({
                "campaign_type": "sponsoredProducts",
                "purchases_1d": i_(row.get("purchases1d")),
                "purchases_7d": i_(row.get("purchases7d")),
                "purchases_14d": i_(row.get("purchases14d")),
                "sales_1d": round(f_(row.get("sales1d")), 2),
                "sales_7d": round(f_(row.get("sales7d")), 2),
                "sales_14d": round(f_(row.get("sales14d")), 2),
                "units_sold_1d": i_(row.get("unitsSoldClicks1d")),
            })
        elif ad_product == "SPONSORED_BRANDS":
            base.update({
                "campaign_type": row.get("campaignType", "sponsoredBrands"),
                "purchases_14d": i_(row.get("purchases14d") or row.get("purchases")),
                "sales_14d": round(f_(row.get("sales14d") or row.get("sales")), 2),
            })
        else:  # SPONSORED_DISPLAY
            base.update({
                "campaign_type": "sponsoredDisplay",
                "purchases_14d": i_(row.get("purchases14d") or row.get("purchases")),
                "sales_14d": round(f_(row.get("sales14d") or row.get("sales")), 2),
            })
        rows.append(base)
    return upsert_chunks(client, T_ADS, rows, "report_date,campaign_id,ad_product")


def _ingest_sp_asin_report(client, data: list, report_date: str) -> int:
    rows = []
    ts = now_iso()
    for row in data:
        rows.append({
            "report_date": report_date,
            "campaign_id": str(row.get("campaignId", "")),
            "campaign_name": row.get("campaignName", ""),
            "ad_group_id": str(row.get("adGroupId", "")),
            "advertised_asin": row.get("advertisedAsin", ""),
            "advertised_sku": row.get("advertisedSku", ""),
            "impressions": i_(row.get("impressions")),
            "clicks": i_(row.get("clicks")),
            "cost": round(f_(row.get("cost")), 2),
            "purchases_1d": i_(row.get("purchases1d")),
            "purchases_7d": i_(row.get("purchases7d")),
            "sales_1d": round(f_(row.get("sales1d")), 2),
            "sales_7d": round(f_(row.get("sales7d")), 2),
            "units_sold_1d": i_(row.get("unitsSoldClicks1d")),
            "synced_at": ts,
        })
    return upsert_chunks(client, T_ADS_SKU, rows,
                         "report_date,campaign_id,ad_group_id,advertised_sku")


def upload_ads_for_date(client, date_str: str) -> dict:
    totals = {}
    for file_key, ad_product in CAMPAIGN_REPORTS:
        path = ads_report_file(date_str, file_key)
        data = read_json_gz(path)
        if data:
            n = _ingest_campaign_report(client, data, ad_product, date_str)
            totals[file_key] = n
            print(f"  ✅ {file_key}: +{n} → {T_ADS}")
            del data; gc.collect()

    asin_path = ads_report_file(date_str, "sp_advertised_product")
    asin_data = read_json_gz(asin_path)
    if asin_data:
        n = _ingest_sp_asin_report(client, asin_data, date_str)
        totals["sp_advertised_product"] = n
        print(f"  ✅ sp_advertised_product: +{n} → {T_ADS_SKU} (Tầng 1)")
        del asin_data; gc.collect()

    return totals


def main():
    ap = argparse.ArgumentParser(description="Upload ads reports → Profit_Phase1_ads_*")
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
        print(f"\n--- Ads {d} ---")
        upload_ads_for_date(client, d)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
