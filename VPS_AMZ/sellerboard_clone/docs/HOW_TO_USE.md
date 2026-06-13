# HOW TO USE — Pipeline Amazon API → Supabase → Báo cáo dạng CSV Sellerboard

> Thư mục: `C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\Phase 2\`

Tài liệu này mô tả **toàn bộ quy trình end-to-end**: gọi API Amazon → lưu
trực tiếp vào Supabase → truy vấn lại để ra báo cáo giống file CSV
"Order Items" của Sellerboard và giống các thẻ số trên Dashboard.

---

## 0. Tổng quan kiến trúc (đọc trước khi làm gì)

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────────────┐
│  Amazon SP-API   │     │                      │     │                         │
│  Amazon Ads-API  │────▶│  3 script fetch_*.py │────▶│        SUPABASE         │
│                  │     │  (upsert TRỰC TIẾP,  │     │   (PostgreSQL, bảng     │
│  - Orders        │     │   từng trang/report, │     │    "NEW_*")             │
│  - OrderItems    │     │   không qua RAM/file │     │                         │
│  - Finances      │     │   trung gian)        │     │  6 bảng dữ liệu thô     │
│  - Ads reports   │     │                      │     │  + 2 bảng nhập tay      │
└─────────────────┘     └──────────────────────┘     │  + 1 VIEW (= file CSV)  │
                                                        │  + 1 FUNCTION (=Dashboard)│
                                                        └───────────┬─────────────┘
                                                                     │
                                                                     ▼
                                                        ┌─────────────────────────┐
                                                        │  Truy vấn SQL / Backend  │
                                                        │  - NEW_v_order_items_csv │
                                                        │    → giống file CSV      │
                                                        │  - NEW_fn_daily_summary  │
                                                        │    → giống Dashboard     │
                                                        └─────────────────────────┘
```

**Nguyên tắc quan trọng:** mỗi script `fetch_24h_*.py` gọi API → xử lý
1 trang/1 report → **upsert ngay vào Supabase** → giải phóng bộ nhớ → lấy
trang tiếp theo. Không có bước "lưu file JSON rồi import lại" — vì vậy
không lo tràn RAM khi dữ liệu lớn.

---

## 1. Setup lần đầu (chỉ làm 1 lần)

### Bước 1.1 — Cài thư viện Python

```powershell
cd "C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\Phase 2"
pip install -r requirements.txt
```

Cài: `requests`, `python-dotenv`, `supabase`.

### Bước 1.2 — Điền file `.env`

Copy `.env.example` → `.env` (nếu chưa có), điền đủ 3 nhóm:

