# Session Handoff — SellerVision: tách Profit/PPC Dashboard + Pipeline Fetch→Upload + Vòng đời dữ liệu + Ảnh sản phẩm

> Repo gốc: `C:\Users\nnh16\ads-trading-system\VPS` (git branch `main`).
> Code chính: `VPS_AMZ/sellerboard_clone/`. Tài liệu nền: `VPS/CLAUDE.md` (guardrails),
> `docs/SESSION_HANDOFF.md`, `docs/DATA_LIFECYCLE.md`, `PIPELINE_3PHASE_README.md`.

## 🎯 Mục tiêu tổng thể

Xây hệ thống "Sellerboard clone" cho seller Amazon **Dr. Hai Craft**, gồm **2 dashboard**:
- **Profit dashboard** — P&L theo SKU/đơn hàng (đã chạy ổn định, đang dùng bảng `NEW_*`).
- **PPC dashboard** — quảng cáo Amazon Ads 5 cấp (Portfolio/Campaign/AdGroup/Keyword/SearchTerm), MỚI.

Định hướng kiến trúc do user chốt:
1. **Gọi API 1 lần dùng chung** cho cả 2 dashboard (không gọi 2 lần).
2. **Tách Fetch ↔ Upload**: fetch lưu raw `.json.gz` local (backup bất biến) → upload đẩy lên Supabase → replay không tốn quota API.
3. **Đổi tên bảng Supabase** cho dễ phân biệt: `Profit_Phase1_*`/`Profit_Phase2_*`, `PPC_Phase1_*`/`PPC_Phase2_*`.
4. **Logic chung ở `shared/`**, mỗi dashboard chỉ là **lớp mỏng** — dễ kiểm soát, sau này có orchestrator chạy tuần tự từng phase tự động (không cần terminal).
5. **Supabase free 500MB** → chỉ giữ **cửa sổ trượt 62 ngày**; dữ liệu cũ ở archive local, hydrate khi cần.
6. Lấy **Sellerboard làm chuẩn** đối chiếu số liệu.

## ✅ Đã hoàn thành

### A. Cấu trúc mới (không xoá code cũ)
- `shared/` — `amz_auth.py` (LWA token cache), `supabase_client.py` (get_supabase_client + upsert_chunks + fetch_all), `config.py` (ADS_BASE, SP_BASE, MARKETPLACE_ID, WINDOW...), `timeutils.py` (Pacific TZ: today/yesterday_pacific, date_range_pacific, utc_window_for_date, now_iso_utc), `ads_api.py` (Ads v3 HTTP: request_report/poll_until_done/download_report/ads_get/ads_post), `retention.py` (prune), `summary_archive.py` (archive/hydrate/evict).
- `profit_dashboard/` — bản SAO 3 phase cũ với tên bảng `Profit_Phase*` (Phase1_Ingestion = LEGACY, Phase1_Upload mới, Phase2_Transformation, Phase3_Application). README.
- `ppc_dashboard/` — pipeline PPC mới (Phase1_Upload + Phase2_PPC_Transform). docs/PPC_PIPELINE_README.md.

### B. Đổi tên bảng Supabase
- Profit raw: `NEW_sp_*`/`NEW_fin_*`/`NEW_ads_*`/`NEW_product_*`/`NEW_fee_*` → `Profit_Phase1_*`.
- Profit summary: `NEW_summary_*` → `Profit_Phase2_*`.
- PPC: `PPC_Phase1_*` (daily + raw mgmt), `PPC_Phase2_summary_*`.
- **Code gốc top-level (`Phase1_Ingestion/`, `Phase2_Transformation/`, `Phase3_Application/`) KHÔNG đụng** — vẫn `NEW_*`. Bảng `Profit_Phase*`/`PPC_*` là bảng MỚI HOÀN TOÀN, phải chạy SQL schema tạo trước.

