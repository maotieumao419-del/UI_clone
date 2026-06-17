"""Phase 1 — Direct-Stream Ingestion Engine.

Amazon API -> Supabase (bảng đệm NEW_*) theo đúng ràng buộc memory-safety:

  - KHÔNG nạp toàn bộ payload phân trang vào RAM: mỗi trang NextToken
    (<=100 records) được transform + Bulk Upsert NGAY vào Supabase
    (chunk <=100 dòng/lần ghi).
  - Sau mỗi chu kỳ ghi: `del payload` + `gc.collect()` để giải phóng
    bộ nhớ vật lý — triệt tiêu rủi ro Linux OOM Killer sập Gunicorn worker.
  - Rate limit 429 đã xử lý trong amz_spapi_client / amz_ads_client
    (Retry-After + backoff, giãn cách giữa các call).

Bảng đích:
  Profit_Phase1_sp_orders, Profit_Phase1_sp_order_items            <- Orders API
  Profit_Phase1_fin_item_fees, Profit_Phase1_fin_refunds,
  Profit_Phase1_fin_adjustments                          <- Finances API
  Profit_Phase1_ads_campaigns_daily                      <- SP/SB/SD campaign reports
  Profit_Phase1_ads_sp_asin_daily                        <- Advertised Product Report
                                                  (cấp SKU — Tầng 1 phân bổ ads)

Chạy:
    python direct_stream_pipeline.py --all                 # orders+finances+ads, 24h/hôm qua
    python direct_stream_pipeline.py --orders --finances   # chọn nguồn
    python direct_stream_pipeline.py --all --date 2026-06-10            # đúng 1 ngày (giờ Seller)
    python direct_stream_pipeline.py --all --from 2026-06-10 --to 2026-06-11   # KHOẢNG NGÀY
    python direct_stream_pipeline.py --all                 # (terminal) sẽ HỎI khoảng từ→đến
Mọi mốc ngày theo giờ Seller Central (Pacific/UTC-7). Cần trong .env:
credentials SP-API/Ads-API + SUPABASE_URL / SUPABASE_SERVICE_KEY.
"""
import argparse
import gc
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amz_ads_client as ads
import amz_spapi_client as sp
import _time_range as tr

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")

CHUNK_SIZE = 100

T_ORDERS   = "Profit_Phase1_sp_orders"
T_ITEMS    = "Profit_Phase1_sp_order_items"
T_FEES     = "Profit_Phase1_fin_item_fees"
T_REFUNDS  = "Profit_Phase1_fin_refunds"
T_ADJ      = "Profit_Phase1_fin_adjustments"
T_ADS      = "Profit_Phase1_ads_campaigns_daily"
T_ADS_SKU  = "Profit_Phase1_ads_sp_asin_daily"
T_PRICE    = "Profit_Phase1_product_price"   # persistent — KHÔNG bị --fresh xóa


def get_supabase_client():
    from supabase import create_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_KEY trong .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _delete_all(client, table: str) -> None:
    """Xóa SẠCH 1 bảng raw qua PostgREST (mọi bảng raw đều có cột synced_at).
    Dùng service-role key nên bỏ qua RLS."""
    client.table(table).delete().gte("synced_at", "1900-01-01T00:00:00Z").execute()


