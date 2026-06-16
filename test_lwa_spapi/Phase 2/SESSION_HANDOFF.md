# Session Handoff — Ads Trading System: Amazon API → Supabase Pipeline (Phase 2)

## 🎯 Mục tiêu tổng thể

Hệ thống chính là **SellerVision clone** (FastAPI + gunicorn + SQLite `sellervision.db`,
domain `https://app.tap2soul.com`, chạy trên VPS tại `~/VPS_AMZ/sellerboard_clone/`),
đang **migrate sang Supabase (PostgreSQL)**.

Phase 1 + Phase 2 (thư mục `VPS/test_lwa_spapi/`) là một **bộ công cụ debug/data
pipeline độc lập**, được xây để:
1. Gọi trực tiếp Amazon SP-API (Orders, Finances) + Advertising API (SP/SB/SD reports).
2. Ghi dữ liệu **thẳng vào Supabase** (bảng `"NEW_*"`) — KHÔNG qua file JSON hay
   tích lũy RAM trung gian (yêu cầu cứng của user: tránh mất dữ liệu nếu RAM tràn).
3. Từ dữ liệu Supabase, tổng hợp lại thành báo cáo **giống định dạng CSV +
   Dashboard của Sellerboard thật** để đối chiếu số liệu.

Mục tiêu cuối: số liệu từ pipeline này phải **khớp với Sellerboard thật** cho
cùng 1 ngày, từ đó tìm và sửa chênh lệch trong logic của Sellerboard clone.

---

## ✅ Đã hoàn thành

### 1. Direct-to-Supabase streaming ingestion (bỏ hoàn toàn file/RAM trung gian)
- Tạo `_supabase_ingest.py` (module dùng chung):
  - `get_supabase_client()`, `_float()`, `_int()`, `_upsert_chunks()` (chunk 100 dòng/lần)
  - `ingest_orders_page()` → upsert `"NEW_sp_orders"` / `"NEW_sp_order_items"`
  - `ingest_finance_events_page()` → upsert `"NEW_fin_item_fees"` / `"NEW_fin_refunds"` / `"NEW_fin_adjustments"`
  - `ingest_ads_report()` → upsert `"NEW_ads_campaigns_daily"`
- Sửa cả 3 script `fetch_24h_orders.py`, `fetch_24h_finances.py`, `fetch_24h_ads.py`:
  mỗi trang/report tải về → upsert ngay vào Supabase → `del ...; gc.collect()`.
  Không còn file `raw_data/*.json`, không còn bước `ingest_pipeline.py` riêng.

### 2. Tài liệu pipeline end-to-end — `HOW_TO_USE.md`
- Mô tả toàn bộ flow: Call API → Supabase (`NEW_*` tables) → nhập tay COGS/expenses
  (`NEW_product_cogs`, `NEW_indirect_expenses`) → VIEW `"NEW_v_order_items_csv"`
  (= file CSV Sellerboard) + FUNCTION `"NEW_fn_daily_summary"(date)` (= Dashboard).
- Có bảng "file nào làm gì", checklist chạy hằng ngày.

### 3. Khoảng thời gian call API tuỳ chỉnh qua `.env`
Thêm các biến: `LOOKBACK_HOURS`, `ORDERS_CREATED_AFTER`/`ORDERS_CREATED_BEFORE`,
`FINANCES_POSTED_AFTER`/`FINANCES_POSTED_BEFORE`, `ADS_DAYS_AGO`, `ADS_REPORT_DATE`.

### 4. Hỏi tương tác chọn ngày + xử lý timezone
- Tạo `_time_range.py`:
  - `SELLER_TIMEZONE` (`.env`, default `America/Los_Angeles`) = timezone Sellerboard
    dùng để tính "1 ngày" (Settings → General → Time Zone).
  - `maybe_prompt()`: nếu chạy ở terminal tương tác **và** chưa có `.env` override
    → hỏi "1. 24h gần nhất / hôm qua (mặc định)" hay "2. Một ngày cụ thể (YYYY-MM-DD)".
    Chọn 2 → tự quy đổi ngày đó sang UTC range (cho Orders/Finances) hoặc dùng thẳng
    (cho Ads, vì Ads API trả `date` theo timezone tài khoản quảng cáo).
  - Non-interactive (cron) hoặc đã có override → bỏ qua prompt, dùng mặc định.
