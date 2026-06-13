"""Phase 3 — Module tổng hợp tài chính hiệu suất sản phẩm (kiểu Sellerboard).

Hợp nhất (Aggregation) dữ liệu đệm vật lý trên Supabase — các bảng NEW_* do
pipeline Phase 2 (fetch_24h_*.py) ghi vào — thành ma trận hiệu suất theo từng
(ASIN, SKU) trong N ngày gần nhất:

  NEW_sp_orders / NEW_sp_order_items  -> Doanh thu, Số lượng, Promo
  NEW_fin_item_fees                   -> Commission (Referral) + FBA fee + Other
  NEW_fin_refunds                     -> Số đơn hoàn + chi phí hoàn (Other_Fees)
  NEW_product_cogs                    -> COGS FIFO theo effective_date (đơn mua
                                         lúc nào áp mức giá vốn hiệu lực lúc đó)
  NEW_ads_campaigns_daily             -> Chi phí quảng cáo, phân bổ xuống SKU
  raw_amazon_campaign_reports         -> Fallback nếu bảng NEW_ ads trống

Công thức nghiêm ngặt cho từng SKU/ASIN:
  Net_Profit = (Price * Quantity) - Product_Cost - Commission - FBA_Fee
               - Promo - Ad_Spend +/- Other_Fees
  Margin     = (Net_Profit / (Price * Quantity)) * 100

Timezone: mọi phép lọc N ngày quy đổi qua to_marketplace_local() /
marketplace_local_to_utc() theo giờ địa phương marketplace (Pacific Time
America/Los_Angeles) để trùng khớp số liệu Amazon Seller Central.

Payload trả về TƯƠNG THÍCH NGƯỢC với UI hiện tại của app.tap2soul.com:
mỗi dòng top_products chứa cả khoá MỚI (sku, quantity, price, product_cost,
commission, fba_fee, promo, ad_spend, net_profit, margin) lẫn khoá CŨ mà
frontend/app.js đang dùng (units, refunds, sales, avg_selling_price, cogs,
fees, ppc, gross_profit, net_profit, margin_pct, roi_pct, bsr) — nên dù chưa
nạp render_performance.js, bảng cũ vẫn hiển thị bình thường.

Chạy thử độc lập (in JSON ra màn hình, không cần FastAPI):
    cd ~/VPS_AMZ/sellerboard_clone
    python Phase3/analytics_aggregator.py --days 7
"""
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PHASE3_DIR = Path(__file__).resolve().parent          # .../sellerboard_clone/Phase3_Application/data_bridge
_ROOT_DIR = _PHASE3_DIR.parent.parent                  # .../sellerboard_clone
_BACKEND_DIR = _ROOT_DIR / "backend"

# ── Bảng dữ liệu đệm trên Supabase ────────────────────────────────────────────
T_ORDERS  = "NEW_sp_orders"
T_ITEMS   = "NEW_sp_order_items"
T_FEES    = "NEW_fin_item_fees"
T_REFUNDS = "NEW_fin_refunds"
T_COGS    = "NEW_product_cogs"
T_ADS     = "NEW_ads_campaigns_daily"
T_ADS_RAW = "raw_amazon_campaign_reports"   # bảng đệm cũ — chỉ dùng fallback

_IN_CHUNK = 150            # số order_id mỗi lần lọc .in_() (tránh URL quá dài)
_CANCELED = ("Canceled", "Cancelled")


# ══════════════════════════════════════════════════════════════════════════════
# 0. Timezone helpers — ưu tiên dùng app.timeutils của backend (đúng yêu cầu
#    "đi qua helper to_marketplace_local() thuộc timeutils.py"); nếu chạy
#    độc lập ngoài backend thì fallback bản nội bộ tương đương.
# ══════════════════════════════════════════════════════════════════════════════
try:
    if str(_BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(_BACKEND_DIR))
    from app.timeutils import (MARKETPLACE_TZ, now_marketplace,   # type: ignore
                               to_marketplace_local)
