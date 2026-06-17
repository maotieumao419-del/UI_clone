"""Phase1_Upload (profit) — Orchestrator: đẩy raw data/ → Supabase Profit_Phase1_*.

KHÔNG gọi Amazon API. Đọc file Phase1_Fetch/data/ rồi upsert. Chạy SAU khi
Phase1_Fetch/run_fetch.py đã lưu raw.

Chạy:
    python run_upload.py --date 2026-06-15
    python run_upload.py --from 2026-06-01 --to 2026-06-15
    python run_upload.py --date 2026-06-15 --skip-finances
    python run_upload.py --date 2026-06-15 --cleanup   # chạy dedup sau upload

Lưu ý: order/finances dùng date_label (1 ngày = "YYYY-MM-DD", khoảng =
"FROM_to_TO"); ads dùng từng ngày — các sub-script tự xử lý đúng.
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
        print(f"❌ {script} thất bại (exit {exc.returncode})")
        return False


def main():
    ap = argparse.ArgumentParser(description="Phase1_Upload orchestrator (profit)")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    ap.add_argument("--skip-orders",   action="store_true")
    ap.add_argument("--skip-finances", action="store_true")
    ap.add_argument("--skip-ads",      action="store_true")
    ap.add_argument("--skip-images",   action="store_true")
    ap.add_argument("--cleanup", action="store_true",
                    help="Chạy dedup process_buffer_cleanup sau khi upload")
    args = ap.parse_args()

    range_args = []
    if args.date:
        range_args = ["--date", args.date]
    elif args.from_date:
        range_args = ["--from", args.from_date]
        if args.to_date:
            range_args += ["--to", args.to_date]

    results = {}
    if not args.skip_orders:
        results["orders"] = _run("upload_orders.py", range_args)
    if not args.skip_finances:
        results["finances"] = _run("upload_finances.py", range_args)
    if not args.skip_ads:
        results["ads"] = _run("upload_ads.py", range_args)
    if not args.skip_images:
        # Ảnh persistent — không cần range
        results["images"] = _run("upload_images.py", [])

    if args.cleanup:
        cleanup = THIS_DIR.parent / "Phase1_Ingestion" / "process_buffer_cleanup.py"
        if cleanup.exists():
            print(f"\n🧹 Chạy dedup: {cleanup.name}")
            try:
                subprocess.run([sys.executable, str(cleanup)], check=True)
            except subprocess.CalledProcessError as exc:
                print(f"❌ Cleanup lỗi: {exc}")

    print(f"\n{'='*70}\n✅ Phase1_Upload (profit) xong: {results}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
