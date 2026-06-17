"""PPC Phase 1 — Supabase writer: transform raw API rows -> PPC_* tables.

Tất cả bảng dùng prefix PPC_ để tách biệt với bảng profit pipeline (NEW_*).
Memory-safety: upsert từng chunk <=100 rows, del + gc.collect() sau mỗi batch.
"""
import gc
import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.supabase_client import upsert_chunks
from shared.timeutils import now_iso_utc

# ── Tên bảng ──────────────────────────────────────────────────────────────────
T_PORTFOLIOS      = "PPC_Phase1_portfolios"
T_CAMPAIGNS_RAW   = "PPC_Phase1_campaigns_raw"
T_ADGROUPS_RAW    = "PPC_Phase1_adgroups_raw"
T_KEYWORDS_RAW    = "PPC_Phase1_keywords_raw"
T_TARGETS_RAW     = "PPC_Phase1_targets_raw"
T_CAMPAIGNS_DAILY = "PPC_Phase1_campaigns_daily"
T_ADGROUPS_DAILY  = "PPC_Phase1_adgroups_daily"
T_KEYWORDS_DAILY  = "PPC_Phase1_keywords_daily"
T_TARGETS_DAILY   = "PPC_Phase1_targets_daily"
T_SEARCHTERMS     = "PPC_Phase1_searchterms_daily"
T_PLACEMENT       = "PPC_Phase1_placement_daily"
T_BID_RECS        = "PPC_Phase1_bid_recommendations"


def _f(val, default=0.0) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return default


def _i(val, default=0) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return default


# ── Portfolios ─────────────────────────────────────────────────────────────────

def write_portfolios(client, portfolios: list) -> int:
    """Snapshot danh sách portfolios (không phân trang theo ngày)."""
    now = now_iso_utc()
    rows = []
    for p in portfolios:
        rows.append({
            "portfolio_id":   str(p.get("portfolioId", "")),
            "name":           p.get("name", ""),
            "state":          p.get("state", ""),
            "budget_amount":  _f(p.get("budget", {}).get("amount")),
            "budget_currency":p.get("budget", {}).get("currencyCode", ""),
            "budget_policy":  p.get("budget", {}).get("policy", ""),
            "in_budget":      p.get("inBudget", True),
            "synced_at":      now,
        })
    n = upsert_chunks(client, T_PORTFOLIOS, rows, "portfolio_id")
    print(f"  → {T_PORTFOLIOS}: +{n}")
    return n


# ── Campaigns raw (management API snapshot) ────────────────────────────────────

def write_campaigns_raw(client, campaigns: list) -> int:
    now = now_iso_utc()
    rows = []
    for c in campaigns:
        rows.append({
            "campaign_id":        str(c.get("campaignId", "")),
            "name":               c.get("name", ""),
            "state":              c.get("state", ""),
            "targeting_type":     c.get("targetingType", ""),
            "daily_budget":       _f(c.get("dailyBudget")),
            "start_date":         c.get("startDate"),
            "end_date":           c.get("endDate"),
            "premium_bid_adj":    c.get("premiumBidAdjustment", False),
            "bidding_strategy":   (c.get("bidding") or {}).get("strategy", ""),
            "portfolio_id":       str(c.get("portfolioId", "") or ""),
            "synced_at":          now,
        })
    n = upsert_chunks(client, T_CAMPAIGNS_RAW, rows, "campaign_id")
    print(f"  → {T_CAMPAIGNS_RAW}: +{n}")
    return n


# ── Ad groups raw ──────────────────────────────────────────────────────────────

def write_adgroups_raw(client, adgroups: list) -> int:
    now = now_iso_utc()
    rows = []
    for ag in adgroups:
        rows.append({
            "adgroup_id":   str(ag.get("adGroupId", "")),
            "campaign_id":  str(ag.get("campaignId", "")),
            "name":         ag.get("name", ""),
            "state":        ag.get("state", ""),
            "default_bid":  _f(ag.get("defaultBid")),
            "synced_at":    now,
        })
    n = upsert_chunks(client, T_ADGROUPS_RAW, rows, "adgroup_id")
    print(f"  → {T_ADGROUPS_RAW}: +{n}")
    return n


# ── Keywords raw ───────────────────────────────────────────────────────────────

def write_keywords_raw(client, keywords: list) -> int:
    now = now_iso_utc()
    rows = []
    for kw in keywords:
        rows.append({
            "keyword_id":   str(kw.get("keywordId", "")),
            "adgroup_id":   str(kw.get("adGroupId", "")),
            "campaign_id":  str(kw.get("campaignId", "")),
            "keyword_text": kw.get("keywordText", ""),
            "match_type":   kw.get("matchType", ""),
            "state":        kw.get("state", ""),
            "bid":          _f(kw.get("bid")),
            "synced_at":    now,
        })
    n = upsert_chunks(client, T_KEYWORDS_RAW, rows, "keyword_id")
    print(f"  → {T_KEYWORDS_RAW}: +{n}")
    return n


