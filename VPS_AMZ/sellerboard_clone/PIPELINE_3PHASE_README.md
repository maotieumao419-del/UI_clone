# SELLERVISION — PIPELINE 3 GIAI ĐOẠN (Refactor 06/2026)

Tái cấu trúc mã nguồn phân mảnh thành dòng chảy dữ liệu tuyến tính, cô lập
vùng xử lý, memory-safe tuyệt đối (chống Linux OOM Killer sập Gunicorn):

```
Amazon API ──(Phase1: Direct-Stream)──► Supabase NEW_* (bảng đệm)
Supabase   ──(Phase2: Transform)──────► NEW_summary_order_items / NEW_summary_products
Summary    ──(Phase3: Bridge/Patch)───► Web App app.tap2soul.com
```

## Cấu trúc thư mục

> Gộp 06/2026: folder `test_lwa_spapi` cũ đã được hợp nhất vào đây — code
> ingestion giữ bản mới (`Phase1_Ingestion`, có fix gộp-khóa + ads SKU); UX
> hỏi-ngày (`_time_range.py`) + tài liệu chi tiết được port sang; bản Phase 3
> standalone cũ (port 8003) đã xóa.

```
sellerboard_clone/
├── Phase1_Ingestion/
│   ├── amz_spapi_client.py        # LWA + STS/SigV4 + retry 429 + generators phân trang
│   ├── amz_ads_client.py          # Ads API v3: SP/SP-ASIN/SB/SD reports (async, 425-reuse)
│   ├── direct_stream_pipeline.py  # Orchestrator: mỗi trang ≤100 records → upsert ngay
│   │                              # Supabase → del + gc.collect(); gộp khóa chống 21000
│   ├── _time_range.py             # Hỏi-ngày tương tác + quy đổi NGÀY Pacific → dải UTC
│   ├── discover_columns.py        # (tool) tra cột hợp lệ của Ads API
│   ├── requirements.txt  .env.example  start.bat
├── Phase2_Transformation/
│   ├── config_cogs.py             # COGS FIFO (effective_date), shipping, timezone Pacific
│   ├── aggregation_models.py      # Model 2 bảng Master + validate_rollup()
│   ├── transform_engine.py        # NEW_* → Summary_Order_Items + Summary_Products (31 chỉ số)
│   ├── import_cogs_from_csv.py    # Nhập COGS từ CSV "Products" của Sellerboard
│   └── sql/
│       └── supabase_schema.sql    # DDL duy nhất khởi tạo toàn bộ bảng, view, index và function cho Phase 1 & 2
├── Phase3_Application/
│   ├── sellerboard_clone/         # Web app core (xem README — production ở ../backend|frontend)
│   ├── manage_user.py             # CLI quản trị tài khoản đăng nhập (đã di chuyển)
│   └── data_bridge/
│       ├── analytics_aggregator.py # Module tổng hợp tài chính hiệu suất sản phẩm (đã di chuyển)
│       ├── supabase_dashboard.py  # build_dashboard + build_periods (TOÀN BỘ KPI từ Supabase)
│       ├── supabase_to_app_db.py  # Supabase → sellervision.db (savepoint, strict mapping)
│       └── patch_scripts/         # patch_dashboard.py / patch_frontend.py / rollback.py
│                                  # (try_replace + backup + py_compile + auto-restore)
├── backend/  frontend/            # ⚠️ PRODUCTION — không sửa tay, chỉ qua patch_scripts
└── docs/                          # Phase_1/2/3.md, HOW_TO_USE, SELLERBOARD_API_ANALYSIS...
```

## Quy ước dấu & công thức (chuẩn Sellerboard)

Doanh thu DƯƠNG, chi phí ÂM — các cột cộng dồn được:

```
Gross_Profit = Sales + Promo + Amazon_fees + Cost_of_Goods + Shipping
Net_Profit   = Gross_Profit + Ads + Refund_cost + Expenses
Margin       = Net_Profit / Sales × 100
Amazon_fees  = Referral (Commission) + FBA Fulfillment — phí THẬT từ Finances API
COGS FIFO    = mức cog_per_unit có effective_date LỚN NHẤT ≤ ngày mua
```