def truncate_for_sources(client, do_orders: bool, do_finances: bool, do_ads: bool) -> None:
    """--fresh: xóa sạch dữ liệu cũ của các nguồn được chọn TRƯỚC khi nạp mới.

    Tôn trọng khóa ngoại (order_items/fin_item_fees/fin_refunds tham chiếu
    Profit_Phase1_sp_orders) -> xóa CON trước, CHA (Profit_Phase1_sp_orders) sau cùng. Vì vậy nếu
    chọn lại Orders thì các bảng finances con cũng bị xóa theo (giống CASCADE)."""
    clear = set()
    if do_orders:
        clear |= {T_ITEMS, T_FEES, T_REFUNDS, T_ORDERS}   # orders là cha -> gồm con
    if do_finances:
        clear |= {T_FEES, T_REFUNDS, T_ADJ}
    if do_ads:
        clear |= {T_ADS, T_ADS_SKU}
    # Thứ tự CON -> CHA để không vi phạm FK:
    order = [T_ITEMS, T_FEES, T_REFUNDS, T_ADJ, T_ADS, T_ADS_SKU, T_ORDERS]
    print("🧹 [--fresh] Xóa sạch dữ liệu cũ:", ", ".join(t for t in order if t in clear))
    for t in order:
        if t in clear:
            _delete_all(client, t)
    print("🧹 [--fresh] Xong — bảng đã trống, bắt đầu nạp dữ liệu mới.")


def _float(val, default=0.0):
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return default


def _int(val, default=0):
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return default


def _money(obj) -> float:
    """Số tiền từ object tiền tệ của Amazon. Finances API dùng key
    'CurrencyAmount', Orders API dùng 'Amount' — đọc cả hai."""
    o = obj or {}
    return _float(o.get("CurrencyAmount", o.get("Amount")))


def _upsert_chunks(client, table: str, rows: list, conflict: str) -> int:
    """Bulk Upsert theo từng chunk <=CHUNK_SIZE dòng. Trả về số dòng đã gửi."""
    total = 0
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i: i + CHUNK_SIZE]
        client.table(table).upsert(chunk, on_conflict=conflict).execute()
        total += len(chunk)
    return total


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# Sink: transform 1 trang dữ liệu API -> rows -> Bulk Upsert Supabase
# ══════════════════════════════════════════════════════════════════════════════

def ingest_orders_page(client, orders: list) -> dict:
    """1 trang orders (mỗi order đã nhúng '_items') -> Profit_Phase1_sp_orders + Profit_Phase1_sp_order_items.

    1 đơn có thể có NHIỀU OrderItem trùng (asin, sku) (vd cùng SKU tách dòng)
    -> GỘP theo khoá conflict (order_id, asin, sku) trước khi upsert, tránh
    PostgREST 21000 'cannot affect row a second time'."""
    orders_rows = []
    items_map: dict[tuple, dict] = {}
    now_iso = _now_iso()
    for o in orders:
        order_id = o.get("AmazonOrderId", "")
        if not order_id:
            continue
        orders_rows.append({
            "order_id":            order_id,
            "purchase_date":       o.get("PurchaseDate"),
            "last_update_date":    o.get("LastUpdateDate"),
            "order_status":        o.get("OrderStatus", ""),
            "fulfillment_channel": o.get("FulfillmentChannel", "AFN"),
            "sales_channel":       o.get("SalesChannel"),
            "marketplace_id":      o.get("MarketplaceId"),
            "synced_at":           now_iso,
        })
        for item in o.get("_items") or []:
            asin = item.get("ASIN", "")
            sku = item.get("SellerSKU", "")
            qty = _int(item.get("QuantityOrdered", 1))
            price_amt = _float((item.get("ItemPrice") or {}).get("Amount"))
            tax_amt = _float((item.get("ItemTax") or {}).get("Amount"))
            promo_amt = _float((item.get("PromotionDiscount") or {}).get("Amount"))
            key = (order_id, asin, sku)
            row = items_map.get(key)
            if row is None:
                items_map[key] = {
                    "order_id":           order_id,
                    "asin":               asin,
                    "sku":                sku,
                    "title":              (item.get("Title") or "")[:512],
                    "quantity_ordered":   qty,
                    "item_price":         round(price_amt, 2),
                    "item_tax":           round(tax_amt, 2),
                    "promotion_discount": round(-abs(promo_amt), 2) if promo_amt else 0.0,
                    "synced_at":          now_iso,
                }
            else:                                      # gộp dòng trùng SKU trong cùng đơn
                row["quantity_ordered"] += qty
                row["item_price"] = round(row["item_price"] + price_amt, 2)
                row["item_tax"] = round(row["item_tax"] + tax_amt, 2)
                row["promotion_discount"] = round(row["promotion_discount"]
                                                  - abs(promo_amt), 2)
    items_rows = []
    price_map: dict[str, float] = {}                  # sku -> đơn giá (đơn Shipped có giá)
    for row in items_map.values():
        q = row["quantity_ordered"]
        row["unit_price"] = round(row["item_price"] / q if q > 0 else row["item_price"], 2)
        items_rows.append(row)
        if row["unit_price"] > 0:                     # chỉ lưu giá thật (>0); Pending=0 bỏ qua
            price_map[row["sku"]] = row["unit_price"]
    # Persistent price: upsert giá đã biết của SKU (dedupe theo sku tránh 21000)
    if price_map:
        price_rows = [{"sku": s, "unit_price": p, "source": "order", "updated_at": now_iso}
                      for s, p in price_map.items() if s]
        _upsert_chunks(client, T_PRICE, price_rows, "sku")
    return {
        "orders": _upsert_chunks(client, T_ORDERS, orders_rows, "order_id"),
        "items":  _upsert_chunks(client, T_ITEMS, items_rows, "order_id,asin,sku"),
    }