### C. Phase1_Fetch — landing zone gọi API 1 lần (CHUNG)
`Phase1_Fetch/`: `fetch_spapi.py` (Orders+Finances), `fetch_ads_reports.py` (9 report types, `spCampaigns` chung profit+ppc), `fetch_ads_mgmt.py` (snapshot campaigns/adgroups/keywords/targets/portfolios), `fetch_bid_recs.py`, `fetch_images.py` (ảnh), `ads_report_configs.py`, `paths.py` (nguồn chân lý đường dẫn), `run_fetch.py` (orchestrator, có `--skip-*`).
- Raw lưu **`data/YYYY/MM/DD/`**: `orders.jsonl.gz`, `finances.jsonl.gz`, `ads_<key>.json.gz`, `mgmt_<key>.json.gz`; ảnh ở `data/_persistent/product_images.json.gz`; summary archive `data/YYYY/MM/DD/summary_<table>.json.gz`.
- Orders/finances = JSONL.gz (stream từng dòng, memory-safe); ads/mgmt = JSON.gz.
- File đã tồn tại → skip; `--force` ghi đè.

### D. Phase1_Upload (đọc local → Supabase, KHÔNG gọi API)
- `profit_dashboard/Phase1_Upload/`: `upload_orders.py`, `upload_finances.py`, `upload_ads.py`, `upload_images.py`, `_common.py` (tên bảng + helpers), `run_upload.py` (`--skip-*`, `--cleanup`).
- `ppc_dashboard/Phase1_Upload/`: `upload_ads_reports.py`, `upload_ads_mgmt.py`, `db_writer.py` (map raw→PPC_Phase1_*), `run_upload.py`.

### E. Phase2 PPC
- `transform_campaigns/adgroups/keywords/searchterms/portfolios.py` → `PPC_Phase2_summary_*` (map 25 cột Sellervision PPC CSV). `calc_derived_metrics.py` (ACOS/CVR/CPC/CTR/ROAS/topOfSearch%/BE-bid). `db_schema.sql`. `run_ppc_transform.py`.
- **Bảng bulk mirror** `PPC_Phase2_bulk_sp` (`transform_bulk.py`) — mô phỏng file Amazon "Sponsored Products Bulk Operations" (53 cột), 1 dòng/entity (Campaign/AdGroup/Keyword/Target) = settings raw + metrics tổng hợp cả kỳ. Chạy `run_ppc_transform.py --bulk` (hoặc `--bulk-only`).

### F. Vòng đời dữ liệu (chống tràn 500MB)
- `shared/retention.py` + `manage_supabase.py` mỗi dashboard: lệnh `archive` (Supabase→local gz), `hydrate` (local→Supabase), `evict`, `prune` (xoá > cửa sổ).
- Cửa sổ mặc định **62 ngày** (`SUPABASE_WINDOW_DAYS`), raw có thể nhỏ hơn (`SUPABASE_RAW_WINDOW_DAYS`).
- KHÔNG prune: profit persistent (`product_price`/`product_cogs`/`fee_cache`/`product_images`), PPC snapshot mgmt (bounded theo id thực thể).
- doc: `docs/DATA_LIFECYCLE.md`.

### G. Audit + sửa Profit frontend (chuẩn Sellerboard)
- Đối chiếu 2 file Sellerboard: Products 31 cột = `SummaryProduct`, Order Items 21 cột = `SummaryOrderItem` → **khớp 100%** tầng dữ liệu. Công thức tổng đúng (đã kiểm số: Margin=Net/Sales, ROI=Net/|COGS|, Real ACOS=|ads|/Sales, **Est payout = Net + |COGS|**).
- **(2) ĐÃ SỬA**: Margin/ROI/Real ACOS hiển thị **2 chữ số thập phân** (trước 1). Sửa `analytics_aggregator.py` (round ...,2) + `render_performance.js` (toFixed(2)).
- **(3) ĐÃ SỬA**: popover P&L per-SKU bổ sung Margin/ROI/Real ACOS/%Refunds + Gross profit + Est payout (trước chỉ thẻ kỳ có). Aggregator phát thêm real_acos/gross_profit/estimated_payout/promo/refunds_pct.

