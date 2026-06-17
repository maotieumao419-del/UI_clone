"""PPC Phase 2 — Transform portfolios: aggregate PPC_Phase2_summary_campaigns
-> PPC_Phase2_summary_portfolios (group by portfolio_id, report_date).

Portfolio-level summary = SUM của tất cả campaigns thuộc portfolio đó.
"""
import gc
import os
import sys
from collections import defaultdict

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.supabase_client import upsert_chunks, fetch_all
from shared.timeutils import now_iso_utc
from calc_derived_metrics import calc_metrics

T_SRC_CAMPAIGNS  = "PPC_Phase2_summary_campaigns"
T_SRC_PORTFOLIOS = "PPC_Phase1_portfolios"
T_DEST           = "PPC_Phase2_summary_portfolios"


def transform_portfolios_for_date(client, date_str: str) -> int:
    print(f"  [Portfolios] {date_str}...")

    campaign_rows = fetch_all(lambda: (
        client.table(T_SRC_CAMPAIGNS)
        .select("portfolio_id,cost,clicks,impressions,purchases_14d,sales_14d,units_sold_14d,same_sku_sales_14d,daily_budget")
        .eq("report_date", date_str)
    ))
    if not campaign_rows:
        print(f"    không có dữ liệu campaigns cho {date_str}")
        return 0

    # Portfolio metadata
    portfolio_info = {r["portfolio_id"]: r for r in fetch_all(lambda: (
        client.table(T_SRC_PORTFOLIOS).select("portfolio_id,name,state,budget_amount")
    ))}

    # Aggregate per portfolio
    agg: dict[str, dict] = defaultdict(lambda: {
        "cost": 0.0, "clicks": 0, "impressions": 0,
        "purchases_14d": 0, "sales_14d": 0.0,
        "units_sold_14d": 0, "same_sku_sales_14d": 0.0,
        "daily_budget": 0.0, "campaign_count": 0,
    })

    for c in campaign_rows:
        pid = c.get("portfolio_id") or "__no_portfolio__"
        a = agg[pid]
        a["cost"]             += float(c.get("cost") or 0)
        a["clicks"]           += int(c.get("clicks") or 0)
        a["impressions"]      += int(c.get("impressions") or 0)
        a["purchases_14d"]    += int(c.get("purchases_14d") or 0)
        a["sales_14d"]        += float(c.get("sales_14d") or 0)
        a["units_sold_14d"]   += int(c.get("units_sold_14d") or 0)
        a["same_sku_sales_14d"] += float(c.get("same_sku_sales_14d") or 0)
        a["daily_budget"]     += float(c.get("daily_budget") or 0)
        a["campaign_count"]   += 1

    now = now_iso_utc()
    summary_rows = []

    for pid, a in agg.items():
        metrics = calc_metrics(a, daily_budget=a["daily_budget"])
        info    = portfolio_info.get(pid, {})
        summary_rows.append({
            "report_date":        date_str,
            "portfolio_id":       pid,
            "portfolio_name":     info.get("name", pid),
            "status":             info.get("state", ""),
            "budget_amount":      float(info.get("budget_amount") or 0),
            "campaign_count":     a["campaign_count"],
            "impressions":        a["impressions"],
            "clicks":             a["clicks"],
            "cost":               round(a["cost"], 2),
            "sales_14d":          round(a["sales_14d"], 2),
            "purchases_14d":      a["purchases_14d"],
            "units_sold_14d":     a["units_sold_14d"],
            "same_sku_sales_14d": round(a["same_sku_sales_14d"], 2),
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
            "synced_at":          now,
        })

    n = upsert_chunks(client, T_DEST, summary_rows, "report_date,portfolio_id")
    print(f"    → {T_DEST}: +{n}")
    del summary_rows, campaign_rows
    gc.collect()
    return n