| Nhóm | Biến | Lấy ở đâu |
|---|---|---|
| **SP-API** | `AMAZON_SPI_CLIENT_ID`, `AMAZON_SPI_CLIENT_SECRET`, `AMAZON_SPI_REFRESH_TOKEN` | developer.amazon.com |
| **AWS (ký SigV4)** | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ROLE_ARN` | AWS IAM Console |
| **Ads-API** | `AMAZON_ADS_REFRESH_TOKEN`, `ADS_PROFILE_ID` | Xem `../Phase 1/HUONG_DAN_CHAY.md` mục 0.3 |
| **Supabase** | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | supabase.com → Project Settings → API |

> `SUPABASE_SERVICE_KEY` = **service_role key** (không phải `anon` key) —
> cần quyền ghi đầy đủ để upsert. Không commit file `.env` lên git.

### Bước 1.3 — Tạo bảng trong Supabase (chạy 1 lần duy nhất)

1. Mở [supabase.com](https://supabase.com) → chọn project → **SQL Editor**
2. Mở file [`supabase_schema.sql`](supabase_schema.sql), copy toàn bộ nội dung
3. Paste vào SQL Editor → **Run**

Lệnh này tạo (idempotent — chạy lại không lỗi nhờ `CREATE TABLE IF NOT EXISTS` /
`CREATE OR REPLACE`):

| Đối tượng | Loại | Mô tả |
|---|---|---|
| `"NEW_sp_orders"` | bảng | 1 dòng / đơn hàng (order_id, ngày mua, trạng thái...) |
| `"NEW_sp_order_items"` | bảng | 1 dòng / sản phẩm trong đơn (asin, sku, sales, units...) |
| `"NEW_fin_item_fees"` | bảng | Phí Amazon (FBA fee, Referral fee...) theo từng item |
| `"NEW_fin_refunds"` | bảng | Dữ liệu hoàn hàng (refund principal/commission/referral) |
| `"NEW_fin_adjustments"` | bảng | Điều chỉnh tài khoản (clawback, disposal fee...) |
| `"NEW_ads_campaigns_daily"` | bảng | Chi phí quảng cáo SP/SB/SD theo ngày |
| `"NEW_product_cogs"` | bảng | **Nhập tay** — giá vốn (COGS) mỗi SKU |
| `"NEW_indirect_expenses"` | bảng | **Nhập tay** — chi phí gián tiếp theo ngày |
| `"NEW_v_order_items_csv"` | VIEW | Tổng hợp ra **đúng định dạng file CSV** Sellerboard |
| `"NEW_fn_daily_summary"(date)` | FUNCTION | Tổng hợp ra **đúng các số trên Dashboard card** |

---

## 1.5. Tuỳ chỉnh khoảng thời gian lấy dữ liệu (tuỳ chọn)

Mặc định: `fetch_24h_orders.py` và `fetch_24h_finances.py` lấy **24h gần nhất**,
`fetch_24h_ads.py` lấy **report của hôm qua**. Có 2 cách tuỳ chỉnh: **hỏi trực
tiếp khi chạy** (interactive prompt) hoặc **điền `.env`** (cho cron/chạy nền).

### a) Chạy ở terminal → script tự HỎI bạn chọn ngày

Nếu bạn chạy `python run_all.py` (hoặc từng script `fetch_24h_*.py`) trực tiếp
trong terminal, **và chưa điền** các biến override trong `.env` (xem bảng bên
dưới), script sẽ hỏi:

```
── Khoảng thời gian lấy dữ liệu (giờ Seller Central = America/Los_Angeles) ──
  1. 24h gần nhất / hôm qua (mặc định)
  2. Một ngày cụ thể (vd để khớp đúng 1 ngày trên Sellerboard)
  Lựa chọn (1/2, Enter = 1):