except Exception:                                    # noqa: BLE001 — chạy standalone
    from zoneinfo import ZoneInfo

    MARKETPLACE_TZ = ZoneInfo(os.getenv("SELLER_TIMEZONE", "America/Los_Angeles"))

    def to_marketplace_local(dt: datetime) -> datetime:
        """UTC (naive/aware) -> giờ địa phương marketplace, trả về naive."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MARKETPLACE_TZ).replace(tzinfo=None)

    def now_marketplace() -> datetime:
        return to_marketplace_local(datetime.now(timezone.utc))


def marketplace_local_to_utc(local_dt: datetime) -> datetime:
    """Nghịch đảo của to_marketplace_local: mốc giờ local (naive) -> UTC naive,
    dùng để lọc các cột TIMESTAMPTZ lưu theo UTC (purchase_date, posted_date)."""
    return (local_dt.replace(tzinfo=MARKETPLACE_TZ)
            .astimezone(timezone.utc).replace(tzinfo=None))


def parse_iso(value) -> datetime | None:
    """Parse chuỗi ISO của Supabase ('...+00:00' hoặc '...Z') -> UTC naive."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ══════════════════════════════════════════════════════════════════════════════
# 1. Kết nối Supabase — ưu tiên client sẵn có của backend (app.config.settings),
#    fallback đọc .env (backend/.env -> Phase3/.env) khi chạy độc lập.
# ══════════════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def get_supabase_client():
    try:
        from app.services.supabase_client import get_supabase_client as _backend_client
        return _backend_client()
    except Exception:                                # noqa: BLE001 — fallback .env
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv(_BACKEND_DIR / ".env")
        load_dotenv(_PHASE3_DIR / ".env")
    except Exception:                                # noqa: BLE001 — dotenv optional
        pass
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "") or os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise ValueError("Thiếu SUPABASE_URL / SUPABASE_KEY (backend/.env hoặc Phase3/.env)")
    from supabase import create_client
    return create_client(url, key)


def fetch_all(make_query, page_size: int = 1000) -> list[dict]:
    """Đọc TOÀN BỘ rows theo trang (PostgREST giới hạn 1000 dòng/lần).
    `make_query` phải trả về query builder MỚI mỗi lần gọi (builder của
    supabase-py không tái sử dụng được sau .execute())."""
    rows: list[dict] = []
    offset = 0
    while True:
        resp = make_query().range(offset, offset + page_size - 1).execute()
        page = resp.data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def _float(val, default=0.0) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════════════
# 2. Orders trong kỳ (lọc theo UTC, gắn lại giờ local để xác định "ngày mua")
# ══════════════════════════════════════════════════════════════════════════════
def _fetch_orders(sb, start_utc: datetime, end_utc: datetime) -> dict[str, datetime]:
    """{order_id: purchase_date đã quy đổi sang giờ local marketplace}."""
    rows = fetch_all(lambda: (
        sb.table(T_ORDERS)
        .select("order_id,purchase_date,order_status")
        .gte("purchase_date", start_utc.isoformat() + "Z")
        .lte("purchase_date", end_utc.isoformat() + "Z")
        .not_.in_("order_status", list(_CANCELED))
    ))
    out: dict[str, datetime] = {}
    for r in rows:
        dt = parse_iso(r.get("purchase_date"))
        if r.get("order_id") and dt:
            out[r["order_id"]] = to_marketplace_local(dt)
    return out


