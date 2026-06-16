# Session Handoff — SellerVision (ERP tài chính Amazon, khớp Sellerboard real-time)

> Paste file này vào session mới để tiếp tục ngay. Chi tiết kỹ thuật đầy đủ: `docs/SESSION_HANDOFF.md` (running log).

## 🎯 Mục tiêu tổng thể
Hệ thống tự build **SellerVision** tính toán tài chính Amazon (Amazon fees, Gross/Net profit, Margin, ROI, ACOS...) **khớp Sellerboard theo thời gian thực** (today/yesterday) — KHÔNG chờ Amazon kết toán (settle) 8-10 ngày. Pipeline 3 giai đoạn qua Supabase. Đang tiến tới **multi-tenant** (mỗi store = 1 Supabase project — physical sharding) cho web app production `app.tap2soul.com`.

## ✅ Đã hoàn thành
- **Pipeline 3 phase** hoạt động end-to-end: Phase1 ingest (Amazon API → Supabase `NEW_*`) → Phase2 transform (→ 3 Mart `NEW_summary_*`) → Phase3 web app (patch_scripts, không sửa tay backend/frontend).
- **Gộp folder** `test_lwa_spapi` cũ vào `sellerboard_clone`, xóa legacy + `raw_amazon_orders`.
- **Timezone Pacific (UTC-7/-8, DST tự động)**: Phase 1 hỗ trợ `--date`, `--from/--to` (khoảng ngày), prompt hỏi từ→đến; quy đổi Pacific→UTC chuẩn. Fix bug `CreatedBefore` của ngày-chưa-hết rơi vào tương lai → Amazon 400.
- **Hybrid fees** (= cách Sellerboard): `fee_state` = ACTUAL (phí thật settled) | ESTIMATED (chưa settle, ước lượng) + true-up tự động. Cả Pending lẫn Shipped đều ước lượng gồm FBA.
- **✅ FEE MODEL XÁC NHẬN (quan trọng):** referral thật = **16.5% = 15% Amazon + 10% VAT VN** (Amazon thu VAT phí dịch vụ cho seller Việt Nam). Min fee $0.33 = $0.30 × 1.1. Giải ngược mô hình Sellerboard từ file Order Items: `SB_fees = -(16.5%×sales + FBA_thật_per_SKU×units)`, median sai số chỉ $0.003. **Kỳ vọng cũ "14-15%" là SAI.**
- **`calibrate_fee_cache`**: học per-SKU `referral = median(commission/principal)`, `fba = median(|FBA|/qty)`, suy `fba_size_tier`, ghi `NEW_fee_cache` (giữ override `source='manual'`). Đã thêm cột `principal` (giá bán thật) vào `NEW_fin_item_fees` (Phase 1 capture từ ItemChargeList).
- **Price impute** cho đơn Pending (Amazon trả `ItemPrice=None`): bảng persistent `NEW_product_price` (Phase 1 tự lưu giá từ đơn Shipped, KHÔNG bị `--fresh` xóa) + `import_price_from_csv.py` seed từ Sellerboard CSV. Cột `price_source` = ACTUAL/IMPUTED/NONE.
- **COGS** import từ Sellerboard Products CSV (`import_cogs_from_csv.py`).
- **Phase 2 "Enterprise ETL" refactor**: `run_transformation(client, target_date, *, days, write, fresh, calibrate)` (multi-tenant entry-point); **Mart 3 `NEW_summary_campaigns`** (profit per campaign + break_even_acos); `load_to_supabase_robust` (sanitize NaN/inf, micro-batch 1000, gc); `run_multistore.py` (lặp qua `stores.json`).
- **`fetch_product_images.py`** (Catalog Items batch 20 ASIN → `products.image_url`).
- **DB reset chủ động 12/06** + rebuild schema (26 bảng, idempotent) cho multi-tenant. Fix 3 lỗi schema sau reset.
- **Phase 3 dashboard.py rewrite**: route `/api/analytics/dashboard/summary` (tab products/orders + KPIs) đọc qua `analytics_aggregator`, `/periods` giữ; route Supabase-based cũ đã xóa.
- **Pipeline chạy end-to-end** (10/06): Sales **$778.70 khớp tuyệt đối** Sellerboard.

