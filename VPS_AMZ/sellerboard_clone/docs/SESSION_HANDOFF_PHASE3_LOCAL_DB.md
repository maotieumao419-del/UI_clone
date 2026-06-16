# Session Handoff — Phase 3: Local DB Dashboard Refactoring (SellerVision)

## 🎯 Mục tiêu tổng thể
Refactor dashboard backend để render **HOÀN TOÀN** từ DB local (SQLite dev /
Postgres qua Supabase pooler prod) bằng SQLAlchemy — **không còn** gọi
`supabase.table().select()` (live REST) trong đường render dashboard.
Architecture chuẩn 3-phase (xem `CLAUDE.md` + `PIPELINE_3PHASE_README.md`):

```
Amazon API ──Phase1──► Supabase NEW_*
Supabase   ──Phase2──► NEW_summary_order_items / NEW_summary_products / NEW_summary_campaigns
Summary    ──Phase3──► Web App app.tap2soul.com (qua patch_scripts, KHÔNG sửa tay backend/frontend)
```

## ✅ Đã hoàn thành

### Backend / ORM
- **`backend/app/models/models.py`** — thêm model `SummaryOrderItem`
  (table `NEW_summary_order_items`), PK composite
  `(owner_id, order_number, sku, asin, row_type)`, có `to_dict()`.
  Export trong `backend/app/models/__init__.py`.
- **`Phase3_Application/data_bridge/analytics_aggregator.py`** — viết lại
  hoàn toàn (~300 dòng), CHỈ còn 3 hàm SQLAlchemy-based:
  - `get_dashboard_kpis(db, owner_id, start, end, compare_start=None, compare_end=None)`
  - `get_sku_performance(db, owner_id, start, end)`
  - `get_order_items_details(db, owner_id, start, end)`
  - Có CLI block (`--days`/`--owner-id`) để test standalone.
  - XÓA SẠCH toàn bộ code cũ dựa Supabase REST (`get_supabase_client`,
    `aggregate_product_performance`, `_fetch_*`, `_ads_spend_by_sku`, v.v.)
- **`Phase3_Application/data_bridge/supabase_dashboard.py`** — **ĐÃ XÓA** hoàn toàn.
- **`backend/app/routers/dashboard.py`** — viết lại, prefix `/api/analytics`,
  **4 routes**:
  - `GET /dashboard/summary?tab=products|orders&start=YYYY-MM-DD&end=YYYY-MM-DD&compare_start=&compare_end=`
    → `{kpis: get_dashboard_kpis(...), products: get_sku_performance(...)}`
      (hoặc `orders: get_order_items_details(...)` nếu `tab=orders`)
  - `GET /periods` → `profit.period_overview(db, current.id)` — **GIỮ LẠI**
    (khác với spec ban đầu định xóa — quyết định cuối: giữ vì frontend
    `loadPeriods()` vẫn dùng để vẽ 5 thẻ Today/Yesterday/MTD/Forecast/Last month).
  - `GET /ltv`, `GET /bsr` — không đổi.
- **`backend/app/services/profit.py`** — `period_overview()` MIGRATED sang
  SQLAlchemy, đọc `SummaryOrderItem` (sales/net_profit/units/refunds/amazon_fees/orders)
  + `SummaryProduct` (ads, theo `period_start == period_end`). Xóa hết code
  Supabase-dependent (`_settlement_fees_by_sku`, `_ads_spend_by_sku`,
  `_build_dataframe`, `dashboard()`, `_supabase_select_all`...). Giữ
  `_fifo_cogs_by_product`, `calculate_cogs_fifo`, `customer_ltv`, `bsr_monitor`,
  `_delta_pct`, `_shift_month`.
- **`Phase3_Application/data_bridge/supabase_to_app_db.py`** — thêm
  `T_SUMMARY_ITEMS = "NEW_summary_order_items"` + hàm mới
  `sync_summary_order_items(db, sb, owner_id, since_utc)` (mirror
  `sync_summary_products`: PAGE=100, `sqlite_insert(...).on_conflict_do_update`,
  savepoint mỗi page). `main()` đã gọi hàm này sau `sync_summary_products`.
- **`Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py`** —
  viết lại theo pattern full-overwrite (`NEW_DASHBOARD_PY` constant khớp
  100% với `backend/app/routers/dashboard.py` hiện tại, kể cả route
  `/periods`). Idempotent, backup + py_compile + auto-rollback khi lỗi.