```

- Gõ **Enter** (hoặc `1`) → chạy như mặc định (24h gần nhất / hôm qua), giống
  hệt khi chạy qua cron.
- Gõ **`2`** rồi nhập ngày `YYYY-MM-DD` → script tự quy đổi ngày đó (theo
  `SELLER_TIMEZONE`) sang đúng khoảng UTC cho Orders/Finances, và dùng thẳng
  ngày đó cho Ads report. Cả 3 script trong `run_all.py` dùng **chung 1 ngày**
  bạn chọn (chỉ hỏi 1 lần).
- Khi chạy qua cron/Task Scheduler (không có terminal tương tác), prompt này
  **tự động bị bỏ qua** — script chạy mặc định như cũ, không bị treo chờ nhập liệu.

### b) Sellerboard tính "1 ngày" theo timezone nào? → biến `SELLER_TIMEZONE`

Đây là điểm hay gây lệch số liệu khi đối chiếu với Sellerboard:

- **SP-API** (Orders, Finances) trả `CreatedDate`/`PostedDate` theo **UTC**
  (hậu tố `Z`).
- **Ads API** trả field `date` trong report theo **timezone của tài khoản
  quảng cáo** (Seller Central → Settings → Account Info), với seller US
  thường là `America/Los_Angeles` (tự xử lý PDT/PST).
- **Sellerboard** tính ranh giới "1 ngày" theo timezone bạn cấu hình trong
  **Sellerboard → Settings → General → Time Zone**.

→ Để khi bạn chọn "ngày 2026-06-08" ở mục (a), dữ liệu kéo về **khớp đúng**
với "ngày 2026-06-08" trên Sellerboard, biến `SELLER_TIMEZONE` trong `.env`
phải **trùng với timezone đang cấu hình trong Sellerboard**:

1. Mở Sellerboard → Settings → General → Time Zone, ghi lại giá trị (vd
   "Pacific Time (US & Canada)").
2. Đặt `SELLER_TIMEZONE` trong `.env` thành tên IANA tương ứng — phổ biến:
   - "Pacific Time (US & Canada)" → `America/Los_Angeles`
   - "Eastern Time (US & Canada)" → `America/New_York`
   - Nếu không chắc, mặc định `America/Los_Angeles` đúng cho phần lớn seller US.
3. Khi đó: ngày bạn chọn ở prompt (a) → quy đổi UTC cho Orders/Finances dựa
   trên `SELLER_TIMEZONE` này → khớp với cách Sellerboard chia ngày.

### c) Bảng biến `.env` đầy đủ

| Biến `.env` | Áp dụng cho | Mặc định | Ví dụ |
|---|---|---|---|
| `SELLER_TIMEZONE` | quy đổi ngày → UTC (mục b) | `America/Los_Angeles` | `America/New_York` |
| `LOOKBACK_HOURS` | orders (`CreatedAfter`), finances (`PostedAfter`) | `24` | `LOOKBACK_HOURS=48` → lấy 48h gần nhất |
| `ORDERS_CREATED_AFTER` | orders | (trống, dùng `LOOKBACK_HOURS`) | `2026-06-01T00:00:00Z` → ghi đè hẳn mốc bắt đầu |
| `ORDERS_CREATED_BEFORE` | orders | (trống = không giới hạn) | `2026-06-02T00:00:00Z` |
| `FINANCES_POSTED_AFTER` | finances | (trống, dùng `LOOKBACK_HOURS`) | `2026-06-01T00:00:00Z` |
| `FINANCES_POSTED_BEFORE` | finances | (trống = "now") | `2026-06-02T00:00:00Z` |
| `ADS_DAYS_AGO` | ads | `1` (hôm qua) | `ADS_DAYS_AGO=2` → lấy report 2 ngày trước |
| `ADS_REPORT_DATE` | ads | (trống, dùng `ADS_DAYS_AGO`) | `2026-06-05` → ghi đè hẳn ngày |

> **Khi nào dùng cái nào:**
> - Chạy hằng ngày qua cron/Task Scheduler → để mặc định (không điền gì) —
>   prompt sẽ tự bỏ qua, script lấy 24h gần nhất / hôm qua như cũ.
> - Chạy thủ công ở terminal, muốn lấy đúng 1 ngày trong quá khứ → để các biến
>   `ORDERS_CREATED_*` / `FINANCES_POSTED_*` / `ADS_REPORT_DATE` **trống**, để
>   script hỏi (mục a) và chọn `2`.
> - Backfill tự động (script/cron không có người ngồi nhập) → điền sẵn
>   `ORDERS_CREATED_AFTER` + `ORDERS_CREATED_BEFORE` + `FINANCES_POSTED_AFTER`
>   + `FINANCES_POSTED_BEFORE` + `ADS_REPORT_DATE` của ngày cần lấy, chạy xong
>   thì xoá lại các biến này (để hôm sau không bị kẹt cứng vào ngày cũ).
> - `FINANCES_POSTED_BEFORE` chỉ nên điền khi lấy dữ liệu quá khứ — Amazon trả
>   lỗi 400 nếu mốc này quá gần hiện tại (data chưa finalize).

---

## 2. Chạy hằng ngày — kéo dữ liệu 24h gần nhất vào Supabase

### Cách nhanh nhất — chạy cả 3 script liên tiếp

```powershell
cd "C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\Phase 2"
python run_all.py
```

(hoặc double-click `start.bat` / mở `start.py` trong VS Code → Run)

`run_all.py` chạy lần lượt 3 script bên dưới, dừng và hỏi nếu 1 bước lỗi.

### Hoặc chạy từng script riêng (để debug từng phần)

#### 2.1 `python fetch_24h_orders.py`

| | |
|---|---|
| **Gọi API** | SP-API `GET /orders/v0/orders` + `GET /orders/v0/orders/{id}/orderItems` |
| **Lấy gì** | Tất cả đơn hàng tạo trong 24h gần nhất + chi tiết từng sản phẩm trong đơn |
| **Ghi vào Supabase** | `"NEW_sp_orders"` (upsert theo `order_id`), `"NEW_sp_order_items"` (upsert theo `order_id + asin + sku`) |
| **Cách xử lý RAM** | Mỗi trang 100 orders → lấy order items → upsert ngay → `gc.collect()` → sang trang tiếp |

#### 2.2 `python fetch_24h_finances.py`

| | |
|---|---|
| **Gọi API** | SP-API `GET /finances/v0/financialEvents` (phân trang `NextToken`) |
| **Lấy gì** | `ShipmentEventList` (phí FBA/Referral), `RefundEventList` (hoàn hàng), `AdjustmentEventList` (điều chỉnh), `ServiceFeeEventList` |
| **Ghi vào Supabase** | `"NEW_fin_item_fees"`, `"NEW_fin_refunds"`, `"NEW_fin_adjustments"` |
| **Cách xử lý RAM** | Mỗi trang events → cộng dồn vài số tổng (để in summary) + upsert ngay → giải phóng → sang trang tiếp |
| **Lưu ý quan trọng** | `RefundCommission` được lưu **DƯƠNG** (Amazon hoàn lại referral fee cho người bán) — nếu bỏ sót sẽ tính sai refund cost |

#### 2.3 `python fetch_24h_ads.py`

| | |
|---|---|
| **Gọi API** | Amazon Advertising API `POST /reporting/reports` (async: request → poll mỗi 15s → download GZIP JSON) |
| **Lấy gì** | Spend + attributed sales của Sponsored Products / Sponsored Brands (+SBV) / Sponsored Display cho **ngày hôm qua** |
| **Ghi vào Supabase** | `"NEW_ads_campaigns_daily"` (upsert theo `report_date + campaign_id + ad_product`) |
| **Cách xử lý RAM** | Mỗi report (SP/SB/SD) sau khi download xong → upsert ngay, không gộp chung |
| **Mất bao lâu** | 1–5 phút (Amazon cần thời gian generate report) |
| **Ghi chú** | Report `SP-ASIN` (chi tiết theo từng SKU) chỉ in ra summary tham khảo, **chưa có bảng Supabase riêng** |

---

## 3. Nhập dữ liệu thủ công (cần thiết để tính đúng Profit/Margin/ROI)

Hai bảng này **không có script tự động** — phải tự nhập vì Amazon API
không trả về giá vốn hay chi phí nội bộ của bạn.

### 3.1 `"NEW_product_cogs"` — Giá vốn hàng hóa (COGS)

```sql
INSERT INTO "NEW_product_cogs" (sku, cog_per_unit, effective_date, notes)
VALUES
  ('SKU-ABC-123', 5.50, '2026-01-01', 'Giá nhập lô tháng 1'),
  ('SKU-ABC-123', 6.00, '2026-06-01', 'Giá nhập lô tháng 6 (tăng giá)')
