# Hướng dẫn chạy API Debug Scripts

> **Folder này nằm tại:**
> `C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\`

---

## Bước 0 — Điền credentials vào .env (BẮT BUỘC trước khi chạy bất cứ thứ gì)

### 0.1 Tìm file .env

File `.env` nằm tại:
```
C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\.env
```

Mở bằng Notepad, VS Code, hoặc bất kỳ text editor nào.

> Nếu chưa có file `.env`: copy file `.env.example` → đổi tên thành `.env` → điền vào.

### 0.2 Nội dung cần điền

```env
# ── SP-API ───────────────────────────────────────────────
AMAZON_SPI_CLIENT_ID=amzn1.application-oa2-client.XXXX
AMAZON_SPI_CLIENT_SECRET=amzn1.oa2-cs.v1.XXXX
AMAZON_SPI_REFRESH_TOKEN=Atzr|XXXX
AMAZON_SPI_MARKETPLACE_ID=ATVPDKIKX0DER

# ── AWS IAM (cần cho SP-API signing) ─────────────────────
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/TenRole
AWS_REGION=us-east-1

# ── ADS-API ──────────────────────────────────────────────
AMAZON_ADS_REFRESH_TOKEN=Atzr|XXXX   ← thường CÙNG với SP refresh token
ADS_PROFILE_ID=1234567890            ← xem Bước 0.3 để lấy
```

### 0.3 Cách lấy ADS_PROFILE_ID (nếu chưa biết)

1. Điền xong phần SP-API + `AMAZON_ADS_REFRESH_TOKEN` nhưng để `ADS_PROFILE_ID=` **trống**
2. Chạy: `python fetch_24h_ads.py`
3. Script sẽ tự in ra danh sách profileId:
   ```
   profileId=1234567890  marketplace=US  type=seller  name=Musemory
   profileId=9876543210  marketplace=US  type=vendor  name=...
   ```
4. Chép `profileId` của tài khoản seller US vào `.env`

---

## Cách 1 — Chạy bằng double-click (dễ nhất)

**Không cần mở terminal.**

1. Mở thư mục: `C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\`
2. Double-click vào file **`start.bat`**
3. Cửa sổ CMD tự mở, chạy hết 3 script, tự đóng khi xong
4. Kết quả trong: `raw_data\`

> **start.bat làm gì?**
> - Chuyển vào đúng thư mục
> - Cài thư viện nếu chưa có (`pip install requests python-dotenv`)
> - Chạy lần lượt: Orders → Finances → Ads
> - Dừng lại hiển thị lỗi nếu bước nào thất bại

---

## Cách 2 — Chạy bằng VS Code / PyCharm (không gõ lệnh)

1. Mở VS Code → **File → Open Folder** → chọn:
   `C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi`

2. Mở file **`start.py`** trong VS Code

3. Nhấn nút **▶ Run** (góc trên phải) hoặc **F5**

4. Output hiện trong terminal tích hợp của VS Code

> **start.py làm gì?**
> - Tự xác định đúng thư mục, không cần `cd`
> - Chạy lần lượt 3 script bằng `subprocess`
> - Nếu 1 script lỗi → hỏi có muốn tiếp tục không
> - Không cần cài thêm gì ngoài `requests` và `python-dotenv`

---

## Cách 3 — Chạy từng phần trên Terminal (để debug)

### Mở terminal đúng thư mục

**PowerShell:**
```powershell
cd C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi
```

**CMD (Command Prompt):**
```cmd
cd /d C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi
```

### Cài thư viện (chỉ cần làm 1 lần)

```
pip install requests python-dotenv
```

### Chạy từng script

```
python fetch_24h_orders.py
```
→ Kéo tất cả orders + order items trong 24h gần nhất từ SP-API
→ Output: `raw_data\orders_24h_raw.json` + `raw_data\fields_map.txt`

---

```
python fetch_24h_finances.py
```
→ Kéo tất cả financial events: FBA fee, Referral fee, Refunds, Adjustments
→ Output: `raw_data\finances_24h_raw.json` + `raw_data\finances_summary.txt`

---

```
python fetch_24h_ads.py
```
→ Request async reports từ Advertising API → poll → download
→ Mất **1–5 phút** vì Amazon generate report
→ Output: `raw_data\ads_sp_raw.json` + `raw_data\ads_sb_raw.json` + `raw_data\ads_summary.txt`

---

```
python run_all.py
```
→ Chạy cả 3 script trên theo thứ tự (giống start.bat nhưng Python thuần)

---

## Cấu trúc thư mục

```
VPS\test_lwa_spapi\
│
├── .env                ← CREDENTIALS (BẮT BUỘC điền trước)
├── .env.example        ← Template — không điền thật vào đây
│
├── start.bat           ← Double-click để chạy (Windows)
├── start.py            ← Mở trong VS Code → Run
├── run_all.py          ← Chạy bằng: python run_all.py
│
├── _auth.py            ← Module dùng chung (không chạy trực tiếp)
├── fetch_24h_orders.py ← SP-API: Orders + OrderItems
├── fetch_24h_finances.py ← SP-API: Financial Events (fees, refunds)
├── fetch_24h_ads.py    ← ADS-API: Advertising reports (async)
│
├── inspect_raw_data.py ← Đọc từ Supabase (script cũ)
├── test_spapi.py       ← Test LWA token (script cũ)
│
└── raw_data\           ← Output tự tạo khi chạy
    ├── orders_24h_raw.json      ← Toàn bộ orders thô
    ├── fields_map.txt           ← Schema fields của orders
    ├── finances_24h_raw.json    ← Toàn bộ financial events thô
    ├── finances_summary.txt     ← Tổng hợp phí theo loại
    ├── finances_fields_map.txt  ← Schema fields của finances
    ├── ads_sp_raw.json          ← Sponsored Products thô
    ├── ads_sp_asin_raw.json     ← SP theo từng ASIN/SKU
    ├── ads_sb_raw.json          ← Sponsored Brands + SBV thô
    ├── ads_sd_raw.json          ← Sponsored Display thô
    ├── ads_summary.txt          ← Tổng hợp spend theo loại
    └── ads_fields_map.txt       ← Schema fields của ads