def ingest_finance_events_page(client, events: dict) -> dict:
    """1 trang FinancialEvents -> Profit_Phase1_fin_item_fees / Profit_Phase1_fin_refunds / Profit_Phase1_fin_adjustments.

    1 đơn có thể có NHIỀU shipment event trùng (sku, fee_type) trong cùng trang
    -> phải GỘP (cộng dồn) theo đúng khoá conflict trước khi upsert, nếu không
    PostgREST báo 21000 'cannot affect row a second time'."""
    adj_rows = []
    now_iso = _now_iso()

    fees_map: dict[tuple, dict] = {}
    for event in events.get("ShipmentEventList", []):
        order_id = event.get("AmazonOrderId", "")
        posted_date = event.get("PostedDate")
        if not order_id:
            continue
        for item in event.get("ShipmentItemList", []):
            asin = item.get("ASIN", "")
            sku = item.get("SellerSKU", "")
            qty = _int(item.get("QuantityShipped", 1))
            # Principal = giá bán THẬT của item (để calibrate referral = commission/principal)
            principal = sum(_money(ch.get("ChargeAmount"))
                            for ch in item.get("ItemChargeList", [])
                            if ch.get("ChargeType") == "Principal")
            for fee in item.get("ItemFeeList", []):
                fee_type = fee.get("FeeType", "")
                amount = _money(fee.get("FeeAmount"))
                if not fee_type or amount == 0:
                    continue
                key = (order_id, sku, asin, fee_type)      # = khoá conflict
                row = fees_map.setdefault(key, {
                    "order_id":    order_id,
                    "posted_date": posted_date,
                    "asin":        asin,
                    "sku":         sku,
                    "quantity":    0,
                    "fee_type":    fee_type,
                    "amount":      0.0,
                    "principal":   0.0,
                    "synced_at":   now_iso,
                })
                row["quantity"] += qty
                row["amount"] = round(row["amount"] + amount, 2)
                row["principal"] = round(row["principal"] + principal, 2)
    fees_rows = list(fees_map.values())

    refunds_map: dict[tuple, dict] = {}
    for event in events.get("RefundEventList", []):
        order_id = event.get("AmazonOrderId", "")
        posted_date = event.get("PostedDate")
        if not order_id:
            continue
        for item in event.get("ShipmentItemAdjustmentList", []):
            principal = commission = ref_referral = 0.0
            for charge in item.get("ItemChargeAdjustmentList", []):
                if charge.get("ChargeType") == "Principal":
                    principal = _money(charge.get("ChargeAmount"))
            for fee in item.get("ItemFeeAdjustmentList", []):
                ft = fee.get("FeeType", "")
                amt = _money(fee.get("FeeAmount"))
                if ft == "Commission":
                    commission = amt
                elif ft == "RefundCommission":
                    ref_referral = amt           # DƯƠNG — Amazon hoàn lại referral fee
            key = (order_id, item.get("SellerSKU", ""), posted_date)   # = khoá conflict
            row = refunds_map.setdefault(key, {
                "order_id":              order_id,
                "posted_date":           posted_date,
                "asin":                  item.get("ASIN", ""),
                "sku":                   item.get("SellerSKU", ""),
                "quantity_returned":     0,
                "refund_principal":      0.0,
                "refund_commission":     0.0,
                "refunded_referral_fee": 0.0,
                "synced_at":             now_iso,
            })
            row["quantity_returned"] += _int(item.get("QuantityShipped", 1))
            row["refund_principal"] = round(row["refund_principal"] + principal, 2)
            row["refund_commission"] = round(row["refund_commission"] + commission, 2)
            row["refunded_referral_fee"] = round(row["refunded_referral_fee"] + ref_referral, 2)
    refunds_rows = list(refunds_map.values())

    for event in events.get("AdjustmentEventList", []):
        adj_type = event.get("AdjustmentType", "")
        posted_date = event.get("PostedDate")
        for item in event.get("AdjustmentItemList", []):
            qty_raw = _float(item.get("Quantity", 1))
            total_amt = _money(item.get("PerUnitAmount")) * qty_raw
            if total_amt == 0:
                continue
            adj_rows.append({
                "posted_date":     posted_date,
                "adjustment_type": adj_type,
                "sku":             item.get("SellerSKU", ""),
                "asin":            item.get("ASIN", ""),
                "quantity":        int(qty_raw),
                "amount":          round(total_amt, 2),
                "synced_at":       now_iso,
            })

    result = {
        "fees":    _upsert_chunks(client, T_FEES, fees_rows, "order_id,sku,asin,fee_type"),
        "refunds": _upsert_chunks(client, T_REFUNDS, refunds_rows, "order_id,sku,posted_date"),
        "adjustments": 0,
    }
    for i in range(0, len(adj_rows), CHUNK_SIZE):
        client.table(T_ADJ).insert(adj_rows[i: i + CHUNK_SIZE]).execute()
        result["adjustments"] += len(adj_rows[i: i + CHUNK_SIZE])
    return result