Phân bổ Ad Spend 3 tầng (từng kênh SP / SB / SBV / SD):
1. Bản ghi cấp SKU/ASIN (`NEW_ads_sp_asin_daily` — Advertised Product Report) → gán thẳng 100%.
2. Regex tên campaign chứa SKU (ưu tiên SKU dài trước) → gán SKU đó.
3. Phần còn lại → phân bổ theo tỷ trọng doanh thu (Revenue Share).

## 🕐 CRITICAL PROTOCOL: Timezone Alignment

Lỗi gốc cần triệt tiêu: API trả UTC, Sellerboard hiển thị Pacific (UTC-7/-8),
server xử lý theo giờ VN (UTC+7) → lệch 14-15h, Daily Sales dồn sai ngày.

| Tầng | Quy tắc |
|---|---|
| Phase 1 (lưu trữ) | Ghi NGUYÊN chuỗi ISO 8601 UTC từ Amazon (`...Z`), không quy đổi |
| Phase 2 (group by ngày) | `purchase_date`/`posted_date`: UTC → `America/Los_Angeles` **trước khi** `.date()` (Python: `config_cogs.to_marketplace_local`; SQL: xem `supabase_schema.sql`) |
| Ads `report_date` | Đã là ngày Pacific (Ads API trả theo TZ tài khoản) — KHÔNG quy đổi lần 2 |
| Backend (Phase 3) | `backend/app/timeutils.py` (`MARKETPLACE_TZ`, `now_marketplace()`) — mốc "hôm nay" của mọi bộ lọc tính server-side theo Pacific |
| Frontend | CHỈ gửi `days=N`, không tự tính ngày bằng đồng hồ máy client (giờ VN) |

Công thức SQL chuẩn hóa trên Supabase (PostgreSQL) trước khi GROUP BY:
```sql
(amazon_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/Los_Angeles')::date
    AS localized_date
```
DST tự động: UTC-7 mùa hè / UTC-8 mùa đông. Tuyệt đối không dùng timezone
mặc định của server hoặc của trình duyệt khi group theo ngày.

Roll-up: `transform_engine` xuất thêm `daily_summary` (ngày Pacific) và
tự đối chiếu `SUM(daily sales) == tổng kỳ` — lệch > $0.01 thì cảnh báo
"kiểm tra phép ép múi giờ". Tuỳ chỉnh TZ qua `SELLER_TIMEZONE` trong `.env`.

## Ràng buộc memory-safety (áp dụng cả 3 phase)

- Phân trang NextToken / `.range(offset, offset+99)`: chunk ≤ 100 records.
- Upsert NGAY từng trang vào Supabase — không tích lũy payload vào list lớn.
- `del payload` + `gc.collect()` sau mỗi chu kỳ ghi.
- Retry 429 với `Retry-After` + backoff; giãn cách giữa các call.
- Bridge: mỗi đơn hàng 1 Savepoint (`db.begin_nested()`) — 1 đơn lỗi không
  làm chết luồng tổng; `calculate_cogs_fifo()` gọi đúng 1 lần sau khi xong.
- Strict Mapping seller → User: không khớp ⇒ `ValueError` dừng ngay,
  KHÔNG fallback (cách ly dữ liệu tài chính giữa các seller).

## Thứ tự chạy

```bash
# 0. Một lần duy nhất: chạy file sql trong Phase2_Transformation/sql/ vào Supabase SQL Editor:
#    chạy duy nhất file: supabase_schema.sql để khởi tạo toàn bộ database

# 1. Thu thập (cron hằng ngày)
python Phase1_Ingestion/direct_stream_pipeline.py --all            # 24h/hôm qua (hoặc HỎI ngày nếu chạy ở terminal)
python Phase1_Ingestion/direct_stream_pipeline.py --all --date 2026-06-09   # đúng ngày 09/06 GIỜ PACIFIC (khớp Sellerboard)

# 2. Nhập COGS (1 lần / khi đổi giá vốn) + Biến đổi & tổng hợp
python Phase2_Transformation/import_cogs_from_csv.py "<Products CSV của Sellerboard>"
python Phase2_Transformation/transform_engine.py --days 7          # ghi 2 bảng Master
python Phase2_Transformation/transform_engine.py --days 7 --no-write --json  # chạy khô

# 3a. Đồng bộ vào DB hiển thị của web app (chạy TRÊN VPS)
python Phase3_Application/data_bridge/supabase_to_app_db.py --seller <email|id> --days 30

# 3b. Kích hoạt UI ma trận hiệu suất (1 lần, có rollback)
python Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py --check
python Phase3_Application/data_bridge/patch_scripts/patch_frontend.py --check
python Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py
python Phase3_Application/data_bridge/patch_scripts/patch_frontend.py
# restart backend, Ctrl+F5 trình duyệt
# Lùi lại: python Phase3_Application/data_bridge/patch_scripts/rollback.py
```

