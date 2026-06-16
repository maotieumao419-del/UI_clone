# Session Handoff — Gắn nhãn mô tả (COMMENT ON) cho schema Supabase

## 🎯 Mục tiêu tổng thể
Gắn **description** cho từng table/view/function trong Supabase Postgres để khi nhìn
Table Editor (cột "Description") hoặc chạy `\d+ tablename` là biết ngay object đó:
thuộc **Phase nào (P1/P2/P3)**, **nhóm nào (Ingestion/Transform/Application)**,
**nguồn dữ liệu nào (Orders/Finances/Ads/Catalog...)**.

Định dạng nhãn thống nhất: `[Phase·Group·Source] mô tả ngắn`.

> Cùng nằm trong dự án lớn **SellerVision** — hệ thống tự build tính toán tài chính
> Amazon khớp Sellerboard theo thời gian thực. Pipeline 3 phase:
> `Amazon API → (P1) Supabase NEW_* → (P2) NEW_summary_* → (P3) Web app app.tap2soul.com`.

## ✅ Đã hoàn thành
- **Inventory thực tế DB live** (query qua `python _dbadmin.py list`): hiện có đúng
  **30 table/view + 1 function = 31 objects**, KHÔNG có orphan.
  - P1 raw (7): `NEW_sp_orders`, `NEW_sp_order_items`, `NEW_fin_item_fees`,
    `NEW_fin_refunds`, `NEW_fin_adjustments`, `NEW_ads_campaigns_daily`, `NEW_ads_sp_asin_daily`
  - P1 input/persistent (4): `NEW_product_cogs`, `NEW_indirect_expenses`,
    `NEW_product_price`, `NEW_fee_cache`
  - P2 mart (3): `NEW_summary_order_items`, `NEW_summary_products`, `NEW_summary_campaigns`
  - P2 view (4): `NEW_v_order_items_csv`, `NEW_v_daily_sales_localized`,
    `NEW_v_daily_refunds_localized`, `NEW_v_daily_fees_localized`
  - P2 function (1): `NEW_fn_daily_summary(date)`
  - P3 app (12): `users`, `products`, `inventory_batches`, `orders`, `order_items`,
    `listing_snapshots`, `bsr_snapshots`, `alerts`, `reimbursement_cases`,
    `settlement_entries`, `aggregated_daily`, `alembic_version`
- **Tạo file** `Phase2_Transformation/sql/comment_schema.sql` — 2 block `DO $$`:
  - Block 1: loop qua VALUES list 30 (table/view), dùng `to_regclass` + `pg_class.relkind`
    để phân biệt table (`r`/`p` → `COMMENT ON TABLE`) vs view (`v` → `COMMENT ON VIEW`);
    object không tồn tại → `RAISE NOTICE` bỏ qua, không lỗi.
  - Block 2: `to_regprocedure('"NEW_fn_daily_summary"(date)')` cho function.
- **Đã CHẠY** file qua `python _dbadmin.py sql Phase2_Transformation/sql/comment_schema.sql`
  → áp dụng thành công lên DB Supabase live (KHÔNG cần dùng SQL Editor trên web vì
  `_dbadmin.py` nối thẳng cùng DB qua `DATABASE_URL`).
- **Đã VERIFY** bằng query `obj_description()` trực tiếp DB: đủ 31 nhãn, đúng nội dung.
  `NEW_summary_reimbursements` được tự bỏ qua (chưa tồn tại trên DB live) — đúng thiết kế.

## 🔄 Đang dở / Chưa hoàn thiện
- File `comment_schema.sql` **chưa commit** vào git (vẫn ở trạng thái untracked).
  Cũng có các thay đổi khác đang dở (xem mục Context).
- `NEW_summary_reimbursements`: đã có nhãn trong file nhưng bảng **chưa tồn tại** trên
  DB live → nhãn sẽ tự áp dụng khi bảng được tạo + chạy lại file (file idempotent).

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)
1. (Tuỳ chọn) **Commit** `comment_schema.sql` vào git nếu muốn versioned cùng pipeline.
2. (Tuỳ chọn) Mở **Supabase → Table Editor** kiểm tra bằng mắt cột "Description".
3. Khi tạo bảng `NEW_summary_reimbursements` thật, chạy lại file để gắn nhãn cho nó.
4. (Ngoài phạm vi nhãn) Quay lại công việc chính của SellerVision — xem
   `docs/SESSION_HANDOFF.md` mục 5: calibrate fees & Returns Report.

## 🏗️ Kiến trúc / Cấu trúc hệ thống
```
Amazon API ──(P1: Direct-Stream)──► Supabase NEW_* (bảng đệm)
Supabase   ──(P2: Transform)──────► NEW_summary_order_items / products / campaigns
Summary    ──(P3: Bridge/Patch)───► Web App app.tap2soul.com
```
- **Supabase Postgres** = VỪA bảng đệm pipeline (`NEW_*`) VỪA DB sống web app
  (`users, products, orders, order_items, settlement_entries...`).
  → TUYỆT ĐỐI không drop bảng không có prefix `NEW_`.
- `COMMENT ON` chỉ gắn metadata — không đụng tên/cấu trúc/data, idempotent, reversible
  (`COMMENT ON ... IS NULL` để gỡ). Lý do chọn COMMENT thay vì đổi tên: đổi tên phá
  ~260 tham chiếu khắp 3 phase + backend, quá rủi ro.

