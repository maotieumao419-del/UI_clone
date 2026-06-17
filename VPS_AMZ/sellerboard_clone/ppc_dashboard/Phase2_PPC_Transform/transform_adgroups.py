"""PPC Phase 2 — Transform ad groups: PPC_Phase1_adgroups_daily + PPC_Phase1_adgroups_raw
-> PPC_Phase2_summary_adgroups.
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

T_SRC_DAILY = "PPC_Phase1_adgroups_daily"
T_SRC_RAW   = "PPC_Phase1_adgroups_raw"
T_DEST      = "PPC_Phase2_summary_adgroups"


def _load_adgroups_raw_map(client) -> dict[str, dict]:
    rows = fetch_all(lambda: (
        client.table(T_SRC_RAW)
        .select("adgroup_id,state,default_bid,campaign_id")
    ))
    return {r["adgroup_id"]: r for r in rows}


def transform_adgroups_for_date(client, date_str: str) -> int:
    print(f"  [AdGroups] {date_str}...")

    daily_rows = fetch_all(lambda: (
        client.table(T_SRC_DAILY)
        .select("*")
        .eq("report_date", date_str)
    ))
    if not daily_rows:
        print(f"    không có dữ liệu daily cho {date_str}")
        return 0

    raw_map      = _load_adgroups_raw_map(client)
    now          = now_iso_utc()
    summary_rows = []

    for row in daily_rows:
        agid = row.get("adgroup_id", "")
        mgmt = raw_map.get(agid, {})
        metrics = calc_metrics(row)

        summary_rows.append({
            "report_date":        date_str,
            "adgroup_id":         agid,
            "adgroup_name":       row.get("adgroup_name", ""),
            "status":             mgmt.get("state") or row.get("adgroup_status", ""),
            "campaign_id":        row.get("campaign_id", ""),
            "default_bid":        float(mgmt.get("default_bid") or 0),
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

    n = upsert_chunks(client, T_DEST, summary_rows, "report_date,adgroup_id")
    print(f"    → {T_DEST}: +{n}")
    del summary_rows, daily_rows
    gc.collect()
    return n