def _fetch_items(sb, order_ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for i in range(0, len(order_ids), _IN_CHUNK):
        chunk = order_ids[i: i + _IN_CHUNK]
        rows.extend(fetch_all(lambda c=chunk: (
            sb.table(T_ITEMS)
            .select("order_id,asin,sku,title,quantity_ordered,item_price,promotion_discount")
            .in_("order_id", c)
        )))
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 3. Phí Amazon THẬT theo (order_id, sku) từ Finances API (NEW_fin_item_fees)
# ══════════════════════════════════════════════════════════════════════════════
def _fees_by_order_sku(sb, order_ids: list[str]) -> dict[tuple[str, str], dict]:
    """{(order_id, sku): {commission, fba, other}}.

    Commission/Referral và FBA* lấy TRỊ TUYỆT ĐỐI (DB lưu số âm); các loại phí
    còn lại GIỮ NGUYÊN DẤU -> thành phần +/- Other_Fees trong công thức."""
    out: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"commission": 0.0, "fba": 0.0, "other": 0.0})
    for i in range(0, len(order_ids), _IN_CHUNK):
        chunk = order_ids[i: i + _IN_CHUNK]
        rows = fetch_all(lambda c=chunk: (
            sb.table(T_FEES)
            .select("order_id,sku,fee_type,amount")
            .in_("order_id", c)
        ))
        for r in rows:
            key = (r.get("order_id") or "", r.get("sku") or "")
            fee_type = (r.get("fee_type") or "").lower()
            amt = _float(r.get("amount"))
            bucket = out[key]
            if "commission" in fee_type or "referral" in fee_type:
                bucket["commission"] += abs(amt)
            elif fee_type.startswith("fba") or "fulfillment" in fee_type:
                bucket["fba"] += abs(amt)
            else:
                bucket["other"] += amt
    return dict(out)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Hoàn hàng trong kỳ (NEW_fin_refunds, gán theo posted_date như Sellerboard)
# ══════════════════════════════════════════════════════════════════════════════
def _refunds_by_sku(sb, start_utc: datetime, end_utc: datetime) -> dict[str, dict]:
    """{sku: {count, cost}} — cost = principal + commission + refunded_referral
    (giữ nguyên dấu, principal âm) -> cộng vào Other_Fees của SKU tương ứng."""
    try:
        rows = fetch_all(lambda: (
            sb.table(T_REFUNDS)
            .select("sku,quantity_returned,refund_principal,refund_commission,refunded_referral_fee")
            .gte("posted_date", start_utc.isoformat() + "Z")
            .lte("posted_date", end_utc.isoformat() + "Z")
        ))
    except Exception as exc:                         # noqa: BLE001
        logger.warning("[Refunds] Khong doc duoc %s (%s) — bo qua.", T_REFUNDS, exc)
        return {}
    out: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost": 0.0})
    for r in rows:
        sku = r.get("sku") or ""
        if not sku:
            continue
        out[sku]["count"] += int(r.get("quantity_returned") or 1)
        out[sku]["cost"] += (_float(r.get("refund_principal"))
                             + _float(r.get("refund_commission"))
                             + _float(r.get("refunded_referral_fee")))
    return dict(out)


# ══════════════════════════════════════════════════════════════════════════════
# 5. COGS FIFO theo effective_date (đơn mua lúc nào áp mức giá vốn lúc đó)
# ══════════════════════════════════════════════════════════════════════════════
def _load_cogs(sb) -> dict[str, list[tuple[str, float]]]:
    """{sku: [(effective_date ISO, cog_per_unit), ...] sort tăng dần}."""
    rows = fetch_all(lambda: (
        sb.table(T_COGS).select("sku,cog_per_unit,effective_date")
    ))
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        if r.get("sku"):
            out[r["sku"]].append((r.get("effective_date") or "2000-01-01",
                                  _float(r.get("cog_per_unit"))))
    for sku in out:
        out[sku].sort()
    return dict(out)


def _unit_cogs(cogs_map: dict, sku: str, purchase_local: datetime) -> float:
    """Mức giá vốn hiệu lực tại thời điểm mua: bản ghi có effective_date lớn
    nhất nhưng <= ngày mua (tính theo giờ local marketplace)."""
    tiers = cogs_map.get(sku)
    if not tiers:
        return 0.0
    day = purchase_local.date().isoformat()
    cost = 0.0
    for eff, cog in tiers:               # đã sort tăng dần theo effective_date
        if eff <= day:
            cost = cog
        else:
            break
    return cost