### H. Pipeline ảnh sản phẩm (3 phase) — MỚI
- API: SP-API Catalog Items `searchCatalogItems` (2022-04-01, batch 20 ASIN, includedData=images, ảnh MAIN).
- **P1**: `fetch_images.py` quét ASIN từ orders local → `data/_persistent/product_images.json.gz`; `upload_images.py` → bảng `Profit_Phase1_product_images` (asin PK, persistent).
- **P2**: cột `image_url` ở `Profit_Phase2_summary_products`/`_order_items`; điền bằng `update_summary_images.py` (decoupled, KHÔNG sửa transform_engine).
- **P3**: `analytics_aggregator._image_lookup` (raw SQL, tránh sửa ORM backend) gắn ảnh cho Products + Order Items; `render_performance.js` thêm thumbnail dòng Order Items (Products đã có). Wired `run_fetch --skip-images`, profit `run_upload --skip-images`.

## 🔄 Đang dở / Chưa hoàn thiện

- **Profit (1) — phí thật referral/FBA**: popover hiện đang ƯỚC LƯỢNG referral = 16.5%×sales (hàm `splitAmazonFees` ở render_performance.js + `_split_amazon_fees` ở aggregator). Số thật có sẵn trong `Profit_Phase1_fin_item_fees.fee_type` (Commission vs FBA). **CHƯA sửa.** → cần: thêm cột `referral_fee`/`fba_fee` vào `Profit_Phase2_summary_*` + sửa `transform_engine.py` ghi split thật + aggregator/JS đọc số thật + chạy lại transform.
- **Chưa CHẠY thực tế** bất kỳ fetch/upload/transform nào (mới viết code, chưa có credentials chạy). Các bảng `Profit_Phase*`/`PPC_*` chưa được tạo trên Supabase.
- **Frontend chưa deploy**: sửa ở file nguồn `Phase3_Application/data_bridge/patch_scripts/render_performance.js` (đã khôi phục file nguồn — trước bị thiếu); cần chạy `patch_frontend.py` + restart service để có hiệu lực.
- **Website vẫn đọc bảng `NEW_summary_*`** (qua ORM model SummaryProduct/SummaryOrderItem). Chưa repoint sang `Profit_Phase2_*` (cần Phase3 patch + sửa ORM model = đụng backend → qua patch).

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)

1. **Tạo bảng trên Supabase**: chạy `profit_dashboard/Phase2_Transformation/sql/supabase_schema.sql` (gồm bảng ảnh + cột image_url) và `ppc_dashboard/Phase2_PPC_Transform/db_schema.sql` (gồm `PPC_Phase2_bulk_sp`).
2. **Chạy thử end-to-end 1 ngày** (cần `.env` thật): `Phase1_Fetch/run_fetch.py --date <D>` → mỗi `Phase1_Upload/run_upload.py --date <D>` → Phase2 transform → `manage_supabase.py archive` → `prune`.
3. **Deploy profit (2)+(3)**: `python Phase3_Application/data_bridge/patch_scripts/patch_frontend.py` + restart service `sellervision`. Kiểm tra trên web.
4. **Làm Profit (1)** — phí thật (xem mục Đang dở). Đây là việc profit còn lại duy nhất.
5. **Phase 3 cho PPC**: tạo frontend/backend cho PPC dashboard (chưa có) + hàm tính thông số hiển thị.
6. **Phase 3 repoint serving**: trỏ website đọc `Profit_Phase2_*` thay `NEW_*` (Phase3 patch) + endpoint `/api/data-window` + nút "nạp khoảng cũ" (hydrate on-demand).
7. **Orchestrator tự động** chạy tuần tự các phase (mục tiêu cuối của user).