ON CONFLICT (sku, effective_date) DO UPDATE SET cog_per_unit = EXCLUDED.cog_per_unit;
```

> View/function tự động lấy COGS có `effective_date <= ngày đơn hàng` gần nhất
> — hỗ trợ nhiều mức giá theo thời gian (FIFO theo ngày).

### 3.2 `"NEW_indirect_expenses"` — Chi phí gián tiếp

```sql
INSERT INTO "NEW_indirect_expenses" (expense_date, description, amount)
VALUES ('2026-06-08', 'Lương nhân viên + thuê kho (phân bổ/ngày)', -50.00);
```

> `amount` để **số âm** vì đây là chi phí trừ vào lợi nhuận.

---

## 4. Lấy báo cáo — từ dữ liệu Supabase ra định dạng CSV / Dashboard

Sau khi đã chạy `run_all.py` (bước 2) và nhập COGS/expenses (bước 3),
mọi báo cáo chỉ cần **query SQL** trong Supabase SQL Editor (hoặc gọi qua
REST API `/rest/v1/`).

### 4.1 Báo cáo dạng file CSV "Order Items" — `"NEW_v_order_items_csv"`

```sql
-- Đơn hàng bình thường của ngày 8/6/2026
SELECT * FROM "NEW_v_order_items_csv"
WHERE row_type = 'normal' AND order_date = '2026-06-08'

