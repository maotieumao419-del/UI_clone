"""Phase 3 — patch_dashboard.py
Ghi đè AN TOÀN backend/app/routers/dashboard.py bằng phiên bản Phase 3:
router /api/analytics chỉ còn /dashboard/summary (KPIs + bảng Products/Orders,
đọc 100% từ SQLite/Postgres local qua analytics_aggregator.py), /ltv, /bsr.
Các route /dashboard và /periods cũ (Supabase-based) đã bị xoá.

Nguyên tắc:
  - Luôn backup file gốc vào Phase3_Application/data_bridge/patch_scripts/backups/
    trước khi ghi đè.
  - Sau khi ghi: kiểm tra cú pháp bằng py_compile — lỗi thì tự khôi phục backup.
  - Idempotent: nếu file đích đã đúng nội dung Phase 3 -> không làm gì thêm.

Chạy:
    cd ~/VPS_AMZ/sellerboard_clone
    python Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py            # vá
    python Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py --check    # chỉ kiểm tra, không ghi
Khôi phục: python Phase3_Application/data_bridge/patch_scripts/rollback.py
"""
import argparse
import py_compile
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Console Windows mặc định cp1252 — ép UTF-8 để in được tiếng Việt
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

PHASE3_DIR = Path(__file__).resolve().parent
ROOT = PHASE3_DIR.parent.parent.parent
TARGET = ROOT / "backend" / "app" / "routers" / "dashboard.py"
BACKUP_DIR = PHASE3_DIR / "backups"

# ── Nội dung MỚI (Phase 3) — phải khớp 100% với backend/app/routers/dashboard.py ──
NEW_DASHBOARD_PY = '''"""Router phân tích: dashboard tổng hợp (SQLite/Postgres local), LTV, BSR monitor."""
import sys
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services import profit

_ROOT = Path(__file__).resolve().parents[3]            # .../sellerboard_clone
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Phase3_Application.data_bridge.analytics_aggregator import (  # noqa: E402
    get_dashboard_kpis, get_order_items_details, get_sku_performance,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard/summary")
def get_dashboard_summary(
    tab: str = Query("products"),
    start: date = Query(...),
    end: date = Query(...),
    compare_start: date | None = Query(None),
    compare_end: date | None = Query(None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """All-in-One Dashboard: thẻ KPI (so sánh kỳ trước) + bảng chi tiết theo tab.

    - tab=products (mặc định) -> bảng SKU performance (GROUP BY asin, sku).
    - tab=orders               -> ledger giao dịch thô NEW_summary_order_items.
    """
    result = {
        "kpis": get_dashboard_kpis(db, current.id, start, end, compare_start, compare_end),
    }
    if tab == "orders":
        result["orders"] = get_order_items_details(db, current.id, start, end)
    else:
        result["products"] = get_sku_performance(db, current.id, start, end)
    return result


@router.get("/periods")
def get_periods(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """5 thẻ tổng quan kiểu Sellerboard (Today/Yesterday/MTD/Forecast/Last month)."""
    return profit.period_overview(db, current.id)


@router.get("/ltv")
def get_ltv(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.customer_ltv(db, current.id)


@router.get("/bsr")
def get_bsr(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.bsr_monitor(db, current.id)
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Chỉ kiểm tra, không ghi file")
    args = ap.parse_args()

    if not TARGET.exists():
        raise SystemExit(f"[LỖI] Không thấy {TARGET}")
    text = TARGET.read_text(encoding="utf-8")

    if text == NEW_DASHBOARD_PY:
        print("[OK] dashboard.py ĐÃ ở trạng thái Phase 3 — không làm gì thêm.")
        return

    if args.check:
        print("[CHECK] dashboard.py khác nội dung Phase 3 — sẵn sàng ghi đè (chưa ghi gì).")
        return

    # Backup trước khi ghi
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"dashboard.py.{stamp}.bak"
    shutil.copy2(TARGET, backup)
    print(f"[BACKUP] {backup}")

    TARGET.write_text(NEW_DASHBOARD_PY, encoding="utf-8")
    # Kiểm tra cú pháp ngay — lỗi thì khôi phục backup tự động
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(backup, TARGET)
        raise SystemExit(f"[LỖI] File vá không compile được, ĐÃ khôi phục backup.\n{exc}")

    print(f"[OK] Đã ghi đè {TARGET.relative_to(ROOT)} (Phase 3)")
    print("     -> Khởi động lại backend (systemctl restart / gunicorn reload) để áp dụng.")
    print("     -> Khôi phục khi cần: python Phase3_Application/data_bridge/patch_scripts/rollback.py")


if __name__ == "__main__":
    sys.exit(main())