- Tích hợp vào cả 3 script `fetch_24h_*.py`.
- Sửa `run_all.py`: hỏi **1 LẦN DUY NHẤT** cho cả 3 script (kiểm tra
  `env_overrides_present()` trước), rồi truyền `start_utc`/`end_utc`/`day_label`
  qua env vars (`ORDERS_CREATED_AFTER/BEFORE`, `FINANCES_POSTED_AFTER/BEFORE`,
  `ADS_REPORT_DATE`) cho từng subprocess.
- Cập nhật `.env.example`: thêm `SELLER_TIMEZONE`, `ORDERS_CREATED_BEFORE`.
- Cập nhật `HOW_TO_USE.md` mục 1.5: giải thích prompt + giải thích timezone
  (SP-API=UTC, Ads API=timezone tài khoản quảng cáo, Sellerboard=timezone tự
  cấu hình) + cách set `SELLER_TIMEZONE` cho khớp Sellerboard.

### 5. Tái cấu trúc thư mục — gom toàn bộ pipeline đang dùng vào `Phase 2/`
Toàn bộ file đang hoạt động được chuyển vào `VPS/test_lwa_spapi/Phase 2/`:
`_auth.py`, `_supabase_ingest.py`, `_time_range.py`, `fetch_24h_orders.py`,
`fetch_24h_finances.py`, `fetch_24h_ads.py`, `run_all.py`, `.env`, `.env.example`,
`requirements.txt`, `start.bat`, `start.py`, `setup.bat`, `supabase_schema.sql`,
`HOW_TO_USE.md`, `Phase_2.md`.