## 🔄 Đang dở / Chưa hoàn thiện
- **amazon_fees 10/06**: ta -$354.87 vs SB -$323.41 (cả hai đều ESTIMATE — phí thật trễ ≥9 ngày, 0/62 đơn settle). Khác biệt do: SKU không có lịch sử FBA → SB ước FBA=0, ta dùng median shop ~$3.1-3.24 (ta cao hơn SB nhưng GẦN sự thật hơn). **Quyết định MỞ**: fallback FBA cho SKU không lịch sử — giữ median shop (đúng về sau) hay đặt 0 (khớp SB real-time). Đề xuất: giữ median.
- **`NEW_product_cogs` rỗng** sau DB reset → COGS=$0 → cần seed lại.
- **`products` rỗng** → `fetch_product_images` chưa chạy được (cần Phase 3 bridge sync `NEW_sp_orders`→`products` trước).
- **Phase 3 chưa deploy/validate** trên VPS sau reset (bridge + patch_dashboard/frontend).
- **VIỆC #2 (refund hybrid) chưa làm.**

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)
1. **Re-ingest Phase 1** cho khoảng ngày cần xem (`--all --fresh --from X --to Y`), rồi **seed lại COGS + price** (`import_cogs_from_csv.py`, `import_price_from_csv.py`).
2. **`transform_engine.py --calibrate --date <ngày> --fresh`** → học lại `NEW_fee_cache` (referral ~16.5%) + ghi 3 Mart; validate `NEW_summary_campaigns` populate đúng + baseline (Sales $778.70, Units 75 cho 10/06).
3. **Phase 3 trên VPS**: chạy `supabase_to_app_db.py` (sync → `products`/`orders`), `fetch_product_images.py`, rồi `patch_dashboard.py`/`patch_frontend.py` + restart service.
4. **VIỆC #2 — Refund hybrid**: ingest Returns Report (`GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA`) → `NEW_returns_daily`; Phase 2 estimate refund cost cho refund chưa settle (`refund_state` ESTIMATED/ACTUAL).
5. **Validate fee true-up**: export SB Order Items một ngày cuối tháng 5 (đã settle hẳn) → so per-order với `NEW_fin_item_fees` (helper `_check_0603_vs_actual.py`).

## 🏗️ Kiến trúc / Cấu trúc hệ thống
- **Tech**: Python (pandas, paramiko, supabase-py, psycopg) + **Supabase Postgres** (vừa bảng đệm `NEW_*` vừa DB chính web app) + FastAPI backend + Vanilla JS/Tailwind frontend (production `app.tap2soul.com` trên VPS).
- **Luồng**: `Amazon SP-API/Ads-API → Phase1 (direct-stream, memory-safe chunk≤100 + gc) → Supabase NEW_* → Phase2 (transform pandas → 3 Mart) → Phase3 (data_bridge → sellervision.db/Postgres + patch web app)`.
- **Multi-tenant**: mỗi store 1 Supabase project (physical sharding); `run_multistore.py` lặp qua `stores.json`.
- **Hybrid estimate + true-up**: ước lượng real-time (fee/refund/price) rồi ghi đè bằng số thật khi Amazon settle.

## 📁 Cấu trúc thư mục quan trọng

```
VPS_AMZ/sellerboard_clone/
├── Phase1_Ingestion/
│   ├── amz_spapi_client.py        # LWA + STS/SigV4 + retry 429 + generators phân trang
│   ├── amz_ads_client.py          # Ads API v3 (SP/SP-ASIN/SB/SD), 425-reuse
│   ├── direct_stream_pipeline.py  # Orchestrator: --orders/--finances/--ads/--all,
│   │                              #   --date | --from/--to | prompt, --fresh, --finances-window-days
│   ├── _time_range.py             # prompt từ→đến + range_to_utc (Pacific→UTC)
│   └── fetch_product_images.py    # Catalog Items → products.image_url
├── Phase2_Transformation/
│   ├── config_cogs.py             # COGS FIFO + timezone Pacific
│   ├── aggregation_models.py      # SummaryOrderItem/Product/Campaign (+fee_state, order_status, price_source)
│   ├── transform_engine.py        # transform() + run_transformation() + calibrate_fee_cache()
│   │                              #   + load_to_supabase_robust() + reconciliation
│   ├── run_multistore.py          # lặp stores.json (multi-tenant)
│   ├── import_cogs_from_csv.py / import_price_from_csv.py
│   └── sql/                       # supabase_schema, summary_schema, summary_campaigns_schema,
│                                  #   timezone_views, fee_cache_schema(+v2), product_price_schema,
│                                  #   fix_finances_fk_and_summary_cols
├── Phase3_Application/
│   ├── data_bridge/
│   │   ├── analytics_aggregator.py     # nguồn cho dashboard/summary (KPIs, SKU perf, order ledger)
│   │   ├── supabase_dashboard.py / supabase_to_app_db.py
│   │   └── patch_scripts/              # patch_dashboard / patch_frontend / rollback (+backups/)
│   └── sellerboard_clone/              # placeholder web app core (README)
├── Phase3/                        # analytics_aggregator (legacy, module patch import)
├── backend/  frontend/           # ⚠️ PRODUCTION — chỉ sửa qua patch_scripts
│   ├── backend/.env              # credentials + DATABASE_URL
│   ├── backend/supabase/migrations/0002_initial_app_schema.sql  # rebuild app schema (12 bảng)
│   └── backend/alembic/versions/0002_add_product_image_url.py
├── docs/                         # SESSION_HANDOFF.md (running log), NEXT_SESSION_HANDOFF.md (file này), Phase_1/2/3.md
└── PIPELINE_3PHASE_README.md

# Helper tạm ở gốc (KHÔNG commit): _dbadmin.py, _vps.py, _vps_upload.py
# reconciliation/: reconcile.py, _analyze_full.py, _analyze_10.py, export_from_supabase.py
# _check_*.py (principal/referral/sb_model/0603_vs_actual) — phân tích fee model
```