### Schema & Live DB Migration (Postgres qua Supabase pooler — ĐÃ CHẠY)
- **`Phase2_Transformation/sql/supabase_schema.sql`** — `NEW_summary_order_items`:
  thêm cột `owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`,
  đổi PK thành `(owner_id, order_number, asin, sku, row_type)`, + thêm
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS owner_id ...` cho deploy cũ.
- **MỚI: `Phase3_Application/data_bridge/patch_scripts/migrate_summary_order_items_owner_id.py`**
  — script migration **idempotent**, ĐÃ CHẠY THÀNH CÔNG trên live DB:
  1. `ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE`
  2. Backfill `owner_id = 1` cho 388 dòng hiện có (DB hiện chỉ có 1 user, id=1)
  3. `SET owner_id NOT NULL`
  4. Drop PK cũ `(order_number, asin, sku, row_type)` → tạo PK mới
     `(owner_id, order_number, sku, asin, row_type)`
  - An toàn để re-run trên DB khác (VPS prod) — tự skip nếu cột đã tồn tại.

### Frontend
- **`Phase3_Application/data_bridge/patch_scripts/render_performance.js`** —
  sửa bug nghiêm trọng: code cũ gọi `/api/analytics/dashboard?days=N`
  (endpoint ĐÃ XÓA → 404 100% các lần load dashboard). Đã sửa:
  - Gọi `GET /api/analytics/dashboard/summary?tab=products&start=...&end=...`
    (start/end tính từ `range-select` ở client).
  - Sửa field mapping cho đúng `get_sku_performance()`: `product` (không phải
    `title`), `average_sales_price`, `cost_of_goods`, `amazon_fees` (gộp,
    không còn tách commission/FBA riêng), `ads`.
  - Thêm `computeTotals(rows)` tính tfoot client-side (backend không trả
    `totals` nữa).
  - Xóa fallback `origLoad()` chết (gọi endpoint cũ cũng đã xóa).
  - `loadPeriods()` → `/api/analytics/periods` giữ nguyên, đã verify hoạt động.
  - Verify: `node --check` OK.
- **`patch_frontend.py`** — sửa comment header (không đổi logic), vẫn copy
  `render_performance.js` → `frontend/render_performance.js` + chèn script tag
  sau `app.js` trong `index.html`.

### Môi trường / Dependencies
- Cài `python-multipart==0.0.20` (đã có trong `requirements.txt` nhưng
  chưa cài trong venv hiện tại) — cần để `app.main` import được (auth router
  dùng `OAuth2PasswordRequestForm`).

### Smoke test (đã chạy, PASS, trên live DB qua Supabase pooler)
- `get_dashboard_kpis(db, 1, start, end)` ✅ — trả KPIs đúng cấu trúc.
- `get_sku_performance(db, 1, start, end)` ✅ — 213 SKU rows.
- `get_order_items_details(db, 1, start, end)` ✅ — 388 rows.
- `profit.period_overview(db, 1)` ✅ — 5 thẻ kỳ tính đúng (MTD sales $4646.51 v.v.)
- `app.main` import full app ✅ — 43 routes, analytics có đủ
  `/dashboard/summary`, `/periods`, `/ltv`, `/bsr`.

## 🔄 Đang dở / Chưa hoàn thiện
- **`frontend/render_performance.js` và `frontend/index.html` CHƯA được patch**
  — `patch_frontend.py` chưa chạy. `frontend/render_performance.js` chưa tồn tại,
  `index.html` chưa có script tag.
- **`patch_dashboard.py`** chưa chạy `--check` để xác nhận
  `backend/app/routers/dashboard.py` thực tế đang khớp `NEW_DASHBOARD_PY`
  (về lý thuyết khớp vì đã viết trực tiếp, nhưng chưa verify bằng script).
- **Chưa deploy lên VPS** — toàn bộ thay đổi đang ở local repo
  (`C:\Users\nnh16\ads-trading-system\VPS`). VPS có thể có DB instance khác
  cần chạy lại `migrate_summary_order_items_owner_id.py`.
- **`backend/app/schemas/schemas.py`** — `DashboardResponse`, `PeriodCard`,
  `PeriodOverview` có thể không còn dùng (chỉ còn ref trong docs) — CHƯA quyết
  định xóa, ưu tiên thấp.
- **Chưa commit git** — tất cả thay đổi đang ở working tree, chưa staged/commit.
- **`docs/SESSION_HANDOFF.md` và `PIPELINE_3PHASE_README.md`** vẫn còn tham chiếu
  tới các hàm/route cũ đã xóa (`aggregate_product_performance`, `build_dashboard`,
  `/api/analytics/dashboard?days=N`) — chưa cập nhật, chỉ là docs.
- **Lưu ý KHÔNG liên quan session này**: `Phase2_Transformation/transform_engine.py`
  hiện `git status` báo modified — đây là thay đổi PRE-EXISTING từ trước session
  này, KHÔNG động tới, không rõ nội dung.

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)
1. Chạy `python Phase3_Application/data_bridge/patch_scripts/patch_dashboard.py --check`
   để xác nhận `dashboard.py` khớp `NEW_DASHBOARD_PY` (idempotent check).
2. Chạy `python Phase3_Application/data_bridge/patch_scripts/patch_frontend.py`
   để deploy `render_performance.js` mới vào `frontend/` + chèn script tag vào
   `index.html`.
3. Test trên browser thật (dev server hoặc VPS sau deploy): load trang Dashboard,
   kiểm tra bảng Products (8 cột: Sản phẩm/Số lượng/Doanh thu/COGS/Phí Amazon/
   Quảng cáo/Lợi nhuận ròng/Biên LN) + 5 thẻ Period cards (Today/Yesterday/MTD/
   Forecast/Last month) hiển thị đúng số liệu.
4. Review toàn bộ `git diff` (10 modified, 1 deleted, 1 new file —
   `migrate_summary_order_items_owner_id.py`), quyết định commit.
5. Deploy lên VPS theo guardrail trong `CLAUDE.md`: KHÔNG sửa tay
   `backend/`/`frontend/` trên VPS — chạy patch scripts + restart service
   `sellervision`. Nếu VPS DB khác instance, chạy lại
   `migrate_summary_order_items_owner_id.py` trên đó (an toàn, idempotent).
6. (Tùy chọn, ưu tiên thấp) Xóa `DashboardResponse`/`PeriodCard`/`PeriodOverview`
   trong `schemas.py` nếu xác nhận unused.
7. (Tùy chọn) Cập nhật `docs/SESSION_HANDOFF.md` / `PIPELINE_3PHASE_README.md`
   để phản ánh kiến trúc dashboard mới.

## 🏗️ Kiến trúc / Cấu trúc hệ thống
- **Backend**: FastAPI + SQLAlchemy 2.0 ORM, `DATABASE_URL` → Postgres qua
  Supabase Transaction Pooler (psycopg, `prepare_threshold=None`).
- **Dashboard data flow MỚI**:
  `Phase2 transform` → `NEW_summary_order_items`/`NEW_summary_products`
  (Supabase) → `supabase_to_app_db.py` (bridge, savepoint-per-page) →
  local `SummaryOrderItem`/`SummaryProduct` (SQLAlchemy models, cùng DB
  Postgres trong môi trường hiện tại) → `analytics_aggregator.py`
  (SQLAlchemy queries) → `routers/dashboard.py` → frontend
  `render_performance.js`.
- **KHÔNG còn** Supabase REST call (`supabase.table().select()`) trong path render.

## 📁 Cấu trúc thư mục quan trọng
```
VPS_AMZ/sellerboard_clone/
├── backend/app/
│   ├── models/models.py          # + SummaryOrderItem
│   ├── models/__init__.py        # + export SummaryOrderItem
│   ├── routers/dashboard.py       # rewritten: /dashboard/summary, /periods, /ltv, /bsr
│   └── services/profit.py         # period_overview() migrated → SQLAlchemy
├── Phase2_Transformation/
│   ├── sql/supabase_schema.sql    # NEW_summary_order_items + owner_id, PK mới
│   └── aggregation_models.py      # (reference, không đổi) SummaryOrderItem dataclass
├── Phase3_Application/data_bridge/
│   ├── analytics_aggregator.py    # rewritten — chỉ 3 hàm SQLAlchemy
│   ├── supabase_dashboard.py      # ĐÃ XÓA
│   ├── supabase_to_app_db.py      # + sync_summary_order_items()
│   └── patch_scripts/
│       ├── patch_dashboard.py     # rewritten, full-overwrite pattern
│       ├── patch_frontend.py      # comment update only
│       ├── render_performance.js  # rewritten — endpoint + field mapping mới
│       ├── migrate_summary_order_items_owner_id.py   # MỚI — đã chạy trên live DB
│       └── rollback.py            # không đổi
└── docs/
    └── SESSION_HANDOFF_PHASE3_LOCAL_DB.md   # file này