## 🏗️ Kiến trúc / Cấu trúc hệ thống

```
Amazon API ──(Phase1_Fetch: gọi 1 lần)──► data/ raw JSON.gz (local, giữ mãi)
   │                                            │
   │                        ┌───────────────────┴───────────────────┐
   │                  profit Phase1_Upload                    ppc Phase1_Upload
   │                        ▼                                       ▼
   └──────────────► Supabase Profit_Phase1_* (62d)        Supabase PPC_Phase1_* (62d)
                            │                                       │
                    Phase2 transform                        Phase2 transform (+bulk)
                            ▼                                       ▼
                  Profit_Phase2_summary_* (62d)           PPC_Phase2_summary_* (62d)
                            │                                       │
                  Phase3 (aggregator + render_performance.js)   (Phase3 PPC: CHƯA)
                            ▼
                    Web app app.tap2soul.com
```
- Stack: Python (requests, supabase-py, psycopg, pandas, openpyxl), FastAPI + SQLAlchemy backend, JS thuần frontend (Tailwind), Supabase Postgres (vừa pipeline buffer vừa DB sống web app).
- Timezone: Pacific (America/Los_Angeles), DST tự động. Phase1 lưu UTC nguyên; group-by ngày ép UTC→Pacific trước `.date()`; ads report_date đã là Pacific.
- Memory-safety: phân trang ≤100 records, upsert từng chunk, `del` + `gc.collect()`.

## 📁 Cấu trúc thư mục quan trọng

```
VPS/VPS_AMZ/sellerboard_clone/
├── shared/                          # ★ logic chung
│   ├── amz_auth.py  supabase_client.py  config.py  timeutils.py
│   ├── ads_api.py  retention.py  summary_archive.py
├── Phase1_Fetch/                    # ★ gọi API 1 lần (chung profit+ppc)
│   ├── fetch_spapi.py  fetch_ads_reports.py  fetch_ads_mgmt.py
│   ├── fetch_bid_recs.py  fetch_images.py
│   ├── ads_report_configs.py  paths.py  run_fetch.py  .env(.example)
│   └── data/YYYY/MM/DD/...  +  data/_persistent/product_images.json.gz
├── profit_dashboard/
│   ├── Phase1_Upload/               # ★ upload_orders/finances/ads/images + run_upload + _common
│   ├── Phase2_Transformation/       # transform_engine.py + update_summary_images.py + sql/supabase_schema.sql
│   ├── Phase3_Application/          # data_bridge (analytics_aggregator, patch_scripts/render_performance.js)
│   ├── manage_supabase.py           # archive/hydrate/evict/prune
│   ├── Phase1_Ingestion/_LEGACY.md  # code cũ — tham khảo, KHÔNG chạy
│   └── README.md
├── ppc_dashboard/
│   ├── Phase1_Upload/               # upload_ads_reports/mgmt + db_writer + run_upload
│   ├── Phase2_PPC_Transform/        # transform_* + transform_bulk + calc_derived_metrics + db_schema.sql + run_ppc_transform
│   ├── manage_supabase.py
│   ├── Phase1_PPC_Ingestion/_LEGACY.md
│   └── docs/PPC_PIPELINE_README.md
├── backend/  frontend/              # production app.tap2soul.com — KHÔNG sửa tay (qua patch_scripts)
├── Phase1_Ingestion/ Phase2_Transformation/ Phase3_Application/   # gốc NEW_* (production hiện tại)
└── docs/  DATA_LIFECYCLE.md  PIPELINE_3PHASE_README.md  SESSION_HANDOFF.md
```

## ⚙️ Biến môi trường & Cấu hình (.env)