Đã sửa kèm theo:
- `start.bat`: `cd /d` trỏ vào `Phase 2\`, bỏ tham chiếu `raw_data\` cũ,
  đổi `pip install requests python-dotenv` → `pip install -r requirements.txt`.
- `setup.bat`: bỏ bước `mkdir raw_data`.
- `HOW_TO_USE.md`: sửa toàn bộ `cd ...` trỏ vào `Phase 2\`, sửa link sang
  `../Phase 1/HUONG_DAN_CHAY.md`, `../ingest_pipeline.py`, thêm dòng `_time_range.py`
  vào bảng "File nào làm gì".
- `Phase_2.md`: thêm mục 5 mô tả việc tái cấu trúc này.

✅ Đã verify: `python -m py_compile` toàn bộ `.py` trong `Phase 2/` — OK.
✅ Đã verify: import `_auth`, `_supabase_ingest`, `_time_range` + `load_dotenv()`
   từ `Phase 2/` hoạt động đúng (SUPABASE_URL, SELLER_TIMEZONE, CLIENT_ID đọc được).
✅ Đã grep toàn project — không còn reference nào tới đường dẫn cũ của các file
   đã di chuyển.

---

## 🔄 Đang dở / Chưa hoàn thiện

- **Chưa chạy thử thực tế** `run_all.py` (hoặc từng `fetch_24h_*.py`) với prompt
  tương tác + gọi API thật từ vị trí mới `Phase 2/` — chỉ mới verify syntax +
  import, chưa test full flow end-to-end (gọi Amazon API thật + upsert Supabase thật).
- **Chưa đối chiếu số liệu** Orders/Finances/Ads cho 1 ngày cụ thể với Sellerboard
  dashboard thật (đây là mục tiêu cuối của Phase 1+2, vẫn pending).
- **Supabase migration cho app chính** (`sellervision.db` → Supabase, FastAPI app
  tại `app.tap2soul.com`) — pipeline này chỉ là tool debug song song, migration
  chính vẫn đang tạm dừng (xem `HANDOFF_SUPABASE_MIGRATION.md` ở root project).
- Các file legacy ở root `test_lwa_spapi/` (`raw_data/`, `ingest_pipeline.py`,
  `discover_columns.py`, `inspect_raw_data.py`, `test_spapi.py`, `run.log`,
  `README.txt`) chưa được dọn dẹp/archive — vẫn còn nằm đó, không dùng nữa.
- Thư mục `Phase 1/` đang được user tự tổ chức song song (đã thấy `CALL_API_PLAN.md`,
  `HUONG_DAN_CHAY.md`, `Phase_1.md`, `SELLERBOARD_API_ANALYSIS.md` trong đó) — chưa
  rõ có cần dọn thêm gì không.

---

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)

1. **Chạy thử thực tế** từ `Phase 2/`:
   ```powershell
   cd "C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\Phase 2"
   python run_all.py
   ```
   - Thử nhập `2` + một ngày cụ thể (vd ngày gần nhất có dữ liệu trên Sellerboard)
     để verify prompt + quy đổi timezone + upsert Supabase hoạt động đúng.
   - Thử Enter (mặc định 24h/hôm qua) để verify behavior cron không đổi.
2. **Đối chiếu số liệu** ngày đã chọn ở bước 1 với Sellerboard dashboard thật:
   - Chạy `SELECT * FROM "NEW_fn_daily_summary"('YYYY-MM-DD');` trong Supabase
     SQL Editor, so với các thẻ số trên Dashboard Sellerboard.
   - Chạy `SELECT * FROM "NEW_v_order_items_csv" WHERE order_date = 'YYYY-MM-DD';`
     so với file CSV "Order Items" export từ Sellerboard.
   - Ghi lại từng dòng chênh lệch (Sales, FBA fee, Referral fee, Refund cost, Ads cost).
3. Nếu có chênh lệch → xác định nguyên nhân (COG, ngày attribution, dấu +/- của
   RefundCommission, timezone `SELLER_TIMEZONE` chưa đúng...) → sửa logic tương ứng
   (có thể trong VIEW/FUNCTION `NEW_*` ở `supabase_schema.sql`, hoặc trong code
   chính của Sellerboard clone trên VPS).
4. (Song song, không gấp) Dọn dẹp file legacy ở root `test_lwa_spapi/` —
   archive hoặc xoá `raw_data/`, `ingest_pipeline.py`, `discover_columns.py`,
   `inspect_raw_data.py`, `test_spapi.py`, `run.log` nếu xác nhận không cần nữa.
5. Tiếp tục migration Supabase cho app chính theo `HANDOFF_SUPABASE_MIGRATION.md`
   (đang tạm dừng, chờ quyết định của user).

---

## 🏗️ Kiến trúc / Cấu trúc hệ thống

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────────────┐
│  Amazon SP-API   │     │                       │     │                         │
│  Amazon Ads-API  │────▶│  3 script fetch_*.py  │────▶│        SUPABASE         │
│  - Orders        │     │  (upsert TRỰC TIẾP,   │     │   (PostgreSQL, bảng     │
│  - OrderItems    │     │   từng trang/report,  │     │    "NEW_*")             │
│  - Finances      │     │   không qua RAM/file  │     │  6 bảng dữ liệu thô     │
│  - Ads reports   │     │   trung gian)         │     │  + 2 bảng nhập tay      │
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

- **Auth SP-API**: LWA OAuth (refresh token) + tuỳ chọn AWS SigV4 (STS AssumeRole).
- **Auth Ads-API**: LWA Bearer token RIÊNG (client id/secret riêng) +
  header `Amazon-Advertising-API-Scope: {profile_id}` — KHÔNG dùng SigV4.
- **Streaming pattern**: mỗi trang/report → transform → upsert Supabase (chunk 100)
  → `del`/`gc.collect()` → trang tiếp theo. Không có file JSON trung gian.
- **Date selection**: `_time_range.py` — prompt tương tác (terminal) hoặc `.env`
  override (cron), quy đổi qua `SELLER_TIMEZONE`.
- **App chính (song song, đang migrate)**: FastAPI + gunicorn + SQLite
  (`sellervision.db`) → Supabase, domain `https://app.tap2soul.com`, VPS path
  `~/VPS_AMZ/sellerboard_clone/`.

---

## 📁 Cấu trúc thư mục quan trọng