# ══════════════════════════════════════════════════════════════════════════════
# 6. Phân bổ chi phí quảng cáo (Attribution Logic) xuống từng SKU
# ══════════════════════════════════════════════════════════════════════════════
def _fetch_ads_rows(sb, start_local: datetime, end_local: datetime) -> list[dict]:
    """Đọc báo cáo ads trong kỳ. Ads API trả report theo timezone tài khoản
    quảng cáo (= local marketplace) nên lọc thẳng theo NGÀY local.

    Ưu tiên NEW_ads_campaigns_daily (Phase 2); nếu trống/lỗi thì fallback sang
    bảng đệm cũ raw_amazon_campaign_reports (cấu trúc raw_json)."""
    start_d = start_local.date().isoformat()
    end_d = end_local.date().isoformat()
    try:
        rows = fetch_all(lambda: (
            sb.table(T_ADS)
            .select("report_date,campaign_name,asin,sku,cost")
            .gte("report_date", start_d)
            .lte("report_date", end_d)
        ))
        if rows:
            return rows
    except Exception as exc:                         # noqa: BLE001
        logger.warning("[Ads] Khong doc duoc %s (%s) — thu bang fallback.", T_ADS, exc)
    try:
        raw = fetch_all(lambda: (
            sb.table(T_ADS_RAW)
            .select("*")
            .gte("report_date", start_d)
            .lte("report_date", end_d)
        ))
    except Exception as exc:                         # noqa: BLE001
        logger.warning("[Ads] Khong doc duoc %s (%s) — bo qua chi phi ads.", T_ADS_RAW, exc)
        return []
    rows = []
    for r in raw:
        j = r.get("raw_json") if isinstance(r.get("raw_json"), dict) else r
        rows.append({
            "campaign_name": j.get("campaignName") or j.get("campaign_name") or "",
            "asin": j.get("advertisedAsin") or j.get("asin"),
            "sku": j.get("advertisedSku") or j.get("sku"),
            "cost": j.get("cost") or j.get("spend") or j.get("ad_spend") or 0,
        })
    return rows


def _ads_spend_by_sku(sb, sales_by_sku: dict[str, float], asin_to_sku: dict[str, str],
                      start_local: datetime, end_local: datetime) -> dict[str, float]:
    """Phân bổ 3 tầng:
      1) Bản ghi cấp SKU/ASIN (report SP theo advertisedSku/Asin) -> gán thẳng.
      2) Bản ghi cấp campaign: tên campaign chứa SKU -> gán cho SKU đó.
      3) Spend còn lại (SB/SD, campaign không match) -> phân bổ theo tỉ trọng
         doanh thu từng SKU trong kỳ.

    Bọc try-except toàn phần: lỗi Supabase -> trả {} (ads = 0), KHÔNG làm sập
    dashboard."""
    try:
        rows = _fetch_ads_rows(sb, start_local, end_local)
    except Exception as exc:                         # noqa: BLE001
        logger.warning("[Ads] Loi doc bao cao ads (%s).", exc)
        return {}

    allocated: dict[str, float] = defaultdict(float)
    unmatched = 0.0
    skus_upper = {s.upper(): s for s in sales_by_sku if s}

    for r in rows:
        cost = _float(r.get("cost"))
        if not cost:
            continue
        sku = r.get("sku") or ""
        asin = r.get("asin") or ""
        if sku in sales_by_sku:                      # tầng 1a: trùng SKU
            allocated[sku] += cost
            continue
        if asin in asin_to_sku:                      # tầng 1b: trùng ASIN
            allocated[asin_to_sku[asin]] += cost
            continue
        name = str(r.get("campaign_name") or "").upper()
        hit = next((orig for up, orig in skus_upper.items() if up and up in name), None)
        if hit:                                      # tầng 2: SKU trong tên campaign
            allocated[hit] += cost
        else:
            unmatched += cost

    total_sales = sum(v for v in sales_by_sku.values() if v > 0)
    if unmatched > 0 and total_sales > 0:            # tầng 3: theo tỉ trọng doanh thu
        for sku, s in sales_by_sku.items():
            if s > 0:
                allocated[sku] += unmatched * (s / total_sales)
    return dict(allocated)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Hàm chính: hợp nhất tất cả thành payload {status, period_days, top_products}
