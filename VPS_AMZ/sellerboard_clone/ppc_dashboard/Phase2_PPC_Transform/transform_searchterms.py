"""PPC Phase 2 — Transform search terms: PPC_Phase1_searchterms_daily
-> PPC_Phase2_summary_searchterms.

Search Terms không có management snapshot (không có status/bid individual) nên
summary chủ yếu là aggregated daily metrics + derived indicators.
"""
import gc
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.supabase_client import upsert_chunks, fetch_all
from shared.timeutils import now_iso_utc
from calc_derived_metrics import calc_metrics

T_SRC  = "PPC_Phase1_searchterms_daily"
T_DEST = "PPC_Phase2_summary_searchterms"


def transform_searchterms_for_date(client, date_str: str) -> int:
    print(f"  [SearchTerms] {date_str}...")

    daily_rows = fetch_all(lambda: (
        client.table(T_SRC)
        .select("*")
        .eq("report_date", date_str)
    ))
    if not daily_rows:
        print(f"    không có dữ liệu daily cho {date_str}")
        return 0

    now          = now_iso_utc()
    summary_rows = []

    for row in daily_rows:
        metrics = calc_metrics(row)
        summary_rows.append({
            "report_date":        date_str,
            "campaign_id":        row.get("campaign_id", ""),
            "adgroup_id":         row.get("adgroup_id", ""),
            "keyword_id":         row.get("keyword_id", ""),
            "keyword_text":       row.get("keyword_text", ""),
            "match_type":         row.get("match_type", ""),
            "query":              row.get("query", ""),
            "impressions":        int(row.get("impressions") or 0),
            "clicks":             int(row.get("clicks") or 0),
            "cost":               float(row.get("cost") or 0),
            "sales_14d":          float(row.get("sales_14d") or 0),
            "purchases_14d":      int(row.get("purchases_14d") or 0),
            "units_sold_14d":     int(row.get("units_sold_14d") or 0),
            "same_sku_sales_14d": float(row.get("same_sku_sales_14d") or 0),
            "acos":               metrics["acos"],
            "cvr":                metrics["cvr"],
            "cpc":                metrics["cpc"],
            "ctr":                metrics["ctr"],
            "roas":               metrics["roas"],
            "orders":             metrics["orders"],
            "units":              metrics["units"],
            "cost_per_order":     metrics["cost_per_order"],
            "same_sku_pct":       metrics["same_sku_pct"],
            "synced_at":          now,
        })

    n = upsert_chunks(client, T_DEST, summary_rows,
                      "report_date,campaign_id,adgroup_id,keyword_id,query")
    print(f"    → {T_DEST}: +{n}")
    del summary_rows, daily_rows
    gc.collect()
    return n
