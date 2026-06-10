# Hướng dẫn chạy — API Debug Scripts

---

## Phần 1: Chạy bằng Terminal (PowerShell)

### Bước 0 — Chuẩn bị môi trường (chỉ làm 1 lần)

Mở **PowerShell** (không cần Admin), chạy theo thứ tự:

```powershell
# Vào đúng thư mục chứa code
cd C:\Users\nnh16\ads-trading-system\test_lwa_spapi

# Cài thư viện cần thiết
pip install requests python-dotenv
```

Kiểm tra nhanh:
```powershell
python --version
# Phải ra: Python 3.x.x
```

---

### Bước 1 — Điền credentials vào .env

File `.env` nằm tại:
```
C:\Users\nnh16\ads-trading-system\test_lwa_spapi\.env
```

Mở bằng Notepad hoặc VS Code, kiểm tra các dòng này đã có giá trị chưa:

```
AMAZON_SPI_CLIENT_ID=<đã điền chưa?>
AMAZON_SPI_CLIENT_SECRET=<đã điền chưa?>
AMAZON_SPI_REFRESH_TOKEN=<đã điền chưa?>
AMAZON_SPI_MARKETPLACE_ID=ATVPDKIKX0DER

AWS_ACCESS_KEY_ID=<đã điền chưa?>
AWS_SECRET_ACCESS_KEY=<đã điền chưa?>
AWS_ROLE_ARN=arn:aws:iam::...:role/...
AWS_REGION=us-east-1

AMAZON_ADS_REFRESH_TOKEN=      ← thêm mới (thường giống SP refresh token)
ADS_PROFILE_ID=                ← thêm mới (xem Bước 2b bên dưới)
```

> **Lưu ý:** `AMAZON_ADS_REFRESH_TOKEN` thường CÙNG giá trị với `AMAZON_SPI_REFRESH_TOKEN`
> nếu bạn tạo cùng 1 app có cả 2 scope SP + Ads.

---

### Bước 2a — Chạy từng script riêng lẻ

Tất cả lệnh đều chạy từ thư mục:
```
C:\Users\nnh16\ads-trading-system\test_lwa_spapi\
```

```powershell
# Vào thư mục (CHỈ cần làm 1 lần mỗi phiên terminal)
cd C:\Users\nnh16\ads-trading-system\test_lwa_spapi

# Script 1: Lấy Orders + OrderItems 24h gần nhất
python fetch_24h_orders.py

# Script 2: Lấy Financial Events 24h (phí FBA, referral, refund)
python fetch_24h_finances.py

# Script 3: Lấy Ads Reports ngày hôm qua (SP + SB + SBV + SD)
python fetch_24h_ads.py

# Hoặc chạy cả 3 cùng lúc theo thứ tự:
python run_all.py
```

---

### Bước 2b — Lần đầu chạy Ads: tìm ADS_PROFILE_ID

Nếu `ADS_PROFILE_ID` trong `.env` đang trống, chạy:

```powershell
cd C:\Users\nnh16\ads-trading-system\test_lwa_spapi
python fetch_24h_ads.py
```

Script sẽ tự động in ra danh sách profiles khi profile_id trống:
```
  Tìm thấy 2 profiles:
    profileId=1234567890  marketplace=US  type=seller  name=Musemory
    profileId=9876543210  marketplace=US  type=vendor  name=...
```

Sao chép `profileId` của seller account (type=seller) → dán vào `.env`:
```
ADS_PROFILE_ID=1234567890
```

Rồi chạy lại:
```powershell
python fetch_24h_ads.py
```

---

### Bước 3 — Xem kết quả

Sau khi chạy xong, các file output nằm tại:
```
C:\Users\nnh16\ads-trading-system\test_lwa_spapi\raw_data\
```

