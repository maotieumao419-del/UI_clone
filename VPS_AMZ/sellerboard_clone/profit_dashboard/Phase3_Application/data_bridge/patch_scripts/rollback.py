"""Phase 3 — rollback.py
Khôi phục các file gốc đã bị patch_dashboard.py / patch_frontend.py sửa,
từ bản backup MỚI NHẤT trong Phase3_Application/data_bridge/patch_scripts/backups/.

Chạy:
    cd ~/VPS_AMZ/sellerboard_clone
    python Phase3_Application/data_bridge/patch_scripts/rollback.py            # khôi phục tất cả
    python Phase3_Application/data_bridge/patch_scripts/rollback.py --list     # chỉ liệt kê backup hiện có
Sau khi rollback backend nhớ khởi động lại service.
"""
import argparse
import shutil
import sys
from pathlib import Path

# Console Windows mặc định cp1252 — ép UTF-8 để in được tiếng Việt
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

PHASE3_DIR = Path(__file__).resolve().parent
ROOT = PHASE3_DIR.parent.parent.parent
BACKUP_DIR = PHASE3_DIR / "backups"

# tên backup (prefix) -> file đích cần khôi phục
TARGETS = {
    "dashboard.py": ROOT / "backend" / "app" / "routers" / "dashboard.py",
    "index.html": ROOT / "frontend" / "index.html",
}
# file do patch_frontend copy vào frontend/ — rollback thì xoá đi
EXTRA_REMOVE = [ROOT / "frontend" / "render_performance.js"]


def latest_backup(prefix: str) -> Path | None:
    if not BACKUP_DIR.exists():
        return None
    cands = sorted(BACKUP_DIR.glob(prefix + ".*.bak"))
    return cands[-1] if cands else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="Chỉ liệt kê backup")
    args = ap.parse_args()

    if args.list:
        if not BACKUP_DIR.exists() or not any(BACKUP_DIR.iterdir()):
            print("(chưa có backup nào)")
            return
        for f in sorted(BACKUP_DIR.iterdir()):
            print(" -", f.name)
        return

    restored = 0
    for prefix, target in TARGETS.items():
        bak = latest_backup(prefix)
        if bak is None:
            print(f"[BỎ QUA] Không có backup cho {prefix} (chưa từng vá?).")
            continue
        try:
            shutil.copy2(bak, target)
            print(f"[OK] Khôi phục {target.relative_to(ROOT)}  <-  {bak.name}")
            restored += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[LỖI] Không khôi phục được {target}: {exc}")

    for f in EXTRA_REMOVE:
        try:
            if f.exists():
                f.unlink()
                print(f"[OK] Xoá {f.relative_to(ROOT)} (file do Phase 3 thêm vào).")
        except Exception as exc:  # noqa: BLE001
            print(f"[LỖI] Không xoá được {f}: {exc}")

    if restored:
        print("\n=> Khởi động lại backend để áp dụng (vd: systemctl restart sellerboard).")
    else:
        print("\n=> Không có gì để khôi phục.")


if __name__ == "__main__":
    sys.exit(main())
