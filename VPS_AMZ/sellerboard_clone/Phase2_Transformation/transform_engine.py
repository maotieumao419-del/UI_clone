"""Phase 2 — Financial Transformation & Aggregation Engine.

Đọc dữ liệu THÔ từ bảng đệm Supabase (NEW_*, do Phase1_Ingestion ghi vào),
xử lý theo múi giờ Pacific Time (America/Los_Angeles), xuất ra 2 bảng Master:

  NEW_summary_order_items  — chi tiết theo đơn hàng (CSV Order Items mẫu)
  NEW_summary_products     — 31 chỉ số hiệu suất theo (ASIN, SKU)

Quy ước dấu (giống CSV Sellerboard): doanh thu DƯƠNG, mọi chi phí ÂM —
các cột cộng dồn được: Gross = Sales + Promo + Amazon_fees + COGS + Shipping;
Net = Gross + Ads + Refund_cost + Expenses.

Amazon fees = Referral (Commission) + FBA Fulfillment — phí THẬT từ Finances
API (NEW_fin_item_fees, match theo order_id + sku). COGS FIFO theo
effective_date (config_cogs.py).

Thuật toán phân bổ Ad Spend 3 tầng (cho từng kênh SP/SB/SBV/SD):
  Tầng 1: bản ghi cấp SKU/ASIN (NEW_ads_sp_asin_daily) -> gán thẳng 100%.
  Tầng 2: regex quét tên campaign chứa SKU -> gán SKU tương ứng.
  Tầng 3: phần còn lại phân bổ theo tỷ trọng doanh thu (Revenue Share).

Quy tắc Roll-up: sau khi tính xong, validate_rollup() đối chiếu
SUM(Summary_Order_Items) == Summary_Products theo từng SKU — lệch quá $0.01
thì in cảnh báo (không chặn ghi).

Chạy:
    python transform_engine.py --days 7              # 7 ngày gần nhất (Pacific)
    python transform_engine.py --date 2026-06-10     # đúng 1 ngày
    python transform_engine.py --days 7 --json       # in JSON, vẫn ghi Supabase
    python transform_engine.py --days 7 --no-write   # chỉ tính, không ghi
"""
import argparse
import gc
import json
import logging
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_cogs as cfg
from aggregation_models import (T_SUMMARY_CAMPAIGNS, T_SUMMARY_ITEMS,
                                T_SUMMARY_PRODUCTS, T_SUMMARY_REIMBURSEMENTS,
                                SummaryCampaign, SummaryOrderItem, SummaryProduct,
                                SummaryReimbursement, validate_rollup)

load_dotenv()
logger = logging.getLogger(__name__)

T_ORDERS    = "NEW_sp_orders"
T_ITEMS     = "NEW_sp_order_items"
T_FEES      = "NEW_fin_item_fees"
T_REFUNDS   = "NEW_fin_refunds"
T_ADJUSTMENTS = "NEW_fin_adjustments"
T_ADS       = "NEW_ads_campaigns_daily"
T_ADS_SKU   = "NEW_ads_sp_asin_daily"
T_FEE_CACHE = "NEW_fee_cache"
T_PRICE     = "NEW_product_price"

_IN_CHUNK   = 150       # số order_id mỗi lần .in_() — tránh URL quá dài
_CHUNK_SIZE = 100       # chunk upsert nội bộ (calibrate_fee_cache)
_LOAD_BATCH = 1000      # micro-batch ghi Master (tránh HTTP 413 Payload Too Large)
# NEW_summary_order_items/NEW_summary_products có owner_id NOT NULL trong PK
# (migrate_summary_order_items_owner_id.py) — DB hiện chỉ có 1 user (id=1).
DEFAULT_OWNER_ID = int(os.getenv("SUMMARY_OWNER_ID", "1"))
_CANCELED   = ("Canceled", "Cancelled")
MARKETPLACE_LABEL = os.getenv("MARKETPLACE_LABEL", "Amazon.com")
# Referral mặc định khi không có override/không suy được (Amazon US chuẩn 15%)
DEFAULT_REFERRAL_RATE = float(os.getenv("DEFAULT_REFERRAL_RATE", "0.15"))


def get_supabase_client():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise ValueError("Thiếu SUPABASE_URL / SUPABASE_SERVICE_KEY trong .env")
    from supabase import create_client
    return create_client(url, key)


def fetch_all(make_query, page_size: int = 1000) -> list[dict]:
    """Đọc toàn bộ rows theo cụm .range() (PostgREST giới hạn 1000 dòng/lần)."""
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
# 1. Đọc dữ liệu thô trong kỳ (cửa sổ thời gian Pacific -> UTC để lọc DB)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_orders(sb, start_utc, end_utc) -> tuple[dict[str, datetime], dict[str, str]]:
    """Trả (orders, status):
      orders = {order_id: purchase_date giờ local marketplace} — bỏ đơn Canceled.
      status = {order_id: order_status}  (Pending/Shipped/...) — cho ước lượng phí."""
    rows = fetch_all(lambda: (
        sb.table(T_ORDERS)
        .select("order_id,purchase_date,order_status")
        .gte("purchase_date", start_utc.isoformat() + "Z")
        .lte("purchase_date", end_utc.isoformat() + "Z")
        .not_.in_("order_status", list(_CANCELED))
    ))
    out, status = {}, {}
    for r in rows:
        dt = cfg.parse_iso(r.get("purchase_date"))
        if r.get("order_id") and dt:
            out[r["order_id"]] = cfg.to_marketplace_local(dt)
            status[r["order_id"]] = r.get("order_status") or ""
    return out, status


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
# HYBRID AMAZON FEES — ACTUAL (phí thật đã kết toán) + ESTIMATED (ước lượng) + true-up
#
# Vì Finances API trễ 8-10 ngày so với ngày đặt, đơn mới chưa có phí thật.
# Quy trình (pandas, memory-safe):
#   BƯỚC 1: đơn (order_id, sku) CÓ phí thật -> dùng phí thật, fee_state='ACTUAL'.
#   BƯỚC 2: đơn KHÔNG có phí thật -> ước lượng theo order_status, fee_state='ESTIMATED':
#             Pending : -(sales * referral_rate)                  (chưa ship, bỏ FBA)
#             Shipped : -(sales * referral_rate) - fba_fee*units  (đã ship, có FBA)
#   Rate cache: ƯU TIÊN NEW_fee_cache (user override) -> AUTO-DERIVE từ phí thật
#               (median per SKU) -> trung bình toàn shop -> default 15%.
# ══════════════════════════════════════════════════════════════════════════════

def _classify_bucket(series: "pd.Series") -> "pd.Series":
    """fee_type -> 'referral' | 'fba' | 'other'."""
    ft = series.astype(str).str.lower()
    out = pd.Series("other", index=series.index)
    out[ft.str.contains("commission|referral", regex=True)] = "referral"
    out[ft.str.startswith("fba") | ft.str.contains("fulfillment")] = "fba"
    return out


