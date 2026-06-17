"""Phase1_Upload (ppc) — Orchestrator: đẩy raw data/ → Supabase PPC_Phase1_*.

KHÔNG gọi Amazon API. Chạy SAU Phase1_Fetch/run_fetch.py.

Chạy:
    python run_upload.py --date 2026-06-15
    python run_upload.py --from 2026-06-01 --to 2026-06-15
    python run_upload.py --date 2026-06-15 --skip-mgmt
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
    ap = argparse.ArgumentParser(description="Phase1_Upload orchestrator (ppc)")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to",   dest="to_date")
    ap.add_argument("--skip-reports", action="store_true")
    ap.add_argument("--skip-mgmt",    action="store_true")
    args = ap.parse_args()

    range_args = []
    if args.date:
        range_args = ["--date", args.date]
    elif args.from_date:
        range_args = ["--from", args.from_date]
        if args.to_date:
            range_args += ["--to", args.to_date]

    snap_date = args.date or args.to_date or args.from_date

    results = {}
    if not args.skip_reports:
        results["ads_reports"] = _run("upload_ads_reports.py", range_args)
    if not args.skip_mgmt:
        mgmt_args = ["--date", snap_date] if snap_date else []
        results["ads_mgmt"] = _run("upload_ads_mgmt.py", mgmt_args)

    print(f"\n{'='*70}\n✅ Phase1_Upload (ppc) xong: {results}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass
    sys.exit(main())
