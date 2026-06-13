# Phase 1 — Debug Tool: Call Amazon SP-API & Ads-API

> Tài liệu Phase 1: `C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\Phase 1\`
> Code mô tả bên dưới nằm tại: `C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\`
>
> ⚠️ **Lưu ý:** Các file code (`_auth.py`, `fetch_24h_*.py`, `run_all.py`...) đã được
> Phase 2 chỉnh sửa tiếp (ghi thẳng vào Supabase, thêm `_supabase_ingest.py`,
> `_time_range.py`...) và hiện là code dùng chung cho Phase 2/3 — xem [Phase_2.md](../Phase_2.md)
> và [HOW_TO_USE.md](../HOW_TO_USE.md) để biết phiên bản hiện tại.
> Tài liệu này mô tả **mục tiêu và kết quả ban đầu** của Phase 1.

## Công việc chính

Xây dựng bộ công cụ Python độc lập để gọi trực tiếp Amazon SP-API và Advertising API,
lấy dữ liệu thô (orders, financial events, ads spend) trong 24h gần nhất, lưu ra file
JSON + file tổng hợp dạng số liệu — phục vụ đối chiếu với Sellerboard nhằm tìm nguyên
nhân chênh lệch số liệu của Sellerboard clone.

Kết quả: cả 3 script đã chạy thành công, lấy được dữ liệu thật từ tài khoản (71 orders,
68 financial events, 4 báo cáo quảng cáo).

---

## Cấu trúc thư mục và nhiệm vụ từng file

```
test_lwa_spapi/
│
├── .env                    ← Credentials thật (SP-API + ADS-API + AWS IAM)
├── .env.example            ← Template credentials (không chứa giá trị thật)
│
├── _auth.py                ← Module dùng chung cho mọi script
├── fetch_24h_orders.py     ← Lấy Orders + OrderItems (SP-API)
├── fetch_24h_finances.py   ← Lấy Financial Events: fees, refunds (SP-API)
├── fetch_24h_ads.py        ← Lấy báo cáo quảng cáo SP/SB/SD (Advertising API)
├── discover_columns.py     ← (phụ) tra schema cột hợp lệ của Ads API
│
├── run_all.py               ← Chạy lần lượt 3 script fetch_*
├── start.bat                ← Double-click để chạy run_all.py (Windows)
├── HUONG_DAN_CHAY.md        ← Hướng dẫn chạy chi tiết, troubleshooting
│
└── raw_data/                ← Toàn bộ output (tự tạo khi chạy)
```

### `_auth.py`
Module dùng chung, không chạy trực tiếp. Chứa:
- `get_lwa_token()` — đổi refresh token lấy access token (LWA OAuth2)
- `get_sts_creds()` — AssumeRole qua AWS STS để lấy temp credentials cho SigV4
- `_sigv4_headers()` — ký request theo chuẩn AWS SigV4 (cho SP-API)
- `spapi_get()` — wrapper gọi SP-API (GET, có ký SigV4, tự retry khi 429)
- `ads_get()` / `ads_post()` — wrapper gọi Advertising API (Bearer token + Scope header, tự retry khi 429)
- `collect_fields()` / `write_fields_map()` — quét đệ quy JSON trả về để liệt kê toàn bộ field Amazon trả (giúp biết schema thật)

### `fetch_24h_orders.py`
Gọi SP-API `GET /orders/v0/orders` + `GET /orders/v0/orders/{id}/orderItems`.
- Lấy toàn bộ đơn hàng tạo trong 24h gần nhất, kèm chi tiết từng item trong đơn.
- Output:
  - `raw_data/orders_24h_raw.json` — toàn bộ orders + items dạng thô
  - `raw_data/fields_map.txt` — danh sách field + kiểu dữ liệu + ví dụ

### `fetch_24h_finances.py`
Gọi SP-API `GET /finances/v0/financialEvents` (PostedAfter = 24h trước, không dùng
PostedBefore vì data quá mới chưa được Amazon finalize).
- Parse 4 nhóm event: `ShipmentEventList` (FBA fee, Referral fee), `RefundEventList`
  (hoàn tiền, hoàn referral fee), `AdjustmentEventList` (bồi thường/clawback),
  `ServiceFeeEventList` (phí dịch vụ khác).
- Output:
  - `raw_data/finances_24h_raw.json` — toàn bộ financial events thô
  - `raw_data/finances_summary.txt` — tổng hợp Sales, FBA fee, Referral fee, Refund cost,
    Adjustments, Service fees → đối chiếu trực tiếp với Sellerboard
  - `raw_data/finances_fields_map.txt` — schema field

### `fetch_24h_ads.py`
Gọi Advertising API v3 (`POST /reporting/reports`) theo flow bất đồng bộ: gửi request →
poll status mỗi 15s → khi `COMPLETED` thì download URL (gzip JSON).
- 4 report được gửi: SP Campaigns, SP theo ASIN/SKU, SB Campaigns (gồm SBV), SD Campaigns.
- Auth riêng biệt với SP-API: dùng `AMAZON_ADS_CLIENT_ID`/`AMAZON_ADS_CLIENT_SECRET` +
  `Amazon-Advertising-API-Scope` = profile ID.
- Output:
  - `raw_data/ads_sp_raw.json`, `ads_sp_asin_raw.json`, `ads_sb_raw.json`, `ads_sd_raw.json`
    — dữ liệu thô từng loại report
  - `raw_data/ads_summary.txt` — tổng spend theo SP / SB / SBV / SD → đối chiếu Advertising cost
    trên Sellerboard
  - `raw_data/ads_fields_map.txt` — schema field

### `discover_columns.py`
Script phụ, gọi endpoint schema của Advertising API để tra cứu danh sách cột hợp lệ cho
từng report type — dùng khi cần thêm cột mới vào `fetch_24h_ads.py` mà không chắc tên cột.

### `run_all.py` / `start.bat`
Chạy tuần tự `fetch_24h_orders.py` → `fetch_24h_finances.py` → `fetch_24h_ads.py`.
`start.bat` cho phép chạy bằng double-click, không cần mở terminal.

---

## Output cuối cùng (`raw_data/`)

| File | Nội dung |
|---|---|
| `orders_24h_raw.json` | Orders + items thô (71 orders) |
| `finances_24h_raw.json` | Financial events thô (68 events) |
| `finances_summary.txt` | Sales $555.88, Amazon fees -$255.57, Refund cost -$7.79 |
| `ads_sp_raw.json`, `ads_sp_asin_raw.json`, `ads_sb_raw.json`, `ads_sd_raw.json` | Báo cáo quảng cáo thô |
| `ads_summary.txt` | Ads cost: SP $166.79, SB $12.47, SD $0 → tổng $179.26 |
| `*_fields_map.txt` | Schema field của từng nguồn dữ liệu |

---

## Bước tiếp theo (Phase 2)

So sánh các số trong `finances_summary.txt` và `ads_summary.txt` với Sellerboard dashboard
cùng ngày, xác định dòng nào lệch → sửa logic tính toán (COG, ngày attribution, dấu +/-
của RefundCommission...) trong code chính của Sellerboard clone.