def ingest_ads_campaign_report(client, data: list, ad_product: str, report_date: str) -> int:
    """1 report campaign-level (SP/SB/SD) -> Profit_Phase1_ads_campaigns_daily."""
    rows = []
    now_iso = _now_iso()
    for row in data:
        base = {
            "report_date":   report_date,
            "campaign_id":   str(row.get("campaignId", "")),
            "campaign_name": row.get("campaignName", ""),
            "ad_product":    ad_product,
            "impressions":   _int(row.get("impressions")),
            "clicks":        _int(row.get("clicks")),
            "cost":          round(_float(row.get("cost")), 2),
            "synced_at":     now_iso,
        }
        if ad_product == "SPONSORED_PRODUCTS":
            base.update({
                "campaign_type": "sponsoredProducts",
                "purchases_1d":  _int(row.get("purchases1d")),
                "purchases_7d":  _int(row.get("purchases7d")),
                "purchases_14d": _int(row.get("purchases14d")),
                "sales_1d":      round(_float(row.get("sales1d")), 2),
                "sales_7d":      round(_float(row.get("sales7d")), 2),
                "sales_14d":     round(_float(row.get("sales14d")), 2),
                "units_sold_1d": _int(row.get("unitsSoldClicks1d")),
            })
        elif ad_product == "SPONSORED_BRANDS":
            base.update({
                "campaign_type": row.get("campaignType", "sponsoredBrands"),
                "purchases_14d": _int(row.get("purchases14d") or row.get("purchases")),
                "sales_14d":     round(_float(row.get("sales14d") or row.get("sales")), 2),
            })
        else:                                          # SPONSORED_DISPLAY
            base.update({
                "campaign_type": "sponsoredDisplay",
                "purchases_14d": _int(row.get("purchases14d")),
                "sales_14d":     round(_float(row.get("sales14d")), 2),
            })
        rows.append(base)
    return _upsert_chunks(client, T_ADS, rows, "report_date,campaign_id,ad_product")


