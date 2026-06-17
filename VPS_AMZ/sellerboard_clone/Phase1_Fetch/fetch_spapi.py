"""Phase1_Fetch — SP-API: Orders (+ items) và Finances, lưu raw THEO NGÀY.

Mỗi ngày Pacific → 1 thư mục data/YYYY/MM/DD/ chứa:
    orders.jsonl.gz     — 1 dòng = 1 order (có _items nhúng), CreatedDate ngày đó
    finances.jsonl.gz   — 1 dòng = 1 page FinancialEvents, PostedDate ngày đó

KHÔNG ghi Supabase, KHÔNG transform. Replay: file đã có → skip (--force ghi đè).

LƯU Ý về finances (phí trễ): phí của đơn ngày D được Amazon post rải rác ngày
D..D+~10. Vì lưu theo PostedDate, muốn có ĐỦ phí cho đơn ngày D thì phải đã fetch
finances của các ngày tới D+~15. Cron hằng ngày fetch "hôm qua" sẽ tự tích lũy đủ.

Chạy:
    python fetch_spapi.py --date 2026-06-15
    python fetch_spapi.py --from 2026-06-01 --to 2026-06-15
    python fetch_spapi.py --date 2026-06-15 --orders-only
    python fetch_spapi.py --date 2026-06-15 --finances-only --force
"""
import argparse
import gc
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from shared.amz_auth import get_lwa_token
from shared.timeutils import utc_window_for_date, yesterday_pacific
from Phase1_Fetch.paths import orders_file, finances_file, open_jsonl_writer, iter_days

SP_BASE        = "https://sellingpartnerapi-na.amazon.com"
MARKETPLACE_ID = os.getenv("AMAZON_SPI_MARKETPLACE_ID", "ATVPDKIKX0DER")
PAGE_SIZE      = 100
ORDER_ITEMS_DELAY   = float(os.getenv("ORDER_ITEMS_DELAY_SECONDS", "1.0"))
FINANCES_PAGE_DELAY = float(os.getenv("FINANCES_PAGE_DELAY_SECONDS", "1.0"))


def _spapi_get(path, params, lwa, retries=6):
    import requests
    from urllib.parse import urlencode
    url = f"{SP_BASE}{path}"
    full_url = f"{url}?{urlencode(sorted(params.items()))}" if params else url
    headers = {"x-amz-access-token": lwa, "content-type": "application/json"}
    for attempt in range(retries):
        r = requests.get(full_url, headers=headers, timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            wait = max(float(r.headers.get("Retry-After", 2.0)), 2.0) + attempt * 2
            print(f"      ⚠️  429 {path} → đợi {wait:.0f}s")
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"      ❌ {r.status_code} {path}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Hết retry cho {path}")


def _fetch_order_items(lwa, order_id):
    resp = _spapi_get(f"/orders/v0/orders/{order_id}/orderItems", {}, lwa)
    time.sleep(ORDER_ITEMS_DELAY)
    return resp.get("payload", {}).get("OrderItems", [])


def _future_guard(end_utc, now):
    """CreatedBefore/PostedBefore không được sát/quá hiện tại → trả None nếu vậy."""
    return None if end_utc >= now - timedelta(minutes=3) else end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_orders_day(lwa, date_str, force=False):
    out = orders_file(date_str)
    if out.exists() and not force:
        print(f"    [Orders {date_str}] đã có — skip"); return 0
    start_utc, end_utc = utc_window_for_date(__import__("datetime").date.fromisoformat(date_str))
    now = datetime.now(timezone.utc)
    if start_utc >= now:
        print(f"    [Orders {date_str}] ngày tương lai — skip"); return 0
    created_after = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    created_before = _future_guard(end_utc, now)

    total, next_token, page = 0, None, 0
    f = open_jsonl_writer(out)
    try:
        while True:
            page += 1
            params = {"MarketplaceIds": MARKETPLACE_ID, "MaxResultsPerPage": PAGE_SIZE}
            if next_token:
                params["NextToken"] = next_token
            else:
                params["CreatedAfter"] = created_after
                if created_before:
                    params["CreatedBefore"] = created_before
            resp = _spapi_get("/orders/v0/orders", params, lwa)
            payload = resp.get("payload", {})
            orders = payload.get("Orders", [])
            next_token = payload.get("NextToken")
            for o in orders:
                oid = o.get("AmazonOrderId", "")
                try:
                    o["_items"] = _fetch_order_items(lwa, oid)
                except Exception as exc:
                    print(f"      ⚠️  items {oid}: {exc}"); o["_items"] = []
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
                total += 1
            del orders; gc.collect()
            if not next_token:
                break
    finally:
        f.close()
    print(f"    [Orders {date_str}] {total} orders → {out.relative_to(out.parents[4])}")
    return total


def fetch_finances_day(lwa, date_str, force=False):
    out = finances_file(date_str)
    if out.exists() and not force:
        print(f"    [Finances {date_str}] đã có — skip"); return 0
    start_utc, end_utc = utc_window_for_date(__import__("datetime").date.fromisoformat(date_str))
    now = datetime.now(timezone.utc)
    if start_utc >= now:
        print(f"    [Finances {date_str}] ngày tương lai — skip"); return 0
    posted_after = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    posted_before = _future_guard(end_utc, now)

    pages, next_token, page = 0, None, 0
    f = open_jsonl_writer(out)
    try:
        while True:
            page += 1
            if next_token:
                params = {"NextToken": next_token}
            else:
                params = {"PostedAfter": posted_after, "MaxResultsPerPage": PAGE_SIZE}
                if posted_before:
                    params["PostedBefore"] = posted_before
            resp = _spapi_get("/finances/v0/financialEvents", params, lwa)
            payload = resp.get("payload", {})
            events = payload.get("FinancialEvents", {})
            next_token = payload.get("NextToken")
            f.write(json.dumps(events, ensure_ascii=False) + "\n")
            pages += 1
            del events; gc.collect()
            if not next_token:
                break
            time.sleep(FINANCES_PAGE_DELAY)
    finally:
        f.close()
    print(f"    [Finances {date_str}] {pages} pages → {out.relative_to(out.parents[4])}")
    return pages


def main():
    ap = argparse.ArgumentParser(description="Fetch SP-API Orders + Finances theo ngày → data/YYYY/MM/DD/")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--orders-only",   action="store_true")
    ap.add_argument("--finances-only", action="store_true")
    args = ap.parse_args()

    if args.date:
        days = [args.date]
    elif args.from_date:
        days = list(iter_days(args.from_date, args.to_date or args.from_date))
    else:
        days = [str(yesterday_pacific())]

    do_orders = not args.finances_only
    do_finances = not args.orders_only

    lwa = get_lwa_token(cache_key="spapi")
    print(f"\n=== FETCH SP-API: {len(days)} ngày ===")
    for d in days:
        print(f"  --- {d} ---")
        if do_orders:
            fetch_orders_day(lwa, d, force=args.force)
        if do_finances:
            fetch_finances_day(lwa, d, force=args.force)
    print("\n✅ SP-API fetch hoàn tất.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
