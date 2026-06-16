# Runbook 0003 — Cơ cấu DB additive: Raw archive + Ads entity tree + Catalog hub

> Hợp nhất: kế thừa SellerVision, bổ sung 2 điểm `call_API` làm tốt hơn (raw bất biến + tách
> dimension). **Additive 100%** — không drop/sửa bảng đang sống, không đụng `backend/` `frontend/`.
> Nền dữ liệu cho Khối E (Automation) ở pha sau.

## Đã thêm gì

| File | Vai trò |
|---|---|
| `Phase2_Transformation/sql/0003_entity_catalog_archive.sql` | Migration additive: `NEW_products` (catalog hub), `NEW_ad_portfolios/_ad_campaigns/_ad_groups/_ad_keywords` (entity tree), `NEW_raw_archive_log`, function `NEW_fn_seed_products()` |
| `Phase2_Transformation/sql/comment_schema.sql` | Gắn nhãn `[Phase·nhóm·nguồn]` qua `COMMENT ON` (idempotent). **Đã gộp** từ `0004_table_comments.sql` cũ vào file canonical của nhánh chính (đã chạy live); bổ sung 6 object entity-tree/catalog của 0003 + `NEW_fn_seed_products`. Chạy lại để gắn nhãn cho object mới |
| `Phase1_Ingestion/raw_archive.py` | Đẩy raw payload → Cloudflare R2 (gzip JSON) trước khi NEW_* bị ghi đè; ghi `NEW_raw_archive_log`. Tắt mặc định, lỗi không chặn ingest |
| `Phase1_Ingestion/amz_ads_client.py` | + `iter_sp_campaigns/ad_groups/keywords` (phân trang vnd v3) + `list_portfolios` (v2) |
| `Phase1_Ingestion/direct_stream_pipeline.py` | + cờ `--entities` (gộp vào `--all`) → upsert `NEW_ad_*`; hook `raw_archive` cho mọi nguồn; `seed_products()` |
| `Phase1_Ingestion/.env.example`, `requirements.txt` | + nhóm `R2_*` / `RAW_ARCHIVE_ENABLED`; + `boto3` |

## Bản đồ bảng — bổ sung vào thống kê (Phase + nguồn)

> Mở rộng thống kê bảng hiện có. Tất cả object mới nằm trong namespace `NEW_` (Part I — pipeline & mart),
> additive. Nhãn theo style `[Phase - nhóm]`:

- `[Phase 1 - Ingestion (Catalog hub)] NEW_products` — hub `asin↔sku↔title`; pipeline seed sau ingest (Ads ASIN ↔ Ops SKU gặp nhau).
- `[Phase 1 - Ingestion (Ads – Entity/Dimension)] NEW_ad_portfolios` — hồ sơ portfolio (budget/state).
- `[Phase 1 - Ingestion (Ads – Entity/Dimension)] NEW_ad_campaigns` — hồ sơ campaign (state/budget/targeting/bidding + `advertised_asin`); **dimension, TÁCH khỏi** `NEW_ads_campaigns_daily` (perf).
- `[Phase 1 - Ingestion (Ads – Entity/Dimension)] NEW_ad_groups` — hồ sơ ad group (`default_bid`).
- `[Phase 1 - Ingestion (Ads – Entity/Dimension)] NEW_ad_keywords` — hồ sơ keyword (`match_type`/`bid`).
- `[Phase 1 - Ingestion (Raw Archive)] NEW_raw_archive_log` — sổ con trỏ object raw đã đẩy lên Cloudflare R2 (bronze).
- `[Phase 1/2 - Helper] NEW_fn_seed_products` (Function) — seed `NEW_products` từ `NEW_sp_order_items` + `NEW_ads_sp_asin_daily`.

**Ghi chú — bảng thiếu trong thống kê gốc (đường ingest THỨ HAI, legacy):**
- `[Phase 1 - Ingestion (Legacy, in-app)] raw_amazon_orders` — buffer JSONB (non-`NEW_`), tạo bởi
  `backend/supabase/migrations/0001_create_raw_amazon_orders.sql`. Được ghi bởi **đường ingest cũ trong
  backend** (`app/services/supabase_ingest.py` + router `amazon_sync`, auto-sync khi app khởi động) →
  map sang bảng app `orders`/`order_items`/`products` (Part II). KHÁC pipeline 3-phase
  (`direct_stream_pipeline.py` → `NEW_*`). `docs/SESSION_HANDOFF.md` đánh dấu **legacy**. → ứng viên dọn
  dẹp/hợp nhất ở pha sau (nằm trong `backend/` → chỉ đụng qua `patch_scripts`).

> ⇒ Toàn hệ có **3 đường dữ liệu**: (A) pipeline `NEW_*` (chính) · (B) in-app `raw_amazon_orders`→bảng app (legacy) · (C) lớp dimension/archive mới (0003).

## Thứ tự triển khai (user chạy — cần creds Supabase/R2)

1. **Áp migration** (Supabase SQL Editor): dán & chạy
   `Phase2_Transformation/sql/0003_entity_catalog_archive.sql`. Idempotent, không lỗi nếu chạy lại.
   → Xuất hiện `NEW_products`, `NEW_ad_portfolios/_ad_campaigns/_ad_groups/_ad_keywords`,
   `NEW_raw_archive_log`; hàm seed chạy 1 lần ngay (backfill hub từ data đã có).

2. **Cài deps + R2:** `pip install -r Phase1_Ingestion/requirements.txt`.
   Tạo bucket R2 + API token (Cloudflare → R2). Điền `Phase1_Ingestion/.env`:
   `RAW_ARCHIVE_ENABLED=1`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.

3. **Self-test R2:** `python Phase1_Ingestion/raw_archive.py --selftest`
   → upload 1 object test + list lại được + 1 dòng `NEW_raw_archive_log`.

4. **Kéo entity tree:** `python Phase1_Ingestion/direct_stream_pipeline.py --entities`
   → 4 bảng `NEW_ad_*` có dữ liệu; `NEW_products` được seed; object raw lên R2.

5. **Verify cây + hub:**
   ```sql
   SELECT count(*) FROM "NEW_ad_campaigns";
   SELECT count(*) FROM "NEW_ad_campaigns" WHERE advertised_asin IS NOT NULL;  -- parse từ tên
   SELECT count(*) FROM "NEW_products";
   SELECT * FROM "NEW_raw_archive_log" ORDER BY id DESC LIMIT 5;
   ```
6. **Idempotent:** chạy lại bước 1 & 4 → không nhân đôi (PK + ON CONFLICT), không lỗi.

## An toàn / lưu ý
- `--fresh` **không** xóa các bảng dimension/hub mới (persistent, giống `NEW_product_price`).
- `raw_archive` lỗi (R2 sai key/mạng) chỉ in cảnh báo, **không** làm hỏng luồng ingest.
- Nếu RPC seed lỗi (PostgREST chưa expose function), chạy tay trong SQL Editor:
  `SELECT "NEW_fn_seed_products"();` (migration đã chạy sẵn 1 lần).
- KHÔNG đụng `backend/`, `frontend/`, `NEW_summary_*`, bảng app non-NEW.

## Pha sau — Khối E (Automation)
Trên nền entity tree này: bảng `automation_rules / proposed_actions / action_log (append-only) /`
`guardrail_configs / action_snapshots`; chạy **dry-run/shadow trước** (guardrail #6); 7 lớp
guardrail + Crawl→Walk→Run. Lên kế hoạch riêng.