```env
# ── Phase1_Fetch/.env  (CHỈ Amazon, không cần Supabase) ──
AMAZON_SPI_CLIENT_ID=        AMAZON_SPI_CLIENT_SECRET=     AMAZON_SPI_REFRESH_TOKEN=
AMAZON_SPI_MARKETPLACE_ID=ATVPDKIKX0DER
AMAZON_ADS_CLIENT_ID=        AMAZON_ADS_CLIENT_SECRET=     AMAZON_ADS_REFRESH_TOKEN=
ADS_PROFILE_ID=
SELLER_TIMEZONE=America/Los_Angeles
ADS_REQUEST_GAP_SECONDS=20   ADS_POLL_INTERVAL_SECONDS=15  ADS_POLL_TIMEOUT_SECONDS=600
ORDER_ITEMS_DELAY_SECONDS=1.0  FINANCES_PAGE_DELAY_SECONDS=1.0

# ── */Phase1_Upload/.env  (CHỈ Supabase) ──
SUPABASE_URL=                SUPABASE_SERVICE_KEY=
SELLER_TIMEZONE=America/Los_Angeles
SUPABASE_WINDOW_DAYS=62      SUPABASE_RAW_WINDOW_DAYS=     # để trống = bằng WINDOW
DATABASE_URL=                # chỉ cần khi run_upload --cleanup (dedup psycopg)
```

## 🔑 Thông số kỹ thuật quan trọng

- **Ads API v3**: base `https://advertising-api.amazon.com`; auth Bearer LWA + header `Amazon-Advertising-API-Scope` (profile id) — KHÔNG SigV4. Report async: POST `/reporting/reports` → poll → download GZIP_JSON. 425 duplicate → tái dùng reportId. Mgmt v2: `/sp/campaigns|adGroups|keywords|targets`, `/portfolios`, `/sp/keywords/bidRecommendations`.
- **SP-API**: base `https://sellingpartnerapi-na.amazon.com`; LWA-only (x-amz-access-token) đủ cho Orders/Finances/Catalog. Catalog Items `/catalog/2022-04-01/items` batch 20 ASIN.
- **Fee model (ĐÃ KIỂM CHỨNG, đừng "sửa" về 15%)**: referral thật = **16.5%** principal (15% Amazon + 10% VAT VN). Sellerboard cũng ước 16.5% + FBA per-SKU. Phí Amazon TRỄ 8-10 ngày → finances lấy cửa sổ rộng hơn orders (mặc định 21 ngày).
- **Quy ước dấu (Sellerboard)**: doanh thu DƯƠNG, mọi chi phí ÂM. `Gross = Sales+Promo+Amazon_fees+COGS+Shipping`; `Net = Gross+Ads+Refund_cost+Expenses`; `amazon_fees = Referral + FBA`.
- **Cột v3 report KHÁC db_writer kỳ vọng**: report trả `keyword`/`searchTerm`/`targeting` (KHÔNG phải `keywordText`/`query`/`targetingText`); status/bid keyword không có trong report (lấy từ mgmt raw ở Phase2). db_writer đã đọc fallback.
- **date_label**: orders/finances 1 ngày = "YYYY-MM-DD", khoảng = per-day (iter_days); ads luôn per-day.
- **Sellerboard PPC CSV**: 5 file = 5 cấp, đều 25 cột. `Strategy` + `Automation status` = ĐỘC QUYỀN Sellervision, KHÔNG có từ Amazon API.
- **xlsx Amazon bulk**: sheet "Sponsored Products Campaigns" 53 cột (Entity discriminator + IDs + settings + metrics) → bảng `PPC_Phase2_bulk_sp`.

## 🐛 Vấn đề đã gặp & Cách giải quyết