# ══════════════════════════════════════════════════════════════════════════════
def aggregate_product_performance(days: int = 30) -> dict:
    """Tính ma trận hiệu suất sản phẩm N ngày gần nhất (theo giờ marketplace).

    Trả về dict sạch cho frontend:
      {status, period_days, days, range, totals, top_products: [...]}"""
    end_local = now_marketplace()
    start_local = end_local - timedelta(days=days)
    start_utc = marketplace_local_to_utc(start_local)
    end_utc = marketplace_local_to_utc(end_local)

    base = {
        "status": "success",
        "period_days": days,
        "days": days,
        "range": {"start": start_local.date().isoformat(),
                  "end": end_local.date().isoformat(),
                  "timezone": str(MARKETPLACE_TZ)},
        "totals": {},
        "top_products": [],
    }

    sb = get_supabase_client()
    orders = _fetch_orders(sb, start_utc, end_utc)
    if not orders:
        return base                                   # kỳ này không có đơn nào

    order_ids = list(orders)
    items = _fetch_items(sb, order_ids)
    fees = _fees_by_order_sku(sb, order_ids)
    refunds = _refunds_by_sku(sb, start_utc, end_utc)
    cogs_map = _load_cogs(sb)

    # ── Gom theo (asin, sku) ──────────────────────────────────────────────────
    agg: dict[tuple[str, str], dict] = {}
    for it in items:
        oid = it.get("order_id") or ""
        purchase_local = orders.get(oid)
        if purchase_local is None or not (start_local <= purchase_local <= end_local):
            continue
        asin = it.get("asin") or ""
        sku = it.get("sku") or ""
        qty = int(it.get("quantity_ordered") or 0)
        sales = _float(it.get("item_price"))
        promo = abs(_float(it.get("promotion_discount")))    # DB lưu số âm
        fee = fees.get((oid, sku), {})
        row = agg.setdefault((asin, sku), {
            "asin": asin, "sku": sku, "title": it.get("title") or "",
            "quantity": 0, "sales": 0.0, "product_cost": 0.0,
            "commission": 0.0, "fba_fee": 0.0, "promo": 0.0,
            "other_fees": 0.0, "ad_spend": 0.0,
            "refunds": 0, "refund_cost": 0.0,
        })
        row["quantity"] += qty
        row["sales"] += sales
        row["promo"] += promo
        row["product_cost"] += _unit_cogs(cogs_map, sku, purchase_local) * qty
        row["commission"] += fee.get("commission", 0.0)
        row["fba_fee"] += fee.get("fba", 0.0)
        row["other_fees"] += fee.get("other", 0.0)

    # ── Gắn refunds trong kỳ vào SKU tương ứng (theo posted_date) ─────────────
    sku_rows: dict[str, list] = defaultdict(list)
    for key, row in agg.items():
        sku_rows[key[1]].append(row)
    for sku, ref in refunds.items():
        rows_ = sku_rows.get(sku)
        if not rows_:
            continue                                   # refund của SKU ngoài kỳ bán
        main = max(rows_, key=lambda r: r["sales"])    # gán vào dòng doanh thu lớn nhất
        main["refunds"] += ref["count"]
        main["refund_cost"] += ref["cost"]
        main["other_fees"] += ref["cost"]              # cost âm -> trừ vào Net Profit

    # ── Phân bổ ads sau khi đã biết doanh thu từng SKU ────────────────────────
    sales_by_sku: dict[str, float] = defaultdict(float)
    asin_to_sku: dict[str, str] = {}
    for (asin, sku), row in agg.items():
        sales_by_sku[sku] += row["sales"]
        if asin and asin not in asin_to_sku:
            asin_to_sku[asin] = sku
    ads_by_sku = _ads_spend_by_sku(sb, dict(sales_by_sku), asin_to_sku,
                                   start_local, end_local)
    # 1 SKU có thể xuất hiện ở nhiều dòng (asin, sku) — chia theo tỉ trọng sales
    for (asin, sku), row in agg.items():
        sku_ads = ads_by_sku.get(sku, 0.0)
        sku_sales = sales_by_sku.get(sku, 0.0)
        row["ad_spend"] = sku_ads * (row["sales"] / sku_sales) if sku_sales else sku_ads

    # ── Tính Net Profit / Margin + xuất payload (khoá mới + khoá cũ) ──────────
    top_products = []
    for row in agg.values():
        sales, qty, cogs = row["sales"], row["quantity"], row["product_cost"]
        fees_total = row["commission"] + row["fba_fee"]
        net = (sales - cogs - row["commission"] - row["fba_fee"]
               - row["promo"] - row["ad_spend"] + row["other_fees"])
        margin = round(net / sales * 100, 1) if sales else 0.0
        price = round(sales / qty, 2) if qty else 0.0
        top_products.append({
            # ── Khoá MỚI theo spec Phase 3 ──
            "asin": row["asin"],
            "sku": row["sku"],
            "title": row["title"],
            "quantity": qty,
            "price": price,
            "sales": round(sales, 2),
            "product_cost": round(cogs, 2),
            "commission": round(row["commission"], 2),
            "fba_fee": round(row["fba_fee"], 2),
            "promo": round(row["promo"], 2),
            "other_fees": round(row["other_fees"], 2),
            "ad_spend": round(row["ad_spend"], 2),
            "net_profit": round(net, 2),
            "margin": margin,
            "refund_cost": round(row["refund_cost"], 2),
            # ── Khoá CŨ (alias) để UI hiện tại không gãy ──
            "product_id": 0,
            "units": qty,
            "refunds": row["refunds"],
            "avg_selling_price": price,
            "cogs": round(cogs, 2),
            "fees": round(fees_total, 2),
            "ppc": round(row["ad_spend"], 2),
            "gross_profit": round(sales - cogs, 2),
            "margin_pct": margin,
            "roi_pct": round(net / cogs * 100, 1) if cogs else 0.0,
            "bsr": None,
        })
    top_products.sort(key=lambda p: p["net_profit"], reverse=True)

    totals = {k: round(sum(p[k] for p in top_products), 2)
              for k in ("quantity", "sales", "product_cost", "commission",
                        "fba_fee", "promo", "other_fees", "ad_spend",
                        "net_profit", "refunds")}
    totals["quantity"] = int(totals["quantity"])
    totals["refunds"] = int(totals["refunds"])
    totals["margin"] = round(totals["net_profit"] / totals["sales"] * 100, 1) \
        if totals["sales"] else 0.0
    totals["orders"] = len(orders)

    base["totals"] = totals
    base["top_products"] = top_products
    return base


# ── CLI: python Phase3/analytics_aggregator.py --days 7 ──────────────────────
if __name__ == "__main__":
    import argparse

    # Console Windows mặc định cp1252 — ép UTF-8 để in được tiếng Việt/JSON
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Phase 3 — tổng hợp hiệu suất sản phẩm")
    ap.add_argument("--days", type=int, default=7, help="Số ngày (7/30/90)")
    args = ap.parse_args()
    try:
        data = aggregate_product_performance(days=args.days)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\n=> {len(data['top_products'])} SKU, kỳ "
              f"{data['range']['start']} -> {data['range']['end']}", file=sys.stderr)
    except Exception as exc:                          # noqa: BLE001
        print(f"LỖI: {exc}", file=sys.stderr)
        sys.exit(1)
