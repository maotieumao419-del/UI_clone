"""Phase 3 — patch_dashboard.py
Vá AN TOÀN backend/app/routers/dashboard.py để endpoint
GET /api/analytics/dashboard?days=N trả thêm ma trận hiệu suất sản phẩm
(top_products với sku/quantity/price/product_cost/commission/fba_fee/promo/
ad_spend/net_profit/margin) từ Phase3_Application/data_bridge/analytics_aggregator.py.

Nguyên tắc:
  - KHÔNG sửa tay file gốc: script này dùng try_replace (khớp chuỗi chính xác,
    thay đúng 1 lần); nếu không khớp (file đã bị đổi) -> báo lỗi và DỪNG,
    không ghi gì cả.
  - Luôn backup file gốc vào Phase3_Application/data_bridge/patch_scripts/backups/ trước khi ghi.
  - Tương thích ngược: vẫn gọi profit.dashboard() cũ cho kpis/timeseries/
    marketplace_breakdown (chart không đổi); chỉ thay mảng top_products bằng
    bản Phase 3 (mỗi dòng chứa CẢ khoá cũ lẫn khoá mới); nếu Phase 3 lỗi
    -> giữ nguyên payload cũ 100%.
  - Bỏ response_model=DashboardResponse trên route này (Pydantic sẽ cắt mất
    các khoá mới nếu giữ) — schema import vẫn giữ nguyên cho các route khác.

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

# ── Đoạn mã GỐC cần thay (phải khớp chính xác 100%) ──────────────────────────
OLD_ROUTE = '''@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(days: int = Query(30, ge=1, le=365),
                  db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.dashboard(db, current.id, days=days)'''

# ── Đoạn mã MỚI (Phase 3) ─────────────────────────────────────────────────────
NEW_ROUTE = '''@router.get("/dashboard")
def get_dashboard(days: int = Query(30, ge=1, le=365),
                  db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """Phase 3: payload cũ (kpis/timeseries/marketplace_breakdown giữ nguyên cho
    chart) + top_products được thay bằng ma trận hiệu suất tính từ Supabase
    (mỗi dòng chứa cả khoá cũ lẫn khoá mới -> tương thích ngược).
    Phase 3 lỗi -> trả nguyên payload cũ, dashboard không bao giờ sập."""
    data = profit.dashboard(db, current.id, days=days)
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _root = str(_Path(__file__).resolve().parents[3])
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from Phase3_Application.data_bridge.analytics_aggregator import aggregate_product_performance
        p3 = aggregate_product_performance(days=days)
        data["status"] = p3.get("status", "success")
        data["period_days"] = days
        data["range"] = p3.get("range", {})
        data["totals"] = p3.get("totals", {})
        data["top_products"] = p3.get("top_products", data.get("top_products", []))
    except Exception as exc:  # noqa: BLE001 — Phase 3 không được làm gãy UI cũ
        import logging
        logging.getLogger(__name__).warning("[Phase3] aggregator loi: %s", exc)
        data.setdefault("status", "legacy")
        data["period_days"] = days
    return data'''


def try_replace(text: str, old: str, new: str, label: str) -> str:
    """Thay old -> new đúng 1 lần; raise nếu không tìm thấy hoặc trùng lặp."""
    n = text.count(old)
    if n == 0:
        raise SystemExit(f"[LỖI] Không tìm thấy đoạn mã gốc ({label}) — file đã bị "
                         f"sửa khác bản mong đợi. KHÔNG ghi gì cả.\nTarget: {TARGET}")
    if n > 1:
        raise SystemExit(f"[LỖI] Đoạn mã ({label}) xuất hiện {n} lần — không an toàn để vá.")
    return text.replace(old, new, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Chỉ kiểm tra, không ghi file")
    args = ap.parse_args()

    if not TARGET.exists():
        raise SystemExit(f"[LỖI] Không thấy {TARGET}")
    text = TARGET.read_text(encoding="utf-8")

    if NEW_ROUTE.splitlines()[0] in text and "aggregate_product_performance" in text:
        print("[OK] dashboard.py ĐÃ được vá Phase 3 trước đó — không làm gì thêm.")
        return

    patched = try_replace(text, OLD_ROUTE, NEW_ROUTE, "route /dashboard")

    if args.check:
        print("[CHECK] Đoạn mã gốc khớp chính xác — sẵn sàng vá (chưa ghi gì).")
        return

    # Backup trước khi ghi
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"dashboard.py.{stamp}.bak"
    shutil.copy2(TARGET, backup)
    print(f"[BACKUP] {backup}")

    TARGET.write_text(patched, encoding="utf-8")
    # Kiểm tra cú pháp ngay — lỗi thì khôi phục backup tự động
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(backup, TARGET)
        raise SystemExit(f"[LỖI] File vá không compile được, ĐÃ khôi phục backup.\n{exc}")

    print(f"[OK] Đã vá {TARGET.relative_to(ROOT)}")
    print("     -> Khởi động lại backend (systemctl restart / gunicorn reload) để áp dụng.")
    print("     -> Khôi phục khi cần: python Phase3_Application/data_bridge/patch_scripts/rollback.py")


if __name__ == "__main__":
    sys.exit(main())
