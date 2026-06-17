"""Router PPC đa-store (Excel-based) + PPC Dashboard API (Mức 4-9).

Endpoints cũ  : /api/ppc/stores|upload|listing|sku|export  — Excel-based PPC
Endpoints mới : /api/ppc/overview|grid|children             — Dashboard Mức 3-9
"""
import math
import random
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from ..deps import get_current_user
from ..models import User
from ..services import ppc as ppc_service

router = APIRouter(prefix="/api/ppc", tags=["ppc"])

MAX_UPLOAD_MB = 25


@router.get("/stores")
def stores(current: User = Depends(get_current_user)):
    """Danh sách store (mỗi store = 1 file Excel PPC)."""
    return ppc_service.list_stores()


@router.post("/upload")
async def upload(file: UploadFile = File(...), current: User = Depends(get_current_user)):
    """Upload file Excel PPC lên server (thay cho đường dẫn local khi chạy trên domain)."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        return {"error": f"File quá lớn (>{MAX_UPLOAD_MB}MB)"}
    return ppc_service.save_upload(file.filename, content)


@router.get("/listing")
def listing(store: str | None = Query(None), current: User = Depends(get_current_user)):
    """Danh sách Listing (SKU) của 1 store."""
    return ppc_service.get_listing(store)


@router.get("/sku")
def sku_detail(sku: str = Query(..., description="Mã SKU lấy từ danh sách Listing"),
              store: str | None = Query(None),
              current: User = Depends(get_current_user)):
    """Chi tiết 1 SKU: campaign + target + Impression/Click/Order + CTR/CVR theo kỳ."""
    return ppc_service.get_sku_detail(sku, store)


@router.get("/export")
def export(store: str | None = Query(None),
           sku: str | None = Query(None, description="Bỏ trống = xuất cả store"),
           format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
           current: User = Depends(get_current_user)):
    """Xuất kết quả (1 SKU hoặc cả store) ra CSV/Excel, đã gồm CTR/CVR."""
    name = (sku or store or "ppc").replace(" ", "_").replace(",", "")
    if format == "csv":
        data = ppc_service.export_csv(store, sku)
        media = "text/csv"
        fname = f"PPC_{name}.csv"
    else:
        data = ppc_service.export_xlsx(store, sku)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        fname = f"PPC_{name}.xlsx"
    import io
    return StreamingResponse(io.BytesIO(data), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ═══════════════════════════════════════════════════════════════════════════════
# PPC Dashboard API  (Mức 3–9) — Mock data theo đúng Schema Contract
#
# Schema Contract mỗi row:
#   { id, entity_type, name, status, image_url,
#     metrics: { impressions, clicks, orders, units, ad_spend, cpc, ppc_sales,
#                cpa, conversion, same_sku_pct, acos, profit },
#     automation: { break_even_acos, break_even_bid, current_bid,
#                   bid_recommendation, daily_budget, strategy, automation_status },
#     has_children }
#
# Thay bằng query Supabase thật khi pipeline PPC data sẵn sàng.
# ═══════════════════════════════════════════════════════════════════════════════

def _seed(s: str) -> float:
    """Deterministic pseudo-random từ string seed (thread-safe, không dùng random.seed)."""
    return (hash(s) % 10000) / 10000.0


def _mock_metrics(seed_key: str, scale: float = 1.0) -> dict[str, Any]:
    """Sinh metrics PPC đầy đủ 12 trường, nhất quán theo seed."""
    r          = _seed(seed_key)
    r2         = _seed(seed_key + "_b")   # seed thứ 2 để tránh tương quan

    impressions = int((500 + r * 50_000) * scale)
    clicks      = max(1, int(impressions * (0.005 + r2 * 0.04)))   # CTR 0.5–4.5%
    orders      = max(0, int(clicks * (0.05 + r * 0.18)))          # CVR 5–23%
    units       = orders + int(orders * r2 * 0.3)                  # đôi khi > orders (multi-unit)
    cpc         = round(0.25 + r * 1.55, 2)
    ad_spend    = round(clicks * cpc, 2)
    avg_price   = round(14 + r2 * 55, 2)
    ppc_sales   = round(orders * avg_price * scale, 2)
    acos        = round(ad_spend / ppc_sales * 100, 2) if ppc_sales else 0.0
    cpa         = round(ad_spend / orders, 2) if orders else 0.0
    conversion  = round(orders / clicks * 100, 2) if clicks else 0.0
    same_sku_pct = round(60 + r * 38, 2)                           # 60–98%
    cogs_ratio  = 0.40 + r2 * 0.20
    profit      = round(ppc_sales * (1 - cogs_ratio) - ad_spend, 2)

    return {
        "impressions":  impressions,
        "clicks":       clicks,
        "orders":       orders,
        "units":        units,
        "ad_spend":     ad_spend,
        "cpc":          cpc,
        "ppc_sales":    ppc_sales,
        "cpa":          cpa,
        "conversion":   conversion,
        "same_sku_pct": same_sku_pct,
        "acos":         acos,
        "profit":       profit,
    }


def _mock_automation(seed_key: str, entity_type: str) -> dict[str, Any]:
    """Sinh automation object cho từng cấp entity."""
    r  = _seed(seed_key + "_auto")
    r2 = _seed(seed_key + "_auto2")

    break_even_acos = round(22 + r * 28, 2)          # 22–50%
    cogs_pct        = 0.40 + r2 * 0.20
    # BEP Bid = BEP_ACOS% × avg_price × (1 - COGS%)   (simplified estimate)
    avg_price       = round(14 + r2 * 55, 2)
    break_even_bid  = round(break_even_acos / 100 * avg_price * (1 - cogs_pct), 2)

    strategies      = ["aggressive", "moderate", "conservative", "target_acos"]
    strategy        = strategies[int(r * len(strategies)) % len(strategies)]
    auto_on         = r > 0.45
    automation_status = "on" if auto_on else "off"

    result: dict[str, Any] = {
        "break_even_acos":  break_even_acos,
        "break_even_bid":   break_even_bid,
        "bid_recommendation": break_even_bid,    # đơn giản: rec = BEP bid
        "strategy":         strategy,
        "automation_status": automation_status,
        # Các trường chỉ xuất hiện ở cấp phù hợp
        "current_bid":   None,
        "daily_budget":  None,
    }

    if entity_type == "keyword":
        result["current_bid"]      = round(break_even_bid * (0.8 + r2 * 0.8), 2)
        result["bid_recommendation"] = break_even_bid
    elif entity_type == "search_term":
        result["current_bid"]      = round(break_even_bid * (0.7 + r2 * 0.9), 2)
    elif entity_type == "campaign":
        result["daily_budget"]     = round(8 + r * 92, 2)    # $8–$100

    return result


# ── Lookup tables ─────────────────────────────────────────────────────────────

_ENTITY_CHILDREN: dict[str, str] = {
    "portfolio":   "campaign",
    "campaign":    "ad_group",
    "ad_group":    "keyword",
    "keyword":     "search_term",
    "search_term": "",
}

_STATUS_POOL = ["ENABLED", "ENABLED", "ENABLED", "PAUSED", "PAUSED", "ARCHIVED"]

_MATCH_TYPES     = ["EXACT", "EXACT", "PHRASE", "BROAD"]   # SKAG → Exact chiếm đa số

_PORTFOLIO_NAMES = [
    "TURTLEJAR — Brand Defense",
    "TURTLEJAR — Competitor Conquest",
    "TURTLEJAR — Category Broad",
    "Auto Campaign Pool",
]
_CAMPAIGN_NAMES = [
    "SP | Exact | Brand KW",
    "SP | Broad | Category",
    "SB | Video | Retargeting",
    "SD | ASIN Target | Competitors",
    "SP | Phrase | Gift Ideas",
    "SB | Headline | Seasonal",
    "SP | Auto | Discovery",
    "SD | Audience | Remarketing",
]
_ADGROUP_NAMES = [
    "Ad Group — Jar 500ml",
    "Ad Group — Jar 1L",
    "Ad Group — Gift Set Bundle",
    "Ad Group — Seasonal Promo",
]
_KW_NAMES = [
    "turtle jar handmade",
    "ceramic storage jar with lid",
    "japanese pottery kitchen jar",
    "clay pot organic design",
    "artisan jar gift set",
    "stoneware jar rustic",
]
_ST_NAMES = [
    "turtle jar",
    "handmade ceramic jar",
    "japanese style pot",
    "clay pot with lid",
    "pottery jar organic",
    "ceramic gift jar",
    "stoneware kitchen container",
]
_SKUS   = ["TURTLE-JAR-500", "TURTLE-JAR-1L", "TURTLE-GFT-SET"]
# Ảnh placeholder public (không cần authen)
_IMAGES = [
    "https://placehold.co/56x56/e0f2fe/0369a1?text=JAR1",
    "https://placehold.co/56x56/fce7f3/be185d?text=JAR2",
    "https://placehold.co/56x56/dcfce7/15803d?text=SET",
]


def _build_row(entity_type: str, idx: int, parent_prefix: str = "") -> dict[str, Any]:
    """Xây 1 row theo đúng Schema Contract."""
    names_map = {
        "portfolio":   _PORTFOLIO_NAMES,
        "campaign":    _CAMPAIGN_NAMES,
        "ad_group":    _ADGROUP_NAMES,
        "keyword":     _KW_NAMES,
        "search_term": _ST_NAMES,
    }
    name   = names_map.get(entity_type, ["Item"])[idx % len(names_map.get(entity_type, ["Item"]))]
    row_id = f"{entity_type[:3]}_{parent_prefix}_{idx:02d}" if parent_prefix else f"{entity_type[:3]}_{idx:02d}"
    r      = _seed(row_id)
    status = _STATUS_POOL[int(r * len(_STATUS_POOL)) % len(_STATUS_POOL)]

    # image_url — chỉ hiển thị ở cấp ad_group trên frontend, nhưng field luôn có
    image_url: str | None = None
    if entity_type == "ad_group":
        image_url = _IMAGES[idx % len(_IMAGES)]

    # match_type — chỉ có nghĩa ở keyword / search_term (SKAG: Exact chiếm đa số)
    match_type: str | None = None
    if entity_type in ("keyword", "search_term"):
        match_type = _MATCH_TYPES[int(r * len(_MATCH_TYPES)) % len(_MATCH_TYPES)]

    # campaign_name — tiêm vào ad_group để frontend hiển thị sub-text tra cứu chéo
    campaign_name: str | None = None
    if entity_type == "ad_group":
        campaign_name = _CAMPAIGN_NAMES[idx % len(_CAMPAIGN_NAMES)]

    return {
        "id":            row_id,
        "entity_type":   entity_type,
        "name":          name,
        "status":        status,
        "image_url":     image_url,
        "match_type":    match_type,    # EXACT | PHRASE | BROAD (keyword/search_term)
        "campaign_name": campaign_name, # tên campaign cha (ad_group only)
        "metrics":       _mock_metrics(row_id),
        "automation":    _mock_automation(row_id, entity_type),
        "has_children":  _ENTITY_CHILDREN.get(entity_type, "") != "",
    }


# ── /api/ppc/overview ────────────────────────────────────────────────────────

@router.get("/overview", summary="KPI tổng hợp + timeseries (Dashboard Mức 3)")
def ppc_overview(
    start:  str = Query("2026-05-12"),
    end:    str = Query("2026-06-12"),
    status: str = Query("ENABLED,PAUSED"),
    sku:    str = Query(""),
    camps:  str = Query(""),
    current: User = Depends(get_current_user),
):
    """KPIs tổng hợp (9 chỉ số) + timeseries daily cho Mid Panel."""
    try:
        d_start = date.fromisoformat(start)
        d_end   = date.fromisoformat(end)
    except ValueError:
        d_start, d_end = date(2026, 5, 12), date(2026, 6, 12)

    timeseries: list[dict] = []
    cur = d_start
    while cur <= d_end:
        day_key = cur.isoformat()
        phase   = (cur - d_start).days / max((d_end - d_start).days, 1) * math.pi * 2
        factor  = 0.65 + 0.35 * math.sin(phase)
        m       = _mock_metrics(day_key, scale=factor)
        timeseries.append({
            "date":      day_key,
            "ppc_sales": m["ppc_sales"],
            "ad_spend":  m["ad_spend"],
            "acos":      m["acos"],
            "profit":    m["profit"],
            "orders":    m["orders"],
            "clicks":    m["clicks"],
        })
        cur += timedelta(days=1)

    # Tổng hợp KPI
    total_sales  = round(sum(d["ppc_sales"] for d in timeseries), 2)
    total_spend  = round(sum(d["ad_spend"]  for d in timeseries), 2)
    total_orders = sum(d["orders"] for d in timeseries)
    total_clicks = sum(d["clicks"] for d in timeseries)
    total_impr   = int(total_clicks * 22)     # CTR ~4.5%

    kpis: dict[str, Any] = {
        "ppc_sales":   total_sales,
        "ad_spend":    total_spend,
        "profit":      round(sum(d["profit"] for d in timeseries), 2),
        "acos":        round(total_spend / total_sales * 100, 2) if total_sales else 0.0,
        "orders":      total_orders,
        "clicks":      total_clicks,
        "impressions": total_impr,
        "cpc":         round(total_spend / total_clicks, 2) if total_clicks else 0.0,
        "cvr":         round(total_orders / total_clicks * 100, 2) if total_clicks else 0.0,
    }

    return {"kpis": kpis, "timeseries": timeseries}


# ── /api/ppc/grid ─────────────────────────────────────────────────────────────

@router.get("/grid", summary="Top-level grid data (Dashboard Bot Panel)")
def ppc_grid(
    entity_type: str = Query("portfolio"),
    start:  str = Query("2026-05-12"),
    end:    str = Query("2026-06-12"),
    status: str = Query("ENABLED,PAUSED"),
    sku:    str = Query(""),
    camps:  str = Query(""),
    current: User = Depends(get_current_user),
):
    """Trả về danh sách rows top-level cho tab được chọn.

    entity_type: portfolio | campaign | ad_group | keyword | search_term
    """
    if entity_type not in _ENTITY_CHILDREN:
        entity_type = "portfolio"

    count_map = {
        "portfolio": 4, "campaign": 8, "ad_group": 10,
        "keyword": 15,  "search_term": 20,
    }
    rows = [_build_row(entity_type, i) for i in range(count_map.get(entity_type, 5))]
    return {"rows": rows, "entity_type": entity_type}


# ── /api/ppc/children ────────────────────────────────────────────────────────

@router.get("/children", summary="Lazy-load children (Mức 6–9)")
def ppc_children(
    parent_id: str = Query(..., description="ID của entity cha"),
    type:      str = Query(..., description="entity_type của entity cha: portfolio|campaign|ad_group|keyword"),
    start:  str = Query("2026-05-12"),
    end:    str = Query("2026-06-12"),
    status: str = Query("ENABLED,PAUSED"),
    camps:  str = Query(""),
    current: User = Depends(get_current_user),
):
    """Lazy-load children của 1 entity.  Schema Contract:

    {
      "children": [
        {
          "id": "kw_123",
          "entity_type": "keyword",
          "name": "turtle gifts",
          "status": "ENABLED",
          "image_url": null,
          "metrics": {
            "impressions": 30076, "clicks": 329, "orders": 26, "units": 26,
            "ad_spend": 237.14, "cpc": 0.72, "ppc_sales": 363.74, "cpa": 11.0,
            "conversion": 7.90, "same_sku_pct": 82.5, "acos": 65.0, "profit": -78.72
          },
          "automation": {
            "break_even_acos": 44.0, "break_even_bid": 0.49,
            "current_bid": 0.60, "bid_recommendation": 0.49,
            "daily_budget": null, "strategy": "moderate", "automation_status": "on"
          },
          "has_children": true
        }
      ]
    }
    """
    child_type = _ENTITY_CHILDREN.get(type, "")
    if not child_type:
        return {"children": []}

    count_map = {"campaign": 4, "ad_group": 3, "keyword": 5, "search_term": 6}
    n = count_map.get(child_type, 3)

    safe_prefix = parent_id.replace(" ", "_")[:10]
    children = [_build_row(child_type, i, parent_prefix=safe_prefix) for i in range(n)]
    return {"children": children}