## ⚙️ Biến môi trường & Cấu hình (.env)
File `backend/.env` (Phase 1/2 cần copy `.env` này vào thư mục chạy; KHÔNG upload lên VPS):

```env
# SP-API
AMAZON_SPI_CLIENT_ID=...        AMAZON_SPI_CLIENT_SECRET=...
AMAZON_SPI_REFRESH_TOKEN=...    AMAZON_SPI_MARKETPLACE_ID=ATVPDKIKX0DER   # US
# AWS SigV4 (tùy chọn)
AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...  AWS_ROLE_ARN=arn:aws:iam::...:role/sp-api-role  AWS_REGION=us-east-1
# Ads API
AMAZON_ADS_CLIENT_ID=...  AMAZON_ADS_CLIENT_SECRET=...  AMAZON_ADS_REFRESH_TOKEN=...  ADS_PROFILE_ID=REDACTED_ADS_PROFILE_ID
# Supabase (bảng đệm + DB web app)
SUPABASE_URL=https://REDACTED_PROJECT_REF.supabase.co   SUPABASE_SERVICE_KEY=...   SUPABASE_KEY=...
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<pwd>@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres
# Thời gian
LOOKBACK_HOURS=24   ADS_DAYS_AGO=1   SELLER_TIMEZONE=America/Los_Angeles   FINANCES_WINDOW_DAYS=21
# Phase 2 (tùy chọn)
DEFAULT_REFERRAL_RATE=0.15   SHIPPING_COST_PER_UNIT=0
```
Multi-tenant: `Phase2_Transformation/stores.json` (gitignored) — mỗi store {name, supabase_url, supabase_key}.

## 🔑 Thông số kỹ thuật quan trọng
- **Fee model (CHỐT):** Amazon fees = Referral + FBA Fulfillment. Referral = **16.5%** (15% + 10% VAT VN). Min referral fee $0.33. FBA = phí thật per-SKU (median |FBA|/qty từ settled), fallback median shop ~$3.1.
- **Độ trễ phí/refund:** financialEvents trễ **8-10 ngày** (đo: ≥9 ngày). Orders lọc theo `purchase_date`, Finances lọc theo `posted_date` → 2 cửa sổ độc lập → finances tự nới `[D, D+21 ngày]`.
- **Bảng Supabase** (prefix `NEW_` = pipeline; không prefix = DB SỐNG web app, KHÔNG xóa):
  - Phase 1: `NEW_sp_orders`, `NEW_sp_order_items`, `NEW_fin_item_fees` (+`principal`), `NEW_fin_refunds`, `NEW_fin_adjustments`, `NEW_ads_campaigns_daily`, `NEW_ads_sp_asin_daily`.
  - Cấu hình/persistent: `NEW_product_cogs`, `NEW_product_price`, `NEW_fee_cache` (referral_rate, fba_fulfillment_fee, fba_size_tier, source, sample_count).
  - Mart: `NEW_summary_order_items` (fee_state, order_status, price_source), `NEW_summary_products`, `NEW_summary_campaigns`. Views `NEW_v_daily_*localized`.
  - App: users, products(+image_url), orders, order_items, settlement_entries, ... (alembic_version='0002').
- **VPS**: `sellervision@REDACTED_VPS_IP` password `<VPS_PASSWORD>`; service systemd `sellervision`; venv `backend/venv`; SSH chỉ nhận password (paramiko). Web app `app.tap2soul.com`, login OAuth2 form-encoded, phân biệt hoa thường.
- **Baseline Sellerboard**: 10/06 Sales $778.70 / Units 75 / Refunds 4 / fees -$306.83(card) -$323.41(file) / COGS -$17.20 / Ads -$180.06 / Net $247.79. 03/06 Sales $597.05 / Units 47 / fees -$245.26 / COGS -$27.10.