```
ads-trading-system/
├── HANDOFF_SUPABASE_MIGRATION.md      ← quy tắc an toàn deploy VPS (app chính)
├── VPS/
│   └── test_lwa_spapi/
│       ├── Phase 1/                   ← tài liệu/script cũ Phase 1 (user tự tổ chức)
│       │   ├── CALL_API_PLAN.md
│       │   ├── HUONG_DAN_CHAY.md
│       │   ├── Phase_1.md
│       │   └── SELLERBOARD_API_ANALYSIS.md
│       ├── Phase 2/                   ← ★ PIPELINE ĐANG DÙNG (session này) ★
│       │   ├── _auth.py               # LWA token, STS SigV4, Ads auth
│       │   ├── _supabase_ingest.py    # upsert vào Supabase NEW_*
│       │   ├── _time_range.py         # prompt ngày + quy đổi timezone
│       │   ├── fetch_24h_orders.py    # SP-API Orders + OrderItems
│       │   ├── fetch_24h_finances.py  # SP-API Financial Events
│       │   ├── fetch_24h_ads.py       # Advertising API reports
│       │   ├── run_all.py             # chạy 3 script, hỏi ngày 1 lần
│       │   ├── start.bat / start.py / setup.bat
│       │   ├── requirements.txt
│       │   ├── .env / .env.example
│       │   ├── supabase_schema.sql    # tạo toàn bộ bảng/view/function NEW_*
│       │   ├── HOW_TO_USE.md          # tài liệu end-to-end
│       │   ├── Phase_2.md             # tóm tắt công việc Phase 2
│       │   └── SESSION_HANDOFF.md     # ← file này
│       ├── Phase3/                    ← KHÔNG LIÊN QUAN (project auth/backend/frontend khác, đừng động vào)
│       ├── raw_data/                  ← legacy, không dùng
│       ├── ingest_pipeline.py         ← legacy
│       ├── discover_columns.py        ← legacy/debug
│       ├── inspect_raw_data.py        ← legacy/debug
│       ├── test_spapi.py              ← legacy/debug
│       ├── run.log
│       └── README.txt
```

---

## ⚙️ Biến môi trường & Cấu hình (`.env` trong `Phase 2/`)

```env
# SP-API (Orders, Finances)
AMAZON_SPI_CLIENT_ID=
AMAZON_SPI_CLIENT_SECRET=
AMAZON_SPI_REFRESH_TOKEN=
AMAZON_SPI_MARKETPLACE_ID=ATVPDKIKX0DER

# AWS SigV4 (tuỳ chọn, nếu có dùng STS AssumeRole)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_ROLE_ARN=arn:aws:iam::ACCOUNT_ID:role/TEN_ROLE
AWS_REGION=us-east-1

# Advertising API (RIÊNG với SP-API, không dùng chung client id/secret)
AMAZON_ADS_REFRESH_TOKEN=
ADS_PROFILE_ID=                  # chạy fetch_24h_ads.py để tool tự in ra nếu để trống

# Supabase
SUPABASE_URL=                    # https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=            # service_role key — KHÔNG commit lên git

# Timezone Sellerboard dùng để tính "1 ngày" (Settings → General → Time Zone)
SELLER_TIMEZONE=America/Los_Angeles

# Khoảng thời gian call API (để trống = mặc định 24h / hôm qua / hỏi tương tác)
LOOKBACK_HOURS=24
ORDERS_CREATED_AFTER=
ORDERS_CREATED_BEFORE=
FINANCES_POSTED_AFTER=
FINANCES_POSTED_BEFORE=
ADS_DAYS_AGO=1
ADS_REPORT_DATE=
```

> Lưu ý: `AMAZON_ADS_REFRESH_TOKEN` cần `AMAZON_ADS_CLIENT_ID`/`AMAZON_ADS_CLIENT_SECRET`
> riêng (xem `_auth.py`) — KHÔNG dùng được `AMAZON_SPI_CLIENT_ID/SECRET` (lỗi 400/401).

---

## 🔑 Thông số kỹ thuật quan trọng

- **SP-API base**: `https://sellingpartnerapi-na.amazon.com`
- **Endpoints**: `GET /orders/v0/orders`, `GET /orders/v0/orders/{id}/orderItems`,
  `GET /finances/v0/financialEvents` (NextToken pagination)
- **Ads API**: async report flow — `POST /reporting/reports` → poll
  `GET /reporting/reports/{id}` đến `COMPLETED` → download GZIP JSON
- **Supabase tables (`"NEW_*"`, cần double-quote vì chữ hoa)**:
  - `"NEW_sp_orders"`, `"NEW_sp_order_items"` — dữ liệu Orders
  - `"NEW_fin_item_fees"`, `"NEW_fin_refunds"`, `"NEW_fin_adjustments"` — Finances
  - `"NEW_ads_campaigns_daily"` — Ads spend theo ngày (SP/SB/SD)
  - `"NEW_product_cogs"`, `"NEW_indirect_expenses"` — **nhập tay**
  - `"NEW_v_order_items_csv"` (VIEW) — format giống CSV Sellerboard
  - `"NEW_fn_daily_summary"(date)` (FUNCTION) — format giống Dashboard cards