```

---

## Mỗi script làm gì chi tiết

### fetch_24h_orders.py

**Gọi API nào:** SP-API `GET /orders/v0/orders` + `GET /orders/v0/orders/{id}/orderItems`

**Auth flow:**
1. Gọi LWA `https://api.amazon.com/auth/o2/token` bằng refresh_token → lấy access_token
2. (Nếu có AWS creds) Gọi STS AssumeRole → lấy temp credentials
3. Ký request bằng AWS SigV4 + đính kèm `x-amz-access-token` header

**Tham số:**
- `CreatedAfter`: 24h trước hiện tại
- `MarketplaceIds`: ATVPDKIKX0DER (US)
- Tự phân trang bằng `NextToken`

**Output quan trọng:**
```
orders_24h_raw.json   → xem AmazonOrderId, PurchaseDate, OrderStatus, OrderTotal
fields_map.txt        → danh sách mọi field Amazon trả về
```

---

### fetch_24h_finances.py

**Gọi API nào:** SP-API `GET /finances/v0/financialEvents`

**Tham số:**
- `PostedAfter` / `PostedBefore`: 24h gần nhất
- Tự phân trang bằng `NextToken`

**Parse các event list:**

| Event List | Chứa gì |
|---|---|
| `ShipmentEventList` | FBA fee, Referral fee cho từng item đã ship |
| `RefundEventList` | Refunded amount, Refund commission, Refunded referral fee (dương!) |
| `AdjustmentEventList` | FBAInventoryReimbursement (clawback), FBADisposalFee |
| `ServiceFeeEventList` | Phí dịch vụ Amazon khác |

**Output quan trọng:**
```
finances_summary.txt → so sánh ngay với con số trong ảnh Sellerboard:
  FBA fulfillment fee:   $-193.33  (phải = -$193.33 trong Sellerboard)
  Referral fee:          $-113.40
  Refunded amount:       $-32.96
  Refunded referral fee: $+5.45    ← DƯƠNG vì Amazon hoàn lại
  Refund cost (tổng):    $-28.60
  TỔNG AMAZON FEES:      $-318.85
```

---

### fetch_24h_ads.py

**Gọi API nào:** Amazon Advertising API v3 `POST /reporting/reports`

**Auth:** Bearer LWA token — KHÔNG cần AWS SigV4

**Luồng async (tự động, không cần làm thủ công):**
```
1. POST /reporting/reports     → nhận reportId (instant)
2. GET  /reporting/reports/ID  → poll mỗi 15 giây
3. Khi status = COMPLETED      → lấy download URL
4. GET  download_url           → download GZIP JSON
5. Decompress + parse          → lưu vào raw_data/
```

**4 loại report gửi đồng thời:**
- SP Campaigns: spend + attributed sales/units theo campaign
- SP ASIN: spend + attributed sales theo từng SKU
- SB Campaigns: tách `campaignType` để biết đâu là SBV vs SB
- SD Campaigns: Sponsored Display

**Output quan trọng:**
```
ads_summary.txt → so sánh với Sellerboard:
  Sponsored Products:     $-166.79
  Sponsored Brands Video: $-12.47
  Sponsored Brands:       $-0.00
  Sponsored Display:      $-0.00
  TỔNG ADV. COST:         $-179.26
```

---

## Troubleshooting

| Lỗi | Nguyên nhân | Cách fix |
|---|---|---|
| `❌ Thiếu credentials` | `.env` chưa điền | Mở `.env`, điền đủ fields |
| `HTTP 401 Unauthorized` | LWA token hết hạn | refresh_token sai → kiểm tra lại |
| `HTTP 403 Forbidden` | SigV4 sai / Role ARN sai | Kiểm tra AWS_ROLE_ARN trong `.env` |
| `HTTP 429 Too Many Requests` | Gọi API quá nhanh | Script tự retry — chờ thêm |
| `Report FAILED` | Ads API: cột không hợp lệ | Xem log, bỏ cột đó trong config |
| `ModuleNotFoundError: requests` | Chưa install thư viện | Chạy: `pip install requests python-dotenv` |
| ADS: `❌ Thiếu ADS_PROFILE_ID` | profile_id chưa điền | Để trống rồi chạy → script tự in danh sách |

---

## Cách kiểm tra Python đã cài chưa

Mở CMD hoặc PowerShell, gõ:
```
python --version
```
→ Phải thấy `Python 3.x.x`

Nếu không thấy: tải Python tại `python.org/downloads`, tích chọn **Add Python to PATH** khi cài.

---

## Quick Start (tóm tắt 3 bước)

```
Bước 1: Mở file  C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\.env
        Điền đủ credentials SP-API + ADS-API

Bước 2: Double-click file  start.bat
        (hoặc mở start.py trong VS Code → Run)

Bước 3: Xem kết quả trong thư mục  raw_data\
        → finances_summary.txt   so sánh với Sellerboard
        → ads_summary.txt        so sánh với Sellerboard
```
