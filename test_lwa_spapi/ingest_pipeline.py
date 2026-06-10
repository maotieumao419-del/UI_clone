"""
ingest_pipeline.py — Đọc raw JSON từ fetch scripts → Normalize → Upsert vào Supabase

Đọc files được tạo bởi:
  fetch_24h_orders.py   → raw_data/orders_24h_raw.json
  fetch_24h_finances.py → raw_data/finances_24h_raw.json
  fetch_24h_ads.py      → raw_data/ads_sp_raw.json, ads_sb_raw.json, ads_sd_raw.json

Upsert vào Supabase (cần chạy supabase_schema.sql trước):
  sp_orders, sp_order_items, fin_item_fees, fin_refunds,
  fin_adjustments, ads_campaigns_daily

Chạy:
  pip install supabase python-dotenv
  python ingest_pipeline.py

Env vars cần có trong .env:
  SUPABASE_URL=https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJhbGc...   (service role key, không phải anon key)
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
RAW_DIR = Path("raw_data")

# Tên bảng (prefix NEW_ để không xung đột với bảng cũ trong project)
T_ORDERS    = "NEW_sp_orders"
T_ITEMS     = "NEW_sp_order_items"
T_FEES      = "NEW_fin_item_fees"
T_REFUNDS   = "NEW_fin_refunds"
T_ADJ       = "NEW_fin_adjustments"
T_ADS       = "NEW_ads_campaigns_daily"

CHUNK_SIZE = 100  # upsert theo batch để tránh payload quá lớn


def get_client():
    from supabase import create_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_KEY trong .env\n"
            "  SUPABASE_URL=https://xxxx.supabase.co\n"
            "  SUPABASE_SERVICE_KEY=eyJhbGc...  ← service role key"
        )
    return create_client(SUPABASE_URL, SUPABASE_KEY)


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


def _upsert_chunks(client, table: str, rows: list, conflict: str):
    """Upsert rows vào Supabase theo từng chunk CHUNK_SIZE."""
    total = 0
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i : i + CHUNK_SIZE]
        client.table(table).upsert(chunk, on_conflict=conflict).execute()
        total += len(chunk)
    return total


# ── 1. Ingest Orders ──────────────────────────────────────────────────────────

def ingest_orders(client, orders: list) -> dict:
    """
    orders_24h_raw.json → sp_orders + sp_order_items

    Mỗi order trong file có:
      - Fields orders API (AmazonOrderId, PurchaseDate, OrderStatus, ...)
      - "_items": list của order items (từ /orders/{id}/orderItems)
    """
    orders_rows = []
    items_rows = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for o in orders:
        order_id = o.get("AmazonOrderId", "")
        if not order_id:
            continue

        # ── sp_orders ────────────────────────────────────────────
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

        # ── sp_order_items ───────────────────────────────────────
        # fetch_24h_orders.py lưu items dưới key "_items"
        raw_items = o.get("_items") or o.get("order_items") or []
        for item in raw_items:
            qty        = _int(item.get("QuantityOrdered", 1))
            price_amt  = _float((item.get("ItemPrice")  or {}).get("Amount"))
            tax_amt    = _float((item.get("ItemTax")    or {}).get("Amount"))
            promo_amt  = _float((item.get("PromotionDiscount") or {}).get("Amount"))
            unit_price = price_amt / qty if qty > 0 else price_amt

            items_rows.append({
                "order_id":           order_id,
                "asin":               item.get("ASIN", ""),
                "sku":                item.get("SellerSKU", ""),
                "title":              (item.get("Title") or "")[:512],
                "quantity_ordered":   qty,
                "unit_price":         round(unit_price, 2),
                "item_price":         round(price_amt, 2),
                "item_tax":           round(tax_amt, 2),
                "promotion_discount": round(-abs(promo_amt), 2) if promo_amt else 0,
                # Promo luôn âm (giảm giá)
                "synced_at":          now_iso,
            })

    result = {
        "orders_upserted": _upsert_chunks(client, T_ORDERS, orders_rows, "order_id"),
        "items_upserted":  _upsert_chunks(client, T_ITEMS,  items_rows,  "order_id,asin,sku"),
    }
    return result


# ── 2. Ingest Finances ────────────────────────────────────────────────────────

def ingest_finances(client, events: dict) -> dict:
    """
    finances_24h_raw.json → fin_item_fees + fin_refunds + fin_adjustments

    events có keys:
      ShipmentEventList    → phí FBA + Referral từng đơn
      RefundEventList      → hoàn hàng (posted_date = ngày Sellerboard dùng)
      AdjustmentEventList  → Clawback, Disposal, Storage, ...
    """
    fees_rows = []
    refunds_rows = []
    adj_rows = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── ShipmentEventList → fin_item_fees ────────────────────────
    for event in events.get("ShipmentEventList", []):
        order_id    = event.get("AmazonOrderId", "")
        posted_date = event.get("PostedDate")
        if not order_id:
            continue

        for item in event.get("ShipmentItemList", []):
            asin = item.get("ASIN", "")
            sku  = item.get("SellerSKU", "")
            qty  = _int(item.get("QuantityShipped", 1))

            for fee in item.get("ItemFeeList", []):
                fee_type = fee.get("FeeType", "")
                amount   = _float((fee.get("FeeAmount") or {}).get("Amount"))
                if not fee_type or amount == 0:
                    continue
                fees_rows.append({
                    "order_id":    order_id,
                    "posted_date": posted_date,
                    "asin":        asin,
                    "sku":         sku,
                    "quantity":    qty,
                    "fee_type":    fee_type,
                    "amount":      round(amount, 2),
                    "synced_at":   now_iso,
                })

    # ── RefundEventList → fin_refunds ────────────────────────────
    for event in events.get("RefundEventList", []):
        order_id    = event.get("AmazonOrderId", "")
        posted_date = event.get("PostedDate")  # ← KEY: Sellerboard dùng cái này
        if not order_id:
            continue

        for item in event.get("ShipmentItemAdjustmentList", []):
            asin = item.get("ASIN", "")
            sku  = item.get("SellerSKU", "")
            qty  = _int(item.get("QuantityShipped", 1))

            principal    = 0.0
            commission   = 0.0
            ref_referral = 0.0

            for charge in item.get("ItemChargeAdjustmentList", []):
                if charge.get("ChargeType") == "Principal":
                    principal = _float((charge.get("ChargeAmount") or {}).get("Amount"))

            for fee in item.get("ItemFeeAdjustmentList", []):
                ft  = fee.get("FeeType", "")
                amt = _float((fee.get("FeeAmount") or {}).get("Amount"))
                if ft == "Commission":
                    commission = amt
                elif ft == "RefundCommission":
                    ref_referral = amt  # DƯƠNG — Amazon hoàn lại referral fee

            refunds_rows.append({
                "order_id":              order_id,
                "posted_date":           posted_date,
                "asin":                  asin,
                "sku":                   sku,
                "quantity_returned":     qty,
                "refund_principal":      round(principal, 2),
                "refund_commission":     round(commission, 2),
                "refunded_referral_fee": round(ref_referral, 2),
                "synced_at":             now_iso,
            })

    # ── AdjustmentEventList → fin_adjustments ───────────────────
    for event in events.get("AdjustmentEventList", []):
        adj_type    = event.get("AdjustmentType", "")
        posted_date = event.get("PostedDate")

        for item in event.get("AdjustmentItemList", []):
            qty_raw      = _float(item.get("Quantity", 1))
            per_unit_amt = _float((item.get("PerUnitAmount") or {}).get("Amount"))
            total_amt    = per_unit_amt * qty_raw
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
        "fees_upserted":        _upsert_chunks(client, T_FEES,    fees_rows,    "order_id,sku,asin,fee_type"),
        "refunds_upserted":     _upsert_chunks(client, T_REFUNDS, refunds_rows, "order_id,sku,posted_date"),
        "adjustments_inserted": 0,
    }

    # Adjustments không có unique key tự nhiên → insert (không upsert)
    if adj_rows:
        for i in range(0, len(adj_rows), CHUNK_SIZE):
            client.table(T_ADJ).insert(adj_rows[i : i + CHUNK_SIZE]).execute()
        result["adjustments_inserted"] = len(adj_rows)

    return result


# ── 3. Ingest Ads ─────────────────────────────────────────────────────────────

def ingest_ads(client, sp_data: list, sb_data: list, sd_data: list, report_date: str) -> dict:
    """
    ads_sp_raw.json + ads_sb_raw.json + ads_sd_raw.json → ads_campaigns_daily

    sp_data: SP Campaigns report (cost, purchases1d, sales1d, ...)
    sb_data: SB Campaigns report — campaign_type phân biệt SB vs SBV
    sd_data: SD Campaigns report
    """
    rows = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for row in sp_data:
        rows.append({
            "report_date":   report_date,
            "campaign_id":   str(row.get("campaignId", "")),
            "campaign_name": row.get("campaignName", ""),
            "ad_product":    "SPONSORED_PRODUCTS",
            "campaign_type": "sponsoredProducts",
            "asin":          row.get("advertisedAsin"),
            "sku":           row.get("advertisedSku"),
            "impressions":   _int(row.get("impressions")),
            "clicks":        _int(row.get("clicks")),
            "cost":          round(_float(row.get("cost")), 2),
            "purchases_1d":  _int(row.get("purchases1d")),
            "purchases_7d":  _int(row.get("purchases7d")),
            "purchases_14d": _int(row.get("purchases14d")),
            "sales_1d":      round(_float(row.get("sales1d")), 2),
            "sales_7d":      round(_float(row.get("sales7d")), 2),
            "sales_14d":     round(_float(row.get("sales14d")), 2),
            "units_sold_1d": _int(row.get("unitsSoldClicks1d")),
            "synced_at":     now_iso,
        })

    for row in sb_data:
        rows.append({
            "report_date":   report_date,
            "campaign_id":   str(row.get("campaignId", "")),
            "campaign_name": row.get("campaignName", ""),
            "ad_product":    "SPONSORED_BRANDS",
            "campaign_type": row.get("campaignType", "sponsoredBrands"),
            # sponsoredBrands | sponsoredBrandsVideo — dùng để tách SB vs SBV
            "impressions":   _int(row.get("impressions")),
            "clicks":        _int(row.get("clicks")),
            "cost":          round(_float(row.get("cost")), 2),
            "purchases_14d": _int(row.get("purchases14d")),
            "sales_14d":     round(_float(row.get("sales14d")), 2),
            "synced_at":     now_iso,
        })

    for row in sd_data:
        rows.append({
            "report_date":   report_date,
            "campaign_id":   str(row.get("campaignId", "")),
            "campaign_name": row.get("campaignName", ""),
            "ad_product":    "SPONSORED_DISPLAY",
            "campaign_type": "sponsoredDisplay",
            "impressions":   _int(row.get("impressions")),
            "clicks":        _int(row.get("clicks")),
            "cost":          round(_float(row.get("cost")), 2),
            "purchases_14d": _int(row.get("purchases14d")),
            "sales_14d":     round(_float(row.get("sales14d")), 2),
            "synced_at":     now_iso,
        })

    total = _upsert_chunks(
        client, T_ADS, rows, "report_date,campaign_id,ad_product"
    )
    return {"rows_upserted": total, "report_date": report_date}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("INGEST PIPELINE — Amazon API raw data → Supabase")
    print("=" * 60)
    print(f"Supabase URL: {SUPABASE_URL[:40]}..." if SUPABASE_URL else "❌ SUPABASE_URL chưa set")
    print()

    client = get_client()
    print("✅ Kết nối Supabase OK\n")

    # ── 1. Orders ────────────────────────────────────────────────
    orders_file = RAW_DIR / "orders_24h_raw.json"
    if orders_file.exists():
        print(f"[1/3] Orders — {orders_file}")
        orders = json.loads(orders_file.read_text(encoding="utf-8"))
        print(f"      Đọc {len(orders)} orders từ file...")
        result = ingest_orders(client, orders)
        print(f"      ✅ sp_orders: {result['orders_upserted']} rows")
        print(f"      ✅ sp_order_items: {result['items_upserted']} rows")
    else:
        print(f"[1/3] ⚠️  Không tìm thấy {orders_file}")
        print("      → Chạy: python fetch_24h_orders.py trước")

    # ── 2. Finances ───────────────────────────────────────────────
    finances_file = RAW_DIR / "finances_24h_raw.json"
    if finances_file.exists():
        print(f"\n[2/3] Finances — {finances_file}")
        events = json.loads(finances_file.read_text(encoding="utf-8"))
        counts = {
            k: len(events.get(k, []))
            for k in ("ShipmentEventList", "RefundEventList", "AdjustmentEventList")
        }
        print(f"      Shipments: {counts['ShipmentEventList']}, "
              f"Refunds: {counts['RefundEventList']}, "
              f"Adjustments: {counts['AdjustmentEventList']}")
        result = ingest_finances(client, events)
        print(f"      ✅ fin_item_fees: {result['fees_upserted']} rows")
        print(f"      ✅ fin_refunds: {result['refunds_upserted']} rows")
        print(f"      ✅ fin_adjustments: {result['adjustments_inserted']} rows")
    else:
        print(f"\n[2/3] ⚠️  Không tìm thấy {finances_file}")
        print("      → Chạy: python fetch_24h_finances.py trước")

    # ── 3. Ads ────────────────────────────────────────────────────
    sp_file = RAW_DIR / "ads_sp_raw.json"
    sb_file = RAW_DIR / "ads_sb_raw.json"
    sd_file = RAW_DIR / "ads_sd_raw.json"

    if any(f.exists() for f in [sp_file, sb_file, sd_file]):
        print(f"\n[3/3] Ads reports")
        sp_data = json.loads(sp_file.read_text(encoding="utf-8")) if sp_file.exists() else []
        sb_data = json.loads(sb_file.read_text(encoding="utf-8")) if sb_file.exists() else []
        sd_data = json.loads(sd_file.read_text(encoding="utf-8")) if sd_file.exists() else []

        # Lấy report_date từ data (field "date") hoặc dùng hôm qua
        report_date = None
        for row in sp_data + sb_data + sd_data:
            if "date" in row and row["date"]:
                report_date = row["date"]
                break
        if not report_date:
            report_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        print(f"      SP: {len(sp_data)} campaigns, SB: {len(sb_data)} campaigns, SD: {len(sd_data)} campaigns")
        print(f"      Report date: {report_date}")
        result = ingest_ads(client, sp_data, sb_data, sd_data, report_date)
        print(f"      ✅ ads_campaigns_daily: {result['rows_upserted']} rows cho {result['report_date']}")
    else:
        print(f"\n[3/3] ⚠️  Không tìm thấy ads JSON files")
        print("      → Chạy: python fetch_24h_ads.py trước")

    print("\n" + "=" * 60)
    print("✅ HOÀN TẤT! Kiểm tra dữ liệu trong Supabase SQL Editor:")
    print()
    print('  -- CSV Order Items cho ngày cụ thể:')
    print('  SELECT * FROM "NEW_v_order_items_csv"')
    print("  WHERE order_date = '2026-06-08'")
    print("    AND row_type = 'normal'")
    print("  ORDER BY sort_ts DESC;")
    print()
    print('  -- Returns cho ngày cụ thể (filter theo posted_date):')
    print('  SELECT * FROM "NEW_v_order_items_csv"')
    print("  WHERE sort_ts::date = '2026-06-08'")
    print("    AND row_type = 'return';")
    print()
    print("  -- Dashboard card:")
    print('  SELECT * FROM "NEW_fn_daily_summary"(\'2026-06-08\');')
    print("=" * 60)


if __name__ == "__main__":
    main()
