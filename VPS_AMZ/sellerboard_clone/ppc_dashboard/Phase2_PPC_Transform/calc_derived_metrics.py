"""PPC Phase 2 — Derived metrics calculator.

Tính các chỉ số derived từ raw metrics (giống 25 cột của Sellervision PPC CSV):

  ACOS             = cost / sales_14d * 100                (nếu sales_14d > 0)
  CVR              = purchases_14d / clicks * 100          (nếu clicks > 0)
  CPC              = cost / clicks                         (nếu clicks > 0)
  CTR              = clicks / impressions * 100            (nếu impressions > 0)
  ROAS             = sales_14d / cost                      (nếu cost > 0)
  Orders           = purchases_14d
  Units            = units_sold_14d (nếu có) else purchases_14d
  CostPerOrder     = cost / purchases_14d                  (nếu orders > 0)
  SameSkuPct       = same_sku_sales_14d / sales_14d * 100  (nếu sales_14d > 0)
  BudgetUtilization= cost / daily_budget * 100             (nếu daily_budget > 0, tính theo kỳ)
  BreakEvenACOS    = (gross_profit_unit / asp) * 100       (cần COGS)
  BreakEvenBid     = break_even_acos * cpc / acos          (nếu acos > 0)
  topOfSearchPct   = impressions_top / impressions_total * 100  (từ PPC_Phase1_placement_daily)

Import:
    from calc_derived_metrics import calc_metrics, calc_break_even
"""
from __future__ import annotations


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not denominator:
        return default
    return numerator / denominator


def calc_metrics(row: dict, daily_budget: float = 0.0) -> dict:
    """Tính derived metrics từ 1 row raw (campaigns/adgroups/keywords/searchterms).

    Args:
        row: dict có các key: cost, clicks, impressions, purchases_14d,
             sales_14d, units_sold_14d, same_sku_sales_14d
        daily_budget: ngân sách ngày (từ PPC_Phase1_campaigns_raw) để tính budget_utilization

    Returns:
        dict với các key derived metrics (KHÔNG mutate row gốc)
    """
    cost         = float(row.get("cost", 0) or 0)
    clicks       = int(row.get("clicks", 0) or 0)
    impressions  = int(row.get("impressions", 0) or 0)
    purchases    = int(row.get("purchases_14d", 0) or 0)
    sales        = float(row.get("sales_14d", 0) or 0)
    units        = int(row.get("units_sold_14d", 0) or 0) or purchases
    same_sku     = float(row.get("same_sku_sales_14d", 0) or 0)

    acos   = _safe_div(cost, sales) * 100
    cvr    = _safe_div(purchases, clicks) * 100
    cpc    = _safe_div(cost, clicks)
    ctr    = _safe_div(clicks, impressions) * 100
    roas   = _safe_div(sales, cost)
    cpo    = _safe_div(cost, purchases)   # CostPerOrder
    same_pct = _safe_div(same_sku, sales) * 100

    budget_util = _safe_div(cost, daily_budget) * 100 if daily_budget > 0 else None

    return {
        "acos":               round(acos, 2),
        "cvr":                round(cvr, 2),
        "cpc":                round(cpc, 4),
        "ctr":                round(ctr, 4),
        "roas":               round(roas, 4),
        "orders":             purchases,
        "units":              units,
        "cost_per_order":     round(cpo, 4),
        "same_sku_pct":       round(same_pct, 2),
        "budget_utilization": round(budget_util, 2) if budget_util is not None else None,
    }


def calc_break_even(asp: float, cogs: float, referral_rate: float = 0.165) -> dict:
    """Tính Break-Even ACOS và Break-Even Bid.

    Args:
        asp: average selling price (giá bán đơn vị)
        cogs: cost of goods sold per unit (ÂM theo quy ước, hoặc truyền dương đều OK)
        referral_rate: tỷ lệ referral fee (mặc định 16.5% = 15% + 10% VAT VN)

    Returns:
        dict: break_even_acos (%), break_even_bid ($)
    """
    if not asp or asp <= 0:
        return {"break_even_acos": None, "break_even_bid": None}

    cogs_abs       = abs(float(cogs or 0))
    referral_fee   = asp * referral_rate
    gross_profit   = asp - cogs_abs - referral_fee

    if gross_profit <= 0:
        return {"break_even_acos": 0.0, "break_even_bid": 0.0}

    be_acos = (gross_profit / asp) * 100

    return {
        "break_even_acos": round(be_acos, 2),
        "break_even_bid":  None,  # tính ở summary dựa trên CPC thực tế
    }


def calc_break_even_bid(break_even_acos: float, cpc: float, acos: float) -> float | None:
    """Break-Even Bid = current_bid * (break_even_acos / current_acos).

    Nếu current ACOS = 0 -> không tính được.
    """
    if not acos or not cpc or not break_even_acos:
        return None
    return round(cpc * (break_even_acos / acos), 4)


def calc_top_of_search_pct(impressions_total: int, impressions_top: int) -> float | None:
    """topOfSearch% = impressions tại Top Of Search / total impressions * 100."""
    if not impressions_total:
        return None
    return round(impressions_top / impressions_total * 100, 2)