- **`_ROOT` sai 3× `".."`** trong file PPC ban đầu → trỏ nhầm `VPS_AMZ` thay vì `sellerboard_clone` (nơi có `shared/`). ĐÃ sửa còn 2× (10 file). py_compile không bắt được lỗi này (chỉ lỗi runtime import) → phải test `--help` để ép full import.
- **PostgREST 21000** "cannot affect row a second time": GỘP rows theo khoá conflict TRƯỚC upsert (orders/finances).
- **Finances tiền ở key `CurrencyAmount`** (không phải `Amount`) → helper `money()` đọc cả hai.
- **CreatedBefore tương lai** → Amazon từ chối → cap None nếu sát "now".
- **File nguồn `patch_scripts/render_performance.js` bị thiếu** (chỉ còn bản copy ở `frontend/`) → đã khôi phục bằng `cp frontend/render_performance.js patch_scripts/`.
- **PowerShell classifier tạm không khả dụng** vài lúc → dùng Bash + Python thay.

## 🚫 Quyết định đã được xác nhận (không thay đổi)

1. **Raw GIỮ trên Supabase** (chia table để dễ thống kê) — user chọn, KHÔNG chuyển sang "transform đọc local". Phase2 vẫn đọc raw từ Supabase.
2. **Cửa sổ 62 ngày** (≈2 tháng cho thẻ "tháng trước"); khoảng cũ hơn → hydrate summary gz local lên Supabase rồi evict (KHÔNG transform lại; lấy TRỌN tháng 30-31 ngày, KHÔNG liên quan window raw).
3. **Mô hình A**: website đọc THẲNG bảng summary (đã sẵn vậy qua analytics_aggregator) — KHÔNG đẩy-theo-từng-lần-chọn (mô hình B).
4. **Logic chung vào `shared/`, dashboard chỉ lớp mỏng**; chia folder để dễ kiểm soát + chuẩn bị orchestrator.
5. **KHÔNG sửa lõi `transform_engine`** cho ảnh (profit đang ổn định) → dùng `update_summary_images.py` decoupled.
6. **Sửa frontend qua file nguồn `patch_scripts/render_performance.js`** + `patch_frontend.py` (có backup/rollback) — KHÔNG sửa tay `frontend/`.
7. **xlsx → bảng Phase2 mirror** (không chỉ thêm cột vào bảng cũ).
8. Profit fixes thứ tự: **(2)+(3) trước** (tầng hiển thị), **(1) sau** (cần migrate schema + chạy lại transform).

## 💡 Context bổ sung

- **GUARDRAILS CỨNG** (xem `VPS/CLAUDE.md`): KHÔNG sửa tay `backend/`+`frontend/` (chỉ qua patch_scripts); KHÔNG drop/sửa bảng không prefix `NEW_`; `--fresh` chỉ xoá raw nguồn được chọn, KHÔNG xoá product_price/cogs/fee_cache; user kiểm soát việc chạy ingest/transform (Claude soạn lệnh, user tự chạy) — Claude chỉ tự chạy read-only/sửa code/khi được phép rõ.
- **Bash thiếu** `cat/grep/sed/tail` trong môi trường này — dùng Python hoặc tool chuyên dụng (Read/Grep/Glob).
- **VPS**: `sellervision@<VPS_IP>`, SSH chỉ password (paramiko), service systemd `sellervision`, venv `backend/venv`, DB = Supabase Postgres qua `DATABASE_URL` (không phải SQLite). Helper gốc không commit: `_dbadmin.py`, `_vps.py`, `_vps_upload.py`.
- **analytics_aggregator.py** đọc qua ORM `app.models.SummaryProduct/SummaryOrderItem` → muốn đọc cột mới (image_url/referral_fee) qua ORM phải sửa model trong `backend/` (đụng guardrail) → đã né bằng raw SQL `_image_lookup`. Cùng cách sẽ áp cho phí thật nếu cần.
- Tất cả code MỚI đã `py_compile` OK + `node --check` OK + test `--help` import sạch. **Chưa chạy thực tế với credentials.**
- File reconciliation số liệu: so SỐ (tolerance 0.01) KHÔNG so chuỗi (Excel ép số→ngày, header Cyrillic `Refund сost`, `'0.00'` vs ô trống); `Canceled` loại khỏi summary, `Pending` vẫn tính sales.

---
*Session kết thúc lúc: 2026-06-17*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
