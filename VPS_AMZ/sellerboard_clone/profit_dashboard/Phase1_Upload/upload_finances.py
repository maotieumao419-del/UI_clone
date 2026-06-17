"""Phase1_Upload (profit) — đọc data/finances/*.jsonl.gz → Profit_Phase1_fin_item_fees
+ Profit_Phase1_fin_refunds + Profit_Phase1_fin_adjustments.

Mỗi dòng file = 1 page FinancialEvents (dict). Logic gộp port nguyên từ
direct_stream_pipeline.ingest_finance_events_page (cộng dồn theo khoá conflict
tránh PostgREST 21000).

Chạy:
    python upload_finances.py --date 2026-06-15
    python upload_finances.py --from 2026-06-01 --to 2026-06-15
"""
import argparse
import gc
import sys
from pathlib import Path

from _common import (T_FEES, T_REFUNDS, T_ADJ, f_, i_, money, now_iso, CHUNK_SIZE)

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.supabase_client import get_supabase_client, upsert_chunks
from shared.timeutils import yesterday_pacific
from Phase1_Fetch.paths import finances_file, read_jsonl_gz, iter_days


def _ingest_events(client, events: dict) -> dict:
    """Port từ direct_stream_pipeline.ingest_finance_events_page."""
    ts = now_iso()

    fees_map: dict[tuple, dict] = {}
    for event in events.get("ShipmentEventList", []):
        order_id = event.get("AmazonOrderId", "")
        posted_date = event.get("PostedDate")
        if not order_id:
            continue
        for item in event.get("ShipmentItemList", []):
            asin = item.get("ASIN", "")
            sku = item.get("SellerSKU", "")
            qty = i_(item.get("QuantityShipped", 1))
            principal = sum(money(ch.get("ChargeAmount"))
                            for ch in item.get("ItemChargeList", [])
                            if ch.get("ChargeType") == "Principal")
            for fee in item.get("ItemFeeList", []):
                fee_type = fee.get("FeeType", "")
                amount = money(fee.get("FeeAmount"))
                if not fee_type or amount == 0:
                    continue
                key = (order_id, sku, asin, fee_type)
                row = fees_map.setdefault(key, {
                    "order_id": order_id, "posted_date": posted_date,
                    "asin": asin, "sku": sku, "quantity": 0,
                    "fee_type": fee_type, "amount": 0.0, "principal": 0.0,
                    "synced_at": ts,
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
                    principal = money(charge.get("ChargeAmount"))
            for fee in item.get("ItemFeeAdjustmentList", []):
                ftype = fee.get("FeeType", "")
                amt = money(fee.get("FeeAmount"))
                if ftype == "Commission":
                    commission = amt
                elif ftype == "RefundCommission":
                    ref_referral = amt
            key = (order_id, item.get("SellerSKU", ""), posted_date)
            row = refunds_map.setdefault(key, {
                "order_id": order_id, "posted_date": posted_date,
                "asin": item.get("ASIN", ""), "sku": item.get("SellerSKU", ""),
                "quantity_returned": 0, "refund_principal": 0.0,
                "refund_commission": 0.0, "refunded_referral_fee": 0.0,
                "synced_at": ts,
            })
            row["quantity_returned"] += i_(item.get("QuantityShipped", 1))
            row["refund_principal"] = round(row["refund_principal"] + principal, 2)
            row["refund_commission"] = round(row["refund_commission"] + commission, 2)
            row["refunded_referral_fee"] = round(row["refunded_referral_fee"] + ref_referral, 2)
    refunds_rows = list(refunds_map.values())

    adj_rows = []
    for event in events.get("AdjustmentEventList", []):
        adj_type = event.get("AdjustmentType", "")
        posted_date = event.get("PostedDate")
        for item in event.get("AdjustmentItemList", []):
            qty_raw = f_(item.get("Quantity", 1))
            total_amt = money(item.get("PerUnitAmount")) * qty_raw
            if total_amt == 0:
                continue
            adj_rows.append({
                "posted_date": posted_date, "adjustment_type": adj_type,
                "sku": item.get("SellerSKU", ""), "asin": item.get("ASIN", ""),
                "quantity": int(qty_raw), "amount": round(total_amt, 2),
                "synced_at": ts,
            })

    result = {
        "fees":    upsert_chunks(client, T_FEES, fees_rows, "order_id,sku,asin,fee_type"),
        "refunds": upsert_chunks(client, T_REFUNDS, refunds_rows, "order_id,sku,posted_date"),
        "adjustments": 0,
    }
    for i in range(0, len(adj_rows), CHUNK_SIZE):
        client.table(T_ADJ).insert(adj_rows[i: i + CHUNK_SIZE]).execute()
        result["adjustments"] += len(adj_rows[i: i + CHUNK_SIZE])
    return result


def upload_finances_file(client, date_str: str) -> dict:
    path = finances_file(date_str)
    if not path.exists():
        print(f"  ⚠️  {date_str}: không có finances.jsonl.gz — bỏ qua")
        return {"fees": 0, "refunds": 0, "adjustments": 0}

    print(f"  [Finances {date_str}] đọc {path}...")
    totals = {"fees": 0, "refunds": 0, "adjustments": 0}
    for events in read_jsonl_gz(path):
        r = _ingest_events(client, events)
        for k in totals:
            totals[k] += r[k]
        del events; gc.collect()
    print(f"  ✅ Finances: {totals}")
    return totals


def main():
    ap = argparse.ArgumentParser(description="Upload finances raw → Profit_Phase1_*")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    args = ap.parse_args()

    if args.date:
        days = [args.date]
    elif args.from_date:
        days = list(iter_days(args.from_date, args.to_date or args.from_date))
    else:
        days = [str(yesterday_pacific())]

    client = get_supabase_client()
    for d in days:
        upload_finances_file(client, d)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