- **CHUNK_SIZE = 100** cho mọi upsert (trong `_supabase_ingest.py`)
- **Timezone rules** (quan trọng để khớp Sellerboard):
  - SP-API trả `CreatedDate`/`PostedDate` theo **UTC** (suffix `Z`)
  - Ads API trả `date` theo **timezone tài khoản quảng cáo** (~`America/Los_Angeles`
    cho seller US, tự xử lý PDT/PST)
  - Sellerboard tính "1 ngày" theo **Settings → General → Time Zone** (cấu hình được)
  - → `SELLER_TIMEZONE` trong `.env` phải khớp với cấu hình Sellerboard

---

## 🐛 Vấn đề đã gặp & Cách giải quyết

(Carry từ Phase 1, vẫn áp dụng cho Phase 2)

| Lỗi | Nguyên nhân | Fix |
|---|---|---|
| `403` Orders API | AWS SigV4 ký `url` không có query params nhưng request gửi `full_url` có params | Build `full_url` (sorted params) **trước**, ký `full_url` |
| `400` Finances API | `PostedBefore` quá gần hiện tại (data chưa finalize) | Bỏ `PostedBefore` trừ khi backfill quá khứ |
| `KeyError: 'Amount'` | Amazon dùng key `CurrencyAmount`, không phải `Amount` | Helper `_amt(obj, key="CurrencyAmount")` dùng `.get()` |
| `400`/`401` LWA Ads API | Dùng chung `AMAZON_SPI_CLIENT_ID/SECRET` cho Ads refresh token | Thêm `ADS_CLIENT_ID`/`ADS_CLIENT_SECRET` riêng trong `_auth.py` |
| `429 Throttled` Ads reports | POST nhiều report liên tiếp quá nhanh | `time.sleep(5)` giữa các POST + retry tự động khi 429 |
| `400` cột report không hợp lệ | SB Campaigns dùng tên cột khác SP (không suffix `Nd`) | Đọc error message 400 (Amazon liệt kê "Allowed values") để sửa cột |

Trong session này (Phase 2): không gặp lỗi runtime mới — chỉ verify bằng
`py_compile` + import smoke test, **chưa chạy full flow thật** (xem mục "Đang dở").

---

## 🚫 Quyết định đã được xác nhận (không thay đổi)

- **Direct-to-Supabase, không qua file/RAM trung gian** — yêu cầu cứng của user:
  *"các code call API phải lưu luôn dữ liệu vào Supabase thay vì trung gian qua RAM"*
  (lý do: tránh mất dữ liệu nếu RAM tràn giữa chừng).
- **Prompt tương tác chỉ hỏi khi terminal tương tác VÀ chưa có `.env` override** —
  để cron/Task Scheduler không bị treo chờ input, vẫn chạy mặc định 24h/hôm qua.
- **`run_all.py` hỏi ngày 1 LẦN cho cả 3 script** (không hỏi 3 lần riêng lẻ).
- **`SELLER_TIMEZONE` default = `America/Los_Angeles`** — phổ biến nhất cho seller US,
  user cần tự verify lại timezone thật trong Sellerboard Settings.
- **Toàn bộ pipeline đang dùng nằm trong `Phase 2/`** (user chọn option "Toàn bộ
  pipeline đang dùng" khi được hỏi phạm vi gom file) — các file legacy/Phase 1
  KHÔNG di chuyển vào đây.
- **`Phase3/` là project khác (auth/backend/frontend), không liên quan, không động vào.**

---

## 💡 Context bổ sung

- File `HANDOFF_SUPABASE_MIGRATION.md` (ở root `ads-trading-system/`) chứa quy tắc
  an toàn khi deploy lên VPS cho **app chính** (không liên quan trực tiếp đến
  `Phase 2/` nhưng cần đọc nếu làm việc tiếp với app chính): không SSH thủ công,
  sửa qua script có backup + idempotent, test qua `https://app.tap2soul.com/api/health`,
  restart từng lệnh một, không commit Supabase service_role key/connection string.
- Python `python-dotenv`'s `load_dotenv()` (gọi không tham số trong `_auth.py`,
  `_supabase_ingest.py`, `fetch_24h_orders.py`) tìm `.env` bắt đầu từ thư mục chứa
  **file gọi nó**, nên `.env` phải nằm cùng thư mục `Phase 2/` với các script —
  đã verify hoạt động đúng sau khi di chuyển.
- `Phase 1/` đang được user tự sắp xếp song song trong lúc session này diễn ra —
  session mới nên `ls "VPS/test_lwa_spapi/Phase 1"` để xem trạng thái mới nhất
  trước khi giả định nội dung.
- Today's date (lúc handoff): 2026-06-16. User email: nt8277992@gmail.com.

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