## Biến môi trường (.env tại thư mục chạy script)

| Nhóm | Biến |
|---|---|
| SP-API | `AMAZON_SPI_CLIENT_ID/SECRET/REFRESH_TOKEN`, `AMAZON_SPI_MARKETPLACE_ID` |
| AWS (tuỳ chọn SigV4) | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ROLE_ARN`, `AWS_REGION` |
| Ads API | `AMAZON_ADS_CLIENT_ID/SECRET/REFRESH_TOKEN`, `ADS_PROFILE_ID` |
| Supabase | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` |
| Thời gian | `LOOKBACK_HOURS` (24), `ADS_DAYS_AGO` (1), `SELLER_TIMEZONE` (America/Los_Angeles), `FINANCES_WINDOW_DAYS` (21) |
| Phase 2 | `SHIPPING_COST_PER_UNIT` (0), `SHIPPING_COST_PER_SKU` (JSON map theo SKU) |

### ⚠️ Orders và Finances dùng cửa sổ thời gian KHÁC nhau (tránh `amazon_fees = 0`)

Phí Amazon (Referral + FBA) được **post 1-5 ngày SAU** ngày đặt đơn (khi đơn
ship/kết toán). Nếu nạp finances cùng đúng 1 ngày với orders, `NEW_fin_item_fees`
chỉ chứa phí của đơn *cũ* (ship hôm đó) → `order_id` không trùng đơn ngày D →
transform match ra **0**. Đây là lỗi kinh điển khiến Amazon fees = 0.

`direct_stream_pipeline.py` tự xử lý: với `--date D`, **orders** lấy đúng ngày D
(theo ngày đặt), còn **finances** lấy dải `[D, D + FINANCES_WINDOW_DAYS]` (mặc
định 21 ngày, cap ở "now") để bắt được phí của đơn ngày D post sau đó. Transform
match phí theo `order_id` nên fees vào đúng đơn. Đặt `--finances-window-days 0`
để quay lại hành vi cũ (chỉ để debug).

### Hybrid Amazon Fees: ACTUAL + ESTIMATED + true-up (như Sellerboard)

Phí thật trễ 8-10 ngày ⇒ đơn mới chưa có phí. `transform_engine.py` xử lý lai:
- **ACTUAL** (`fee_state='ACTUAL'`): đơn `(order_id, sku)` ĐÃ có phí thật trong
  `NEW_fin_item_fees` → dùng Referral + FBA thật. Khi đơn settle, ước lượng bị
  thay bằng phí thật (true-up tự động ở lần transform sau).
- **ESTIMATED** (`fee_state='ESTIMATED'`): đơn chưa có phí thật → ước lượng theo
  `order_status`:
  - `Pending`: `-(sales × referral_rate)` (chưa ship, bỏ FBA).
  - `Shipped`: `-(sales × referral_rate) − fba_fee × units`.
- **Rate**: ưu tiên `NEW_fee_cache` (user override per SKU) → AUTO-DERIVE FBA/đơn
  vị từ phí thật (`median(|FBA|/qty)` per SKU) → median toàn shop → referral mặc
  định 15% (`DEFAULT_REFERRAL_RATE`).
- `transform_engine` in **reconciliation** (Sales / fees ACTUAL vs ESTIMATED /
  net / margin) để đối chiếu Sellerboard. Cột `fee_state` lưu ở cả 2 bảng Master
  (`MIXED` nếu 1 SKU gộp cả 2 loại). Schema: `sql/supabase_schema.sql`.

## Chỉ số chưa có nguồn API (giữ chỗ trong schema, điền sau)

Sellable Quota, BSR, Sessions, Unit Session %, Google ads, Facebook ads,
Coupon — cột tồn tại sẵn trong `NEW_summary_*` để Dashboard render đúng
ma trận; giá trị mặc định 0/NULL cho đến khi có nguồn dữ liệu.
