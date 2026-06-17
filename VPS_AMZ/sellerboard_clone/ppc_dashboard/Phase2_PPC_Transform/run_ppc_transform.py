"""PPC Phase 2 — Main entry point: transform PPC_*_daily -> PPC_summary_*.

Chạy:
    python run_ppc_transform.py --date 2026-06-15
    python run_ppc_transform.py --days 7
    python run_ppc_transform.py --from 2026-06-01 --to 2026-06-15
    python run_ppc_transform.py --date 2026-06-15 --no-write   # chỉ xem log, không ghi

Thứ tự transform (phụ thuộc nhau):
  1. campaigns  -> PPC_Phase2_summary_campaigns  (dùng placement data)
  2. adgroups   -> PPC_Phase2_summary_adgroups
  3. keywords   -> PPC_Phase2_summary_keywords   (dùng bid recs)
  4. searchterms-> PPC_Phase2_summary_searchterms
  5. portfolios -> PPC_Phase2_summary_portfolios (aggregate từ PPC_Phase2_summary_campaigns)
"""
import argparse
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "Phase1_PPC_Ingestion", ".env"))

from shared.supabase_client import get_supabase_client
from shared.timeutils import date_range_pacific, yesterday_pacific

import transform_campaigns  as tc
import transform_adgroups   as ta
import transform_keywords   as tk
import transform_searchterms as ts
import transform_portfolios  as tp
import transform_bulk        as tb


def run_transform(client, date_str: str, no_write: bool = False) -> dict:
    print(f"\n=== PPC TRANSFORM: {date_str} ===")
    totals = {}

    if no_write:
        print("  [--no-write] Chỉ tính, không ghi Supabase")
        return totals

    # Thứ tự quan trọng: portfolios phụ thuộc campaigns
    totals["campaigns"]   = tc.transform_campaigns_for_date(client, date_str)
    totals["adgroups"]    = ta.transform_adgroups_for_date(client, date_str)
    totals["keywords"]    = tk.transform_keywords_for_date(client, date_str)
    totals["searchterms"] = ts.transform_searchterms_for_date(client, date_str)
    totals["portfolios"]  = tp.transform_portfolios_for_date(client, date_str)

    print(f"  Tổng: {totals}")
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description="PPC Phase 2 — Transform")
    ap.add_argument("--date",  help="Đúng 1 ngày YYYY-MM-DD (Pacific)")
    ap.add_argument("--days",  type=int, help="N ngày gần nhất (tính từ hôm qua Pacific)")
    ap.add_argument("--from",  dest="from_date", help="Ngày bắt đầu khoảng")
    ap.add_argument("--to",    dest="to_date",   help="Ngày kết thúc khoảng")
    ap.add_argument("--no-write", action="store_true", help="Chỉ log, không ghi DB")
    ap.add_argument("--bulk", action="store_true",
                    help="Dựng thêm bảng PPC_Phase2_bulk_sp (mirror file Amazon bulk) "
                         "cho TOÀN khoảng [đầu, cuối]")
    ap.add_argument("--bulk-only", action="store_true",
                    help="CHỈ dựng bulk, bỏ qua các summary theo ngày")
    args = ap.parse_args()

    if args.date:
        dates = [args.date]
    elif args.from_date:
        end = args.to_date or args.from_date
        dates = [str(d) for d in date_range_pacific(args.from_date, end)]
    elif args.days:
        yesterday = yesterday_pacific()
        dates = [str(yesterday - timedelta(days=i)) for i in range(args.days - 1, -1, -1)]
    else:
        dates = [str(yesterday_pacific())]

    client = get_supabase_client()
    grand_total: dict = {}

    if not args.bulk_only:
        for d in dates:
            result = run_transform(client, d, no_write=args.no_write)
            for k, v in result.items():
                grand_total[k] = grand_total.get(k, 0) + v
        print(f"\n✅ PPC Phase 2 (summary theo ngày) xong ({len(dates)} ngày): {grand_total}")

    # Bulk = tổng hợp CẢ khoảng thành 1 dòng/entity (mirror file Amazon bulk)
    if (args.bulk or args.bulk_only) and not args.no_write:
        n = tb.transform_bulk_for_range(client, dates[0], dates[-1])
        print(f"✅ PPC_Phase2_bulk_sp: {n} dòng cho kỳ {dates[0]} → {dates[-1]}")

    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