```

## ⚙️ Biến môi trường & Cấu hình (.env)
```env
DATABASE_URL=postgresql+psycopg://...@<supabase-pooler-host>:6543/postgres   # Transaction Pooler
```
- `_is_sqlite = DATABASE_URL.startswith("sqlite")` → quyết định `connect_args`
  (`check_same_thread` vs `prepare_threshold=None`) và `pool_kwargs`
  (`pool_size=5, max_overflow=10, pool_timeout=30` cho Postgres).
- Trong môi trường dev hiện tại, `DATABASE_URL` **đang trỏ tới Postgres qua
  Supabase pooler** (không phải SQLite) — mọi thay đổi DB là LIVE.

## 🔑 Thông số kỹ thuật quan trọng
- **`SummaryOrderItem`** (table `NEW_summary_order_items`):
  PK `(owner_id, order_number, sku, asin, row_type)`, 388 rows, `owner_id=1`
  cho toàn bộ (single-tenant hiện tại).
- **`SummaryProduct`** (table `NEW_summary_products`): PK
  `(owner_id, period_start, period_end, asin, sku)`, 213 rows — đã có
  `owner_id` từ trước (mẫu để mirror).
- **Endpoints**:
  - `GET /api/analytics/dashboard/summary?tab=products|orders&start=YYYY-MM-DD&end=YYYY-MM-DD[&compare_start=&compare_end=]`
    → `{kpis: {...}, products: [...]}` hoặc `{kpis: {...}, orders: [...]}`
  - `GET /api/analytics/periods` → `{periods: [...5 cards...]}`
  - `GET /api/analytics/ltv`, `GET /api/analytics/bsr`
- **`get_dashboard_kpis` shape**:
  ```json
  {"period": {"start":..., "end":...}, "compare_period": {...},
   "kpis": {"sales": {"value":, "compare_value":, "delta_pct":},
            "net_profit": {...}, "units": {...}, "refunds": {...},
            "fees": {...}, "ads": {...}, "cogs": {...}}}
  ```
- **`get_sku_performance` row fields**: `asin, sku, product, units, refunds,
  sales, promo, ads, refund_cost, amazon_fees, cost_of_goods, shipping,
  gross_profit, net_profit, estimated_payout, expenses,
  average_sales_price, margin_pct, roi_pct, bsr`.
- **`get_order_items_details`**: `SummaryOrderItem.to_dict()`, `limit(1000)`,
  order by `order_date desc`.

## 🐛 Vấn đề đã gặp & Cách giải quyết
- **`psycopg.errors.UndefinedColumn: NEW_summary_order_items.owner_id does not
  exist`** — bảng live thiếu cột `owner_id` (khác `NEW_summary_products` đã có
  từ trước). Giải quyết: tạo + chạy
  `migrate_summary_order_items_owner_id.py` (ADD COLUMN → backfill owner_id=1
  → SET NOT NULL → rebuild PK). Đã xác nhận với user trước khi chạy DDL trên
  live DB (PK change trên bảng có data = hard-to-reverse).
- **`RuntimeError: Form data requires "python-multipart"`** khi import
  `app.main` — thiếu package (có trong `requirements.txt` nhưng chưa cài).
  Giải quyết: `pip install python-multipart==0.0.20`.
- **Frontend gọi endpoint đã xóa** (`/api/analytics/dashboard?days=N`) —
  404 chắc chắn. Giải quyết: rewrite `render_performance.js` (xem trên).

## 🚫 Quyết định đã được xác nhận (không thay đổi)
- **Hard delete** cho code cũ — không giữ dead code/fallback "phòng hờ".
  Áp dụng cho `supabase_dashboard.py`, `analytics_aggregator.py`,
  `origLoad()` fallback trong `render_performance.js`.
- **Route `/api/analytics/periods` ĐƯỢC GIỮ LẠI** (khác spec ban đầu định
  xóa) vì frontend còn dùng cho 5 thẻ period cards, và `profit.period_overview()`
  đã migrate xong sang SQLAlchemy nên không còn vi phạm "no Supabase REST".
- **Backfill `owner_id=1`** cho toàn bộ `NEW_summary_order_items` — an toàn vì
  DB hiện chỉ có 1 user (single-tenant), đã user confirm trước khi chạy.
- **Migration DDL trên live Postgres (Supabase pooler) được chạy trực tiếp**
  sau khi user confirm rõ ràng (vì đây là DB "local" duy nhất khả dụng trong
  môi trường dev này).
- Quy ước dấu/công thức, fee model 16.5% (15% Amazon + 10% VAT VN) — giữ
  nguyên theo `CLAUDE.md`, KHÔNG đụng tới trong session này.

## 💡 Context bổ sung
- Memory liên quan: `sellervision-3phase-pipeline`, `sellervision-fee-model`
  (xem `~/.claude` memory index).
- Guardrails `CLAUDE.md` vẫn áp dụng đầy đủ: không sửa tay
  `backend/`/`frontend/` trên production — mọi thay đổi qua
  `Phase3_Application/data_bridge/patch_scripts/` (`--check` trước, có backup +
  rollback).
- `--fresh` chỉ xóa raw `NEW_*` của nguồn được chọn; KHÔNG xóa
  `NEW_product_price/NEW_product_cogs/NEW_fee_cache` (persistent).
- File mới `migrate_summary_order_items_owner_id.py` nên được coi là một phần
  của bộ patch_scripts — chạy 1 lần trên mỗi DB instance (idempotent, tự
  skip nếu `owner_id` đã tồn tại).

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