def ingest_ads_sp_asin_report(client, data: list, report_date: str) -> int:
    """Advertised Product Report (cấp SKU/ASIN) -> Profit_Phase1_ads_sp_asin_daily."""
    rows = []
    now_iso = _now_iso()
    for row in data:
        rows.append({
            "report_date":    report_date,
            "campaign_id":    str(row.get("campaignId", "")),
            "campaign_name":  row.get("campaignName", ""),
            "ad_group_id":    str(row.get("adGroupId", "")),
            "advertised_asin": row.get("advertisedAsin", ""),
            "advertised_sku":  row.get("advertisedSku", ""),
            "impressions":    _int(row.get("impressions")),
            "clicks":         _int(row.get("clicks")),
            "cost":           round(_float(row.get("cost")), 2),
            "purchases_1d":   _int(row.get("purchases1d")),
            "purchases_7d":   _int(row.get("purchases7d")),
            "sales_1d":       round(_float(row.get("sales1d")), 2),
            "sales_7d":       round(_float(row.get("sales7d")), 2),
            "units_sold_1d":  _int(row.get("unitsSoldClicks1d")),
            "synced_at":      now_iso,
        })
    return _upsert_chunks(client, T_ADS_SKU, rows,
                          "report_date,campaign_id,ad_group_id,advertised_sku")


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration: từng nguồn dữ liệu — fetch trang -> upsert -> del + gc.collect()
# ══════════════════════════════════════════════════════════════════════════════

def run_orders(client, created_after: str, created_before: str = None) -> dict:
    print(f"\n=== ORDERS: CreatedAfter={created_after}"
          + (f" CreatedBefore={created_before}" if created_before else "") + " ===")
    session = sp.auth_session()
    totals = {"orders": 0, "items": 0}
    for orders in sp.iter_orders_pages(session, created_after, created_before):
        for o in orders:
            oid = o.get("AmazonOrderId", "")
            try:
                o["_items"] = sp.fetch_order_items(session, oid)
            except Exception as exc:                   # noqa: BLE001
                print(f"    ⚠️  OrderItems {oid}: {exc}")
                o["_items"] = []
        result = ingest_orders_page(client, orders)
        totals["orders"] += result["orders"]
        totals["items"] += result["items"]
        print(f"    → Supabase: +{result['orders']} orders, +{result['items']} items")
        del orders
        gc.collect()
    print(f"✅ Orders: {totals['orders']} orders, {totals['items']} items")
    return totals


def run_finances(client, posted_after: str, posted_before: str = None) -> dict:
    print(f"\n=== FINANCES: PostedAfter={posted_after}"
          + (f" PostedBefore={posted_before}" if posted_before else "") + " ===")
    session = sp.auth_session()
    totals = {"fees": 0, "refunds": 0, "adjustments": 0}
    for events in sp.iter_financial_events_pages(session, posted_after, posted_before):
        result = ingest_finance_events_page(client, events)
        for k in totals:
            totals[k] += result[k]
        print(f"    → Supabase: +{result['fees']} fees, +{result['refunds']} refunds, "
              f"+{result['adjustments']} adjustments")
        del events
        gc.collect()
    print(f"✅ Finances: {totals}")
    return totals