UNION ALL

-- Returns được GÁN vào ngày 8/6/2026 theo posted_date (ngày Amazon xử lý hoàn tiền)
SELECT * FROM "NEW_v_order_items_csv"
WHERE row_type = 'return' AND sort_ts::date = '2026-06-08'

ORDER BY sort_ts;
```

Mỗi dòng trả về tương ứng 1 dòng trong file CSV Sellerboard, gồm các cột:

| Cột | Ý nghĩa |
|---|---|
| `order_id`, `order_status`, `order_date`, `fulfillment_channel` | Thông tin đơn hàng |
| `title`, `asin`, `sku`, `unit_price`, `units` | Thông tin sản phẩm |
| `refunds` | Số lượng bị hoàn (chỉ có ở dòng `row_type='return'`) |
| `sales` | = `unit_price × units` |
| `promo` | Khuyến mãi (số âm) |
| `refund_cost` | = `refund_principal + refund_commission + refunded_referral_fee` |
| `amazon_fees` | Tổng phí Amazon cho item này (số âm) |
| `cost_of_goods`, `cog_per_unit` | Giá vốn (lấy từ `NEW_product_cogs`) |
| `gross_profit` | = `sales + amazon_fees + cost_of_goods` |
| `net_profit` | = `gross_profit + indirect_expenses` |
| `margin_pct` | = `net_profit / sales × 100` |
| `roi_pct` | = `net_profit / abs(cost_of_goods) × 100` |
| `row_type` | `'normal'` (đơn hàng) hoặc `'return'` (hoàn hàng) |

### 4.2 Báo cáo dạng Dashboard card — `"NEW_fn_daily_summary"(date)`

```sql
SELECT * FROM "NEW_fn_daily_summary"('2026-06-08');
```

Trả về **1 dòng duy nhất** với các số tổng giống các ô số trên Dashboard
Sellerboard:

| Cột | Ý nghĩa |
|---|---|
| `sales` | Tổng doanh thu (Sales) |
| `orders_count`, `units` | Số đơn, số sản phẩm bán ra |
| `refunds_count` | Số lượt hoàn hàng |
| `promo` | Tổng khuyến mãi |
| `adv_cost` | Chi phí quảng cáo (Adv. cost, số âm) |
| `refund_cost` | Tổng chi phí hoàn hàng |
| `amazon_fees` | Tổng phí Amazon (FBA + Referral + Adjustments) |
| `cost_of_goods` | Tổng giá vốn (số âm) |
| `gross_profit` | = `sales + amazon_fees + refund_cost + adv_cost + cost_of_goods` |
| `indirect_expenses` | Tổng chi phí gián tiếp |
| `net_profit` | = `gross_profit + indirect_expenses` |
| `est_payout` | = `sales + amazon_fees + refund_cost + adv_cost` (KHÔNG trừ COGS) |
| `real_acos_pct` | = `abs(adv_cost) / sales × 100` |
| `refund_rate_pct` | = `refunds_count / units × 100` |
| `margin_pct` | = `net_profit / sales × 100` |
| `roi_pct` | = `net_profit / abs(cost_of_goods) × 100` |

---

## 5. Tóm tắt quy trình hằng ngày (checklist)

```
[ ] 1. python run_all.py
       → kéo Orders + Finances + Ads của 24h/ngày hôm qua
       → tự upsert vào "NEW_sp_orders", "NEW_sp_order_items",
         "NEW_fin_item_fees", "NEW_fin_refunds", "NEW_fin_adjustments",
         "NEW_ads_campaigns_daily"

