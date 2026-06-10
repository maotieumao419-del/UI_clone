"""
Bấm Run file này trong VS Code hoặc PyCharm là xong.
Không cần mở terminal, không cần gõ lệnh thủ công.
"""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

SCRIPTS = [
    ("fetch_24h_orders.py",   "[1/3] SP-API Orders + OrderItems"),
    ("fetch_24h_finances.py", "[2/3] SP-API Financial Events"),
    ("fetch_24h_ads.py",      "[3/3] Advertising API Reports"),
]

for script, label in SCRIPTS:
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"  File: {os.path.join(HERE, script)}")
    print(f"{'='*50}")
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print(f"\n❌ {script} gặp lỗi (exit code {result.returncode})")
        print("Nhấn Enter để chạy script tiếp theo, hoặc Ctrl+C để dừng...")
        try:
            input()
        except KeyboardInterrupt:
            print("\nDừng.")
            break

print(f"\n{'='*50}")
print("  XONG.")
print(f"  Kết quả trong: {os.path.join(HERE, 'raw_data')}")
print(f"{'='*50}")
input("\nNhấn Enter để đóng cửa sổ...")
