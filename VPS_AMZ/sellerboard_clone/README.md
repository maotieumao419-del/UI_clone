# SellerVision — Clone Sellerboard bằng Python

Nền tảng phân tích lợi nhuận & vận hành cho người bán Amazon, xây dựng theo
**kiến trúc Headless** (FastAPI backend + REST API + SPA dashboard). Dùng chung
một nguồn dữ liệu (single source of truth) cho cả Web và Mobile App.

## Tính năng đã có

| Mô-đun | Nội dung |
|--------|----------|
| **1. Profit Analytics** | Bóc tách Doanh thu − Phí Amazon − COGS (FIFO) − PPC → Lợi nhuận ròng, biên LN, ROI. Dashboard KPI + biểu đồ. |
| **LTV Dashboard** | Giá trị vòng đời khách hàng, tỷ lệ mua lại. |
| **BSR Monitor** | So sánh BSR hiện tại với trung bình tuần/tháng. |
| **Đa nền tảng** | Hợp nhất doanh thu Amazon / Shopify / Walmart / eBay. |
| **2. Supply Chain** | Vận tốc bán **có trọng số thời gian** + **mùa vụ** + **tăng trưởng mục tiêu** + **lead time & đệm an toàn** → điểm đặt hàng lại & số lượng nên nhập. |
| **3. Alerts** | Giám sát listing 24/7: đổi tiêu đề/ảnh/kích thước/phí, **mất Buy Box**, **hijacker**. |
| **Reimbursements** | Tự sinh hồ sơ bồi thường (hoàn tiền không trả hàng, FBA mất/hư). |
| **🛡️ Lớp Đạo đức Dữ liệu** | Cổng minh bạch, đồng ý theo từng mục (meaningful choice), Data Minimization. **Điểm khác biệt cốt lõi.** |

## Tech Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 + Pydantic v2
- **Analytics:** Pandas + NumPy (COGS FIFO, vận tốc bán có trọng số)
- **Auth:** JWT (PyJWT) + PBKDF2 (stdlib)
- **DB:** SQLite mặc định → đổi sang PostgreSQL khi production
- **Frontend:** SPA (HTML + Tailwind + Chart.js) — gọi REST API

## Chạy thử (Windows / PowerShell)

```powershell
cd backend
# Tạo môi trường ảo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Tạo dữ liệu mẫu
python seed.py

# Khởi động server (API + UI)
uvicorn app.main:app --reload
```

Mở trình duyệt:
- **Giao diện:** http://localhost:8000/
- **Tài liệu API tự động:** http://localhost:8000/docs

Đăng nhập demo: `demo@sellervision.io` / `demo1234`

## Lộ trình nâng cấp lên production (theo Structure.md)
1. **PostgreSQL** cho dữ liệu giao dịch + **MongoDB (Motor)** cho listing/log.
2. **Redis** cache + **Celery + RabbitMQ/Redis** cho đồng bộ Amazon SP-API (rate-limit nghiêm ngặt) chạy ngầm.
3. **Alembic** cho migration thay cho `create_all`.
4. Tách frontend thành **React/Next.js (web)** + **React Native/Flutter (app)** dùng chung REST API.
5. **Trình tối ưu PPC** tự điều chỉnh bid theo ACOS mục tiêu.

## Cấu trúc thư mục
```
backend/
  app/
    main.py            # điểm vào, gắn router + phục vụ SPA
    config.py          # cấu hình (env)
    database.py        # engine SQLAlchemy
    deps.py            # dependency auth
    core/security.py   # JWT + băm mật khẩu
    models/            # bảng ORM
    schemas/           # Pydantic (hợp đồng API)
    services/          # logic: profit, inventory, alerts
    routers/           # endpoint REST
  seed.py              # dữ liệu mẫu
frontend/
  index.html, app.js   # SPA dashboard
```
