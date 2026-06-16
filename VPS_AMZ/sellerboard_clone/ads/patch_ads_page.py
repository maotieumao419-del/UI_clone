"""Module ADS — patch_ads_page.py
Kích hoạt trang chỉ số ADS trên giao diện (giống patch_frontend.py, KHÔNG đụng app.js):
  1. Copy ads/render_ads.js -> frontend/render_ads.js (serve tại /static, xem backend/app/main.py).
  2. Vá frontend/index.html: chèn <script src="/static/render_ads.js"></script> NGAY SAU app.js.

render_ads.js ghi đè App.loadAmazonAds lúc runtime để gọi /api/ads/analytics/* (đọc DB)
và render thẻ KPI + bảng campaign/SKU. Độc lập với render_performance.js.

Chạy:
    cd ~/VPS_AMZ/sellerboard_clone
    python ads/patch_ads_page.py            # vá
    python ads/patch_ads_page.py --check     # chỉ kiểm tra, không ghi
"""
import argparse
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

ADS_DIR = Path(__file__).resolve().parent
ROOT = ADS_DIR.parent                                  # .../sellerboard_clone
INDEX = ROOT / "frontend" / "index.html"
JS_SRC = ADS_DIR / "render_ads.js"
JS_DST = ROOT / "frontend" / "render_ads.js"
BACKUP_DIR = ADS_DIR / "backups"

OLD_TAG = '<script src="/static/app.js"></script>'
NEW_TAG = ('<script src="/static/app.js"></script>\n'
           '  <script src="/static/render_ads.js"></script>')


def try_replace(text: str, old: str, new: str, label: str) -> str:
    """Thay old -> new đúng 1 lần; raise nếu không tìm thấy hoặc trùng lặp."""
    n = text.count(old)
    if n == 0:
        raise SystemExit(f"[LỖI] Không tìm thấy ({label}) trong {INDEX} — "
                         "file đã khác bản mong đợi. KHÔNG ghi gì cả.")
    if n > 1:
        raise SystemExit(f"[LỖI] ({label}) xuất hiện {n} lần — không an toàn để vá.")
    return text.replace(old, new, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Chỉ kiểm tra, không ghi file")
    args = ap.parse_args()

    if not INDEX.exists():
        raise SystemExit(f"[LỖI] Không thấy {INDEX}")
    if not JS_SRC.exists():
        raise SystemExit(f"[LỖI] Không thấy {JS_SRC}")

    html = INDEX.read_text(encoding="utf-8")
    already = "render_ads.js" in html

    if args.check:
        if already:
            print("[CHECK] index.html ĐÃ có render_ads.js.")
        else:
            try_replace(html, OLD_TAG, NEW_TAG, "script tag app.js")
            print("[CHECK] Thẻ script app.js khớp chính xác — sẵn sàng vá (chưa ghi gì).")
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) Copy JS (luôn cập nhật bản mới nhất; backup bản cũ nếu có)
    if JS_DST.exists():
        shutil.copy2(JS_DST, BACKUP_DIR / f"render_ads.js.{stamp}.bak")
    shutil.copy2(JS_SRC, JS_DST)
    print(f"[OK] Copy {JS_SRC.relative_to(ROOT)} -> {JS_DST.relative_to(ROOT)}")

    # 2) Chèn script tag (chỉ khi chưa có)
    if already:
        print("[OK] index.html đã có thẻ render_ads.js — bỏ qua bước chèn.")
        return
    patched = try_replace(html, OLD_TAG, NEW_TAG, "script tag app.js")
    backup = BACKUP_DIR / f"index.html.{stamp}.bak"
    shutil.copy2(INDEX, backup)
    print(f"[BACKUP] {backup}")
    INDEX.write_text(patched, encoding="utf-8")
    print(f"[OK] Đã vá {INDEX.relative_to(ROOT)} — Ctrl+F5 trên trình duyệt để thấy trang ADS mới.")


if __name__ == "__main__":
    sys.exit(main())
