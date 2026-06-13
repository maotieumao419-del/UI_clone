# Phase3_Application / sellerboard_clone — Web App Core

Theo blueprint 3 giai đoạn, thư mục này là vị trí của **mã nguồn vận hành
ứng dụng Web** (FastAPI backend + frontend Vanilla JS/Tailwind/Chart.js).

## ⚠️ Vì sao thư mục này chỉ chứa README

Mã nguồn web app **đang chạy Production** tại `app.tap2soul.com` hiện nằm ở
thư mục gốc repo:

| Khối | Vị trí thật (Production) |
|---|---|
| Backend (FastAPI, Routers, JWT Auth) | `../../backend/` |
| Frontend (HTML/JS/Tailwind/Chart.js) | `../../frontend/` |
| Database hiển thị | `../../sellervision.db` |

Nguyên tắc kỷ luật triển khai **cấm can thiệp thủ công vào file gốc đang
chạy Production** — bao gồm cả việc DI CHUYỂN vật lý 2 thư mục trên (đường
dẫn được hard-code trong systemd unit / gunicorn / Dockerfile / nginx).
Việc di chuyển vật lý vào đây là một bước vận hành (ops) riêng, chỉ thực
hiện khi có kế hoạch downtime và cập nhật đồng bộ toàn bộ cấu hình deploy.

## Cách tích hợp hiện tại (không cần di chuyển)

Mọi thay đổi lên web app đi qua `../data_bridge/`:

- `data_bridge/supabase_to_app_db.py` — đồng bộ dữ liệu sạch từ Supabase
  vào `sellervision.db` (savepoint từng đơn, strict seller mapping).
- `data_bridge/patch_scripts/` — vá `dashboard.py` / `index.html` bằng
  cơ chế `try_replace` + backup + rollback (không sửa tay file gốc).