def _run_ads_one_day(client, lwa_ads, report_date: str) -> dict:
    import time as _time
    print(f"\n=== ADS REPORTS: {report_date} ===")
    totals = {}
    report_ids = []
    for name, config, ad_product in ads.REPORT_JOBS:
        try:
            rid = ads.request_report(lwa_ads, config, name, report_date)
        except Exception as exc:                       # noqa: BLE001 — 1 report lỗi không sập cả batch
            print(f"  ⚠️  Không tạo được report {name}: {exc} — bỏ qua report này.")
            rid = ""
        report_ids.append((name, ad_product, rid))
        _time.sleep(ads.REQUEST_GAP)

    for name, ad_product, report_id in report_ids:
        if not report_id:
            continue
        url = ads.poll_until_done(lwa_ads, report_id, name)
        if not url:
            continue
        data = ads.download_report(url)
        print(f"  [ADS] {name}: {len(data)} rows")
        if ad_product:
            n = ingest_ads_campaign_report(client, data, ad_product, report_date)
            print(f"    → Supabase {T_ADS}: +{n} rows")
        else:
            n = ingest_ads_sp_asin_report(client, data, report_date)
            print(f"    → Supabase {T_ADS_SKU}: +{n} rows (cấp SKU — Tầng 1 phân bổ)")
        totals[name] = n
        del data
        gc.collect()
    return totals