# ── Targets raw ────────────────────────────────────────────────────────────────

def write_targets_raw(client, targets: list) -> int:
    now = now_iso_utc()
    rows = []
    for t in targets:
        expr = t.get("expression") or []
        expr_str = str(expr)[:500]
        rows.append({
            "target_id":     str(t.get("targetId", "")),
            "adgroup_id":    str(t.get("adGroupId", "")),
            "campaign_id":   str(t.get("campaignId", "")),
            "targeting_type": t.get("type", ""),
            "expression":    expr_str,
            "bid":           _f(t.get("bid")),
            "state":         t.get("state", ""),
            "synced_at":     now,
        })
    n = upsert_chunks(client, T_TARGETS_RAW, rows, "target_id")
    print(f"  → {T_TARGETS_RAW}: +{n}")
    return n


# ── Report rows (daily metrics) ────────────────────────────────────────────────

def write_campaigns_daily(client, data: list, report_date: str) -> int:
    now = now_iso_utc()
    rows = []
    for r in data:
        rows.append({
            "report_date":        report_date,
            "campaign_id":        str(r.get("campaignId", "")),
            "campaign_name":      r.get("campaignName", ""),
            "campaign_status":    r.get("campaignStatus", ""),
            "bidding_strategy":   r.get("campaignBiddingStrategy", ""),
            "impressions":        _i(r.get("impressions")),
            "clicks":             _i(r.get("clicks")),
            "cost":               round(_f(r.get("cost")), 2),
            "purchases_1d":       _i(r.get("purchases1d")),
            "purchases_7d":       _i(r.get("purchases7d")),
            "purchases_14d":      _i(r.get("purchases14d")),
            "sales_1d":           round(_f(r.get("sales1d")), 2),
            "sales_7d":           round(_f(r.get("sales7d")), 2),
            "sales_14d":          round(_f(r.get("sales14d")), 2),
            "units_sold_1d":      _i(r.get("unitsSoldClicks1d")),
            "units_sold_14d":     _i(r.get("unitsSoldClicks14d")),
            "same_sku_sales_14d": round(_f(r.get("attributedSalesSameSku14d")), 2),
            "roas_14d":           round(_f(r.get("roasClicks14d")), 4),
            "synced_at":          now,
        })
    n = upsert_chunks(client, T_CAMPAIGNS_DAILY, rows, "report_date,campaign_id")
    print(f"  → {T_CAMPAIGNS_DAILY}: +{n}")
    return n


def write_adgroups_daily(client, data: list, report_date: str) -> int:
    now = now_iso_utc()
    rows = []
    for r in data:
        rows.append({
            "report_date":        report_date,
            "campaign_id":        str(r.get("campaignId", "")),
            "adgroup_id":         str(r.get("adGroupId", "")),
            "adgroup_name":       r.get("adGroupName", ""),
            "adgroup_status":     r.get("adGroupStatus", ""),
            "impressions":        _i(r.get("impressions")),
            "clicks":             _i(r.get("clicks")),
            "cost":               round(_f(r.get("cost")), 2),
            "purchases_1d":       _i(r.get("purchases1d")),
            "purchases_14d":      _i(r.get("purchases14d")),
            "sales_1d":           round(_f(r.get("sales1d")), 2),
            "sales_14d":          round(_f(r.get("sales14d")), 2),
            "units_sold_1d":      _i(r.get("unitsSoldClicks1d")),
            "units_sold_14d":     _i(r.get("unitsSoldClicks14d")),
            "same_sku_sales_14d": round(_f(r.get("attributedSalesSameSku14d")), 2),
            "synced_at":          now,
        })
    n = upsert_chunks(client, T_ADGROUPS_DAILY, rows, "report_date,adgroup_id")
    print(f"  → {T_ADGROUPS_DAILY}: +{n}")
    return n


def write_keywords_daily(client, data: list, report_date: str) -> int:
    now = now_iso_utc()
    rows = []
    for r in data:
        rows.append({
            "report_date":        report_date,
            "campaign_id":        str(r.get("campaignId", "")),
            "adgroup_id":         str(r.get("adGroupId", "")),
            "keyword_id":         str(r.get("keywordId", "")),
            # v3 report trả cột 'keyword' (text); status & bid KHÔNG có trong
            # report — lấy từ mgmt raw ở Phase 2.
            "keyword_text":       r.get("keyword") or r.get("keywordText", ""),
            "keyword_status":     r.get("keywordStatus", ""),
            "match_type":         r.get("matchType", ""),
            "bid":                round(_f(r.get("bid")), 2),
            "impressions":        _i(r.get("impressions")),
            "clicks":             _i(r.get("clicks")),
            "cost":               round(_f(r.get("cost")), 2),
            "purchases_1d":       _i(r.get("purchases1d")),
            "purchases_14d":      _i(r.get("purchases14d")),
            "sales_1d":           round(_f(r.get("sales1d")), 2),
            "sales_14d":          round(_f(r.get("sales14d")), 2),
            "units_sold_1d":      _i(r.get("unitsSoldClicks1d")),
            "units_sold_14d":     _i(r.get("unitsSoldClicks14d")),
            "same_sku_sales_14d": round(_f(r.get("attributedSalesSameSku14d")), 2),
            "synced_at":          now,
        })
    n = upsert_chunks(client, T_KEYWORDS_DAILY, rows, "report_date,keyword_id")
    print(f"  → {T_KEYWORDS_DAILY}: +{n}")
    return n


