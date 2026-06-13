# SELLERVISION — SESSION HANDOFF (cập nhật 12/06/2026)

Tài liệu chuyển giao để tiếp tục ở session mới. Mục tiêu xuyên suốt:
**hệ thống tự build (SellerVision) tính toán tài chính Amazon KHỚP Sellerboard
theo thời gian thực (today/yesterday), không phải chờ kết toán.**

---

## 1. KIẾN TRÚC & VỊ TRÍ CODE

Gốc dự án: `C:\Users\nnh16\ads-trading-system\VPS\VPS_AMZ\sellerboard_clone\`
Pipeline 3 giai đoạn (folder `test_lwa_spapi` cũ ĐÃ gộp/xóa, xem `docs/`):

```
Phase1_Ingestion/          # Amazon API -> Supabase (bảng đệm NEW_*)
  amz_spapi_client.py      # LWA + STS/SigV4 + retry 429 + generators phân trang
  amz_ads_client.py        # Ads API v3 (SP/SP-ASIN/SB/SD), 425-reuse
  direct_stream_pipeline.py# Orchestrator: --orders/--finances/--ads/--all,
                           #   --date / --from/--to (KHOẢNG NGÀY), --fresh,
                           #   --finances-window-days, prompt hỏi khoảng ngày
  _time_range.py           # prompt hỏi từ→đến + range_to_utc (Pacific->UTC)
Phase2_Transformation/
  config_cogs.py           # COGS FIFO (effective_date), timezone Pacific
  aggregation_models.py    # SummaryOrderItem / SummaryProduct (+fee_state, order_status)
  transform_engine.py      # NEW_* -> NEW_summary_order_items / NEW_summary_products
                           #   hybrid fees, price impute, calibrate_fee_cache, reconciliation
  import_cogs_from_csv.py  # nhập COGS từ Sellerboard Products CSV
  import_price_from_csv.py # seed giá vào NEW_product_price từ Sellerboard Products CSV
  sql/                     # supabase_schema, summary_schema, timezone_views,
                           #   fee_cache_schema, fee_cache_v2, product_price_schema
Phase3_Application/
  data_bridge/
    supabase_dashboard.py  # build_dashboard + build_periods (KPI từ Supabase)
    supabase_to_app_db.py  # Supabase -> sellervision.db (savepoint, strict mapping)
    patch_scripts/         # patch_dashboard.py / patch_frontend.py / rollback.py
