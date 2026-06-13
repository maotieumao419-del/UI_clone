# Phase 2 — Tóm tắt công việc

> Thư mục: `C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi\Phase 2\`

Phase này tiếp nối Phase 1 (migration sang Supabase). Mục tiêu: làm cho các
script `fetch_24h_*.py` **lấy dữ liệu trực tiếp từ Amazon API và ghi thẳng vào
Supabase**, dễ dùng cho người mới, và linh hoạt chọn khoảng thời gian/ngày cần lấy.

---

## 1. Bỏ hoàn toàn bước trung gian (file/RAM) — ghi thẳng vào Supabase

**Vấn đề trước đó:** flow là call API → lưu file JSON (`raw_data/*.json`) →
chạy `ingest_pipeline.py` riêng để đẩy vào Supabase. Yêu cầu của user:
*"các code call API phải lưu luôn dữ liệu vào Supabase thay vì trung gian qua RAM"*
— vì nếu RAM tràn giữa chừng, dữ liệu đã fetch sẽ mất.

**Đã làm:**
- Tạo module dùng chung **`_supabase_ingest.py`**:
  - `get_supabase_client()`, `_upsert_chunks()` (chunk 100 dòng/lần)
  - `ingest_orders_page()` → upsert `"NEW_sp_orders"` / `"NEW_sp_order_items"`
  - `ingest_finance_events_page()` → upsert `"NEW_fin_item_fees"` /
    `"NEW_fin_refunds"` / `"NEW_fin_adjustments"`
  - `ingest_ads_report()` → upsert `"NEW_ads_campaigns_daily"`
- Sửa cả 3 script `fetch_24h_orders.py`, `fetch_24h_finances.py`,
  `fetch_24h_ads.py`:
  - **Orders**: mỗi trang (NextToken) → lấy OrderItems → `ingest_orders_page()`
    ngay → `del orders; gc.collect()`.
  - **Finances**: mỗi trang FinancialEvents → cộng dồn summary (scalar) +
    `ingest_finance_events_page()` ngay → giải phóng RAM.
  - **Ads**: mỗi report (SP/SB/SD) tải xong → `ingest_ads_report()` ngay.
- Kết quả: **không còn file JSON trung gian, không còn bước
  `ingest_pipeline.py` riêng** — mỗi script tự đủ để đưa dữ liệu vào Supabase.

---

## 2. Tài liệu hướng dẫn toàn bộ pipeline — `HOW_TO_USE.md`

Theo yêu cầu *"tổng hợp lại 1 file HOW_TO_USE.md ... người mới đọc cũng biết
được quy trình của hệ thống"*, đã viết file `HOW_TO_USE.md` mô tả liền mạch:

1. **Call API → Supabase**: chạy 3 script `fetch_24h_*.py` (hoặc `run_all.py`)
   → dữ liệu vào các bảng `"NEW_sp_orders"`, `"NEW_sp_order_items"`,
   `"NEW_fin_item_fees"`, `"NEW_fin_refunds"`, `"NEW_fin_adjustments"`,
   `"NEW_ads_campaigns_daily"`.
2. **Nhập tay COGS / chi phí gián tiếp** vào `"NEW_product_cogs"` và
   `"NEW_indirect_expenses"`.
3. **Thống kê ra định dạng giống CSV / Dashboard**:
   - VIEW `"NEW_v_order_items_csv"` → đúng định dạng file CSV Sellerboard.
   - FUNCTION `"NEW_fn_daily_summary"(date)` → đúng số liệu trên Dashboard card.
4. Bảng tổng hợp file/script nào tương ứng bước nào, checklist chạy hằng ngày.

---

## 3. Cho phép tuỳ chỉnh khoảng thời gian call API qua `.env`

Theo yêu cầu *"điều chỉnh thời gian call thì sao?"*, thêm các biến `.env`
(không cần sửa code):

| Biến | Áp dụng cho | Mặc định |
|---|---|---|
| `LOOKBACK_HOURS` | orders/finances | `24` |
| `ORDERS_CREATED_AFTER` / `ORDERS_CREATED_BEFORE` | orders | trống |
| `FINANCES_POSTED_AFTER` / `FINANCES_POSTED_BEFORE` | finances | trống |
| `ADS_DAYS_AGO` | ads | `1` (hôm qua) |
| `ADS_REPORT_DATE` | ads | trống |

---

## 4. Hỏi tương tác chọn ngày + xử lý timezone

Yêu cầu cuối: *"khi chạy fetch_24h nó sẽ hỏi tôi lấy mốc thời gian nào, hoặc
nhập ngày cụ thể"* + *"sellerboard lấy mốc thời gian theo UTC+? để setting
ngày?"*

**Đã làm:**
- Tạo module **`_time_range.py`**:
  - `SELLER_TIMEZONE` (`.env`, mặc định `America/Los_Angeles`) = timezone
    Sellerboard đang dùng để tính "1 ngày" (Settings → General → Time Zone).
  - `maybe_prompt()`: nếu chạy ở terminal tương tác **và** chưa có biến `.env`
    override → hỏi:
    ```
    1. 24h gần nhất / hôm qua (mặc định)
    2. Một ngày cụ thể (vd để khớp đúng 1 ngày trên Sellerboard)
    ```
    Nếu chọn `2` và nhập `YYYY-MM-DD`, tự quy đổi sang UTC range (cho
    Orders/Finances) hoặc dùng thẳng ngày đó (cho Ads, vì Ads API đã trả theo
    timezone tài khoản quảng cáo).
  - Nếu chạy qua cron (non-interactive) hoặc đã có override → bỏ qua prompt,
    dùng mặc định như cũ.
- Tích hợp `_time_range` vào `fetch_24h_orders.py`, `fetch_24h_finances.py`,
  `fetch_24h_ads.py`.
- Sửa **`run_all.py`**: hỏi **1 lần duy nhất** cho cả 3 script, rồi truyền kết
  quả (ngày đã chọn → UTC range / `ADS_REPORT_DATE`) qua biến môi trường cho
  từng subprocess — tránh bị hỏi 3 lần.
- Cập nhật `.env.example`: thêm `SELLER_TIMEZONE`, `ORDERS_CREATED_BEFORE`.
- Cập nhật `HOW_TO_USE.md` mục 1.5: giải thích prompt tương tác + giải thích
  timezone (SP-API = UTC, Ads API = timezone tài khoản quảng cáo, Sellerboard
  = timezone tự cấu hình trong Settings) và cách set `SELLER_TIMEZONE` cho
  khớp với Sellerboard.

---

## File đã tạo/sửa trong Phase 2

| File | Thay đổi |
|---|---|
| `_supabase_ingest.py` | **Mới** — module upsert trực tiếp vào Supabase |
| `_time_range.py` | **Mới** — module hỏi ngày + quy đổi timezone |
| `fetch_24h_orders.py` | Upsert trực tiếp theo trang + hỏi ngày + `ORDERS_CREATED_BEFORE` |
| `fetch_24h_finances.py` | Upsert trực tiếp theo trang + hỏi ngày |
| `fetch_24h_ads.py` | Upsert trực tiếp mỗi report + hỏi ngày |
| `run_all.py` | Hỏi ngày 1 lần, truyền qua env cho cả 3 script |
| `.env.example` | Thêm `SELLER_TIMEZONE`, `ORDERS_CREATED_BEFORE`, comment hướng dẫn |
| `HOW_TO_USE.md` | **Mới** — tài liệu quy trình end-to-end + mục 1.5 (thời gian/timezone) |

✅ Đã chạy `python -m py_compile` cho toàn bộ file `.py` ở trên — không lỗi cú pháp.

---

## 5. Gom toàn bộ pipeline đang dùng vào thư mục con `Phase 2/`

Để tách rõ "đang dùng" (Phase 2) khỏi các file cũ/không dùng nữa của Phase 1
(`raw_data/`, `ingest_pipeline.py`, `discover_columns.py`, `inspect_raw_data.py`,
`test_spapi.py`...), toàn bộ pipeline đang hoạt động được chuyển vào thư mục
con `Phase 2/`:

```
test_lwa_spapi/
├── Phase 1/            ← tài liệu/script cũ của Phase 1
├── Phase 2/            ← TOÀN BỘ pipeline đang dùng (thư mục này)
│   ├── _auth.py
│   ├── _supabase_ingest.py
│   ├── _time_range.py
│   ├── fetch_24h_orders.py
│   ├── fetch_24h_finances.py
│   ├── fetch_24h_ads.py
│   ├── run_all.py
│   ├── start.bat / start.py / setup.bat
│   ├── requirements.txt
│   ├── .env / .env.example
│   ├── supabase_schema.sql
│   ├── HOW_TO_USE.md
│   └── Phase_2.md
├── raw_data/, ingest_pipeline.py, discover_columns.py,
│   inspect_raw_data.py, test_spapi.py   ← cũ, không còn dùng
└── README.txt
```

**Đã sửa khi di chuyển** (vì `import _auth`, `import _supabase_ingest`,
`import _time_range`, và `load_dotenv()` đều phụ thuộc cùng thư mục với script):
- Toàn bộ `_auth.py`, `_supabase_ingest.py`, `_time_range.py`, `.env`,
  `.env.example` chuyển **cùng** với `fetch_24h_*.py`/`run_all.py` → import và
  `load_dotenv()` vẫn hoạt động bình thường (Python tự thêm thư mục chứa
  script vào `sys.path`, `load_dotenv()` tìm `.env` cùng thư mục script).
- `start.bat`: sửa `cd /d ...` trỏ vào `Phase 2\`, bỏ tham chiếu `raw_data\`
  (không còn dùng — dữ liệu giờ vào thẳng Supabase).
- `setup.bat`: bỏ bước `mkdir raw_data` (không còn cần).
- `HOW_TO_USE.md`: cập nhật toàn bộ lệnh `cd ...` trỏ vào `Phase 2\`, sửa link
  sang `../Phase 1/HUONG_DAN_CHAY.md`, `../ingest_pipeline.py`... (đường dẫn
  tương đối từ `Phase 2/` ra ngoài), thêm dòng cho `_time_range.py` vào bảng
  "File nào làm gì".

→ `python run_all.py` (hoặc `start.bat`) vẫn chạy y hệt như trước, chỉ khác
đường dẫn thư mục.