[ ] 2. (nếu có SKU mới hoặc giá vốn thay đổi)
       → INSERT vào "NEW_product_cogs"

[ ] 3. (nếu có chi phí gián tiếp phát sinh trong ngày)
       → INSERT vào "NEW_indirect_expenses"

[ ] 4. Kiểm tra số liệu:
       → SELECT * FROM "NEW_fn_daily_summary"('YYYY-MM-DD');
       → SELECT * FROM "NEW_v_order_items_csv" WHERE order_date = 'YYYY-MM-DD';
```

---

## 6. File nào làm gì (tổng hợp)

| File | Vai trò |
|---|---|
| `_auth.py` | Module dùng chung: lấy LWA token, STS role, gọi SP-API/Ads-API có retry |
| `_supabase_ingest.py` | Module dùng chung: transform dữ liệu Amazon → upsert vào bảng `"NEW_*"` |
| `_time_range.py` | Module dùng chung: hỏi/quy đổi khoảng thời gian + ngày (mục 1.5) |
| `fetch_24h_orders.py` | Bước 2.1 — Orders + OrderItems → Supabase |
| `fetch_24h_finances.py` | Bước 2.2 — Financial Events → Supabase |
| `fetch_24h_ads.py` | Bước 2.3 — Ads reports → Supabase |
| `run_all.py` | Chạy 3 script trên theo thứ tự |
| `start.bat` / `start.py` | Chạy `run_all.py` không cần gõ lệnh |
| `supabase_schema.sql` | Tạo toàn bộ bảng/view/function `"NEW_*"` (chạy 1 lần) |
| `../ingest_pipeline.py` | **[LEGACY]** chỉ dùng để nạp lại file `raw_data/*.json` cũ (nếu còn), không còn cần dùng |
| `../inspect_raw_data.py`, `../test_spapi.py`, `../discover_columns.py` | Script debug/khám phá API từ Phase 1, không nằm trong flow chính |

---

## 7. Troubleshooting

| Lỗi | Nguyên nhân | Cách fix |
|---|---|---|
| `Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_KEY` | `.env` chưa điền phần Supabase | Điền `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` (service_role) |
| `❌ Thiếu credentials LWA/ADS` | `.env` chưa điền phần Amazon | Xem `../Phase 1/HUONG_DAN_CHAY.md` mục 0 |
| `HTTP 429 Too Many Requests` | Gọi API quá nhanh | Script tự retry có chờ — không cần can thiệp |
| `duplicate key value violates unique constraint` | Bình thường — đây là **upsert**, Supabase tự update nếu trùng key | Không phải lỗi |
| `gross_profit` / `roi_pct` ra `NULL` hoặc sai | Chưa nhập `"NEW_product_cogs"` cho SKU đó | Thêm dòng vào `NEW_product_cogs` (mục 3.1) |
| Số liệu Dashboard lệch ngày so với Sellerboard | Returns được gán theo `posted_date`, không phải ngày đặt hàng gốc | Đây là hành vi đúng — Sellerboard cũng làm vậy |
| `ModuleNotFoundError: supabase` | Chưa cài thư viện | `pip install -r requirements.txt` |

---

## 8. Liên quan đến migration SQLite → Supabase

Tài liệu này chỉ nói về **pipeline lấy dữ liệu Amazon → Supabase (bảng `NEW_*`)**.
Việc chuyển backend FastAPI (`sellervision`) từ SQLite sang đọc/ghi Supabase
là một việc khác, xem `HANDOFF_SUPABASE_MIGRATION.md` ở thư mục gốc project.
