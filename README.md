# SellerVision — Hệ Thống Đồng Bộ & Đối Chiếu Lợi Nhuận Amazon (Sellerboard Clone)

[![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-orange.svg)](https://supabase.com/)
[![Aesthetics](https://img.shields.io/badge/Design-Glassmorphism%20%26%20Tailwind-purple.svg)]()

> **SellerVision** là một nền tảng phân tích lợi nhuận, vận hành chuỗi cung ứng, và cảnh báo Listing dành riêng cho nhà bán hàng trên sàn thương mại điện tử Amazon. Dự án được xây dựng theo kiến trúc **Headless** (FastAPI backend cung cấp REST API + Single Page Application Frontend), hỗ trợ đồng bộ thời gian thực từ Amazon SP-API/Ads API và tích hợp công cụ đối chiếu tài chính tự động (Reconciliation Engine).

---

## 📌 Mục lục
- [✨ Tính năng nổi bật](#-tính-năng-nổi bật)
- [🛠️ Công nghệ sử dụng (Tech Stack)](#-công-nghệ-sử-dụng-tech-stack)
- [📋 Điều kiện tiên quyết (Prerequisites)](#-điều-kiện-tiên-quyết-prerequisites)
- [🚀 Hướng dẫn cài đặt từng bước (Installation & Setup)](#-hướng-dẫn-cài-đặt-từng-bước-installation--setup)
- [⚙️ Hướng dẫn cấu hình biến môi trường (Configuration)](#️-hướng-dẫn-cấu-hình-biến-môi-trường-configuration)
- [💻 Hướng dẫn vận hành & Sử dụng (Usage)](#-hướng-dẫn-vận-hành--sử-dụng-usage)
- [📁 Cấu trúc thư mục dự án (Project Structure)](#-cấu-trúc-thư-mục-dự-án-project-structure)
- [🔍 Khắc phục lỗi thường gặp (Troubleshooting)](#-khắc-phục-lỗi-thường-gặp-troubleshooting)

---

## ✨ Tính năng nổi bật

Hệ thống được thiết kế giải quyết triệt để bài toán tài chính phức tạp của Amazon FBA:

1. **Profit Analytics (Phân tích Lợi nhuận chuyên sâu)**
   - Bóc tách chi tiết: *Doanh thu (Sales) ➔ Phí Amazon (Amazon Fees) ➔ Chi phí quảng cáo (PPC) ➔ Giá vốn hàng bán (COGS) ➔ Lợi nhuận gộp (Gross Profit) ➔ Lợi nhuận ròng (Net Profit)*.
   - Hỗ trợ tính toán chỉ số tài chính chuẩn xác: **Biên lợi nhuận (Margin)**, **ROI**, và giá trị vòng đời khách hàng (**LTV Dashboard**).
   - Tích hợp biểu đồ trực quan (Chart.js) hiển thị các mốc thời gian linh hoạt.
2. **Supply Chain & Inventory (Tối ưu chuỗi cung ứng)**
   - Tính toán vận tốc bán hàng tự động dựa trên: **Trọng số thời gian gần nhất**, **Yếu tố mùa vụ (Seasonality)**, và **Mục tiêu tăng trưởng**.
   - Dự báo điểm đặt hàng lại (Reorder Point) dựa trên Lead Time (Thời gian sản xuất + Vận chuyển + Chuẩn bị) và kho đệm an toàn (Safety Stock).
3. **Automated Alerts (Giám sát Listing 24/7)**
   - Phát hiện ngay lập tức các thay đổi: *Tiêu đề, Ảnh chính, Kích thước sản phẩm, Phí giới thiệu (Referral Fee)*.
   - Cảnh báo **mất Buy Box** và phát hiện **Hijacker** xâm nhập listing.
4. **FBA Reimbursement (Hồ sơ bồi thường tự động)**
   - Tự động quét và lập hồ sơ đòi tiền hoàn cho các trường hợp: *FBA làm mất hàng, hư hỏng sản phẩm trong kho* mà Amazon chưa bồi thường.
5. **🛡️ Data Ethics Layer (Tầng Đạo đức Dữ liệu & Quyền riêng tư)**
   - Cơ chế kiểm soát quyền thu thập dữ liệu minh bạch (Meaningful Consent Portal) cho phép người dùng tùy chọn bật/tắt chia sẻ dữ liệu theo quy tắc Data Minimization.
6. **Reconciliation Engine (Bộ đối chiếu tài chính độc lập)**
   - Tự động so khớp các file báo cáo xuất ra từ API hệ thống và báo cáo của Sellerboard để chỉ ra chính xác dòng giao dịch bị lệch phí vượt quá `$0.01`.

---

## 🛠️ Công nghệ sử dụng (Tech Stack)

- **Backend:** FastAPI (Python 3.10+) + SQLAlchemy 2.0 + Pydantic v2 + Alembic (Migrations).
- **Phân tích dữ liệu:** Pandas + NumPy (Tính toán COGS FIFO, vận tốc bán có trọng số).
- **Cơ sở dữ liệu:** SQLite (mặc định cho Dev) ➔ Hỗ trợ chuyển cấu hình sang PostgreSQL (Supabase) ở Production.
- **Frontend:** Single Page Application (HTML5 + Vanilla CSS + Tailwind CSS + Chart.js) kết nối trực tiếp đến REST API.
- **Triển khai:** Docker & Docker Compose.

---

## 📋 Điều kiện tiên quyết (Prerequisites)

Trước khi bắt đầu, hãy đảm bảo máy tính của bạn đã cài đặt sẵn các công cụ sau:
1. **Python (Phiên bản từ 3.10 trở lên)**
   - Tải về tại: [python.org](https://www.python.org/downloads/)
   - Khi cài đặt trên Windows, **BẮT BUỘC** tích chọn ô `"Add Python to PATH"`.
2. **Git**
   - Tải về tại: [git-scm.com](https://git-scm.com/)
3. **Supabase Account / PostgreSQL (Tùy chọn cho Production)**
   - Đăng ký tài khoản miễn phí tại: [supabase.com](https://supabase.com/)
4. **Docker Desktop (Tùy chọn nếu muốn chạy container)**
   - Đăng ký và tải về tại: [docker.com](https://www.docker.com/products/docker-desktop/)

---

## 🚀 Hướng dẫn cài đặt từng bước (Installation & Setup)

Hãy mở terminal (PowerShell trên Windows hoặc Terminal trên macOS/Linux) và làm theo các bước sau:

### Bước 1: Tải mã nguồn dự án (Clone Repository)
```bash
git clone <url-repository-cua-ban>
cd ads-trading-system/VPS
```

### Bước 2: Tạo và kích hoạt Môi trường ảo (Virtual Environment)
Môi trường ảo giúp cô lập các thư viện của dự án, tránh xung đột hệ thống.
* **Trên Windows (PowerShell):**
  ```powershell
  cd VPS_AMZ/sellerboard_clone
  python -m venv .venv
  # Nếu gặp lỗi quyền thực thi, hãy chạy lệnh kích hoạt này:
  .\.venv\Scripts\Activate.ps1
  ```
* **Trên macOS / Linux:**
  ```bash
  cd VPS_AMZ/sellerboard_clone
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### Bước 3: Cài đặt các thư viện phụ thuộc (Dependencies)
Dự án được chia thành các phần riêng biệt, hãy cài đặt đầy đủ:
1. **Cài đặt thư viện cho Backend chính:**
   ```bash
   pip install -r backend/requirements.txt
   ```
2. **Cài đặt thư viện cho Module Ingestion (Thu thập dữ liệu):**
   ```bash
   pip install -r Phase1_Ingestion/requirements.txt
   ```

### Bước 4: Khởi tạo Cơ sở dữ liệu
* **Cách 1: Dùng SQLite (Khuyên dùng cho người mới bắt đầu chạy thử local)**
  Bạn không cần cấu hình gì thêm. SQLite sẽ tự động sinh file `sellervision.db` ngay trong thư mục khi chạy lệnh nạp dữ liệu mẫu (Seed Data) ở phần dưới.
* **Cách 2: Dùng Supabase PostgreSQL (Cho Production)**
  1. Truy cập trang quản trị dự án Supabase, mở **SQL Editor**.
  2. Copy và chạy nội dung của file SQL duy nhất trong thư mục `Phase2_Transformation/sql/`:
     - `supabase_schema.sql` (Tạo toàn bộ bảng, view, index và function cần thiết cho cả Phase 1 và Phase 2)

---

## ⚙️ Hướng dẫn cấu hình biến môi trường (Configuration)

Hệ thống nạp các thông số bảo mật và kết nối thông qua file `.env`. 

### Khởi tạo file `.env` nhanh trên Windows
Nếu chạy trên Windows, bạn có thể chạy file script PowerShell tự động điền cấu hình an toàn:
```powershell
powershell -ExecutionPolicy Bypass -File setup_env.ps1
```
Script sẽ tự động sinh mã khóa ngẫu nhiên cho bạn và tạo ra file `backend/.env`.

### Khởi tạo thủ công (Tất cả nền tảng)
1. Hãy tìm file mẫu cấu hình tại: [backend/.env.example](file:///c:/Users/nnh16/ads-trading-system/VPS/VPS_AMZ/sellerboard_clone/backend/.env.example).
2. Tạo một bản sao của file này và đặt tên là `.env` đặt tại thư mục `backend/` (`backend/.env`).
3. Điền các giá trị thích hợp vào file `.env`. Dưới đây là ý nghĩa các biến số quan trọng nhất:

| Tên biến | Giá trị mặc định | Giải thích |
|---|---|---|
| `APP_NAME` | `SellerVision` | Tên của ứng dụng. |
| `ENV` | `dev` | Chế độ chạy: `dev` (hiện tài liệu API `/docs`), `prod` (ẩn tài liệu, bảo mật cao). |
| `SECRET_KEY` | *Tự tạo ngẫu nhiên* | Khóa bí mật dùng để mã hóa mã JWT đăng nhập. Tuyệt đối giữ kín. |
| `DATABASE_URL` | `sqlite:///./sellervision.db` | Đường dẫn kết nối DB. Để mặc định để dùng SQLite. Đổi thành PostgreSQL URI khi lên Prod. |
| `PPC_DIR` | `data/ppc` | Thư mục lưu trữ các file báo cáo quảng cáo Excel người dùng upload lên. |
| `DATA_SOURCE` | `file` | Nguồn lấy số liệu: `file` (đọc file Excel tải lên), `vst` (gọi API VST), `spi` (SP-API). |
| `SELLER_TIMEZONE`| `America/Los_Angeles`| Múi giờ gốc của Amazon Marketplace (Giờ Pacific) để group số liệu chuẩn. |
| `SUPABASE_URL` | *Để trống* | URL dự án Supabase nếu bạn dùng Supabase làm Database đệm. |
| `SUPABASE_KEY` | *Để trống* | Service_role key của Supabase. |

---

## 💻 Hướng dẫn vận hành & Sử dụng (Usage)

### 1. Luồng chạy thử nhanh (Local Quickstart với SQLite)

Dành cho người mới muốn kiểm tra nhanh giao diện và tính toán mà không cần đăng ký tài khoản API Amazon:

**Bước 1: Nạp dữ liệu mẫu (Seed Data)**
Từ thư mục `VPS_AMZ/sellerboard_clone/backend`, hãy chạy:
```bash
python seed.py
```
*Lệnh này sẽ xóa DB cũ, tạo mới cấu trúc bảng SQLite và nạp 90 ngày dữ liệu đơn hàng, lô hàng, sản phẩm, và cảnh báo mẫu.*

**Bước 2: Khởi động Server**
```bash
uvicorn app.main:app --reload
```
*Màn hình hiển thị `Uvicorn running on http://127.0.0.1:8000` là bạn đã thành công!*

**Bước 3: Trải nghiệm ứng dụng**
- Truy cập Dashboard (SPA Frontend): **[http://localhost:8000/](http://localhost:8000/)**
- Tài liệu API (Swagger UI): **[http://localhost:8000/docs](http://localhost:8000/docs)** *(chỉ hiển thị ở chế độ `ENV=dev`)*
- **Tài khoản đăng nhập Demo:**
  - Email: `demo@sellervision.io`
  - Mật khẩu: `demo1234`

---

### 2. Luồng chạy Ingestion & Transformation thực tế (Production)

Khi kết nối với tài khoản Amazon thật, quy trình xử lý dữ liệu sẽ đi qua 3 giai đoạn:

```
[Amazon API] 
     │  (Giai đoạn 1: Direct-Stream API ➔ Supabase Buffer)
     ▼
[Supabase Bảng NEW_*]
     │  (Giai đoạn 2: Transform Engine tính toán COGS FIFO, múi giờ)
     ▼
[Bảng NEW_summary_*]
     │  (Giai đoạn 3: Data Bridge đồng bộ về Local SQLite & Web App hiển thị)
     ▼
[Web App Dashboard /]
```

**Lệnh chạy thu thập dữ liệu (Phase 1):**
```bash
# Thu thập tất cả dữ liệu đơn hàng, tài chính, quảng cáo 24h qua
python Phase1_Ingestion/direct_stream_pipeline.py --all

# Thu thập dữ liệu của một ngày cụ thể (theo giờ Pacific)
python Phase1_Ingestion/direct_stream_pipeline.py --all --date 2026-06-09
```

**Lệnh chạy tổng hợp KPI (Phase 2):**
```bash
# Tổng hợp dữ liệu 7 ngày qua từ bảng thô sang bảng Master KPI
python Phase2_Transformation/transform_engine.py --days 7
```

**Lệnh đồng bộ dữ liệu hiển thị (Phase 3):**
```bash
# Đồng bộ dữ liệu tổng hợp về file DB hiển thị của ứng dụng
python Phase3_Application/data_bridge/supabase_to_app_db.py --seller demo@sellervision.io --days 30
```

---

### 3. Vận hành Bộ Đối chiếu Tài chính (Reconciliation Engine)

Công cụ này giúp so khớp giữa dữ liệu thu được từ hệ thống API của bạn (file bắt đầu bằng `New_` hoặc `Summary_`) với báo cáo tải về trực tiếp từ Dashboard Sellerboard của khách hàng (file chứa chữ `Dr_Hai_` hoặc `Dashboard_`).

**Luồng dữ liệu mẫu:**
1. **Input mẫu:**
   - Đặt file báo cáo order items hệ thống: `reconciliation/data/input/New_order_items-10_06_2026.xlsx`
   - Đặt file đối chiếu Sellerboard tương ứng: `reconciliation/data/input/Dr_Hai_Craft_Dashboard_Order_Items_10_06_2026.xlsx`
2. **Khởi chạy lệnh đối chiếu:**
   ```bash
   cd reconciliation
   python reconcile.py
   ```
3. **Output kỳ vọng:**
   - Một file báo cáo tổng quan định dạng Markdown sẽ được ghi tại `reconciliation/data/output/order_items/reconciliation_summary.md` chứa bảng đối chiếu các chỉ số: *Sales, Promo, Amazon Fees, COGS, Gross Profit, Net Profit, Margin, ROI...* kèm trạng thái `✅ MATCH` hoặc `❌ MISMATCH`.
   - File `mismatch_report.csv` liệt kê chính xác các mã đơn hàng bị lệch tiền để bạn tiến hành điều tra lỗi code hoặc lỗi API.

---

## 📁 Cấu trúc thư mục dự án (Project Structure)

Dưới đây là cây thư mục rút gọn của dự án để bạn dễ dàng định vị các file quan trọng:

```
VPS/
├── VPS_AMZ/
│   └── sellerboard_clone/             # Mã nguồn cốt lõi ứng dụng SellerVision
│       ├── Phase1_Ingestion/          # Phase 1: Call API Amazon SP-API & Ads, nạp vào Supabase
│       │   ├── amz_spapi_client.py    # Client SP-API (Xử lý Auth SigV4 & phân trang)
│       │   ├── amz_ads_client.py      # Client Ads API v3
│       │   └── direct_stream_pipeline.py # Điều phối luồng Ingest chính
│       ├── Phase2_Transformation/     # Phase 2: Xử lý ETL dữ liệu thô sang Master KPI
│       │   ├── transform_engine.py    # Công cụ tổng hợp 31 chỉ số tài chính FBA
│       │   └── sql/                   # Thư mục chứa các file DDL khởi tạo DB Supabase
│       ├── Phase3_Application/        # Phase 3: Đồng bộ dữ liệu & Vá UI
│       │   ├── manage_user.py         # CLI quản trị tài khoản đăng nhập (đã di chuyển)
│       │   └── data_bridge/           # Công cụ Data Bridge và vá UI
│       │       ├── analytics_aggregator.py # Module tổng hợp tài chính hiệu suất sản phẩm (đã di chuyển)
│       │       ├── supabase_dashboard.py # Xử lý dữ liệu KPI từ Supabase
│       │       ├── supabase_to_app_db.py # Đồng bộ Supabase -> SQLite
│       │       └── patch_scripts/     # Các script vá tự động (patch_dashboard.py, patch_frontend.py, rollback.py)
│       ├── backend/                   # Backend FastAPI Production (Chạy chính trên VPS)
│       │   ├── app/
│       │   │   ├── main.py            # File chạy chính (Entry Point) kết nối Router & SPA UI
│       │   │   ├── config.py          # Đọc và validate cấu hình từ file .env
│       │   │   ├── database.py        # Cấu hình SQLAlchemy Engine & Connection Session
│       │   │   ├── models/            # Các Model định nghĩa cấu trúc bảng Database
│       │   │   ├── routers/           # Các endpoints API (dashboard, auth, alerts...)
│       │   │   └── services/          # Logic nghiệp vụ (Tính Profit, tính toán Inventory...)
│       │   ├── seed.py                # File tạo dữ liệu Mock local
│       │   └── requirements.txt       # Danh sách thư viện Python cho backend
│       ├── frontend/                  # Frontend SPA Dashboard tĩnh
│       │   ├── index.html             # Giao diện SPA Dashboard
│       │   └── app.js                 # Xử lý logic gọi API REST & vẽ biểu đồ Chart.js
│       ├── Dockerfile                 # File cấu hình đóng gói container Docker ứng dụng
│       ├── docker-compose.yml         # File điều phối chạy ứng dụng & DB PostgreSQL
│       └── setup_env.ps1              # Script PowerShell tạo file .env tự động
├── reconciliation/                    # Bộ đối chiếu dữ liệu tài chính Excel độc lập
│   ├── reconcile.py                   # File chạy đối chiếu so khớp
│   └── data/
│       ├── input/                     # Chứa các file Excel đầu vào để đối chiếu
│       └── output/                    # Kết quả đối chiếu (summary.md & mismatch.csv)
└── HUONG_DAN_CHAY.md                  # Tài liệu hướng dẫn vận hành chi tiết các scripts
```

---

## 🔍 Khắc phục lỗi thường gặp (Troubleshooting)

### 1. Lệch số liệu Sales/Profit theo ngày (Timezone Misalignment)
* **Triệu chứng:** Biểu đồ doanh thu hoặc số lượng đơn hàng trên Dashboard bị lệch so với Sellerboard từ vài đơn đến cả ngàn đô vào thời điểm đầu/cuối ngày.
* **Nguyên nhân:** Amazon API trả ngày giờ dạng giờ UTC. Nếu server chạy giờ Việt Nam (UTC+7) hoặc hiển thị theo giờ mặc định của máy khách, số liệu sẽ bị dồn sai ngày.
* **Cách sửa:** Đảm bảo cấu hình biến `SELLER_TIMEZONE=America/Los_Angeles` trong `.env`. Trong code xử lý dữ liệu và SQL, luôn chuyển đổi múi giờ từ UTC sang Pacific trước khi lấy `.date()`:
  ```sql
  -- Công thức ép múi giờ chuẩn trong Postgres:
  (purchase_date AT TIME ZONE 'UTC' AT TIME ZONE 'America/Los_Angeles')::date
  ```

### 2. Phí Amazon Fees hiển thị bằng 0 hoặc quá thấp
* **Triệu chứng:** Biểu đồ Gross Profit quá cao do cột Amazon Fees bị trống hoặc chỉ có giá trị ước lượng.
* **Nguyên nhân:** Amazon chỉ tạo bản ghi phí thật (Settled Fees) từ Finances API **sau 1-5 ngày** khi đơn hàng đã thực sự được đóng gói và vận chuyển. Nếu chạy ingestion khớp đúng 1 ngày, hệ thống sẽ không tìm thấy phí cho các đơn mới tạo.
* **Cách sửa:** Đảm bảo biến `FINANCES_WINDOW_DAYS` trong cấu hình tối thiểu là `21` ngày. Công cụ thu thập dữ liệu sẽ tự động lấy dữ liệu tài chính mở rộng về tương lai để cập nhật bù phí thật (True-up) cho các đơn hàng cũ.

### 3. Lỗi `ModuleNotFoundError: No module named '...'`
* **Triệu chứng:** Terminal báo lỗi thiếu thư viện khi chạy `python seed.py` hoặc `uvicorn app.main:app`.
* **Nguyên nhân:** Chưa kích hoạt môi trường ảo `.venv` hoặc chưa cài đặt thư viện từ file `requirements.txt`.
* **Cách sửa:** Hãy chắc chắn bạn đã chạy lệnh kích hoạt môi trường ảo (ví dụ: `.\.venv\Scripts\Activate.ps1` trên Windows) và chạy lệnh cài đặt:
  ```bash
  pip install -r backend/requirements.txt
  ```

### 4. Lỗi `403 Forbidden` khi kết nối Amazon SP-API
* **Triệu chứng:** Khi đồng bộ dữ liệu, server trả về lỗi `Access to requested resource is denied` hoặc lỗi phân quyền AWS.
* **Nguyên nhân:** AWS IAM Role hoặc AWS STS cấu hình không chính xác, hoặc App ID trên Amazon Partner Network chưa được cấp quyền tương ứng (Orders/Finance Roles).
* **Cách sửa:** Kiểm tra kỹ `AWS_ROLE_ARN` trong file `.env`. Đảm bảo tài khoản AWS của bạn đã thực hiện assume role chính xác và User IAM có quyền gọi STS.

---

Chúc bạn có trải nghiệm tuyệt vời khi vận hành **SellerVision**! Nếu bạn gặp bất kỳ khó khăn nào trong quá trình cài đặt, hãy đọc kỹ tài liệu [HUONG_DAN_CHAY.md](file:///c:/Users/nnh16/ads-trading-system/VPS/HUONG_DAN_CHAY.md) hoặc kiểm tra log lỗi hiển thị tại terminal. Cùng xây dựng hệ thống phân tích tài chính Amazon thông minh và minh bạch dữ liệu!
"# UI_clone" 