Phase3/                    # analytics_aggregator.py (module per-SKU mà patch import)
backend/  frontend/        # ⚠️ PRODUCTION app.tap2soul.com — KHÔNG sửa tay, chỉ qua patch_scripts
docs/                      # tài liệu (Phase_1/2/3.md, HOW_TO_USE, file này...)
PIPELINE_3PHASE_README.md  # tổng quan
```

Helper tạm ở gốc (KHÔNG commit, dùng cho thao tác DB/VPS):
- `_dbadmin.py` — `list|all|count|status|feematch|sql <file>|drop <name>` qua DATABASE_URL.
- `_vps.py`, `_vps_upload.py` — chạy lệnh/upload lên VPS qua paramiko (password).
- `reconciliation/` — `reconcile.py`, `_analyze_full.py`, `_analyze_10.py`,
  `export_from_supabase.py` (export 2 bảng Master ra xlsx, lọc theo ngày).

---

## 2. HẠ TẦNG DỮ LIỆU

- **Supabase Postgres** vừa là bảng đệm pipeline (`NEW_*`) VỪA là DB chính của
  web app backend (qua `DATABASE_URL` trong `backend/.env`). Các bảng KHÔNG
  prefix `NEW_` (users, products, orders, order_items, settlement_entries...)
  là **DB SỐNG của web app — TUYỆT ĐỐI không xóa**. (`raw_amazon_orders` legacy
  đã drop.)
- Credentials: `backend/.env` có SP-API/Ads/AWS/Supabase + DATABASE_URL. Phase
  1/2 cần `.env` cùng thư mục (copy từ backend/.env). `.env` KHÔNG được upload.
- VPS: `sellervision@REDACTED_VPS_IP`, password `<VPS_PASSWORD>`, service systemd
  `sellervision`, venv `backend/venv`. SSH chỉ nhận password (paramiko).

### Bảng Supabase chính
| Bảng | Phase | Nội dung |
|---|---|---|
| `NEW_sp_orders`, `NEW_sp_order_items` | 1 | Orders + items (item_price=0 nếu Pending) |
| `NEW_fin_item_fees` | 1 | Phí thật settled (+ cột `principal` = giá bán thật, MỚI) |
| `NEW_fin_refunds`, `NEW_fin_adjustments` | 1 | Refund/adjustment thật |
| `NEW_ads_campaigns_daily`, `NEW_ads_sp_asin_daily` | 1 | Ads (campaign + cấp SKU) |
| `NEW_product_cogs` | nhập tay | COGS FIFO |
| `NEW_product_price` | persistent | đơn giá per SKU (Phase 1 tự lưu từ đơn Shipped; KHÔNG bị --fresh xóa) — IMPUTE giá đơn Pending |
| `NEW_fee_cache` | calibrate/manual | referral_rate, fba_fulfillment_fee, fba_size_tier, source, sample_count |
| `NEW_summary_order_items`, `NEW_summary_products` | 2 | Master (có fee_state, order_status, price_source) |
| views `NEW_v_daily_*localized` | 2 | tổng theo ngày Pacific |

---

## 3. KHÁI NIỆM CỐT LÕI (đã kiểm chứng bằng dữ liệu thật)

1. **Timezone Pacific (UTC-7/-8, DST tự động):** mọi mốc ngày theo
   `America/Los_Angeles` (Sellerboard dùng). `--date`/`--from/--to` quy đổi
   Pacific→UTC. Bug đã fix: `CreatedBefore` của ngày-chưa-hết rơi vào tương lai
   → Amazon 400 → cap về None (mở đến now).
2. **Độ trễ phí 8-10 ngày:** `financialEvents` (phí THẬT) trễ 8-10 ngày so với
   ngày đặt (đo thực tế). Orders dùng cửa sổ ngày D; **finances tự nới rộng**
   `[D, D+FINANCES_WINDOW_DAYS=21]` để bắt phí của đơn D post sau.
3. **Hybrid fees (= cách Sellerboard):**
   - `ACTUAL` (`fee_state`): đơn đã có phí thật trong `NEW_fin_item_fees` → dùng
     Referral+FBA thật. True-up tự động ở lần transform sau.
   - `ESTIMATED`: chưa settle → ước lượng `-(sales×referral) - fba×units` (cả
     Pending lẫn Shipped đều gồm FBA — đã xác nhận Sellerboard cũng vậy).
4. **Price impute:** Amazon trả `ItemPrice=None` cho đơn Pending. `price_source`
   = ACTUAL (Shipped có giá) / IMPUTED (Pending lấy từ NEW_product_price) / NONE.
5. **Refund cũng trễ** vì `financialEvents`. Sellerboard dùng **Returns Report**
   (operational, real-time) để estimate ngay rồi true-up — ta CHƯA làm (việc #2).

---

## 4. TRẠNG THÁI KHỚP SELLERBOARD (ngày 03/06 & 10/06)

✅ **Khớp tuyệt đối:** Units, Sales, Promo, COGS, Shipping.
- Sales 10/06: $778.70 = $778.70 (sau khi impute giá + seed 5 SKU).

❌ **Còn lệch (đang xử lý):**
- **amazon_fees:** 10/06 hệ thống -$355 vs Sellerboard -$323 (ước lượng cao ~10%).
  Lệch ở cả referral (15% hơi cao, thực ~14%) lẫn FBA (median shop hơi cao cho
  SKU chưa có lịch sử). → ĐANG calibrate (việc #1).
- **refunds:** financialEvents mới post 2/4 (trễ) → việc #2 (Returns Report).
- gross/net/margin/roi: hệ quả của fees, tự đúng khi fix fees.

---

## 5. CÔNG VIỆC ĐANG DỞ — VIỆC #1: CALIBRATE FEES (ƯU TIÊN)

Đã code xong, ĐANG chờ data để validate:
- `transform_engine.calibrate_fee_cache(sb)`: học per-SKU từ phí thật →
  `fba = median(|FBA|/qty)`, `referral = median(|commission| / principal)`
  (principal = giá bán thật, MỚI thêm vào Phase 1). Suy `fba_size_tier`. Ghi
  `NEW_fee_cache`, GIỮ override `source='manual'`. Flag `--calibrate`.
- `_resolve_hybrid_fees` đọc cache (manual+calibrated) → fallback runtime FBA → default 15%.

### ✅ KẾT LUẬN CALIBRATE (12/06/2026 — đã re-pull finances 480h, principal 2163/2163):

**Referral 16.53% là ĐÚNG, không phải bug.** Kỳ vọng cũ "~0.14-0.15" SAI. Bằng chứng:
1. Phân phối `commission/principal` cực chụm: p5–p95 = 0.1649–0.1660 (n=1077).
2. Min fee thật = **$0.33** = $0.30 (min referral Amazon) × 1.10 → **15% + 10% VAT**
   (Amazon thu VAT phí dịch vụ cho seller Việt Nam). 16.5% = 15% × 1.1.
3. **Giải ngược mô hình Sellerboard** từ file Order Items 03/06 (per-SKU,
   `_check_sb_model.py`): SB_fees = -(16.5% × sales + FBA_thật_per_SKU × units),
   median |sai số| = **$0.003** — SB dùng đúng 16.5% + FBA thật (gồm VAT).
   → Cache calibrate của ta (referral 0.1653, FBA median per-SKU) ≈ trùng mô hình SB.

**Vì sao SB 10/06 = -323.41 còn ta = -357 (cả hai đều ESTIMATE, phí thật trễ ≥9 ngày):**
- SKU mà SB chưa có lịch sử FBA → **SB ước FBA = 0** (bằng chứng: NURSEBADGEREEL_*,
  250TH_DOORSIGN_250TH có impl@16.5% = 0.00); ta dùng median shop 3.12 → ta CAO hơn
  SB nhưng GẦN sự thật hơn (phí thật rồi sẽ post).
- Đơn promo/giveaway (vd 250TH_GNOME_*): commission thật = min $0.33 (giá sau coupon
  ~0) nhưng cả SB lẫn ta đều ước 16.5% × giá gốc → cả hai cao hơn thật ở các đơn này.
- Độ trễ phí đo lại: ≥9 ngày (0/46 đơn 03/06 settle tính đến 12/06).

**Dự đoán kiểm chứng được:** khi phí 03/06 + 10/06 post (~13–20/06), số SB sẽ
true-up TĂNG về phía ước lượng của ta. Test: export SB Order Items một ngày cuối
tháng 5 (đã settle hẳn) → so per-order với NEW_fin_item_fees (`_check_0603_vs_actual.py`).

**Quyết định mở:** fallback FBA cho SKU không lịch sử — giữ median shop (đúng hơn về
sau) hay đặt 0 (khớp SB real-time tuyệt đối). Đề xuất: giữ median.

Helper phân tích đã có ở gốc: `_check_principal.py`, `_check_referral.py`,
`_check_0610_actual.py`, `_check_0603_vs_actual.py`, `_check_sb_model.py`.

⚠️ Lưu ý dữ liệu: `NEW_sp_orders` hiện chỉ còn 114 đơn (10–12/06, ngày 10/06 chỉ
còn 19 đơn/$233 — bị --fresh của lần ingest sau xóa). Muốn re-run reconciliation
10/06 phải re-ingest orders ngày đó (KHÔNG --fresh để khỏi xóa 11–12/06).

---

## 5b. PHASE 2 REFACTOR "ENTERPRISE ETL" (12/06/2026 — ĐÃ XONG CODE)

6 quyết định đã chốt: REFACTOR (không rewrite); Pending CÓ FBA; Canceled LOẠI HẲN;
GIỮ schema/tên cột 2 bảng summary hiện tại; multi-tenant = MỖI STORE 1 SUPABASE
PROJECT (Physical Sharding); traffic/bid/strategy để NULL chờ Sprint tới.

Đã triển khai trong `Phase2_Transformation/`:
- `transform_engine.transform(start, end, sb=None)` — nhận client từ ngoài.
- **`run_transformation(supabase_client, target_date, *, days, write, fresh, calibrate)`**
  — entry-point multi-tenant; CLI main() cũng đi qua hàm này.
- **Mart 3 `NEW_summary_campaigns`** (`_build_campaigns` + `SummaryCampaign` trong
  aggregation_models + `sql/summary_campaigns_schema.sql`): gom NEW_ads_campaigns_daily
  per campaign; profit = GPU(SKU quảng cáo, trọng số spend từ NEW_ads_sp_asin_daily)
  × units + ad_spend(âm); fallback GPU trung bình shop (SB/SD); break_even_acos =
  GPU/ASP×100; attribution 7d (units chỉ có 1d); status/current_bid/strategy/
  automation_status = NULL chờ Ads campaign-mgmt API. ad_spend ÂM (quy ước hệ thống).
- **`load_to_supabase_robust(rows, table, client, conflict_keys)`**: sanitize
  (NaN/inf→0, numpy→python, str strip, ''→NULL trừ cột khóa, inject updated_at UTC)
  → micro-batch 1000 → upsert returning='minimal' → del + gc.collect().
- `run_multistore.py` — vòng for qua `stores.json` (gitignored), 1 store lỗi không
  chặn store khác. SummaryProduct.sessions default 0 (chờ traffic report true-up).
- Ads allocation giữ 3 tầng cũ (SP per-SKU thật → regex tên campaign → revenue
  share) — superset của mock logic 2 tầng đã chốt.
- Phase 1 phụ: `Phase1_Ingestion/fetch_product_images.py` (Catalog Items batch 20
  ASIN, ảnh MAIN → products.image_url; đã ALTER thêm cột).

✅ **DB ĐÃ ĐƯỢC RESET CHỦ ĐỘNG 12/06 (xác nhận từ user)** — không phải sự cố.
User chủ động xoá sạch DB `REDACTED_PROJECT_REF` để dọn sạch trước multi-tenant
(Quyết định 5). Đã tái tạo lại TOÀN BỘ schema (26/26 bảng, 0 dòng — đã verify
qua `_dbadmin.py all`):
- `backend/supabase/migrations/0002_initial_app_schema.sql` (MỚI) — bản SQL thô
  tương đương alembic 0001 + 0002, dùng vì máy dev này KHÔNG có
  alembic/sqlalchemy cài sẵn. Tạo lại 12 bảng app (users, products, orders...)
  + `products.image_url` (đã thêm thẳng vào schema, không cần ALTER riêng) +
  ghi `alembic_version = '0002'` để VPS (có alembic thật) không tạo trùng.
- `backend/app/models/models.py` — `Product.image_url: Mapped[str | None]` (Text).
- `backend/alembic/versions/0002_add_product_image_url.py` (MỚI) — migration
  tương ứng cho VPS chạy `alembic upgrade head`.
- `Phase2_Transformation/sql/supabase_schema.sql` — chạy lại, tạo 14 bảng
  NEW_* + 4 view + 1 function (idempotent, IF NOT EXISTS).
- `_dbadmin.py` — sửa phân loại `NEW_TABLES`/`APP_TABLES` (trước đó
  NEW_fee_cache/NEW_product_price/NEW_summary_campaigns bị gắn nhãn sai
  "BẢNG SỐNG web app").

**VIỆC CẦN LÀM TIẾP (theo thứ tự, user chạy lệnh ingest):**
1. Re-ingest Phase 1 (orders + finances + ads) cho khoảng ngày cần xem.
2. Seed lại `NEW_product_cogs` / `NEW_product_price` (import_cogs_from_csv /
   import_price_from_csv).
3. `transform_engine.py --calibrate --date <ngày> --fresh` — học lại
   `NEW_fee_cache` (referral ~16.5%) + ghi 3 Mart (kiểm tra NEW_summary_campaigns
   populate đúng).
4. `python fetch_product_images.py` — điền `products.image_url` (cần ASIN trong
   NEW_sp_order_items / products từ bước 1).
5. Validate lại engine refactor (Mart 3, profit/break_even_acos) so với baseline
   mục 9 (Sales $778.70, Units 75 cho 10/06).

### 5c. 2 LỖI SCHEMA PHÁT SINH SAU RESET — ĐÃ FIX 12/06 (lần re-ingest đầu tiên)

Sau bước 5b, lần re-ingest đầu tiên (`--all --fresh --from 2026-06-10 --to
2026-06-12`) gặp 2 lỗi mới do schema rebuild ở 5b chưa đồng bộ hết với code.
Đã fix bằng `Phase2_Transformation/sql/fix_finances_fk_and_summary_cols.sql`
(đã chạy qua `_dbadmin.py sql`, đã NOTIFY pgrst reload schema) + cập nhật
`supabase_schema.sql` để rebuild lần sau không bị lại:

1. **FK violation `NEW_fin_item_fees_order_id_fkey`** — Finances API lọc theo
   `posted_date`, Orders API lọc theo `purchase_date` → 2 cửa sổ ngày độc lập.
   Một fee/refund event có `order_id` chưa tồn tại trong `NEW_sp_orders` (đơn
   mua trước `--from`) làm `_upsert_chunks` lỗi `23503`, crash toàn bộ batch
   Finances (0 dòng `NEW_fin_item_fees` được ghi → calibrate bỏ qua → fee
   ESTIMATED dùng default ~15% thay vì referral đã calibrate ~16.5%).
   **Fix:** DROP FK `order_id -> NEW_sp_orders` trên `NEW_fin_item_fees` VÀ
   `NEW_fin_refunds` (giữ FK ở `NEW_sp_order_items` vì cùng nguồn/cùng cửa sổ
   với Orders).

2. **`NEW_summary_order_items` thiếu cột `order_status` và `price_source`** —
   2 field này có trong `SummaryOrderItem` dataclass (`aggregation_models.py`)
   từ trước nhưng chưa từng được thêm vào `supabase_schema.sql`. Lỗi
   `PGRST204: Could not find the 'order_status' column` làm `write_summaries()`
   fail ngay ở Mart 1 (items) → Mart 2 (products) và Mart 3 (campaigns) cũng
   không được ghi theo (dict comprehension short-circuit).
   **Fix:** `ALTER TABLE "NEW_summary_order_items" ADD COLUMN ... order_status
   TEXT DEFAULT ''`, `price_source TEXT DEFAULT 'ACTUAL'`.

   Lưu ý: bản thân `transform()` tính đúng (Sales $778.70, 62 đơn, 29 SKU khớp
   baseline 10/06) — chỉ bước WRITE 3 Mart bị fail, không phải lỗi logic.

3. **`NEW_fee_cache` thiếu cột `sample_count`** (phát hiện ở lần chạy
   calibrate kế tiếp, sau khi fix #1+#2) — `calibrate_fee_cache()` upsert
   thêm `sample_count = ref_n + fba_n` (số dòng fee dùng để tính median) nhưng
   cột này chưa có trong schema. **Fix:** thêm `sample_count INTEGER DEFAULT 0`.

### ✅ KẾT QUẢ RE-RUN 12/06 (sau khi fix cả 3 lỗi trên) — PIPELINE CHẠY END-TO-END

```
python Phase1_Ingestion\direct_stream_pipeline.py --all --fresh --from 2026-06-10 --to 2026-06-12
python Phase2_Transformation\transform_engine.py --calibrate --date 2026-06-10 --fresh
```
Phase 1: 176 orders, 178 items, 261 fees (ACTUAL), 4 refunds, 54 adjustments,
Ads 3 ngày (1964 campaign rows + 2514 SP-ASIN rows) — KHÔNG còn crash FK.
Phase 2: calibrate 49 SKU (referral median 16.52%, fba median $3.24), ghi
64 `NEW_summary_order_items` + 31 `NEW_summary_products` + 689
`NEW_summary_campaigns`.

Đối chiếu baseline 10/06:
| Metric | Kết quả | Baseline Sellerboard | Ghi chú |
|---|---|---|---|
| Sales | $778.70 | $778.70 | ✅ khớp tuyệt đối |
| Orders/SKU | 62 / 31 | — | — |
| Amazon fees | -$354.87 (100% ESTIMATED) | -$306.83 / -$323.41 | hơi cao, do referral median áp dụng đồng loạt |
| COGS | $0.00 | -$17.20 | `NEW_product_cogs` còn rỗng — VIỆC seed COGS vẫn deferred |
| Net profit | $232.70 | $247.79 | lệch ~$15, trong khoảng hợp lý |
| Margin | 29.88% | — | — |

0/62 dòng có phí ACTUAL — đúng theo thiết kế hybrid: Amazon settle phí FBA/
referral trễ 1-3+ ngày sau purchase_date, nên phí của đơn mua 10/06 thường
chưa "post" trong cửa sổ Finances đến 12/06. 261 dòng `NEW_fin_item_fees` đã
có thuộc các đơn khác (mua trước 10/06) đã settle trong kỳ này.

**ĐÃ XONG bước 1-3 của checklist 5b.** Bước 4 (fetch_product_images) phải chạy
SAU Phase 3 (vì `products` hiện vẫn rỗng — chỉ có data sau khi
`supabase_to_app_db.py` sync từ `NEW_sp_orders`/`NEW_sp_order_items`). Tiếp
theo: chạy Phase 3 trên VPS (mục 7).

## 6. CÔNG VIỆC KẾ TIẾP — VIỆC #2: REFUND HYBRID (real-time)

Đối xứng hoàn toàn với fee hybrid:
- **Phase 1 mới:** ingest **Returns Report** (`GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA`
  hoặc `GET_XML_RETURNS_DATA_BY_RETURN_DATE`) theo ngày return → bảng `NEW_returns_daily`.
- **Phase 2:** refund chưa có trong `financialEvents` → ESTIMATE cost từ
  `NEW_product_price` × qty + referral hoàn lại − phí xử lý; `refund_state='ESTIMATED'`.
- financialEvents refund → ACTUAL true-up.
→ Refund khớp Sellerboard ngay tại ngày T.

---

## 7. QUY ƯỚC & LƯU Ý KHI LÀM VIỆC

- **Quy ước dấu Sellerboard:** doanh thu DƯƠNG, mọi chi phí ÂM; các cột cộng dồn được.
  `Net = Sales + Promo + Amazon_fees + COGS + Shipping (+ Ads + Refund_cost)`.
- **amazon_fees = Referral (Commission) + FBA Fulfillment** thôi (DigitalServicesFee,
  ShippingChargeback... vào other, KHÔNG vào amazon_fees để khớp định nghĩa SB).
- **`--fresh`** xóa bảng raw NEW_* của nguồn được chọn TRƯỚC khi nạp (reset rồi nạp).
  KHÔNG xóa: NEW_product_price, NEW_product_cogs, NEW_fee_cache, summary (transform --fresh xóa summary riêng).
- **So sánh file** phải so SỐ (tolerance 0.01), KHÔNG so chuỗi — Excel ép số→ngày
  (18.01→datetime), header Cyrillic ('Refund сost'), '0.00' vs ô trống.
- File hệ thống user export đôi khi KHÔNG có header → đọc theo vị trí cột.
- Đơn `Canceled` bị loại khỏi summary (giống Sellerboard); `Pending` VẪN tính sales.
- Bash trong môi trường này thiếu `cat/grep/sed/tail` — dùng python/PowerShell thay.
- **User kiểm soát việc chạy ingest** — Claude soạn lệnh, user tự chạy; chỉ tự
  chạy các thao tác read-only/DB-admin/sửa code khi được phép.
- Lọc output transform (reconciliation in ra stderr): `2>&1 | python -c "import sys;[sys.stdout.write(l) for l in sys.stdin if 'INFO' not in l and 'HTTP Request' not in l]"`.

---

## 8. CHEAT-SHEET LỆNH

```powershell
# Phase 1 (giờ Seller/Pacific): 1 ngày / khoảng / tương tác
python direct_stream_pipeline.py --all --fresh --date 2026-06-10
python direct_stream_pipeline.py --all --fresh --from 2026-06-10 --to 2026-06-11
python direct_stream_pipeline.py --all --fresh        # terminal -> HỎI từ→đến
python direct_stream_pipeline.py --finances --hours 480   # re-pull phí (có principal)

# Phase 2
python transform_engine.py --calibrate --date 2026-06-10 --fresh   # học cache + ghi Master
python transform_engine.py --date 2026-06-10 --no-write            # chỉ xem reconciliation

# Export + so sánh
python reconciliation/export_from_supabase.py 2026-06-10
python reconciliation/reconcile.py

# DB admin
python _dbadmin.py status        # phân bố order_status
python _dbadmin.py feematch      # overlap order<->fee
python _dbadmin.py sql <file.sql>
```

---

## 9. BASELINE SELLERBOARD ĐÃ BIẾT (để đối chiếu)
- 10/06: Sales $778.70, Units 75, Refunds 4, Amazon fees -$306.83 (card) /
  -$323.41 (Order Items file), COGS -$17.20, Ads -$180.06, Net (card) $247.79.
- 03/06: Sales $597.05, Units 47, Amazon fees -$245.26, COGS -$27.10.
- File Sellerboard: `Dr_Hai_Craft_*` (Order Items / Products / Dashboard).
  File hệ thống: `New_order_items-*` / `Order_Items-*` / `Products-*`.