| File | Nội dung | Mở bằng |
|---|---|---|
| `orders_24h_raw.json` | Toàn bộ đơn hàng thô từ Amazon | VS Code / Notepad++ |
| `fields_map.txt` | Danh sách tất cả field Orders API trả về | Notepad |
| `finances_24h_raw.json` | Toàn bộ financial events thô | VS Code |
| `finances_summary.txt` | Tổng tiền từng loại phí — SO SÁNH VỚI SELLERBOARD | Notepad |
| `finances_fields_map.txt` | Danh sách field Finances API | Notepad |
| `ads_sp_raw.json` | Sponsored Products report thô | VS Code |
| `ads_sb_raw.json` | Sponsored Brands + SBV report thô | VS Code |
| `ads_sd_raw.json` | Sponsored Display report thô | VS Code |
| `ads_sp_asin_raw.json` | SP report chi tiết theo ASIN/SKU | VS Code |
| `ads_summary.txt` | Tổng spend từng loại — SO SÁNH VỚI SELLERBOARD | Notepad |
| `ads_fields_map.txt` | Danh sách field Ads API | Notepad |

---

### Lỗi thường gặp khi chạy terminal

| Lỗi | Nguyên nhân | Cách sửa |
|---|---|---|
| `ModuleNotFoundError: requests` | Chưa cài thư viện | `pip install requests python-dotenv` |
| `❌ Thiếu credentials` | .env chưa điền đủ | Mở .env, điền các giá trị còn trống |
| `403 Forbidden` từ SP-API | STS role sai hoặc LWA-only | Kiểm tra `AWS_ROLE_ARN` trong .env |
| `❌ Thiếu ADS_PROFILE_ID` | Chưa điền profile | Chạy script → đọc output → copy profileId vào .env |
| `TimeoutError` khi poll Ads | Amazon chậm generate report | Chờ 5-10 phút, chạy lại |
| `python` không nhận lệnh | Python chưa cài hoặc không trong PATH | Thử `python3` hoặc cài Python từ python.org |

---

## Phần 2: Chạy bằng Code Python (không cần gõ terminal)

### Ý tưởng

Thay vì mở terminal và gõ lệnh, bạn tạo 1 file `.py` bấm Run trong IDE
(VS Code, PyCharm) hoặc double-click — nó sẽ tự làm tất cả.

---

### File: `start.py` — bấm Run 1 cái, chạy hết

Tạo file `start.py` trong thư mục `test_lwa_spapi\`:

```python
"""
Bấm Run file này trong VS Code hoặc PyCharm là xong.
Không cần mở terminal, không cần gõ lệnh.
"""
import subprocess
import sys
import os

# Tự động cd vào đúng thư mục chứa script
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

SCRIPTS = [
    "fetch_24h_orders.py",
    "fetch_24h_finances.py",
    "fetch_24h_ads.py",
]

for script in SCRIPTS:
    print(f"\n{'='*50}")
    print(f"Đang chạy: {script}")
    print(f"{'='*50}")
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print(f"❌ {script} có lỗi. Nhấn Enter để chạy tiếp...")
        input()

print("\n✅ Xong. Xem kết quả trong thư mục raw_data/")
input("Nhấn Enter để đóng...")
```

> **Chạy trong VS Code:** mở file `start.py` → nhấn nút ▶ Run ở góc trên phải
> **Chạy bằng double-click:** đổi tên thành `start.bat` (xem bên dưới)

---

### File: `start.bat` — double-click để chạy (Windows)

Tạo file `start.bat` trong thư mục `test_lwa_spapi\`:

```batch
@echo off
cd /d C:\Users\nnh16\ads-trading-system\test_lwa_spapi
echo ========================================
echo  SELLERBOARD API DEBUG - START
echo ========================================

echo.
echo [1/3] Orders...
python fetch_24h_orders.py
if %errorlevel% neq 0 (
    echo FAILED: fetch_24h_orders.py
    pause
    exit /b 1
)

echo.
echo [2/3] Finances...
python fetch_24h_finances.py
if %errorlevel% neq 0 (
    echo FAILED: fetch_24h_finances.py
    pause
    exit /b 1
)

echo.
echo [3/3] Ads Reports...
python fetch_24h_ads.py
if %errorlevel% neq 0 (
    echo FAILED: fetch_24h_ads.py
    pause
)