def _actual_fees_df(sb, order_ids: list[str]) -> "pd.DataFrame":
    """DataFrame phí THẬT theo (order_id, sku): cột referral/fba/other (GIỮ DẤU âm)."""
    rows: list[dict] = []
    for i in range(0, len(order_ids), _IN_CHUNK):
        chunk = order_ids[i: i + _IN_CHUNK]
        rows.extend(fetch_all(lambda c=chunk: (
            sb.table(T_FEES).select("order_id,sku,quantity,fee_type,amount").in_("order_id", c)
        )))
    cols = ["order_id", "sku", "referral", "fba", "other"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["bucket"] = _classify_bucket(df["fee_type"])
    piv = (df.pivot_table(index=["order_id", "sku"], columns="bucket",
                          values="amount", aggfunc="sum", fill_value=0.0)
             .reset_index())
    for b in ("referral", "fba", "other"):
        if b not in piv.columns:
            piv[b] = 0.0
    return piv[cols]


def _load_fee_cache(sb) -> dict[str, dict]:
    """{sku: {referral_rate, fba_fee}} do user khai báo tay (override). Lỗi/trống -> {}."""
    try:
        rows = fetch_all(lambda: sb.table(T_FEE_CACHE)
                         .select("sku,referral_rate,fba_fulfillment_fee"))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[FeeCache] Không đọc được %s (%s) — chỉ dùng auto-derive.", T_FEE_CACHE, exc)
        return {}
    out = {}
    for r in rows:
        sku = r.get("sku")
        if not sku:
            continue
        out[sku] = {
            "referral_rate": (None if r.get("referral_rate") is None else _float(r["referral_rate"])),
            "fba_fee": (None if r.get("fba_fulfillment_fee") is None else _float(r["fba_fulfillment_fee"])),
        }
    return out


def _derive_fee_rates(sb) -> tuple[dict[str, float], float]:
    """AUTO-DERIVE phí FBA/đơn vị theo SKU từ TOÀN BỘ phí thật đã có
    (|FBA amount| / quantity, median per SKU). Trả ({sku: fba_per_unit}, shop_median_fba).
    Referral rate không suy được từ bảng fees (thiếu sales) -> dùng default/override."""
    try:
        rows = fetch_all(lambda: sb.table(T_FEES).select("sku,quantity,fee_type,amount"))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[FeeDerive] Không đọc được %s (%s).", T_FEES, exc)
        return {}, 0.0
    if not rows:
        return {}, 0.0
    df = pd.DataFrame(rows)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(1).clip(lower=1)
    fba = df[_classify_bucket(df["fee_type"]) == "fba"].copy()
    if fba.empty:
        return {}, 0.0
    fba["per_unit"] = fba["amount"].abs() / fba["quantity"]
    by_sku = fba.groupby("sku")["per_unit"].median().round(2).to_dict()
    shop = round(float(fba["per_unit"].median()), 2)
    return by_sku, shop


def _infer_size_tier(fba) -> str | None:
    """Suy NGƯỢC size-tier từ phí FBA/đơn vị (US 2025-26, xấp xỉ — chỉ để gắn nhãn)."""
    if fba is None:
        return None
    f = abs(float(fba))
    if f == 0:
        return None
    if f < 3.50:
        return "Small Standard-Size"
    if f < 5.00:
        return "Large Standard-Size"
    if f < 8.00:
        return "Large Bulky / Small Oversize"
    return "Oversize"


def calibrate_fee_cache(sb) -> dict:
    """B1 — HỌC profile phí per-SKU từ phí THẬT đã settle, ghi NEW_fee_cache:
      fba_fulfillment_fee = median(|FBA|/qty)
      referral_rate       = median(|commission| / (đơn_giá × qty))  [dùng NEW_product_price]
    Suy size_tier. GIỮ NGUYÊN override source='manual' (chỉ điền field đang NULL).
    Profile bền — ESTIMATED đọc nó nên sát ngay tại ngày T (không chờ true-up)."""
    fees = fetch_all(lambda: sb.table(T_FEES).select("sku,quantity,fee_type,amount,principal"))
    if not fees:
        print("⚠️  [calibrate] Chưa có phí thật trong NEW_fin_item_fees — bỏ qua.")
        return {"calibrated": 0}

    # Đơn giá per SKU (mẫu số referral) từ bảng giá persistent + products
    price_map: dict[str, float] = {}
    for r in fetch_all(lambda: sb.table(T_PRICE).select("sku,unit_price")):
        if r.get("sku") and _float(r.get("unit_price")) > 0:
            price_map[r["sku"]] = _float(r["unit_price"])
    for r in fetch_all(lambda: sb.table("products").select("sku,price")):
        if r.get("sku") and _float(r.get("price")) > 0:
            price_map.setdefault(r["sku"], _float(r["price"]))

    df = pd.DataFrame(fees)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(1).clip(lower=1)
    df["bucket"] = _classify_bucket(df["fee_type"])

    fba = df[df["bucket"] == "fba"].copy()
    fba["pu"] = fba["amount"].abs() / fba["quantity"]
    fba_by = fba.groupby("sku")["pu"].median()
    fba_n = fba.groupby("sku").size()

    ref = df[df["bucket"] == "referral"].copy()
    # Mẫu số = PRINCIPAL thật của đơn (chính xác); fallback price_map cho dòng cũ chưa có
    ref["principal"] = pd.to_numeric(ref.get("principal"), errors="coerce").fillna(0.0).abs()
    ref["denom"] = ref["principal"]
    m0 = ref["denom"] <= 0
    ref.loc[m0, "denom"] = (ref.loc[m0, "sku"].map(price_map).fillna(0.0)
                            * ref.loc[m0, "quantity"])
    ref = ref[ref["denom"] > 0]
    ref["rate"] = ref["amount"].abs() / ref["denom"]
    ref = ref[(ref["rate"] >= 0.03) & (ref["rate"] <= 0.30)]   # loại bất thường
    ref_by = ref.groupby("sku")["rate"].median()
    ref_n = ref.groupby("sku").size()

    existing = {r["sku"]: r for r in fetch_all(lambda: sb.table(T_FEE_CACHE)
                .select("sku,referral_rate,fba_fulfillment_fee,source"))}

    rows, kept_manual = [], 0
    for sku in set(fba_by.index) | set(ref_by.index):
        cr = round(float(ref_by[sku]), 4) if sku in ref_by.index else None
        cf = round(float(fba_by[sku]), 2) if sku in fba_by.index else None
        e = existing.get(sku, {})
        if e.get("source") == "manual":                # giữ override, chỉ điền NULL
            referral = e["referral_rate"] if e.get("referral_rate") is not None else cr
            fba_fee = e["fba_fulfillment_fee"] if e.get("fba_fulfillment_fee") is not None else cf
            source = "manual"
            kept_manual += 1
        else:
            referral, fba_fee, source = cr, cf, "calibrated"
        rows.append({
            "sku": sku,
            "referral_rate": referral,
            "fba_fulfillment_fee": fba_fee,
            "fba_size_tier": _infer_size_tier(cf),
            "sample_count": int(ref_n.get(sku, 0)) + int(fba_n.get(sku, 0)),
            "source": source,
        })
    for i in range(0, len(rows), _CHUNK_SIZE):
        sb.table(T_FEE_CACHE).upsert(rows[i: i + _CHUNK_SIZE], on_conflict="sku").execute()
    print(f"✅ [calibrate] {len(rows)} SKU vào NEW_fee_cache "
          f"(giữ {kept_manual} manual override). "
          f"referral median={round(float(ref_by.median()), 4) if len(ref_by) else '?'}, "
          f"fba median={round(float(fba_by.median()), 2) if len(fba_by) else '?'}")
    return {"calibrated": len(rows), "manual_kept": kept_manual}


def _build_price_map(sb, items: list[dict]) -> dict[str, float]:
    """{sku: đơn giá} để IMPUTE doanh thu cho đơn Pending (Amazon trả ItemPrice=None).
    Phủ chồng theo độ tin cậy TĂNG DẦN (nguồn sau ghi đè nguồn trước):
      1) products.price (giá app, có thể cũ)
      2) NEW_product_price (persistent — Phase 1 tự lưu từ MỌI đơn Shipped, không bị --fresh xóa)
      3) giá thực của SKU trong kỳ (đơn Shipped item_price>0) — mới nhất, ưu tiên cao nhất."""
    pm: dict[str, float] = {}
    try:                                               # (1) products.price
        for r in fetch_all(lambda: sb.table("products").select("sku,price")):
            sku, pr = r.get("sku"), _float(r.get("price"))
            if sku and pr > 0:
                pm[sku] = round(pr, 2)
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[PriceMap] Không đọc được products (%s).", exc)
    try:                                               # (2) NEW_product_price (persistent)
        for r in fetch_all(lambda: sb.table(T_PRICE).select("sku,unit_price")):
            sku, pr = r.get("sku"), _float(r.get("unit_price"))
            if sku and pr > 0:
                pm[sku] = round(pr, 2)
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[PriceMap] Không đọc được %s (%s).", T_PRICE, exc)
    by_sku: dict[str, list] = defaultdict(list)        # (3) giá thực trong kỳ — mới nhất
    for it in items:
        qty = int(it.get("quantity_ordered") or 0)
        price = _float(it.get("item_price"))
        if price > 0 and qty > 0:
            by_sku[it.get("sku") or ""].append(price / qty)
    for sku, vals in by_sku.items():
        vals.sort()
        pm[sku] = round(vals[len(vals) // 2], 2)
    return pm


def _effective_sales(it: dict, price_map: dict[str, float]) -> tuple[float, str]:
    """Doanh thu hiệu dụng + nguồn giá. Pending (item_price=0) -> impute từ price_map."""
    s = _float(it.get("item_price"))
    if s > 0:
        return round(s, 2), "ACTUAL"
    qty = int(it.get("quantity_ordered") or 0)
    unit = price_map.get(it.get("sku") or "", 0.0)
    if unit > 0 and qty > 0:
        return round(unit * qty, 2), "IMPUTED"
    return 0.0, "NONE"


def _resolve_hybrid_fees(sb, items: list[dict], order_status: dict[str, str],
                         price_map: dict[str, float]) -> dict[tuple[str, str], dict]:
    """{(order_id, sku): {amazon_fees, referral, fba, fee_state}}.
    BƯỚC 1 (ACTUAL) + BƯỚC 2 (ESTIMATED). Đơn Pending impute giá rồi ước lượng
    referral + FBA (giống Sellerboard — KHÔNG bỏ FBA cho Pending)."""
    order_ids = sorted({it.get("order_id") for it in items if it.get("order_id")})
    actual = _actual_fees_df(sb, order_ids)
    actual_map = {(r["order_id"], r["sku"]):
                  {"referral": _float(r["referral"]), "fba": _float(r["fba"]),
                   "other": _float(r["other"])}
                  for _, r in actual.iterrows()}
    manual = _load_fee_cache(sb)
    fba_by_sku, shop_fba = _derive_fee_rates(sb)

    out: dict[tuple[str, str], dict] = {}
    for it in items:
        oid, sku = it.get("order_id") or "", it.get("sku") or ""
        key = (oid, sku)
        if key in out:
            continue
        a = actual_map.get(key)
        if a and (abs(a["referral"]) > 0 or abs(a["fba"]) > 0):
            # BƯỚC 1 — phí THẬT (true-up): triệt tiêu mọi ước lượng
            out[key] = {"referral": round(a["referral"], 2), "fba": round(a["fba"], 2),
                        "amazon_fees": round(a["referral"] + a["fba"], 2),
                        "fee_state": "ACTUAL"}
            continue
        # BƯỚC 2 — ƯỚC LƯỢNG (Pending đã impute giá; cả Pending & Shipped đều có FBA)
        sales, _src = _effective_sales(it, price_map)
        qty = int(it.get("quantity_ordered") or 0)
        m = manual.get(sku, {})
        rate = m.get("referral_rate") if m.get("referral_rate") is not None else DEFAULT_REFERRAL_RATE
        fba_unit = (m.get("fba_fee") if m.get("fba_fee") is not None
                    else fba_by_sku.get(sku, shop_fba))
        referral = -round(sales * rate, 2)
        fba = -round(fba_unit * qty, 2)
        out[key] = {"referral": referral, "fba": fba,
                    "amazon_fees": round(referral + fba, 2), "fee_state": "ESTIMATED"}
    return out


def _fetch_refunds(sb, start_utc, end_utc) -> list[dict]:
    """Refund events trong kỳ — gán theo posted_date (như Sellerboard)."""
    try:
        return fetch_all(lambda: (
            sb.table(T_REFUNDS)
            .select("order_id,asin,sku,posted_date,quantity_returned,"
                    "refund_principal,refund_commission,refunded_referral_fee,"
                    "refund_promotion,return_disposition")
            .gte("posted_date", start_utc.isoformat() + "Z")
            .lte("posted_date", end_utc.isoformat() + "Z")
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Refunds] Không đọc được %s (%s) — bỏ qua.", T_REFUNDS, exc)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# 1b. Reimbursements / "Money Back" (AdjustmentEventList — NEW_fin_adjustments)
# ══════════════════════════════════════════════════════════════════════════════

# AdjustmentType (Finances API) phổ biến ứng với reimbursement (Amazon TRẢ tiền
# cho hàng mất/hỏng tại kho FBA) — amount DƯƠNG.
_REIMBURSEMENT_TYPES = {
    "WAREHOUSE_DAMAGE", "WAREHOUSE_LOST", "WAREHOUSE_THEFT",
    "REVERSAL_REIMBURSEMENT", "FREE_REPLACEMENT_REFUND_ITEMS",
    "MISSING_FROM_INBOUND", "FBAInventoryReimbursement",
}
# AdjustmentType ứng với clawback (Amazon THU HỒI 1 khoản đã hoàn trước đó)
# — amount ÂM.
_CLAWBACK_TYPES = {
    "COMPENSATED_CLAWBACK", "REIMBURSEMENT_CLAWBACK", "ReimbursementClawback",
}


def _classify_adjustment(adj_type: str, amount: float) -> str:
    """'reimbursement' (Amazon trả tiền cho hàng mất/hỏng tại kho FBA) hoặc
    'clawback' (Amazon thu hồi 1 khoản đã hoàn trước đó). AdjustmentType lạ ->
    suy theo dấu amount."""
    if adj_type in _CLAWBACK_TYPES:
        return "clawback"
    if adj_type in _REIMBURSEMENT_TYPES:
        return "reimbursement"
    return "reimbursement" if amount >= 0 else "clawback"


def _fetch_adjustments(sb, start_utc, end_utc) -> list[dict]:
    """Adjustment events (Money Back: WAREHOUSE_DAMAGE/WAREHOUSE_LOST/...) trong
    kỳ — gán theo posted_date."""
    try:
        return fetch_all(lambda: (
            sb.table(T_ADJUSTMENTS)
            .select("posted_date,adjustment_type,sku,asin,quantity,amount")
            .gte("posted_date", start_utc.isoformat() + "Z")
            .lte("posted_date", end_utc.isoformat() + "Z")
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Adjustments] Không đọc được %s (%s) — bỏ qua.", T_ADJUSTMENTS, exc)
        return []


def _build_reimbursements(adjustments: list[dict], period_start: str, period_end: str,
                          title_by_key: dict[tuple[str, str], str]) -> list[dict]:
    """Gộp NEW_fin_adjustments theo (adjustment_type, asin, sku) cho cả kỳ ->
    NEW_summary_reimbursements ("Money Back" / Lost & Damaged kiểu Sellerboard)."""
    agg: dict[tuple[str, str, str], dict] = {}
    for r in adjustments:
        asin, sku = r.get("asin") or "", r.get("sku") or ""
        adj_type = r.get("adjustment_type") or ""
        a = agg.setdefault((adj_type, asin, sku), {"quantity": 0, "amount": 0.0})
        a["quantity"] += int(r.get("quantity") or 0)
        a["amount"] += _float(r.get("amount"))

    rows = []
    for (adj_type, asin, sku), a in agg.items():
        amount = round(a["amount"], 2)
        rows.append(SummaryReimbursement(
            period_start=period_start, period_end=period_end,
            adjustment_type=adj_type, category=_classify_adjustment(adj_type, amount),
            product=title_by_key.get((asin, sku)) or sku or adj_type,
            asin=asin, sku=sku, quantity=a["quantity"], amount=amount,
        ).to_row())
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 2. Ads: đọc theo kênh + phân bổ 3 tầng xuống từng SKU
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_ads_by_channel(sb, start_d: str, end_d: str) -> dict[str, list[dict]]:
    """{channel: [{sku, asin, campaign_name, cost}]}.
    channel: sponsored_products | sponsored_brands | sponsored_brands_video |
             sponsored_display.
    SP ưu tiên bảng cấp SKU (NEW_ads_sp_asin_daily) — Tầng 1; thiếu thì
    fallback campaign-level."""
    channels: dict[str, list[dict]] = defaultdict(list)

    sp_sku_rows = []
    try:
        sp_sku_rows = fetch_all(lambda: (
            sb.table(T_ADS_SKU)
            .select("report_date,campaign_name,advertised_asin,advertised_sku,cost")
            .gte("report_date", start_d).lte("report_date", end_d)
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Ads] Không đọc được %s (%s).", T_ADS_SKU, exc)
    for r in sp_sku_rows:
        channels["sponsored_products"].append({
            "sku": r.get("advertised_sku") or "", "asin": r.get("advertised_asin") or "",
            "campaign_name": r.get("campaign_name") or "", "cost": _float(r.get("cost")),
        })

    try:
        camp_rows = fetch_all(lambda: (
            sb.table(T_ADS)
            .select("report_date,campaign_name,ad_product,campaign_type,asin,sku,cost")
            .gte("report_date", start_d).lte("report_date", end_d)
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Ads] Không đọc được %s (%s) — bỏ qua ads campaign.", T_ADS, exc)
        camp_rows = []

    for r in camp_rows:
        ad_product = r.get("ad_product") or ""
        entry = {"sku": r.get("sku") or "", "asin": r.get("asin") or "",
                 "campaign_name": r.get("campaign_name") or "", "cost": _float(r.get("cost"))}
        if ad_product == "SPONSORED_PRODUCTS":
            # đã có dữ liệu cấp SKU thì bỏ campaign-level SP (tránh đếm đôi spend)
            if not sp_sku_rows:
                channels["sponsored_products"].append(entry)
        elif ad_product == "SPONSORED_BRANDS":
            if (r.get("campaign_type") or "") == "sponsoredBrandsVideo":
                channels["sponsored_brands_video"].append(entry)
            else:
                channels["sponsored_brands"].append(entry)
        elif ad_product == "SPONSORED_DISPLAY":
            channels["sponsored_display"].append(entry)
    return dict(channels)


def _allocate_channel(rows: list[dict], sales_by_sku: dict[str, float],
                      asin_to_sku: dict[str, str]) -> dict[str, float]:
    """Phân bổ spend 1 kênh xuống SKU theo 3 tầng. Trả {sku: cost DƯƠNG}."""
    allocated: dict[str, float] = defaultdict(float)
    unmatched = 0.0
    # Tầng 2: regex word-boundary tên campaign chứa SKU (ưu tiên SKU dài trước
    # để "AB-12-XL" không bị "AB-12" nuốt mất)
    sku_patterns = [(s, re.compile(re.escape(s.upper()))) for s in
                    sorted((s for s in sales_by_sku if s), key=len, reverse=True)]

    for r in rows:
        cost = r["cost"]
        if not cost:
            continue
        if r["sku"] in sales_by_sku:                   # Tầng 1a: trùng SKU
            allocated[r["sku"]] += cost
            continue
        if r["asin"] in asin_to_sku:                   # Tầng 1b: trùng ASIN
            allocated[asin_to_sku[r["asin"]]] += cost
            continue
        name = r["campaign_name"].upper()
        hit = next((s for s, pat in sku_patterns if pat.search(name)), None)
        if hit:                                        # Tầng 2
            allocated[hit] += cost
        else:
            unmatched += cost

    total_sales = sum(v for v in sales_by_sku.values() if v > 0)
    if unmatched > 0 and total_sales > 0:              # Tầng 3: Revenue Share
        for sku, s in sales_by_sku.items():
            if s > 0:
                allocated[sku] += unmatched * (s / total_sales)
    elif unmatched > 0:
        logger.warning("[Ads] $%.2f spend không phân bổ được (kỳ không có doanh thu).",
                       unmatched)
    return dict(allocated)


# ══════════════════════════════════════════════════════════════════════════════
# 2b. Mart 3 — Campaign Profitability (NEW_summary_campaigns)
# ══════════════════════════════════════════════════════════════════════════════

def _build_campaigns(sb, prod: dict, period_start: str, period_end: str) -> list[dict]:
    """Gom NEW_ads_campaigns_daily theo campaign + tính lợi nhuận per campaign.

    Profit = GPU(SKU quảng cáo) × units_attributed + ad_spend(âm), trong đó
    GPU (Gross Profit per Unit) lấy từ Mart 2 (prod):
      - Campaign CÓ map SKU (NEW_ads_sp_asin_daily — Sponsored Products):
        GPU = trung bình GPU các SKU quảng cáo, trọng số theo spend từng SKU.
      - Campaign KHÔNG map được SKU (SB/SD): fallback GPU trung bình toàn shop.
    Attribution: orders/ppc_sales dùng cửa sổ 7d (chuẩn SP); units chỉ có 1d
    trong report hiện tại — chấp nhận, true-up khi Phase 1 mở rộng."""
    try:
        camp_rows = fetch_all(lambda: (
            sb.table(T_ADS)
            .select("report_date,campaign_id,campaign_name,ad_product,"
                    "cost,clicks,impressions,purchases_7d,sales_7d,units_sold_1d")
            .gte("report_date", period_start).lte("report_date", period_end)
        ))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Campaigns] Không đọc được %s (%s) — bỏ qua Mart 3.", T_ADS, exc)
        return []
    if not camp_rows:
        return []
    df = pd.DataFrame(camp_rows)
    num_cols = ["cost", "clicks", "impressions", "purchases_7d", "sales_7d", "units_sold_1d"]
    for c in num_cols:
        df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0)
    df["campaign_id"] = df["campaign_id"].astype(str).str.strip()
    df = df[df["campaign_id"] != ""]
    agg = df.groupby(["campaign_id"], as_index=False).agg(
        campaign_name=("campaign_name", "last"), ad_product=("ad_product", "last"),
        cost=("cost", "sum"), clicks=("clicks", "sum"), impressions=("impressions", "sum"),
        orders=("purchases_7d", "sum"), ppc_sales=("sales_7d", "sum"),
        units=("units_sold_1d", "sum"))

    # GPU / giá bán trung bình per SKU từ Mart 2 (gộp các dòng (asin, sku) cùng SKU)
    units_by, gross_by, sales_by = defaultdict(int), defaultdict(float), defaultdict(float)
    for (_a, s), p in prod.items():
        units_by[s] += p.units
        gross_by[s] += p.gross_profit
        sales_by[s] += p.sales
    gpu_by_sku = {s: gross_by[s] / u for s, u in units_by.items() if u > 0}
    asp_by_sku = {s: sales_by[s] / u for s, u in units_by.items() if u > 0}
    tot_units = sum(units_by.values())
    store_gpu = (sum(gross_by.values()) / tot_units) if tot_units else 0.0   # SAFEGUARD /0
    store_asp = (sum(sales_by.values()) / tot_units) if tot_units else 0.0

    # Map campaign -> {sku: spend} từ bảng cấp SKU (chỉ SP có)
    sku_w: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    try:
        for r in fetch_all(lambda: (
                sb.table(T_ADS_SKU)
                .select("report_date,campaign_id,advertised_sku,cost")
                .gte("report_date", period_start).lte("report_date", period_end))):
            cid, sku = str(r.get("campaign_id") or "").strip(), r.get("advertised_sku") or ""
            if cid and sku:
                sku_w[cid][sku] += _float(r.get("cost"))
    except Exception as exc:                           # noqa: BLE001
        logger.warning("[Campaigns] Không đọc được %s (%s) — GPU dùng trung bình shop.",
                       T_ADS_SKU, exc)

    rows: list[dict] = []
    for _, c in agg.iterrows():
        spend = float(c["cost"])
        clicks, orders = int(c["clicks"]), int(c["orders"])
        units, ppc_sales = int(c["units"]), round(float(c["ppc_sales"]), 2)
        weights = {s: v for s, v in sku_w.get(c["campaign_id"], {}).items()
                   if s in gpu_by_sku and v > 0}
        tw = sum(weights.values())
        if tw > 0:
            gpu = sum(gpu_by_sku[s] * v for s, v in weights.items()) / tw
            asp = sum(asp_by_sku[s] * v for s, v in weights.items()) / tw
        else:                                          # SB/SD hoặc SKU không bán trong kỳ
            gpu, asp = store_gpu, store_asp
        rows.append(SummaryCampaign(
            period_start=period_start, period_end=period_end,
            campaign_id=str(c["campaign_id"]), campaign_name=str(c["campaign_name"] or ""),
            marketplace=MARKETPLACE_LABEL, ad_product=str(c["ad_product"] or ""),
            ad_spend=-round(spend, 2), clicks=clicks, impressions=int(c["impressions"]),
            orders=orders, units=units, ppc_sales=ppc_sales,
            conversion_rate=round(orders / clicks * 100, 2) if clicks else None,
            cpc=round(spend / clicks, 2) if clicks else None,
            cost_per_order=round(spend / orders, 2) if orders else None,
            acos=round(spend / ppc_sales * 100, 2) if ppc_sales else None,
            profit=round(gpu * units - spend, 2),
            break_even_acos=round(gpu / asp * 100, 2) if asp else None,
        ).to_row())
    rows.sort(key=lambda r: r["profit"] or 0, reverse=True)
    return rows


def _aggregate_products(sb, item_rows: list[dict], period_start: str, period_end: str,
                        title_by_key: dict[tuple[str, str], str]
                        ) -> tuple[dict[tuple[str, str], SummaryProduct], list[dict]]:
    """Gom item_rows theo (asin, sku) -> SummaryProduct(period_start, period_end)
    + phân bổ Ad Spend 3 tầng theo từng kênh trong [period_start, period_end].
    Trả (prod_dict, product_rows) — prod_dict dùng cho _build_campaigns (GPU/SKU)."""
    prod: dict[tuple[str, str], SummaryProduct] = {}
    prod_states: dict[tuple[str, str], set] = defaultdict(set)
    for r in item_rows:
        key = (r["asin"], r["sku"])
        p = prod.setdefault(key, SummaryProduct(
            period_start=period_start, period_end=period_end,
            product=title_by_key.get(key, r["product"]), asin=key[0], sku=key[1]))
        p.units += r["units"]
        p.refunds += r["refunds"]
        p.sales += r["sales"]
        p.promo += r["promo"]
        p.refund_cost += r["refund_cost"]
        p.amazon_fees += r["amazon_fees"]
        p.cost_of_goods += r["cost_of_goods"]
        p.shipping += r["shipping"]
        if r.get("fee_state") in ("ACTUAL", "ESTIMATED"):
            prod_states[key].add(r["fee_state"])
    for key, p in prod.items():
        st = prod_states.get(key, set())
        p.fee_state = "MIXED" if len(st) > 1 else (next(iter(st)) if st else "NONE")

    # ── Phân bổ Ad Spend 3 tầng theo từng kênh ───────────────────────────────
    sales_by_sku: dict[str, float] = defaultdict(float)
    asin_to_sku: dict[str, str] = {}
    for (asin, sku), p in prod.items():
        sales_by_sku[sku] += p.sales
        if asin and asin not in asin_to_sku:
            asin_to_sku[asin] = sku
    channels = _fetch_ads_by_channel(sb, period_start, period_end)
    alloc = {ch: _allocate_channel(rows, dict(sales_by_sku), asin_to_sku)
             for ch, rows in channels.items()}

    def _share(sku: str, p_sales: float, channel: str) -> float:
        """SKU xuất hiện ở nhiều dòng (asin, sku) -> chia theo tỉ trọng sales."""
        total = alloc.get(channel, {}).get(sku, 0.0)
        sku_sales = sales_by_sku.get(sku, 0.0)
        return total * (p_sales / sku_sales) if sku_sales else total

    for (asin, sku), p in prod.items():
        p.sponsored_products = -round(_share(sku, p.sales, "sponsored_products"), 2)
        p.sponsored_brands = -round(_share(sku, p.sales, "sponsored_brands"), 2)
        p.sponsored_brands_video = -round(_share(sku, p.sales, "sponsored_brands_video"), 2)
        p.sponsored_display = -round(_share(sku, p.sales, "sponsored_display"), 2)
        p.ads = round(p.sponsored_products + p.sponsored_brands
                      + p.sponsored_brands_video + p.sponsored_display
                      + p.google_ads + p.facebook_ads, 2)

        for attr in ("sales", "promo", "refund_cost", "amazon_fees",
                     "cost_of_goods", "shipping"):
            setattr(p, attr, round(getattr(p, attr), 2))
        p.gross_profit = round(p.sales + p.promo + p.amazon_fees
                               + p.cost_of_goods + p.shipping, 2)
        p.net_profit = round(p.gross_profit + p.ads + p.refund_cost + p.expenses, 2)
        p.estimated_payout = round(p.net_profit - p.cost_of_goods, 2)
        p.average_sales_price = round(p.sales / p.units, 2) if p.units else 0.0
        p.margin = round(p.net_profit / p.sales * 100, 2) if p.sales else None
        p.roi = round(p.net_profit / abs(p.cost_of_goods) * 100, 2) if p.cost_of_goods else None
        p.refunds_pct = round(p.refunds / p.units * 100, 2) if p.units else None
        p.real_acos = round(-p.ads / p.sales * 100, 2) if p.sales else None

    product_rows = [p.to_row() for p in prod.values()]
    product_rows.sort(key=lambda r: r["net_profit"], reverse=True)
    return prod, product_rows


# ══════════════════════════════════════════════════════════════════════════════
# 3. Engine chính
# ══════════════════════════════════════════════════════════════════════════════

def transform(start_local: datetime, end_local: datetime, sb=None) -> dict:
    """Tính 3 bảng Master cho cửa sổ [start_local, end_local] (giờ Pacific).
    `sb`: Supabase client truyền từ ngoài (multi-tenant) — None = tự tạo từ .env.
    Trả {range, item_rows, product_rows, campaign_rows, totals, warnings}."""
    start_utc = cfg.marketplace_local_to_utc(start_local)
    end_utc = cfg.marketplace_local_to_utc(end_local)
    period_start = start_local.date().isoformat()
    period_end = end_local.date().isoformat()

    sb = sb or get_supabase_client()
    orders, order_status = _fetch_orders(sb, start_utc, end_utc)
    order_ids = list(orders)
    items = _fetch_items(sb, order_ids) if order_ids else []
    price_map = _build_price_map(sb, items) if items else {}
    fees = _resolve_hybrid_fees(sb, items, order_status, price_map) if items else {}
    refunds = _fetch_refunds(sb, start_utc, end_utc)
    adjustments = _fetch_adjustments(sb, start_utc, end_utc)
    cogs_map = cfg.load_cogs_map(sb)

    # ── Summary_Order_Items: dòng normal ─────────────────────────────────────
    item_rows: list[dict] = []
    title_by_key: dict[tuple[str, str], str] = {}
    for it in items:
        oid = it.get("order_id") or ""
        purchase_local = orders.get(oid)
        if purchase_local is None or not (start_local <= purchase_local <= end_local):
            continue
        asin, sku = it.get("asin") or "", it.get("sku") or ""
        qty = int(it.get("quantity_ordered") or 0)
        sales, price_source = _effective_sales(it, price_map)        # Pending -> impute giá
        promo = -abs(_float(it.get("promotion_discount")))          # luôn âm
        fee = fees.get((oid, sku), {})
        amazon_fees = round(fee.get("amazon_fees", 0.0), 2)
        fee_state = fee.get("fee_state", "NONE")
        cogs = -round(cfg.unit_cogs(cogs_map, sku, purchase_local) * qty, 2)
        shipping = -round(cfg.shipping_per_unit(sku) * qty, 2)
        gross = round(sales + promo + amazon_fees + cogs + shipping, 2)
        net = gross                                     # expenses cấp đơn = 0
        row = SummaryOrderItem(
            order_number=oid, order_date=purchase_local.date().isoformat(),
            product=it.get("title") or "", asin=asin, sku=sku,
            units=qty, sales=round(sales, 2), promo=round(promo, 2),
            amazon_fees=amazon_fees, cost_of_goods=cogs, shipping=shipping,
            gross_profit=gross, net_profit=net,
            margin=round(net / sales * 100, 2) if sales else None,
            roi=round(net / abs(cogs) * 100, 2) if cogs else None,
            order_status=order_status.get(oid, ""), fee_state=fee_state,
            price_source=price_source,
        )
        title_by_key[(asin, sku)] = row.product
        item_rows.append(row.to_row())

    # ── Summary_Order_Items: dòng return (gộp theo order+asin+sku) ───────────
    # Nạp fee_cache để lấy tỷ lệ referral gốc tính phí phạt 20%
    fee_cache = _load_fee_cache(sb)

    ref_agg: dict[tuple[str, str, str], dict] = {}
    for r in refunds:
        key = (r.get("order_id") or "", r.get("asin") or "", r.get("sku") or "")
        agg = ref_agg.setdefault(key, {
            "qty": 0, "refund_principal": 0.0, "refund_promo": 0.0, 
            "date": "", "disposition": r.get("return_disposition") or "Sellable"
        })
        agg["qty"] += int(r.get("quantity_returned") or 1)
        agg["refund_principal"] += _float(r.get("refund_principal"))
        agg["refund_promo"] += _float(r.get("refund_promotion", 0.0))
        
        # Nếu có bất kỳ item nào bị hỏng, ghi nhận cả cục là Damaged để siết COGS
        disp = (r.get("return_disposition") or "").lower()
        if disp in ["customerdamaged", "defective", "unsellable"]:
            agg["disposition"] = "Damaged"
            
        posted = cfg.parse_iso(r.get("posted_date"))
        if posted:
            agg["date"] = cfg.to_marketplace_local(posted).date().isoformat()

    for (oid, asin, sku), agg in ref_agg.items():
        qty = agg["qty"]

        # 1. Hoàn Doanh thu (Sales & Promo) — KHÔNG ghi vào sales/promo của dòng
        # return (mô hình Sellerboard: Sales chỉ phản ánh doanh số bán ra).
        refund_principal = -abs(agg["refund_principal"])
        refund_promo = abs(agg["refund_promo"])  # DƯƠNG: trả lại khoản promo khách từng xài

        # 2. Amazon Fees hoàn lại (Referral Refund - Admin Fee Penalty)
        m = fee_cache.get(sku, {})
        rate = m.get("referral_rate") if m.get("referral_rate") is not None else DEFAULT_REFERRAL_RATE

        original_referral = abs(refund_principal * rate)
        admin_fee = min(original_referral * 0.20, 5.00)  # Phạt 20% tối đa $5
        # Amazon trả lại tiền cho seller (+) sau khi đã trừ phạt
        refund_fees = round(original_referral - admin_fee, 2)

        # 3. COGS hoàn lại theo tình trạng nhập kho
        try:
            ref_date = cfg.parse_iso(agg["date"] + "T00:00:00Z")
        except:
            ref_date = cfg.now_marketplace()

        unit_cogs = abs(cfg.unit_cogs(cogs_map, sku, ref_date))
        if agg["disposition"].lower() == "sellable":
            refund_cogs = round(unit_cogs * qty, 2)  # (+) Hàng về kho an toàn, hoàn lại COGS
        else:
            refund_cogs = 0.0  # Hỏng/Mất trắng -> KHÔNG HOÀN COGS (Chịu khoản lỗ gốc)

        # 4. Dồn toàn bộ tác động kinh tế của refund vào refund_cost (mô hình
        # Sellerboard): sales/promo/amazon_fees/cost_of_goods/shipping = 0,
        # gross_profit = 0, net_profit = refund_cost.
        refund_cost = round(refund_principal + refund_promo + refund_fees + refund_cogs, 2)

        item_rows.append(SummaryOrderItem(
            order_number=oid, order_date=agg["date"],
            product=title_by_key.get((asin, sku), f"Refund {sku}"), asin=asin, sku=sku,
            refunds=qty, units=0,  # units = 0 để không xô lệch doanh số bán ra
            sales=0.0, promo=0.0,
            refund_cost=refund_cost,
            amazon_fees=0.0, cost_of_goods=0.0, shipping=0.0,
            gross_profit=0.0, net_profit=refund_cost, row_type="return",
            order_status="Refund", fee_state="ACTUAL_REFUND",
        ).to_row())

    # ── Summary_Products: gom theo (asin, sku) cho CẢ KỲ + phân bổ Ad Spend ──
    prod, product_rows = _aggregate_products(sb, item_rows, period_start, period_end, title_by_key)
    period_product_rows = product_rows                 # dùng cho totals/validate (1 dòng/kỳ)

    # ── Summary_Reimbursements: "Money Back" / Lost & Damaged (Mart 4) ───────
    reimbursement_rows = _build_reimbursements(adjustments, period_start, period_end, title_by_key)

    # ── Mart 3: Campaign Profitability (GPU per SKU từ Mart 2, cả kỳ) ────────
    campaign_rows = _build_campaigns(sb, prod, period_start, period_end)

    warnings = validate_rollup([r for r in item_rows], period_product_rows)

    # ── Roll-up theo NGÀY LOCALIZED (Pacific): Daily_Sales = SUM(Product_Sales)
    # order_date/refund date của item_rows đã ép UTC -> America/Los_Angeles
    # -> ::date ở bước trên; tổng các ngày phải khớp tổng kỳ.
    daily: dict[str, dict] = {}
    for r in item_rows:
        d = daily.setdefault(r["order_date"] or "?", {
            "localized_date": r["order_date"] or "?",
            "orders": set(), "units": 0, "refunds": 0,
            "sales": 0.0, "promo": 0.0, "refund_cost": 0.0, "net_profit": 0.0,
        })
        d["orders"].add(r["order_number"])
        d["units"] += r["units"]
        d["refunds"] += r["refunds"]
        d["sales"] += r["sales"]
        d["promo"] += r["promo"]
        d["refund_cost"] += r["refund_cost"]
        d["net_profit"] += r["net_profit"]
    daily_summary = []
    for key in sorted(daily):
        d = daily[key]
        d["orders"] = len(d["orders"])
        for k in ("sales", "promo", "refund_cost", "net_profit"):
            d[k] = round(d[k], 2)
        daily_summary.append(d)
    day_sales_sum = round(sum(d["sales"] for d in daily_summary), 2)
    period_sales = round(sum(r["sales"] or 0 for r in period_product_rows), 2)
    if abs(day_sales_sum - period_sales) > 0.01:
        warnings.append(f"[Roll-up] SUM(daily localized sales) {day_sales_sum} "
                        f"!= tổng kỳ {period_sales} — kiểm tra phép ép múi giờ!")

    for w in warnings:
        logger.warning(w)

    totals = {k: round(sum(r[k] or 0 for r in period_product_rows), 2)
              for k in ("units", "refunds", "sales", "promo", "ads", "amazon_fees",
                        "cost_of_goods", "shipping", "refund_cost",
                        "gross_profit", "net_profit", "estimated_payout")}
    totals["units"] = int(totals["units"])
    totals["refunds"] = int(totals["refunds"])
    totals["orders"] = len(orders)
    totals["margin"] = round(totals["net_profit"] / totals["sales"] * 100, 2) \
        if totals["sales"] else 0.0

    # ── Daily breakdown (period_start == period_end mỗi ngày) ────────────────
    # Card "Adv. cost" ở backend (profit.py: period_overview/agg) chỉ
    # SUM(SummaryProduct.ads) khi period_start == period_end -> cần thêm
    # 1 dòng/ngày/SKU bên cạnh dòng tổng kỳ ở trên (không thay thế, không trùng
    # khoá NEW_summary_products vì period_start/period_end khác nhau).
    if period_start != period_end:
        items_by_date: dict[str, list[dict]] = defaultdict(list)
        for r in item_rows:
            d = r.get("order_date")
            if d:
                items_by_date[d].append(r)
        for d, day_items in items_by_date.items():
            _, day_product_rows = _aggregate_products(sb, day_items, d, d, title_by_key)
            product_rows.extend(day_product_rows)

    # ── Reconciliation phí: tách ACTUAL vs ESTIMATED (đối chiếu Sellerboard) ──
    normal = [r for r in item_rows if r.get("row_type") == "normal"]
    totals["fees_actual"] = round(sum(r["amazon_fees"] for r in normal
                                      if r.get("fee_state") == "ACTUAL"), 2)
    totals["fees_estimated"] = round(sum(r["amazon_fees"] for r in normal
                                         if r.get("fee_state") == "ESTIMATED"), 2)
    totals["lines_actual"] = sum(1 for r in normal if r.get("fee_state") == "ACTUAL")
    totals["lines_estimated"] = sum(1 for r in normal if r.get("fee_state") == "ESTIMATED")

    # ── "Money Back" / Lost & Damaged (Mart 4 — KHÔNG cộng vào net_profit,
    # theo dõi riêng giống tab Reimbursements của Sellerboard) ──────────────
    totals["reimbursements"] = round(sum(r["amount"] for r in reimbursement_rows), 2)
    totals["reimbursements_received"] = round(sum(r["amount"] for r in reimbursement_rows
                                                    if r["category"] == "reimbursement"), 2)
    totals["reimbursements_clawback"] = round(sum(r["amount"] for r in reimbursement_rows
                                                    if r["category"] == "clawback"), 2)

    return {
        "range": {"start": period_start, "end": period_end, "timezone": str(cfg.SELLER_TZ)},
        "item_rows": item_rows,
        "product_rows": product_rows,
        "campaign_rows": campaign_rows,    # Mart 3 — NEW_summary_campaigns
        "reimbursement_rows": reimbursement_rows,  # Mart 4 — NEW_summary_reimbursements
        "daily_summary": daily_summary,    # ngày Pacific — nguồn cho chart Daily Sales
        "totals": totals,
        "warnings": warnings,
    }


def truncate_summaries(sb) -> None:
    """--fresh: xóa sạch 4 bảng Master TRƯỚC khi ghi (reset rồi nhét lại)."""
    for table in (T_SUMMARY_ITEMS, T_SUMMARY_PRODUCTS, T_SUMMARY_CAMPAIGNS, T_SUMMARY_REIMBURSEMENTS):
        sb.table(table).delete().gte("updated_at", "1900-01-01T00:00:00Z").execute()
    print(f"🧹 [--fresh] Đã xóa sạch {T_SUMMARY_ITEMS} + {T_SUMMARY_PRODUCTS} "
          f"+ {T_SUMMARY_CAMPAIGNS} + {T_SUMMARY_REIMBURSEMENTS}.")


def _sanitize_record(rec: dict, now_iso: str, key_cols: set[str]) -> dict:
    """Data Sanitization trước khi LOAD:
      - float NaN/inf -> 0.0 (artifact pandas); python None giữ nguyên = SQL NULL
        (margin/roi None là CHỦ ĐÍCH — không ép 0).
      - numpy scalar -> python scalar (json serializable).
      - str: strip; ''/'nan' -> None, TRỪ cột thuộc conflict key (PK không NULL được).
      - bổ sung updated_at (UTC) nếu thiếu."""
    out = {}
    for k, v in rec.items():
        if hasattr(v, "item") and not isinstance(v, (str, bytes)):
            v = v.item()                               # numpy -> python
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            v = 0.0
        elif isinstance(v, str):
            v = v.strip()
            if (not v or v.lower() == "nan") and k not in key_cols:
                v = None
        out[k] = v
    out.setdefault("updated_at", now_iso)
    return out


def load_to_supabase_robust(rows, table_name: str, supabase_client,
                            conflict_keys: str, batch_size: int = _LOAD_BATCH) -> int:
    """LOAD chuẩn production: sanitize -> micro-batch (chống HTTP 413) ->
    upsert idempotent (returning='minimal') -> giải phóng RAM (chống OOM VPS).
    `rows`: list[dict] hoặc pandas.DataFrame. Trả số dòng đã ghi."""
    if isinstance(rows, pd.DataFrame):
        rows = rows.to_dict("records")
    if not rows:
        return 0
    now_iso = datetime.now(timezone.utc).isoformat()
    key_cols = {c.strip() for c in conflict_keys.split(",")}
    clean = [_sanitize_record(r, now_iso, key_cols) for r in rows]
    written = 0
    for i in range(0, len(clean), batch_size):
        chunk = clean[i: i + batch_size]
        supabase_client.table(table_name).upsert(
            chunk, on_conflict=conflict_keys, returning="minimal").execute()
        written += len(chunk)
        del chunk
    del clean
    gc.collect()
    return written


def write_summaries(sb, result: dict) -> dict:
    """Upsert 4 bảng Master lên Supabase qua load_to_supabase_robust."""
    # owner_id là 1 phần PRIMARY KEY của NEW_summary_order_items/NEW_summary_products/
    # NEW_summary_reimbursements
    for r in result["item_rows"]:
        r["owner_id"] = DEFAULT_OWNER_ID
    for r in result["product_rows"]:
        r["owner_id"] = DEFAULT_OWNER_ID
    for r in result["reimbursement_rows"]:
        r["owner_id"] = DEFAULT_OWNER_ID
    return {
        "items": load_to_supabase_robust(
            result["item_rows"], T_SUMMARY_ITEMS, sb,
            "owner_id,order_number,asin,sku,row_type"),
        "products": load_to_supabase_robust(
            result["product_rows"], T_SUMMARY_PRODUCTS, sb,
            "owner_id,period_start,period_end,asin,sku"),
        "campaigns": load_to_supabase_robust(
            result["campaign_rows"], T_SUMMARY_CAMPAIGNS, sb,
            "period_start,period_end,campaign_id"),
        "reimbursements": load_to_supabase_robust(
            result["reimbursement_rows"], T_SUMMARY_REIMBURSEMENTS, sb,
            "owner_id,period_start,period_end,adjustment_type,asin,sku"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. Entry-point MULTI-TENANT — gọi được từ vòng lặp nhiều store (MORY, LLH...)
# ══════════════════════════════════════════════════════════════════════════════

def run_transformation(supabase_client, target_date: str, *, days: int | None = None,
                       write: bool = True, fresh: bool = False,
                       calibrate: bool = False) -> dict:
    """Chạy trọn Phase 2 cho 1 store qua client truyền vào (Physical Sharding —
    mỗi store 1 Supabase project, KHÔNG cần store_id trong schema).

      supabase_client : Client đã khởi tạo (URL/Key của store tương ứng)
      target_date     : 'YYYY-MM-DD' (ngày Pacific). days=N -> cửa sổ N ngày
                        kết thúc tại target_date (None = đúng 1 ngày).
      write/fresh/calibrate : như các flag CLI tương ứng.

    Trả result dict của transform() + result['written'] nếu có ghi."""
    if calibrate:
        calibrate_fee_cache(supabase_client)
    day = datetime.strptime(target_date, "%Y-%m-%d")
    end_local = day + timedelta(days=1, microseconds=-1)
    start_local = day - timedelta(days=days - 1) if days and days > 1 else day

    result = transform(start_local, end_local, sb=supabase_client)
    if write:
        if fresh:
            truncate_summaries(supabase_client)
        result["written"] = write_summaries(supabase_client, result)
    gc.collect()
    return result


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Phase 2 — Transformation Engine (NEW_* -> Summary_*)")
    ap.add_argument("--days", type=int, default=None,
                    help="Số ngày của cửa sổ (Pacific). Mặc định 7 nếu không có --date. "
                         "Kết hợp với --date: cửa sổ N ngày KẾT THÚC tại --date.")
    ap.add_argument("--date", help="Ngày YYYY-MM-DD (Pacific) làm mốc kết thúc. "
                                     "Không có --days -> đúng 1 ngày này.")
    ap.add_argument("--json", action="store_true", help="In kết quả JSON ra stdout")
    ap.add_argument("--no-write", action="store_true", help="Chỉ tính, không ghi Supabase")
    ap.add_argument("--fresh", action="store_true",
                    help="XÓA SẠCH 2 bảng Master trước khi ghi (reset rồi nhét lại)")
    ap.add_argument("--calibrate", action="store_true",
                    help="HỌC lại NEW_fee_cache (referral_rate + fba_fee per-SKU) từ phí thật "
                         "TRƯỚC khi transform — để ESTIMATED sát hơn. Có thể chạy riêng.")
    args = ap.parse_args()

    sb = get_supabase_client()
    if args.date:
        target_date, days = args.date, args.days   # --days đi kèm --date -> cửa sổ N ngày kết thúc tại --date
    else:                       # --days N (mặc định 7): cửa sổ N ngày TRỌN (Pacific) đến hôm nay
        target_date, days = cfg.now_marketplace().date().isoformat(), (args.days or 7)
    result = run_transformation(sb, target_date, days=days,
                                write=False, calibrate=args.calibrate)
    t = result["totals"]
    print(f"\n=> Kỳ {result['range']['start']} → {result['range']['end']} "
          f"({result['range']['timezone']}): {t.get('orders', 0)} đơn, "
          f"{len(result['product_rows'])} SKU, {len(result['campaign_rows'])} campaign, "
          f"sales ${t.get('sales', 0):,.2f}, "
          f"net ${t.get('net_profit', 0):,.2f}", file=sys.stderr)

    # ── Bảng đối chiếu phí (so trực tiếp với Sellerboard baseline) ──
    print("\n── RECONCILIATION (đối chiếu Sellerboard) ──", file=sys.stderr)
    print(f"  Tổng Sales:            ${t.get('sales', 0):>10,.2f}", file=sys.stderr)
    print(f"  Amazon fees (tổng):    ${t.get('amazon_fees', 0):>10,.2f}", file=sys.stderr)
    print(f"    ├─ ACTUAL  (phí thật):  ${t.get('fees_actual', 0):>10,.2f}  "
          f"({t.get('lines_actual', 0)} dòng đã kết toán)", file=sys.stderr)
    print(f"    └─ ESTIMATED (ước lượng):${t.get('fees_estimated', 0):>10,.2f}  "
          f"({t.get('lines_estimated', 0)} dòng chưa kết toán)", file=sys.stderr)
    print(f"  Cost of goods (tổng):  ${t.get('cost_of_goods', 0):>10,.2f}", file=sys.stderr)
    print(f"  Net profit (tổng):     ${t.get('net_profit', 0):>10,.2f}", file=sys.stderr)
    print(f"  Margin:                 {t.get('margin', 0):>9.2f}%", file=sys.stderr)

    # ── "Money Back" / Lost & Damaged (Mart 4) ──
    print("\n── MONEY BACK (Lost & Damaged / Reimbursements) ──", file=sys.stderr)
    print(f"  Reimbursement nhận:    ${t.get('reimbursements_received', 0):>10,.2f}  "
          f"({sum(1 for r in result['reimbursement_rows'] if r['category'] == 'reimbursement')} dòng)",
          file=sys.stderr)
    print(f"  Clawback bị thu hồi:   ${t.get('reimbursements_clawback', 0):>10,.2f}  "
          f"({sum(1 for r in result['reimbursement_rows'] if r['category'] == 'clawback')} dòng)",
          file=sys.stderr)
    print(f"  Net:                   ${t.get('reimbursements', 0):>10,.2f}", file=sys.stderr)

    if result["warnings"]:
        print(f"⚠️  {len(result['warnings'])} cảnh báo roll-up (xem log).", file=sys.stderr)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if not args.no_write:
        if args.fresh:
            truncate_summaries(sb)
        written = write_summaries(sb, result)
        print(f"✅ Đã ghi Supabase: {written['items']} dòng {T_SUMMARY_ITEMS}, "
              f"{written['products']} dòng {T_SUMMARY_PRODUCTS}, "
              f"{written['campaigns']} dòng {T_SUMMARY_CAMPAIGNS}, "
              f"{written['reimbursements']} dòng {T_SUMMARY_REIMBURSEMENTS}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except Exception:                          # noqa: BLE001
                pass
    sys.exit(main())