def write_targets_daily(client, data: list, report_date: str) -> int:
    now = now_iso_utc()
    rows = []
    for r in data:
        rows.append({
            "report_date":   report_date,
            "campaign_id":   str(r.get("campaignId", "")),
            "adgroup_id":    str(r.get("adGroupId", "")),
            "target_id":     str(r.get("targetId", "")),
            "targeting_text": r.get("targeting") or r.get("targetingText", ""),
            "targeting_type": r.get("targetingType", ""),
            "bid":           round(_f(r.get("bid")), 2),
            "impressions":   _i(r.get("impressions")),
            "clicks":        _i(r.get("clicks")),
            "cost":          round(_f(r.get("cost")), 2),
            "purchases_1d":  _i(r.get("purchases1d")),
            "purchases_14d": _i(r.get("purchases14d")),
            "sales_1d":      round(_f(r.get("sales1d")), 2),
            "sales_14d":     round(_f(r.get("sales14d")), 2),
            "units_sold_1d": _i(r.get("unitsSoldClicks1d")),
            "synced_at":     now,
        })
    n = upsert_chunks(client, T_TARGETS_DAILY, rows, "report_date,target_id")
    print(f"  → {T_TARGETS_DAILY}: +{n}")
    return n


def write_searchterms_daily(client, data: list, report_date: str) -> int:
    now = now_iso_utc()
    rows = []
    for r in data:
        rows.append({
            "report_date":        report_date,
            "campaign_id":        str(r.get("campaignId", "")),
            "adgroup_id":         str(r.get("adGroupId", "")),
            "keyword_id":         str(r.get("keywordId", "")),
            "keyword_text":       r.get("keyword") or r.get("keywordText", ""),
            "match_type":         r.get("matchType", ""),
            # v3 spSearchTerm trả cột 'searchTerm'
            "query":              r.get("searchTerm") or r.get("query", ""),
            "impressions":        _i(r.get("impressions")),
            "clicks":             _i(r.get("clicks")),
            "cost":               round(_f(r.get("cost")), 2),
            "purchases_1d":       _i(r.get("purchases1d")),
            "purchases_14d":      _i(r.get("purchases14d")),
            "sales_1d":           round(_f(r.get("sales1d")), 2),
            "sales_14d":          round(_f(r.get("sales14d")), 2),
            "units_sold_1d":      _i(r.get("unitsSoldClicks1d")),
            "units_sold_14d":     _i(r.get("unitsSoldClicks14d")),
            "same_sku_sales_14d": round(_f(r.get("attributedSalesSameSku14d")), 2),
            "synced_at":          now,
        })
    n = upsert_chunks(client, T_SEARCHTERMS, rows,
                      "report_date,campaign_id,adgroup_id,keyword_id,query")
    print(f"  → {T_SEARCHTERMS}: +{n}")
    return n


def write_placement_daily(client, data: list, report_date: str) -> int:
    """Placement-segmented report (topOfSearch breakdown per campaign)."""
    now = now_iso_utc()
    rows = []
    for r in data:
        rows.append({
            "report_date":      report_date,
            "campaign_id":      str(r.get("campaignId", "")),
            "placement":        r.get("placementClassification", ""),
            "impressions":      _i(r.get("impressions")),
            "clicks":           _i(r.get("clicks")),
            "cost":             round(_f(r.get("cost")), 2),
            "purchases_14d":    _i(r.get("purchases14d")),
            "sales_14d":        round(_f(r.get("sales14d")), 2),
            "synced_at":        now,
        })
    n = upsert_chunks(client, T_PLACEMENT, rows, "report_date,campaign_id,placement")
    print(f"  → {T_PLACEMENT}: +{n}")
    return n


def write_bid_recommendations(client, recs: list, snapshot_date: str) -> int:
    """Snapshot bid recommendations per keyword."""
    now = now_iso_utc()
    rows = []
    for rec in recs:
        keyword_id = str(rec.get("keywordId", ""))
        for suggestion in rec.get("bidRecommendations", []):
            rows.append({
                "snapshot_date":    snapshot_date,
                "keyword_id":       keyword_id,
                "placement":        suggestion.get("placement", ""),
                "suggested_bid":    round(_f(suggestion.get("suggestedBid")), 2),
                "range_start":      round(_f(suggestion.get("rangeStart")), 2),
                "range_end":        round(_f(suggestion.get("rangeEnd")), 2),
                "synced_at":        now,
            })
    n = upsert_chunks(client, T_BID_RECS, rows, "snapshot_date,keyword_id,placement")
    print(f"  → {T_BID_RECS}: +{n}")
    return n
