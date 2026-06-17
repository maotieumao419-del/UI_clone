"""PPC Phase 2 — Transform campaigns: PPC_Phase1_campaigns_daily + PPC_Phase1_campaigns_raw
-> PPC_Phase2_summary_campaigns.

Kết quả: 1 row per (report_date, campaign_id) với đầy đủ:
  - Metrics từ daily report (cost, clicks, impressions, sales, purchases, units)
  - Derived: ACOS, CVR, CPC, CTR, ROAS, CostPerOrder, SameSkuPct, BudgetUtil
  - Management info: status, bidding_strategy, daily_budget, portfolio_id
  - topOfSearch%: từ PPC_Phase1_placement_daily (row có placement='TOP_OF_SEARCH')
  - Break-Even ACOS / Bid: NULL ở đây (không có COGS cấp campaign; tính ở keyword)
"""
import gc
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.supabase_client import get_supabase_client, upsert_chunks, fetch_all
from shared.timeutils import now_iso_utc
from calc_derived_metrics import calc_metrics, calc_top_of_search_pct

T_SRC_DAILY   = "PPC_Phase1_campaigns_daily"
T_SRC_RAW     = "PPC_Phase1_campaigns_raw"
T_SRC_PLACE   = "PPC_Phase1_placement_daily"
T_DEST        = "PPC_Phase2_summary_campaigns"


def _load_placement_top(client, date_filter: str) -> dict[str, int]:
    """Trả {campaign_id: impressions tại TOP_OF_SEARCH} cho ngày date_filter."""
    rows = fetch_all(lambda: (
        client.table(T_SRC_PLACE)
        .select("campaign_id,impressions")
        .eq("report_date", date_filter)
        .eq("placement", "TOP_OF_SEARCH")
    ))
    return {r["campaign_id"]: int(r.get("impressions") or 0) for r in rows}


def _load_campaign_raw_map(client) -> dict[str, dict]:
    """Trả {campaign_id: {status, daily_budget, bidding_strategy, portfolio_id}} từ snapshot."""
    rows = fetch_all(lambda: (
        client.table(T_SRC_RAW)
        .select("campaign_id,state,daily_budget,bidding_strategy,portfolio_id")
    ))
    return {r["campaign_id"]: r for r in rows}


def transform_campaigns_for_date(client, date_str: str) -> int:
    print(f"  [Campaigns] {date_str}...")

    daily_rows = fetch_all(lambda: (
        client.table(T_SRC_DAILY)
        .select("*")
        .eq("report_date", date_str)
    ))
    if not daily_rows:
        print(f"    không có dữ liệu daily cho {date_str}")
        return 0

    raw_map       = _load_campaign_raw_map(client)
    top_imp_map   = _load_placement_top(client, date_str)
    now           = now_iso_utc()
    summary_rows  = []

    for row in daily_rows:
        cid = row.get("campaign_id", "")
        mgmt = raw_map.get(cid, {})

        metrics = calc_metrics(row, daily_budget=float(mgmt.get("daily_budget") or 0))

        imp_total = int(row.get("impressions") or 0)
        imp_top   = top_imp_map.get(cid, 0)
        tos_pct   = calc_top_of_search_pct(imp_total, imp_top)

        summary_rows.append({
            "report_date":        date_str,
            "campaign_id":        cid,
            "campaign_name":      row.get("campaign_name", ""),
            "status":             mgmt.get("state") or row.get("campaign_status", ""),
            "bidding_strategy":   mgmt.get("bidding_strategy") or row.get("bidding_strategy", ""),
            "daily_budget":       float(mgmt.get("daily_budget") or 0),
            "portfolio_id":       mgmt.get("portfolio_id") or "",
            "impressions":        int(row.get("impressions") or 0),
            "clicks":             int(row.get("clicks") or 0),
            "cost":               float(row.get("cost") or 0),
            "sales_14d":          float(row.get("sales_14d") or 0),
            "purchases_14d":      int(row.get("purchases_14d") or 0),
            "units_sold_14d":     int(row.get("units_sold_14d") or 0),
            "same_sku_sales_14d": float(row.get("same_sku_sales_14d") or 0),
            # Derived
            "acos":               metrics["acos"],
            "cvr":                metrics["cvr"],
            "cpc":                metrics["cpc"],
            "ctr":                metrics["ctr"],
            "roas":               metrics["roas"],
            "orders":             metrics["orders"],
            "units":              metrics["units"],
            "cost_per_order":     metrics["cost_per_order"],
            "same_sku_pct":       metrics["same_sku_pct"],
            "budget_utilization": metrics["budget_utilization"],
            "top_of_search_pct":  tos_pct,
            # Break-even: cần COGS cấp campaign (không có -> NULL)
            "break_even_acos":    None,
            "break_even_bid":     None,
            "synced_at":          now,
        })

    n = upsert_chunks(client, T_DEST, summary_rows, "report_date,campaign_id")
    print(f"    → {T_DEST}: +{n}")
    del summary_rows, daily_rows
    gc.collect()
    return n
