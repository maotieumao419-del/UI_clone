"""PPC Phase 2 — Bulk mirror: dựng PPC_Phase2_bulk_sp mô phỏng file
"Sponsored Products Bulk Operations" của Amazon (1 sheet phẳng, mỗi dòng 1 entity).

Nguồn:
  - Settings: Phase1 raw mgmt (campaigns_raw / adgroups_raw / keywords_raw /
    targets_raw / portfolios) — trạng thái HIỆN TẠI.
  - Metrics:  Phase1 daily (campaigns/adgroups/keywords/targets_daily) — TỔNG HỢP
    trong khoảng [period_start, period_end].

Khác các transform_*_for_date (theo từng ngày): bulk gom metrics CẢ KỲ thành 1
dòng/entity — đúng như file Amazon tải về theo khoảng ngày.

Chạy qua run_ppc_transform.py --bulk (xem file đó), hoặc trực tiếp:
    python -c "from transform_bulk import transform_bulk_for_range; ..."
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

T_DEST = "PPC_Phase2_bulk_sp"

# Phase1 raw mgmt
T_CAMP_RAW = "PPC_Phase1_campaigns_raw"
T_AG_RAW   = "PPC_Phase1_adgroups_raw"
T_KW_RAW   = "PPC_Phase1_keywords_raw"
T_TG_RAW   = "PPC_Phase1_targets_raw"
T_PF       = "PPC_Phase1_portfolios"
# Phase1 daily metrics
T_CAMP_D = "PPC_Phase1_campaigns_daily"
T_AG_D   = "PPC_Phase1_adgroups_daily"
T_KW_D   = "PPC_Phase1_keywords_daily"
T_TG_D   = "PPC_Phase1_targets_daily"

# Cột metric đọc từ daily (đủ cho calc_metrics)
_MCOLS = "campaign_id,adgroup_id,keyword_id,target_id,impressions,clicks,cost,sales_14d,purchases_14d,units_sold_14d"


def _agg_daily(client, table: str, id_col: str, start: str, end: str) -> dict:
    """SUM metrics theo id_col trong [start, end]. Trả {id: {metric dồn}}."""
    rows = fetch_all(lambda: (
        client.table(table).select("*")
        .gte("report_date", start).lte("report_date", end)
    ))
    agg: dict[str, dict] = {}
    for r in rows:
        key = str(r.get(id_col) or "")
        if not key:
            continue
        a = agg.setdefault(key, {"impressions": 0, "clicks": 0, "cost": 0.0,
                                 "sales_14d": 0.0, "purchases_14d": 0, "units_sold_14d": 0})
        a["impressions"]    += int(r.get("impressions") or 0)
        a["clicks"]         += int(r.get("clicks") or 0)
        a["cost"]           += float(r.get("cost") or 0)
        a["sales_14d"]      += float(r.get("sales_14d") or 0)
        a["purchases_14d"]  += int(r.get("purchases_14d") or 0)
        a["units_sold_14d"] += int(r.get("units_sold_14d") or 0)
    return agg


def _map(client, table: str, key: str, cols: str) -> dict:
    rows = fetch_all(lambda: client.table(table).select(cols))
    return {str(r.get(key) or ""): r for r in rows}


def _blank(entity: str, row_key: str, start: str, end: str, ts: str) -> dict:
    return {
        "period_start": start, "period_end": end, "entity": entity, "row_key": row_key,
        "portfolio_id": None, "campaign_id": None, "adgroup_id": None,
        "keyword_id": None, "target_id": None,
        "campaign_name": None, "adgroup_name": None, "portfolio_name": None,
        "start_date": None, "end_date": None, "targeting_type": None, "state": None,
        "daily_budget": None, "sku": None, "asin": None,
        "adgroup_default_bid": None, "bid": None, "keyword_text": None,
        "match_type": None, "bidding_strategy": None, "placement": None,
        "percentage": None, "product_targeting_expression": None,
        "impressions": 0, "clicks": 0, "ctr": None, "spend": 0.0, "sales": 0.0,
        "orders": 0, "units": 0, "conversion_rate": None, "acos": None,
        "cpc": None, "roas": None, "synced_at": ts,
    }


def _fill_metrics(row: dict, agg: dict) -> None:
    m = calc_metrics(agg)
    row["impressions"]     = agg["impressions"]
    row["clicks"]          = agg["clicks"]
    row["spend"]           = round(agg["cost"], 2)
    row["sales"]           = round(agg["sales_14d"], 2)
    row["orders"]          = agg["purchases_14d"]
    row["units"]           = m["units"]
    row["ctr"]             = m["ctr"]
    row["conversion_rate"] = m["cvr"]
    row["acos"]            = m["acos"]
    row["cpc"]             = m["cpc"]
    row["roas"]            = m["roas"]


def transform_bulk_for_range(client, start: str, end: str) -> int:
    print(f"  [Bulk] {start} → {end}...")
    ts = now_iso_utc()

    # Settings maps
    camp = _map(client, T_CAMP_RAW, "campaign_id",
                "campaign_id,name,state,targeting_type,daily_budget,bidding_strategy,portfolio_id,start_date,end_date")
    ag   = _map(client, T_AG_RAW, "adgroup_id", "adgroup_id,campaign_id,name,state,default_bid")
    kw   = _map(client, T_KW_RAW, "keyword_id", "keyword_id,adgroup_id,campaign_id,keyword_text,match_type,state,bid")
    tg   = _map(client, T_TG_RAW, "target_id", "target_id,adgroup_id,campaign_id,targeting_type,expression,bid,state")
    pf   = _map(client, T_PF, "portfolio_id", "portfolio_id,name")

    # Metrics maps (tổng hợp kỳ)
    m_camp = _agg_daily(client, T_CAMP_D, "campaign_id", start, end)
    m_ag   = _agg_daily(client, T_AG_D, "adgroup_id", start, end)
    m_kw   = _agg_daily(client, T_KW_D, "keyword_id", start, end)
    m_tg   = _agg_daily(client, T_TG_D, "target_id", start, end)

    rows = []

    # Campaign rows
    for cid, c in camp.items():
        r = _blank("Campaign", cid, start, end, ts)
        r.update({"campaign_id": cid, "campaign_name": c.get("name"),
                  "portfolio_id": c.get("portfolio_id") or None,
                  "portfolio_name": pf.get(str(c.get("portfolio_id") or ""), {}).get("name"),
                  "targeting_type": c.get("targeting_type"), "state": c.get("state"),
                  "daily_budget": c.get("daily_budget"),
                  "bidding_strategy": c.get("bidding_strategy"),
                  "start_date": c.get("start_date"), "end_date": c.get("end_date")})
        if cid in m_camp:
            _fill_metrics(r, m_camp[cid])
        rows.append(r)

    # Ad Group rows
    for agid, a in ag.items():
        r = _blank("Ad Group", agid, start, end, ts)
        r.update({"adgroup_id": agid, "campaign_id": a.get("campaign_id"),
                  "adgroup_name": a.get("name"), "state": a.get("state"),
                  "adgroup_default_bid": a.get("default_bid"),
                  "campaign_name": camp.get(str(a.get("campaign_id") or ""), {}).get("name")})
        if agid in m_ag:
            _fill_metrics(r, m_ag[agid])
        rows.append(r)

    # Keyword rows
    for kid, k in kw.items():
        r = _blank("Keyword", kid, start, end, ts)
        r.update({"keyword_id": kid, "adgroup_id": k.get("adgroup_id"),
                  "campaign_id": k.get("campaign_id"), "keyword_text": k.get("keyword_text"),
                  "match_type": k.get("match_type"), "state": k.get("state"), "bid": k.get("bid")})
        if kid in m_kw:
            _fill_metrics(r, m_kw[kid])
        rows.append(r)

    # Product Targeting rows
    for tid, t in tg.items():
        r = _blank("Product Targeting", tid, start, end, ts)
        r.update({"target_id": tid, "adgroup_id": t.get("adgroup_id"),
                  "campaign_id": t.get("campaign_id"), "targeting_type": t.get("targeting_type"),
                  "product_targeting_expression": t.get("expression"),
                  "state": t.get("state"), "bid": t.get("bid")})
        if tid in m_tg:
            _fill_metrics(r, m_tg[tid])
        rows.append(r)

    n = upsert_chunks(client, T_DEST, rows, "period_start,period_end,entity,row_key")
    print(f"    → {T_DEST}: +{n} (Campaign/AdGroup/Keyword/Target)")
    del rows
    gc.collect()
    return n
