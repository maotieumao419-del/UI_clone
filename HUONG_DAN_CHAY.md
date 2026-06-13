# Hướng dẫn chạy — Vận hành Hệ thống 3 Giai đoạn (Phase 1, 2, 3)

Tài liệu này hướng dẫn chi tiết cách chạy hệ thống thu thập, xử lý và tích hợp dữ liệu SellerVision (bao gồm Phase 1 Ingestion, Phase 2 Transformation, và Phase 3 Application Bridge).

---

## Mục lục
1. [Phase 1: Thu thập dữ liệu (Ingestion)](#phase-1-thu-thập-dữ-liệu-ingestion)
2. [Phase 2: Biến đổi dữ liệu (Transformation)](#phase-2-biến-đổi-dữ-liệu-transformation)
3. [Phase 3: Tích hợp ứng dụng & Vá UI (Application & Patch)](#phase-3-tích-hợp-ứng-dụng--vá-ui-application--patch)
4. [Khắc phục lỗi thường gặp](#khắc-phục-lỗi-thường-gặp)

---

## Chuẩn bị môi trường chung (chỉ làm 1 lần)

Đảm bảo bạn đang ở thư mục gốc của dự án (`VPS/VPS_AMZ/sellerboard_clone`) và môi trường ảo `.venv` đã được kích hoạt:

* **Windows (PowerShell):**
  ```powershell
  cd C:\Users\nnh16\ads-trading-system\VPS\VPS_AMZ\sellerboard_clone
  .\.venv\Scripts\Activate.ps1
  ```
* **macOS / Linux:**
  ```bash
  cd ~/ads-trading-system/VPS/VPS_AMZ/sellerboard_clone
  source .venv/bin/activate
  ```

---

## Phase 1: Thu thập dữ liệu (Ingestion)

Phase 1 thực hiện kéo dữ liệu thô từ Amazon SP-API và Ads API, sau đó đẩy trực tiếp thành các dòng đệm trên Supabase (bảng `NEW_*`).

### 1. Cấu hình credentials
Sao chép file cấu hình mẫu và điền đầy đủ thông tin tài khoản API:
- File mẫu: `Phase1_Ingestion/.env.example`
- File cấu hình thật: tạo file `.env` nằm tại thư mục `Phase1_Ingestion/` (`Phase1_Ingestion/.env`)

### 2. Khởi chạy bằng dòng lệnh (Terminal)
Từ thư mục `VPS_AMZ/sellerboard_clone/`:

```bash
# Thu thập tất cả dữ liệu (Orders, Finances, Ads) trong 24 giờ qua
python Phase1_Ingestion/direct_stream_pipeline.py --all

# Thu thập dữ liệu của một ngày cụ thể (theo giờ Pacific của Seller Central)
python Phase1_Ingestion/direct_stream_pipeline.py --all --date 2026-06-09
```

### 3. Tìm profile quảng cáo (ADS_PROFILE_ID)
Nếu biến `ADS_PROFILE_ID` trong `.env` đang trống, hãy khởi chạy script Ads:
```bash
python Phase1_Ingestion/direct_stream_pipeline.py --ads
```
Hệ thống sẽ liệt kê các `profileId` khả dụng trên màn hình. Hãy copy `profileId` tương ứng với tài khoản Seller bán hàng của bạn và dán vào file `.env`.

### 4. Vận hành nhanh trên Windows
Bạn chỉ cần click đúp vào file `Phase1_Ingestion/start.bat`. Cửa sổ console sẽ mở ra và tự động hỏi bạn muốn chạy kéo dữ liệu cho "24 giờ qua" hay chọn "một ngày cụ thể".

### 5. Dọn dẹp & loại bỏ trùng lặp (Buffer Cleanup)
Hệ thống tự động gom nhóm và loại bỏ các dòng bị trùng lặp ngay sau khi ingest. Bạn có thể tự kích hoạt quy trình này thủ công bằng lệnh:
```bash
python Phase1_Ingestion/process_buffer_cleanup.py
```

---

## Phase 2: Biến đổi dữ liệu (Transformation)

Phase 2 biến đổi dữ liệu thô từ các bảng đệm `NEW_*` thành các chỉ số tài chính FBA (Master KPI) và lưu vào bảng tổng hợp `NEW_summary_*` trên Supabase.

### 1. Nhập bảng giá vốn sản phẩm (COGS)
Để hệ thống tính toán chính xác biên lợi nhuận và giá vốn hàng bán, hãy nhập file CSV chứa giá vốn (COGS) được xuất từ Sellerboard:
```bash
python Phase2_Transformation/import_cogs_from_csv.py "đường/dẫn/đến/file_products.csv"
```

### 2. Khởi chạy công cụ biến đổi dữ liệu (ETL Engine)
Từ thư mục `VPS_AMZ/sellerboard_clone/`:

```bash
# Tổng hợp dữ liệu hiệu suất của 7 ngày gần nhất và ghi vào Supabase
python Phase2_Transformation/transform_engine.py --days 7

# Chạy thử nghiệm (Dry-run) - chỉ in kết quả JSON ra màn hình chứ không ghi vào cơ sở dữ liệu
python Phase2_Transformation/transform_engine.py --days 7 --no-write --json
```

---

## Phase 3: Tích hợp ứng dụng & Vá UI (Application & Patch)

Phase 3 đồng bộ dữ liệu KPI từ Supabase về SQLite local của Web App (`sellervision.db`), đồng thời cung cấp các công cụ vá lỗi giao diện để hiển thị bảng hiệu suất sản phẩm mới.

### 1. Đồng bộ cơ sở dữ liệu về Web App (Bridge)
Đồng bộ các dòng tổng hợp từ Supabase về cơ sở dữ liệu SQLite cục bộ để phục vụ hiển thị trên giao diện:
```bash
# Đồng bộ dữ liệu của tài khoản email demo cho 30 ngày gần nhất
python Phase3_Application/data_bridge/supabase_to_app_db.py --seller demo@sellervision.io --days 30
```

### 2. Quản trị tài khoản người dùng bằng dòng lệnh (CLI)
Do hệ thống backend không mở public API đổi mật khẩu, bạn quản trị tài khoản trực tiếp trên VPS qua file CLI:
```bash
# Xem danh sách người dùng hiện có
python Phase3_Application/manage_user.py --list

# Tạo tài khoản mới
python Phase3_Application/manage_user.py --create --email user@test.com --password mysecurepassword

# Thay đổi mật khẩu người dùng hiện có (vẫn giữ nguyên ID và dữ liệu cũ)
python Phase3_Application/manage_user.py --set --email demo@sellervision.io --password newpassword
```

### 3. Kích hoạt bảng hiệu suất sản phẩm mới (Patch Scripts)
Sử dụng các script vá tự động để chèn mã vẽ bảng tài chính chuẩn Sellerboard vào FastAPI backend và SPA Frontend:

* **Bước 1: Chạy thử kiểm tra (Dry-run)**
  ```bash
  python Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py --check
  python Phase3_Application/data_bridge/patch_scripts/patch_frontend.py --check
  ```
  *Màn hình hiển thị "khớp chính xác - sẵn sàng vá" là an toàn.*

* **Bước 2: Thực hiện vá thực tế (Tự động sao lưu và biên dịch thử)**
  ```bash
  python Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py
  python Phase3_Application/data_bridge/patch_scripts/patch_frontend.py
  ```

* **Bước 3: Khởi động lại ứng dụng**
  Sau khi chạy thành công, hãy khởi động lại service backend (vd: reload gunicorn hoặc restart uvicorn) và bấm **Ctrl + F5** trên trình duyệt để trải nghiệm giao diện bảng hiệu suất sản phẩm mới.

### 4. Khôi phục trạng thái ban đầu (Rollback)
Nếu muốn gỡ bỏ hoàn toàn bảng hiệu suất và khôi phục các file code nguyên bản của web app:
```bash
python Phase3_Application/data_bridge/patch_scripts/rollback.py
```
*Script sẽ tự động tìm bản sao lưu gần nhất trong thư mục backups/ để ghi đè trả lại file gốc.*

---

## Khắc phục lỗi thường gặp

### 1. Lỗi `ModuleNotFoundError: No module named '...'`
- **Cách sửa:** Đảm bảo bạn đã kích hoạt môi trường ảo `.venv` và cài đặt đầy đủ dependencies bằng lệnh:
  ```bash
  pip install -r backend/requirements.txt
  pip install -r Phase1_Ingestion/requirements.txt
  ```

### 2. Lệch số liệu so với Amazon Seller Central
- **Cách sửa:** Do Amazon tính theo giờ Pacific (`America/Los_Angeles`). Hãy kiểm tra xem file `.env` của bạn đã cấu hình múi giờ chuẩn chưa: `SELLER_TIMEZONE=America/Los_Angeles`. Tuyệt đối không dùng múi giờ local của server hoặc trình duyệt client khi group theo ngày.

### 3. Lỗi 403 khi kết nối SP-API
- **Cách sửa:** Kiểm tra kỹ cấu hình `AWS_ROLE_ARN` trong file `Phase1_Ingestion/.env`. Đảm bảo tài khoản AWS của bạn có quyền assume role và đã cấu hình chính xác Orders/Finance Roles trên cổng Amazon Partner Network.
