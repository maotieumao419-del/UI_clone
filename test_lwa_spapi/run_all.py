"""
Chạy toàn bộ pipeline debug: Orders → Finances → Ads → In tổng hợp.

Chạy:
    python run_all.py

Hoặc từng phần:
    python fetch_24h_orders.py      # SP-API Orders + OrderItems
    python fetch_24h_finances.py    # SP-API Financial Events
    python fetch_24h_ads.py         # Advertising API Reports
"""
import subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = [
    ("fetch_24h_orders.py",   "SP-API Orders + OrderItems"),
    ("fetch_24h_finances.py", "SP-API Financial Events"),
    ("fetch_24h_ads.py",      "Advertising API Reports"),
]

def run_script(script, label):
    print(f"\n{'='*60}")
    print(f"  CHẠY: {script}  ({label})")
    print(f"{'='*60}")
    start = time.time()
    result = subprocess.run(
        [sys.executable, script],
        capture_output=False,   # in trực tiếp ra terminal
        text=True,
        cwd=Path(__file__).parent,
    )
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"\n  ❌ {script} thất bại (exit code {result.returncode})")
        return False
    print(f"\n  ✅ {script} hoàn thành ({elapsed:.0f}s)")
    return True

def print_output_summary():
    out_dir = Path(__file__).parent / "raw_data"
    if not out_dir.exists():
        return
    print(f"\n{'='*60}")
    print("OUTPUT FILES:")
    print(f"{'='*60}")
    for f in sorted(out_dir.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name:<40} {size_kb:>6} KB")

def main():
    print(f"\n{'='*60}")
    print(f"  SELLERBOARD DEBUG PIPELINE")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}")

    results = {}
    for script, label in SCRIPTS:
        ok = run_script(script, label)
        results[script] = ok
        if not ok:
            print(f"\n  ⚠️  Bỏ qua các bước tiếp theo? (nhấn Enter tiếp tục / Ctrl+C dừng)")
            try:
                input()
            except KeyboardInterrupt:
                break

    print_output_summary()

    print(f"\n{'='*60}")
    print("KẾT QUẢ:")
    for script, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {script}")
    print(f"{'='*60}")
    print("\nBước tiếp theo:")
    print("  1. Mở raw_data/orders_24h_raw.json   — xem cấu trúc đơn hàng")
    print("  2. Mở raw_data/finances_summary.txt  — so sánh Amazon fees với Sellerboard")
    print("  3. Mở raw_data/ads_summary.txt       — so sánh Adv. cost với Sellerboard")
    print("  4. Mở raw_data/*_fields_map.txt      — xem tất cả field Amazon trả về")

if __name__ == "__main__":
    main()
