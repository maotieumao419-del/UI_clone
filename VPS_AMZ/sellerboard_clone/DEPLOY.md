# Hướng dẫn đưa SellerVision lên domain

> Một **domain** (tencuaban.com) chỉ là tên miền — bạn vẫn cần **nơi chạy server**
> (VPS hoặc nền tảng PaaS). Dưới đây là 3 cách phổ biến. Sau khi server chạy, bạn
> trỏ DNS bản ghi **A** của domain về **IP server** (hoặc CNAME nếu PaaS yêu cầu).

## Những gì đã chỉnh để chạy trên domain (đầu vào / đầu ra)
- **Đầu vào (input):** mọi cấu hình nhạy cảm đọc từ ENV (`SECRET_KEY`, `DATABASE_URL`,
  `CORS_ORIGINS`, `ALLOWED_HOSTS`). File PPC **không còn dùng đường dẫn `E:\...`** —
  thay bằng **upload qua web** (nút *⬆ Tải file PPC lên*) lưu vào `PPC_DIR` (`data/ppc`).
- **Đầu ra (output):** bind `0.0.0.0` + `PORT` từ ENV; tin cậy header HTTPS sau reverse
  proxy (`--forwarded-allow-ips=*`); CORS/Host giới hạn theo domain; ẩn `/docs` khi `ENV=prod`;
  frontend gọi API theo `location.origin` (tự khớp domain) — hoặc `window.SV_API_BASE`.

Trước khi deploy: tạo `backend/.env` từ `backend/.env.example` và đổi `SECRET_KEY`,
`CORS_ORIGINS`, `ALLOWED_HOSTS` thành domain của bạn.

---

## ⭐ Cách dành cho cPanel / StableHost (host của bạn) — SQLite

cPanel chạy app Python qua **"Setup Python App" (Phusion Passenger, giao thức WSGI)**.
FastAPI là ASGI nên dự án đã có sẵn **`backend/passenger_wsgi.py`** (bọc bằng `a2wsgi`)
— file này là điểm vào cho Passenger. **Không dùng** Docker/gunicorn/systemd ở đây.

**Bước 1 — Đưa code lên host**
- Nén dự án thành .zip → **cPanel → File Manager** → upload vào home (vd `~/sellervision`) → Extract.
  Kết quả: `~/sellervision/backend` và `~/sellervision/frontend`.
- (Hoặc dùng **cPanel → Git Version Control** clone repo về.)

**Bước 2 — Tạo Python App**
- **cPanel → Setup Python App → Create Application**:
  - *Python version*: 3.12 (hoặc cao nhất có; ≥3.10 là chạy được).
  - *Application root*: `sellervision/backend`
  - *Application URL*: chọn domain/subdomain bạn muốn (vd `app.tencuaban.com`).
  - *Application startup file*: `passenger_wsgi.py`
  - *Application Entry point*: `application`
  - Create.

**Bước 3 — Cài thư viện**
- Trong trang app vừa tạo, mục *Configuration files* điền `requirements.txt` → **Run Pip Install**.
  (Hoặc copy dòng *"Enter to the virtual environment"* cPanel hiển thị, chạy trong Terminal:
  `pip install -r requirements.txt`.)

**Bước 4 — Biến môi trường** (mục *Environment variables* trong trang app), thêm:
- `SECRET_KEY` = chuỗi ngẫu nhiên (bắt buộc) · `ENV` = `prod`
- `ALLOWED_HOSTS` = `app.tencuaban.com` · `CORS_ORIGINS` = `https://app.tencuaban.com`
- (SQLite mặc định — không cần `DATABASE_URL`.)
- Bấm **Restart** ứng dụng.

**Bước 5 — HTTPS & domain**
- **cPanel → SSL/TLS Status → Run AutoSSL** để cấp chứng chỉ Let's Encrypt cho domain.
- Mở `https://app.tencuaban.com` → đăng nhập, vào **🎯 PPC_LHHKMT → ⬆ Tải file PPC lên**.

**Lưu ý shared hosting:**
- File `sellervision.db` (SQLite) và `data/ppc/` tự tạo trong `backend/` — ghi được, dữ liệu giữ nguyên.
- Mỗi lần đổi code: bấm **Restart** trong Setup Python App (hoặc `touch tmp/restart.txt`).
- Nếu upload file PPC bị chặn dung lượng: thêm vào `backend/.htaccess` dòng `LimitRequestBody 31457280` (30MB).
- `pip install pandas/numpy` cần đủ RAM; nếu lỗi memory, liên hệ StableHost xin tăng giới hạn hoặc cài lần lượt.
- Tác vụ nền (Celery cho Amazon SP-API sau này) **không chạy** trên shared hosting — khi cần sẽ phải lên VPS.

---

## (Tham khảo) Cách 1 — Docker (khuyến nghị, chạy mọi VPS có Docker)
```bash
git clone <repo> sellervision && cd sellervision
cp backend/.env.example backend/.env && nano backend/.env   # đổi SECRET_KEY, domain...
docker compose up -d --build
```
App chạy ở cổng 8000. Đặt Nginx phía trước để gắn domain + HTTPS:
```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/sellervision
sudo ln -s /etc/nginx/sites-available/sellervision /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d tencuaban.com         # cấp SSL miễn phí (Let's Encrypt)
```

## Cách 2 — VPS Linux không Docker (systemd + Nginx)
```bash
sudo apt install python3.12-venv nginx
cd /var/www/sellervision/backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env
sudo cp ../deploy/sellervision.service.example /etc/systemd/system/sellervision.service
sudo systemctl daemon-reload && sudo systemctl enable --now sellervision
# rồi cấu hình Nginx + certbot như Cách 1
```

## Cách 3 — PaaS (Render / Railway / Fly.io) — không cần quản lý server
- Push code lên GitHub, tạo service mới từ repo.
- Nền tảng tự nhận **Dockerfile** (hoặc **Procfile**).
- Khai báo biến môi trường trong dashboard: `SECRET_KEY`, `CORS_ORIGINS`,
  `ALLOWED_HOSTS`, `ENV=prod`, và `DATABASE_URL` (nếu dùng Postgres của nền tảng).
- Thêm **custom domain** trong dashboard rồi trỏ DNS theo hướng dẫn của nền tảng.
- Lưu ý: ổ đĩa PaaS thường **tạm thời** → dùng **PostgreSQL** cho CSDL và
  cân nhắc lưu file PPC ở object storage (S3) nếu cần giữ lâu dài.

---

## Sau khi deploy
1. Mở `https://tencuaban.com` → đăng nhập (tạo tài khoản qua *Tạo tài khoản mới*).
2. Vào **🎯 PPC_LHHKMT** → bấm **⬆ Tải file PPC lên** để nạp dữ liệu (mỗi file = 1 store).
3. (Nếu muốn dữ liệu demo dashboard) chạy 1 lần: `python seed.py`.

## Khuyến nghị production
- **Đổi `SECRET_KEY`** và **không để `CORS_ORIGINS=*`**.
- Dùng **PostgreSQL** thay SQLite khi có >1 worker.
- Sao lưu định kỳ thư mục `data/ppc` và CSDL.
- Đặt `WEB_CONCURRENCY` = 2×số CPU + 1.