## 🐛 Vấn đề đã gặp & Cách giải quyết
1. **Finances API trả tiền ở key `CurrencyAmount`** (không phải `Amount`) → mọi phí=0. Fix: helper `_money()` đọc cả hai.
2. **PostgREST 21000** "ON CONFLICT cannot affect row a second time" → gộp dòng trùng theo khóa conflict trước upsert (orders items, fees).
3. **Ads API 425 duplicate** → tái dùng reportId trong `detail`. **429 throttle** → backoff dài (15s+), gap 20s.
4. **`CreatedBefore` tương lai** (ngày chưa hết) → Amazon 400 → cap về None (mở đến now).
5. **amazon_fees=0** vì finances ingest cùng cửa sổ ngày với orders (phí post sau) → finances tự nới rộng `--finances-window-days`.
6. **Đơn Pending `ItemPrice=None`** → impute từ `NEW_product_price` persistent + seed CSV.
7. **Referral calibrate ra 16.52% tưởng sai** → thực ra ĐÚNG (VAT VN). Nguyên nhân nghi sai (price_map) đã thay bằng `commission/principal` chính xác.
8. **FK violation `NEW_fin_item_fees_order_id_fkey` (23503)** sau DB reset — fee có order_id chưa có trong NEW_sp_orders (đơn mua trước `--from`) → crash batch Finances. Fix: DROP FK order_id trên NEW_fin_item_fees + NEW_fin_refunds (giữ FK ở NEW_sp_order_items).
9. **`NEW_summary_order_items` thiếu cột `order_status`/`price_source`**, **`NEW_fee_cache` thiếu `sample_count`** → PGRST204, write Mart fail. Fix: ALTER + cập nhật `supabase_schema.sql`.

## 🚫 Quyết định đã được xác nhận (không thay đổi)
- **6 quyết định Phase 2 refactor:** (1) REFACTOR không rewrite; (2) Pending CÓ FBA trong ước lượng; (3) Canceled LOẠI HẲN khỏi summary; (4) GIỮ schema/tên cột 2 bảng summary hiện tại; (5) multi-tenant = **mỗi store 1 Supabase project** (physical sharding); (6) traffic/bid/strategy/sessions để NULL/0 chờ Sprint sau.
- **Referral = 16.5%** (15% + 10% VAT VN) — KHÔNG đổi về 14-15%.
- **amazon_fees chỉ gồm Referral + FBA** (DigitalServicesFee/ShippingChargeback → other, không vào amazon_fees).
- **KHÔNG sửa tay `backend/`/`frontend/`** — chỉ qua `patch_scripts` (try_replace/ghi-đè + backup + py_compile + rollback).
- **DB reset 12/06 là chủ động** (dọn trước multi-tenant), không phải sự cố.
- **User kiểm soát việc chạy ingest** — Claude soạn lệnh, user tự chạy. Claude tự chạy: read-only, DB-admin (`_dbadmin.py`), sửa code.

## 💡 Context bổ sung
- **Quy ước dấu Sellerboard:** doanh thu DƯƠNG, mọi chi phí ÂM (fees/COGS/ads/refund_cost). `Net = Sales + Promo + Amazon_fees + COGS + Shipping (+ Ads + Refund_cost)`. ad_spend ÂM.
- **So sánh file Sellerboard:** so SỐ (tolerance 0.01) KHÔNG so chuỗi — Excel ép số→ngày (18.01→datetime, reconstruct = day + month/100), header Cyrillic (`Refund сost`), `'0.00'` vs ô trống. File hệ thống export đôi khi KHÔNG có header → đọc theo vị trí cột.
- **Bash môi trường này thiếu `cat/grep/sed/tail/basename`** — dùng python/PowerShell. Lọc output transform (reconciliation in ra stderr): `2>&1 | python -c "import sys;[sys.stdout.write(l) for l in sys.stdin if 'INFO' not in l and 'HTTP Request' not in l]"`.
- **Hybrid là triết lý xuyên suốt:** estimate real-time (fee 16.5%+FBA, price impute, refund tương lai) + retrospective true-up khi Amazon settle. Đừng "sửa" ước lượng cao hơn SB thành thấp — vì phí thật rồi sẽ post cao như ta ước.
- **Cheat-sheet:** `direct_stream_pipeline.py --all --fresh --from X --to Y`; `transform_engine.py --calibrate --date <d> --fresh`; `_dbadmin.py status|feematch|all|sql <f>`; `export_from_supabase.py <d>`.

---
*Session kết thúc lúc: 2026-06-12*
*File này được tạo để kế thừa sang session tiếp theo. Đọc kèm `docs/SESSION_HANDOFF.md` cho chi tiết running log.*
