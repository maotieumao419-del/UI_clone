"""Phase1_Upload (profit) — đọc data/orders/*.jsonl.gz → Profit_Phase1_sp_orders
+ Profit_Phase1_sp_order_items + Profit_Phase1_product_price.

KHÔNG gọi API. Đọc raw file do Phase1_Fetch/fetch_spapi.py lưu, transform thành
rows, bulk upsert Supabase. Logic transform port nguyên từ direct_stream_pipeline
(gộp dòng trùng SKU trong cùng đơn để tránh PostgREST 21000).

Memory-safety: đọc generator từng order, gom theo lô PAGE rồi upsert + gc.

Chạy:
    python upload_orders.py --date 2026-06-15
    python upload_orders.py --from 2026-06-01 --to 2026-06-15
"""
import argparse
import gc
import sys
from pathlib import Path

from _common import (T_ORDERS, T_ITEMS, T_PRICE, f_, i_, now_iso)

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.supabase_client import get_supabase_client, upsert_chunks
from shared.timeutils import yesterday_pacific
from Phase1_Fetch.paths import orders_file, read_jsonl_gz, iter_days

PAGE = 100


def _ingest_orders_batch(client, orders: list) -> dict:
    """Port từ direct_stream_pipeline.ingest_orders_page — đổi tên bảng Profit_Phase1_*."""
    orders_rows = []
    items_map: dict[tuple, dict] = {}
    ts = now_iso()
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
            "synced_at":           ts,
        })
        for item in o.get("_items") or []:
            asin = item.get("ASIN", "")
            sku = item.get("SellerSKU", "")
            qty = i_(item.get("QuantityOrdered", 1))
            price_amt = f_((item.get("ItemPrice") or {}).get("Amount"))
            tax_amt = f_((item.get("ItemTax") or {}).get("Amount"))
            promo_amt = f_((item.get("PromotionDiscount") or {}).get("Amount"))
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
                    "synced_at":          ts,
                }
            else:
                row["quantity_ordered"] += qty
                row["item_price"] = round(row["item_price"] + price_amt, 2)
                row["item_tax"] = round(row["item_tax"] + tax_amt, 2)
                row["promotion_discount"] = round(row["promotion_discount"] - abs(promo_amt), 2)

    items_rows = []
    price_map: dict[str, float] = {}
    for row in items_map.values():
        q = row["quantity_ordered"]
        row["unit_price"] = round(row["item_price"] / q if q > 0 else row["item_price"], 2)
        items_rows.append(row)
        if row["unit_price"] > 0:
            price_map[row["sku"]] = row["unit_price"]

    if price_map:
        price_rows = [{"sku": s, "unit_price": p, "source": "order", "updated_at": ts}
                      for s, p in price_map.items() if s]
        upsert_chunks(client, T_PRICE, price_rows, "sku")

    return {
        "orders": upsert_chunks(client, T_ORDERS, orders_rows, "order_id"),
        "items":  upsert_chunks(client, T_ITEMS, items_rows, "order_id,asin,sku"),
    }


def upload_orders_file(client, date_str: str) -> dict:
    path = orders_file(date_str)
    if not path.exists():
        print(f"  ⚠️  {date_str}: không có orders.jsonl.gz — bỏ qua (chạy fetch_spapi.py trước)")
        return {"orders": 0, "items": 0}

    print(f"  [Orders {date_str}] đọc {path}...")
    totals = {"orders": 0, "items": 0}
    batch = []
    for order in read_jsonl_gz(path):
        batch.append(order)
        if len(batch) >= PAGE:
            r = _ingest_orders_batch(client, batch)
            totals["orders"] += r["orders"]; totals["items"] += r["items"]
            batch.clear(); gc.collect()
    if batch:
        r = _ingest_orders_batch(client, batch)
        totals["orders"] += r["orders"]; totals["items"] += r["items"]
        batch.clear(); gc.collect()

    print(f"  ✅ Orders: +{totals['orders']} orders, +{totals['items']} items")
    return totals


def main():
    ap = argparse.ArgumentParser(description="Upload orders raw → Profit_Phase1_*")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    args = ap.parse_args()

    # Dữ liệu lưu per-day (data/YYYY/MM/DD/) → upload lặp từng ngày.
    if args.date:
        days = [args.date]
    elif args.from_date:
        days = list(iter_days(args.from_date, args.to_date or args.from_date))
    else:
        days = [str(yesterday_pacific())]

    client = get_supabase_client()
    for d in days:
        upload_orders_file(client, d)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