echo.
echo ========================================
echo  XONG. Ket qua trong thu muc raw_data/
echo ========================================
pause
```

**Cách dùng:** Double-click vào file `start.bat` → cửa sổ CMD tự mở → tự chạy → hiện kết quả.

---

### Cách các script hoạt động bên trong

```
fetch_24h_orders.py
│
├── 1. Đọc credentials từ .env
├── 2. Gọi LWA → lấy access_token (hết hạn sau 1h)
├── 3. Gọi STS → assume role → lấy temp AWS credentials (cho SigV4)
├── 4. Loop: GET /orders/v0/orders (mỗi trang 100 đơn, có NextToken)
│         + GET /orders/v0/orders/{id}/orderItems (mỗi đơn 1 lần gọi)
│         + sleep 1s giữa các lần gọi (tránh bị rate limit)
└── 5. Lưu raw JSON + fields map vào raw_data/

fetch_24h_finances.py
│
├── 1-3. Auth giống trên
├── 4. Loop: GET /finances/v0/financialEvents (pagination NextToken)
│         — lấy ShipmentEventList, RefundEventList,
│           AdjustmentEventList, ServiceFeeEventList
└── 5. Tính tổng từng loại phí + lưu summary + raw JSON

fetch_24h_ads.py
│
├── 1. Đọc credentials từ .env
├── 2. Gọi LWA cho Ads token (KHÔNG cần AWS SigV4)
├── 3. Gửi 4 POST requests tạo report (SP, SP-ASIN, SB, SD) → nhận reportId
├── 4. Poll mỗi 15 giây cho đến status=COMPLETED (1-5 phút)
├── 5. Download từ pre-signed S3 URL → giải nén gzip → parse JSON
└── 6. Tính tổng spend + lưu summary + raw JSON
```

---

## Phần 3: Sơ đồ thư mục đầy đủ

```
C:\Users\nnh16\ads-trading-system\
└── test_lwa_spapi\                    ← THƯ MỤC LÀM VIỆC CHÍNH
    ├── .env                           ← CREDENTIALS (không commit git)
    ├── .env.example                   ← Template tham khảo
    │
    ├── _auth.py                       ← Module dùng chung (auth, SigV4, helpers)
    ├── fetch_24h_orders.py            ← Script 1: SP-API Orders
    ├── fetch_24h_finances.py          ← Script 2: SP-API Finances
    ├── fetch_24h_ads.py               ← Script 3: Advertising API
    ├── run_all.py                     ← Chạy cả 3 theo thứ tự (terminal)
    │
    ├── start.py                       ← Bấm Run trong VS Code (tạo file này)
    ├── start.bat                      ← Double-click để chạy (tạo file này)
    │
    ├── inspect_raw_data.py            ← Đọc từ Supabase (script cũ)
    ├── README.txt                     ← Hướng dẫn gốc
    ├── requirements.txt               ← Danh sách thư viện
    └── raw_data\                      ← KẾT QUẢ OUTPUT (tự tạo khi chạy)
        ├── orders_24h_raw.json
        ├── fields_map.txt
        ├── finances_24h_raw.json
        ├── finances_summary.txt
        ├── finances_fields_map.txt
        ├── ads_sp_raw.json
        ├── ads_sb_raw.json
        ├── ads_sd_raw.json
        ├── ads_sp_asin_raw.json
        ├── ads_summary.txt
        └── ads_fields_map.txt
```

---

## Phần 4: Checklist trước khi chạy

- [ ] Python đã cài: `python --version` ra 3.x.x
- [ ] Thư viện đã cài: `pip install requests python-dotenv`
- [ ] File `.env` đã có: CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
- [ ] File `.env` đã có: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ROLE_ARN
- [ ] File `.env` đã có: AMAZON_ADS_REFRESH_TOKEN (thường = SP refresh token)
- [ ] `ADS_PROFILE_ID` đã điền (chạy script 1 lần để lấy nếu chưa có)
- [ ] Đang ở đúng thư mục: `C:\Users\nnh16\ads-trading-system\test_lwa_spapi\`