## 📁 Cấu trúc thư mục quan trọng
```
VPS/VPS_AMZ/sellerboard_clone/
├── Phase1_Ingestion/          # Amazon API -> Supabase NEW_*
├── Phase2_Transformation/
│   ├── transform_engine.py
│   ├── aggregation_models.py
│   └── sql/
│       ├── supabase_schema.sql        # schema gốc (table/view/function)
│       └── comment_schema.sql         # ★ FILE MỚI session này (gắn nhãn)
├── Phase3_Application/        # bridge/patch -> web app (KHÔNG sửa backend/frontend tay)
├── backend/                   # ⚠️ PRODUCTION; .env chứa DATABASE_URL
│   └── supabase/migrations/0002_initial_app_schema.sql  # schema 12 bảng app P3
├── docs/
│   ├── SESSION_HANDOFF.md     # bàn giao chính (fees, pipeline)
│   └── SESSION_HANDOFF_COMMENT_SCHEMA.md  # ★ file này
└── _dbadmin.py                # helper DB (KHÔNG commit): list|all|count|status|sql <file>|drop
```

## ⚙️ Biến môi trường & Cấu hình (.env)
File `backend/.env` (KHÔNG upload/commit). `_dbadmin.py` đọc `DATABASE_URL` từ đây.
```env
DATABASE_URL=postgresql+psycopg://...   # Supabase Postgres (DB sống web app); _dbadmin tự thay +psycopg-> postgresql://
# + SP-API / Ads API / AWS credentials (cho Phase 1, không liên quan task nhãn)
```

## 🔑 Thông số kỹ thuật quan trọng
- **Lệnh chạy nhãn:** `python _dbadmin.py sql Phase2_Transformation/sql/comment_schema.sql`
  (chạy từ thư mục `sellerboard_clone/`).
- **Lệnh list objects:** `python _dbadmin.py list`
- **Query verify nhãn (table/view):**
  `SELECT relname, obj_description(oid) FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','v','p') AND obj_description(oid) IS NOT NULL;`
- **Query verify function:**
  `SELECT proname, obj_description(oid) FROM pg_proc WHERE pronamespace='public'::regnamespace AND proname LIKE 'NEW_%';`
- **Phân biệt kind trong block:** `pg_class.relkind` → `r`/`p` = table, `v` = view.
- **Function cần chữ ký:** `to_regprocedure('"NEW_fn_daily_summary"(date)')`
  (chú ý DB lưu tham số tên là `p_date date`, nhưng `to_regprocedure` match theo type `(date)`).
- **Môi trường Windows:** PowerShell stdout mặc định cp1252 → script Python in tiếng Việt
  phải `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` nếu không sẽ
  `UnicodeEncodeError`. `_dbadmin.py` đã tự reconfigure sẵn.
- **`_dbadmin.py sql` chỉ nhận PATH file**, không có flag `-c "..."` inline.

## 🐛 Vấn đề đã gặp & Cách giải quyết
- `python _dbadmin.py sql -c "SELECT..."` → lỗi `FileNotFoundError: '-c'` vì `cmd_sql`
  chỉ `open(path)`. **Cách đúng:** ghi SQL ra file tạm rồi truyền path.
- Script verify in tiếng Việt qua PowerShell → `UnicodeEncodeError 'charmap'`.
  **Fix:** thêm `sys.stdout.reconfigure(encoding="utf-8")` đầu script.
- Hỏi "có cần tạo SQL Editor trên Supabase không?" → **KHÔNG.** `_dbadmin.py` nối thẳng
  cùng DB Supabase qua `DATABASE_URL`; chạy file = y hệt dán vào SQL Editor web. SQL
  Editor web chỉ cần khi máy local không chạy được `_dbadmin.py`.

## 🚫 Quyết định đã được xác nhận (không thay đổi)
- **Dùng `COMMENT ON` thay vì đổi tên bảng** — đổi tên phá ~260 tham chiếu, quá rủi ro.
  COMMENT chỉ metadata, an toàn tuyệt đối.
- **Format nhãn:** `[P{1,2,3}·Group·Source] mô tả` — đã chốt và áp dụng cho cả 31 object.
- **Áp dụng nhãn cũ** (theo bảng đề xuất trong session, không đổi gì thêm) — user xác nhận
  "nếu không có đề xuất mới thì áp dụng nhãn cũ".
- **Claude tự chạy SQL** (user duyệt) vì thuộc nhóm DB-admin qua `_dbadmin.py` (guardrail #4).
- File đặt trong `Phase2_Transformation/sql/` để versioned chung với `supabase_schema.sql`.

## 💡 Context bổ sung
- 2 file SQL tạm (`_tmp_list_functions.sql`, `_tmp_verify_comments.sql`) đã được **xoá**
  sau khi dùng — không để lại rác.
- Guardrails CỨNG của repo (xem `CLAUDE.md`): KHÔNG sửa tay `backend/`+`frontend/`;
  KHÔNG drop bảng non-`NEW_`; `--fresh` không xoá `NEW_product_price/cogs/fee_cache`;
  user kiểm soát ingest/transform (tốn quota), Claude chỉ tự chạy read-only / DB-admin
  qua `_dbadmin.py` / sửa code.
- Git status đầu session (các thay đổi KHÁC, không thuộc task nhãn, đang dở):
  modified `aggregation_models.py`, `supabase_schema.sql`, `transform_engine.py`;
  untracked `comment_schema.sql` (file session này), `_out.txt`.
- Quy ước dấu chuẩn Sellerboard: doanh thu DƯƠNG, mọi chi phí ÂM. Referral thật =
  16.5% principal (15% + 10% VAT VN) — đã kiểm chứng, đừng "sửa" về 15%.

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
