"""Phase1_Fetch — Orchestrator: gọi TẤT CẢ Amazon API 1 LẦN, lưu raw vào data/.

Đây là điểm gọi API DUY NHẤT cho cả profit_dashboard lẫn ppc_dashboard.
Sau khi chạy xong, data/ chứa toàn bộ raw JSON.gz làm backup; rồi mỗi dashboard
chạy Phase1_Upload riêng để đẩy lên bảng Supabase của mình (không gọi lại API).

Thứ tự:
  1. SP-API: Orders + Finances        (profit dùng)
  2. Ads Reports: 9 report types       (profit + ppc dùng chung spCampaigns)
  3. Ads Mgmt snapshot                 (ppc dùng)
  4. Bid recommendations               (ppc dùng — cần mgmt trước)

Chạy:
    python run_fetch.py --date 2026-06-15            # đầy đủ 1 ngày
    python run_fetch.py --from 2026-06-01 --to 2026-06-15
    python run_fetch.py --date 2026-06-15 --skip-mgmt --skip-bidrecs   # chỉ profit cần
    python run_fetch.py --date 2026-06-15 --force

Lưu ý: SP-API và Ads API là 2 credentials có thể khác nhau — mỗi sub-fetch tự
xác thực. Lỗi 1 nguồn không chặn nguồn khác (bọc try/except).
"""
import argparse
import subprocess
import sys
from pathlib import Path

THIS_DIR = Path(__file__).parent


def _run(script: str, extra_args: list) -> bool:
    cmd = [sys.executable, str(THIS_DIR / script)] + extra_args
    print(f"\n{'='*70}\n▶ {script} {' '.join(extra_args)}\n{'='*70}")
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"❌ {script} thất bại (exit {exc.returncode}) — tiếp tục nguồn khác.")
        return False


def main():
    ap = argparse.ArgumentParser(description="Phase1_Fetch orchestrator")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-spapi",   action="store_true", help="Bỏ Orders+Finances")
    ap.add_argument("--skip-ads",     action="store_true", help="Bỏ Ads reports")
    ap.add_argument("--skip-mgmt",    action="store_true", help="Bỏ mgmt snapshot")
    ap.add_argument("--skip-bidrecs", action="store_true", help="Bỏ bid recommendations")
    ap.add_argument("--skip-images",  action="store_true", help="Bỏ lấy ảnh sản phẩm")
    args = ap.parse_args()

    # Args ngày dùng chung cho các sub-script
    range_args = []
    if args.date:
        range_args = ["--date", args.date]
    elif args.from_date:
        range_args = ["--from", args.from_date]
        if args.to_date:
            range_args += ["--to", args.to_date]
    force_args = ["--force"] if args.force else []

    # Snapshot date cho mgmt/bidrecs = ngày cuối khoảng (hoặc --date)
    snap_date = args.date or args.to_date or args.from_date

    results = {}
    if not args.skip_spapi:
        results["spapi"] = _run("fetch_spapi.py", range_args + force_args)
    if not args.skip_images:
        # Ảnh quét ASIN từ orders local → chạy SAU spapi. --refresh nếu --force.
        results["images"] = _run("fetch_images.py", range_args + (["--refresh"] if args.force else []))
    if not args.skip_ads:
        results["ads_reports"] = _run("fetch_ads_reports.py", range_args + force_args)
    if not args.skip_mgmt:
        mgmt_args = (["--date", snap_date] if snap_date else []) + force_args
        results["ads_mgmt"] = _run("fetch_ads_mgmt.py", mgmt_args)
    if not args.skip_bidrecs:
        bid_args = (["--date", snap_date] if snap_date else []) + force_args
        results["bid_recs"] = _run("fetch_bid_recs.py", bid_args)

    print(f"\n{'='*70}\n✅ Phase1_Fetch xong. Kết quả: {results}")
    print("   Raw data đã ở Phase1_Fetch/data/ — giờ chạy Phase1_Upload mỗi dashboard.")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
