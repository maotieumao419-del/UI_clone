-- ============================================================
-- 0004 — COMMENT ON TABLE/VIEW/FUNCTION: gắn NHÃN [Phase·nhóm·nguồn] cho mọi object.
--
-- Mục tiêu: "nhìn là biết table tạo ở phase nào, do nguồn nào (orders/finances/ads)"
-- mà KHÔNG đổi tên (đổi tên đụng ~260+ tham chiếu ở 3 phase + backend → rủi ro).
-- Comment hiện trong Supabase Table Editor (cột Description), \d+, information_schema.
--
-- AN TOÀN: không đụng dữ liệu/tên/code; chạy lại nhiều lần OK (idempotent);
-- TỰ BỎ QUA object chưa tồn tại (dù 0003 đã áp hay chưa). Chạy: Supabase SQL Editor.
-- ============================================================

-- ── Tables + Views: 1 vòng lặp, tự chọn TABLE/VIEW theo relkind, bỏ qua nếu thiếu ──
DO $$
DECLARE
    r record;
    k "char";
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            -- Part I · NEW_* · Phase 1 — Ingestion (raw buffer)
            ('NEW_sp_orders',            '[P1·Ingestion·Orders] đơn hàng thô SP-API (1 dòng/đơn)'),
            ('NEW_sp_order_items',       '[P1·Ingestion·Orders] item theo đơn (asin/sku/qty/giá)'),
            ('NEW_product_price',        '[P1·Ingestion·Orders] cache đơn giá SKU (estimate đơn Pending)'),
            ('NEW_fin_item_fees',        '[P1·Ingestion·Finances] phí Amazon thật/item (referral+FBA)'),
            ('NEW_fin_refunds',          '[P1·Ingestion·Finances] hoàn tiền / trả hàng'),
            ('NEW_fin_adjustments',      '[P1·Ingestion·Finances] điều chỉnh số dư tài khoản'),
            ('NEW_ads_campaigns_daily',  '[P1·Ingestion·Ads] perf campaign theo ngày (SP/SB/SD)'),
            ('NEW_ads_sp_asin_daily',    '[P1·Ingestion·Ads] perf cấp SKU/ASIN (Advertised Product Report)'),
            -- Part I · NEW_* · Phase 2 — Transformation (config nhập tay)
            ('NEW_product_cogs',         '[P2·Transform·Config] giá vốn COGS theo effective_date (FIFO)'),
            ('NEW_indirect_expenses',    '[P2·Transform·Config] chi phí gián tiếp (user nhập)'),
            ('NEW_fee_cache',            '[P2·Transform·Config] cấu hình/ước lượng phí (referral+FBA) theo SKU'),
            -- Part I · NEW_* · Phase 2 — Transformation (summary / mart)
            ('NEW_summary_order_items',  '[P2·Transform·Mart] chi tiết theo đơn (trang Order Items Sellerboard)'),
            ('NEW_summary_products',     '[P2·Transform·Mart] 31 chỉ số/SKU theo kỳ'),
            ('NEW_summary_campaigns',    '[P2·Transform·Mart] hiệu quả + lợi nhuận theo campaign'),
            -- Part I · NEW_* · Phase 2 — Views
            ('NEW_v_order_items_csv',         '[P2·Transform·View] tái tạo CSV Order Items Sellerboard'),
            ('NEW_v_daily_sales_localized',   '[P2·Transform·View] doanh số/ngày (giờ Pacific)'),
            ('NEW_v_daily_refunds_localized', '[P2·Transform·View] hoàn hàng/ngày (giờ Pacific)'),
            ('NEW_v_daily_fees_localized',    '[P2·Transform·View] phí Amazon/ngày (giờ Pacific)'),
            -- Part I · NEW_* · MỚI (migration 0003) — Catalog hub + Ads entity tree + Raw archive
            ('NEW_products',         '[P1·Ingestion·Catalog] hub asin↔sku↔title (Ads ASIN ↔ Ops SKU)'),
            ('NEW_ad_portfolios',    '[P1·Ingestion·Ads/Entity] hồ sơ portfolio (dimension)'),
            ('NEW_ad_campaigns',     '[P1·Ingestion·Ads/Entity] hồ sơ campaign (state/budget/bid+advertised_asin) — tách khỏi *_daily'),
            ('NEW_ad_groups',        '[P1·Ingestion·Ads/Entity] hồ sơ ad group (default_bid)'),
            ('NEW_ad_keywords',      '[P1·Ingestion·Ads/Entity] hồ sơ keyword (match_type/bid)'),
            ('NEW_raw_archive_log',  '[P1·Ingestion·RawArchive] sổ con trỏ object raw trên Cloudflare R2 (bronze)'),
            -- raw buffer legacy (non-NEW_) — đường ingest THỨ HAI trong backend
            ('raw_amazon_orders',    '[P1·Ingestion·Legacy/in-app] buffer JSONB đường ingest cũ (backend → bảng app); LEGACY'),
            -- Part II · App core (Phase 3 — Application, DB sống web app)
            ('users',                '[P3·Application] tài khoản người dùng'),
            ('products',             '[P3·Application] danh mục sản phẩm web app (lead time/tồn kho/safety)'),
            ('inventory_batches',    '[P3·Application] lô nhập kho (COGS FIFO)'),
            ('orders',               '[P3·Application] đơn hàng hiển thị UI'),
            ('order_items',          '[P3·Application] item đơn hàng (UI)'),
            ('listing_snapshots',    '[P3·Application] snapshot listing (giám sát thay đổi)'),
            ('bsr_snapshots',        '[P3·Application] lịch sử BSR'),
            ('alerts',               '[P3·Application] cảnh báo listing/tồn kho'),
            ('reimbursement_cases',  '[P3·Application] hồ sơ bồi thường FBA'),
            ('settlement_entries',   '[P3·Application] dòng settlement report (đối soát)'),
            ('aggregated_daily',     '[P3·Application] tổng hợp ngày/user (vẽ đồ thị UI)'),
            ('alembic_version',      '[P3·Application] phiên bản migration Alembic')
        ) AS t(obj, cmt)
    LOOP
        SELECT c.relkind INTO k
        FROM pg_class c
        WHERE c.oid = to_regclass(format('%I', r.obj));

        IF k IN ('r', 'p') THEN
            EXECUTE format('COMMENT ON TABLE %I IS %L', r.obj, r.cmt);
        ELSIF k = 'v' THEN
            EXECUTE format('COMMENT ON VIEW %I IS %L', r.obj, r.cmt);
        ELSE
            RAISE NOTICE 'Bỏ qua (chưa tồn tại): %', r.obj;
        END IF;
    END LOOP;
END $$;

-- ── Functions: gắn comment có chữ ký, bỏ qua nếu chưa tồn tại ──
DO $$
BEGIN
    IF to_regprocedure('"NEW_fn_daily_summary"(date)') IS NOT NULL THEN
        EXECUTE 'COMMENT ON FUNCTION "NEW_fn_daily_summary"(date) IS ''[P2·Transform·Helper] dashboard card 1 ngày''';
    END IF;
    IF to_regprocedure('"NEW_fn_seed_products"()') IS NOT NULL THEN
        EXECUTE 'COMMENT ON FUNCTION "NEW_fn_seed_products"() IS ''[P1/2·Helper] seed hub NEW_products từ order_items + ads_sp_asin''';
    END IF;
END $$;

-- ── Kiểm tra nhanh sau khi chạy: xem nhãn đã gắn ──
-- SELECT relname AS object,
--        obj_description(('"' || relname || '"')::regclass) AS comment
-- FROM pg_class
-- WHERE relkind IN ('r','v') AND relname LIKE 'NEW\_%' ESCAPE '\'
-- ORDER BY 1;
