"""PPC Phase 2 — Transform keywords: PPC_Phase1_keywords_daily + PPC_Phase1_keywords_raw
-> PPC_Phase2_summary_keywords.

Đây là level quan trọng nhất để tính Break-Even Bid:
  - Có bid thực tế (từ PPC_Phase1_keywords_raw)
  - Có bid recommendation (từ PPC_Phase1_bid_recommendations)
  - Break-Even Bid = current_bid * (break_even_acos / current_acos)
"""
import gc
import os
import sys
from datetime import date

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.supabase_client import get_supabase_client, upsert_chunks, fetch_all
from shared.timeutils import now_iso_utc
from calc_derived_metrics import calc_metrics, calc_break_even, calc_break_even_bid

T_SRC_DAILY  = "PPC_Phase1_keywords_daily"
T_SRC_RAW    = "PPC_Phase1_keywords_raw"
T_SRC_RECS   = "PPC_Phase1_bid_recommendations"
T_DEST       = "PPC_Phase2_summary_keywords"


def _load_keywords_raw_map(client) -> dict[str, dict]:
    rows = fetch_all(lambda: (
        client.table(T_SRC_RAW)
        .select("keyword_id,state,bid,keyword_text,match_type")
    ))
    return {r["keyword_id"]: r for r in rows}


def _load_bid_recs_map(client, snapshot_date: str) -> dict[str, float]:
    """Trả {keyword_id: suggested_bid} cho placement TOP_OF_SEARCH."""
    rows = fetch_all(lambda: (
        client.table(T_SRC_RECS)
        .select("keyword_id,suggested_bid")
        .eq("snapshot_date", snapshot_date)
        .eq("placement", "TOP_OF_SEARCH")
    ))
    return {r["keyword_id"]: float(r.get("suggested_bid") or 0) for r in rows}


def transform_keywords_for_date(client, date_str: str,
                                 cogs_map: dict[str, float] = None,
                                 asp_map: dict[str, float] = None,
                                 referral_rate: float = 0.165) -> int:
    """
    cogs_map: {sku: cogs_per_unit} — từ NEW_product_cogs nếu muốn tính Break-Even
    asp_map:  {sku: unit_price}    — từ NEW_product_price
    Nếu không truyền -> Break-Even = NULL
    """
    print(f"  [Keywords] {date_str}...")

    daily_rows = fetch_all(lambda: (
        client.table(T_SRC_DAILY)
        .select("*")
        .eq("report_date", date_str)
    ))
    if not daily_rows:
        print(f"    không có dữ liệu daily cho {date_str}")
        return 0

    raw_map  = _load_keywords_raw_map(client)
    recs_map = _load_bid_recs_map(client, date_str)
    now      = now_iso_utc()
    summary_rows = []

    for row in daily_rows:
        kid = row.get("keyword_id", "")
        mgmt = raw_map.get(kid, {})

        metrics = calc_metrics(row)
        current_bid = float(mgmt.get("bid") or row.get("bid") or 0)
        bid_rec     = recs_map.get(kid)

        # Break-even (nếu có COGS — keyword không biết SKU nên thường NULL)
        be_acos = None
        be_bid  = None

        summary_rows.append({
            "report_date":       date_str,
            "keyword_id":        kid,
            "keyword_text":      row.get("keyword_text") or mgmt.get("keyword_text", ""),
            "match_type":        row.get("match_type") or mgmt.get("match_type", ""),
            "status":            mgmt.get("state") or row.get("keyword_status", ""),
            "campaign_id":       row.get("campaign_id", ""),
            "adgroup_id":        row.get("adgroup_id", ""),
            "current_bid":       current_bid,
            "bid_recommendation": bid_rec,
            "impressions":       int(row.get("impressions") or 0),
            "clicks":            int(row.get("clicks") or 0),
            "cost":              float(row.get("cost") or 0),
            "sales_14d":         float(row.get("sales_14d") or 0),
            "purchases_14d":     int(row.get("purchases_14d") or 0),
            "units_sold_14d":    int(row.get("units_sold_14d") or 0),
            "same_sku_sales_14d":float(row.get("same_sku_sales_14d") or 0),
            # Derived
            "acos":              metrics["acos"],
            "cvr":               metrics["cvr"],
            "cpc":               metrics["cpc"],
            "ctr":               metrics["ctr"],
            "roas":              metrics["roas"],
            "orders":            metrics["orders"],
            "units":             metrics["units"],
            "cost_per_order":    metrics["cost_per_order"],
            "same_sku_pct":      metrics["same_sku_pct"],
            "break_even_acos":   be_acos,
            "break_even_bid":    be_bid,
            "synced_at":         now,
        })

    n = upsert_chunks(client, T_DEST, summary_rows, "report_date,keyword_id")
    print(f"    → {T_DEST}: +{n}")
    del summary_rows, daily_rows
    gc.collect()
    return n