def run_ads(client, report_dates) -> dict:
    """Lặp từng ngày trong khoảng (Ads report theo từng report_date)."""
    if isinstance(report_dates, str):
        report_dates = [report_dates]
    lwa_ads = ads.get_ads_token()
    all_totals = {}
    for d in report_dates:
        all_totals[d] = _run_ads_one_day(client, lwa_ads, d)
    print(f"✅ Ads ({len(report_dates)} ngày): {all_totals}")
    return all_totals


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1 — Direct-Stream Ingestion (Amazon -> Supabase)")
    ap.add_argument("--orders",   action="store_true", help="Kéo Orders + Order Items")
    ap.add_argument("--finances", action="store_true", help="Kéo Financial Events")
    ap.add_argument("--ads",      action="store_true", help="Kéo 4 báo cáo quảng cáo")
    ap.add_argument("--all",      action="store_true", help="Cả 3 nguồn")
    ap.add_argument("--date", help="Lấy đúng 1 NGÀY THEO GIỜ SELLER (Pacific/UTC-7, đặt qua "
                                   "SELLER_TIMEZONE) — vd 2026-06-09 = trọn ngày 09/06 giờ "
                                   "Seller Central. Tương đương --from X --to X.")
    ap.add_argument("--from", dest="from_date",
                    help="KHOẢNG NGÀY (giờ Seller) — mốc ĐẦU YYYY-MM-DD. Phase 1 thu TOÀN BỘ "
                         "dữ liệu từ ngày này đến --to (gồm cả 2 đầu).")
    ap.add_argument("--to", dest="to_date",
                    help="KHOẢNG NGÀY (giờ Seller) — mốc CUỐI YYYY-MM-DD. Để trống = bằng --from.")
    ap.add_argument("--hours", type=float, default=float(os.getenv("LOOKBACK_HOURS", "24")),
                    help="Lookback giờ cho orders (và mốc bắt đầu finances) khi KHÔNG dùng --date")
    ap.add_argument("--fresh", action="store_true",
                    help="XÓA SẠCH bảng raw của các nguồn được chọn TRƯỚC khi nạp mới "
                         "(reset rồi nhét lại). Không có cờ này = upsert dồn thêm như cũ.")
    ap.add_argument("--finances-window-days", type=int,
                    default=int(os.getenv("FINANCES_WINDOW_DAYS", "21")),
                    help="Cửa sổ nạp finances (ngày) TÍNH TỪ mốc bắt đầu orders. Vì phí Amazon "
                         "post 1-5 ngày SAU ngày đặt đơn, finances phải lấy RỘNG hơn orders thì "
                         "mới có phí của đơn ngày đó (khớp theo order_id). Mặc định 21. "
                         "0 = dùng đúng cửa sổ orders (sẽ bị amazon_fees=0).")
    args = ap.parse_args()

    do_orders = args.orders or args.all
    do_finances = args.finances or args.all
    do_ads = args.ads or args.all
    if not (do_orders or do_finances or do_ads):
        ap.error("Chọn ít nhất 1 nguồn: --orders / --finances / --ads / --all")

    now = datetime.now(timezone.utc)
    ads_dates = None
    # ── Cửa sổ ORDERS (theo NGÀY ĐẶT) — hỗ trợ KHOẢNG NGÀY [from, to] ──────────
    from_d = args.from_date or args.date          # --date là shorthand cho khoảng 1 ngày
    to_d = args.to_date or args.date or args.from_date
    if from_d:
        # Quy đổi KHOẢNG giờ Seller (Pacific) -> dải UTC + danh sách ngày (cho ads)
        o_after, o_before, ads_dates = tr.range_to_utc(from_d, to_d)
    else:
        # Terminal tương tác (không có --date/--from): hỏi chọn 24h gần nhất / khoảng ngày
        s, e, days = tr.maybe_prompt()
        if s:
            o_after, o_before, ads_dates = s, e, days
        else:
            o_after = (now - timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
            o_before = None
    if not ads_dates:
        ads_dates = [(now - timedelta(days=int(os.getenv("ADS_DAYS_AGO", "1")))).strftime("%Y-%m-%d")]

    # Cap CreatedBefore: Amazon Orders API TỪ CHỐI CreatedBefore ở tương lai
    # (phải <= now - 2 phút). Khoảng ngày kết thúc ở HÔM NAY (chưa hết ngày) sẽ
    # cho o_before = ngày mai 00:00 Pacific = tương lai -> None = mở đến hiện tại.
    if o_before:
        try:
            ob = datetime.strptime(o_before, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if ob >= now - timedelta(minutes=3):
                o_before = None
        except ValueError:
            pass

    # ── Cửa sổ FINANCES (theo NGÀY POST) — RỘNG hơn orders ────────────────────
    # Phí Amazon post 1-5 ngày SAU ngày đặt. Muốn có phí của đơn ngày D thì phải
    # lấy finances posted từ D đến D+N ngày. PostedBefore để None nếu quá gần "now"
    # (Finances API trả 400 nếu PostedBefore sát thời điểm hiện tại).
    f_after = o_after
    if args.finances_window_days and args.finances_window_days > 0:
        f_before = None
        try:
            base = datetime.strptime(o_after, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            end = base + timedelta(days=args.finances_window_days)
            if end < now - timedelta(hours=1):
                f_before = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    else:
        f_before = o_before          # window=0: dùng đúng cửa sổ orders (hành vi cũ)

    client = get_supabase_client()
    if args.fresh:
        truncate_for_sources(client, do_orders, do_finances, do_ads)
    if do_orders:
        run_orders(client, o_after, o_before)
    if do_finances:
        run_finances(client, f_after, f_before)
    if do_ads:
        run_ads(client, ads_dates)
    print("\n✅ Phase 1 hoàn tất — dữ liệu đã ở bảng đệm Supabase NEW_*.")
    
    # Trigger standalone post-processing cleanup and deduplication script
    print("\n🧹 Bắt đầu chạy hậu xử lý làm sạch & khử trùng lặp dữ liệu (process_buffer_cleanup)...")
    try:
        import subprocess
        cleanup_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "process_buffer_cleanup.py")
        subprocess.run([sys.executable, cleanup_script], check=True)
    except Exception as exc:
        print(f"❌ Cảnh báo: Chạy hậu xử lý dữ liệu thất bại: {exc}")
        
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:                              # noqa: BLE001
            pass
    sys.exit(main())
