-- ============================================================
-- COMMENT ON cho schema Supabase — gắn nhãn [Phase·Group·Source]
-- để Table Editor / \d+ tablename hiện rõ object thuộc P1/P2/P3,
-- nhóm nào, nguồn dữ liệu nào.
--
-- AN TOÀN: chỉ COMMENT ON TABLE/VIEW/FUNCTION (metadata) — KHÔNG
-- đổi tên, KHÔNG đụng cấu trúc/data. Idempotent (chạy lại OK).
-- Object không tồn tại sẽ bị bỏ qua (RAISE NOTICE), không lỗi.
--
-- Chạy: python _dbadmin.py sql Phase2_Transformation/sql/comment_schema.sql
-- ============================================================

-- ============================================================
-- BLOCK 1: TABLE & VIEW (30 objects)
-- ============================================================
DO $$
DECLARE
    r RECORD;
    k "char";
BEGIN
    FOR r IN SELECT * FROM (VALUES
        -- ── P1 · Ingestion (raw từ Amazon API) ──────────────────────
        ('Profit_Phase1_sp_orders',              '[P1·Ingestion·Orders] Đơn hàng thô từ SP-API (1 dòng/order)'),
        ('Profit_Phase1_sp_order_items',         '[P1·Ingestion·Orders] Line items thô từ SP-API (1 dòng/order+asin+sku)'),
        ('Profit_Phase1_fin_item_fees',          '[P1·Ingestion·Finances] Phí Amazon thật theo item (Referral/FBA, từ ShipmentEvent)'),
        ('Profit_Phase1_fin_refunds',            '[P1·Ingestion·Finances] Hoàn hàng thật (Refund Events)'),
        ('Profit_Phase1_fin_adjustments',        '[P1·Ingestion·Finances] Điều chỉnh tài khoản (Adjustment Events: reimbursement/clawback)'),
        ('Profit_Phase1_ads_campaigns_daily',    '[P1·Ingestion·Ads] Kết quả campaign theo ngày (SP/SB/SD)'),
        ('Profit_Phase1_ads_sp_asin_daily',      '[P1·Ingestion·Ads] Kết quả Sponsored Products theo ASIN/SKU/ngày'),

        -- ── P1 · Input/Persistent (nhập tay / tích lũy) ─────────────
        ('Profit_Phase1_product_cogs',           '[P1·Input·COGS] Giá vốn theo SKU, FIFO theo effective_date (nhập tay)'),
        ('Profit_Phase1_indirect_expenses',       '[P1·Input·Expenses] Chi phí gián tiếp (nhập tay)'),
        ('Profit_Phase1_product_price',          '[P1·Persistent·Price] Đơn giá per-SKU (tự lưu từ đơn Shipped) — impute giá đơn Pending'),
        ('Profit_Phase1_fee_cache',               '[P1·Persistent·FeeConfig] Cấu hình referral/FBA per-SKU (manual/calibrated)'),

        -- ── P2 · Transform · Mart ────────────────────────────────────
        ('Profit_Phase2_summary_order_items',     '[P2·Transform·Mart] Master chi tiết theo đơn hàng (~CSV Order Items Sellerboard)'),
        ('Profit_Phase2_summary_products',        '[P2·Transform·Mart] 31 chỉ số P&L theo (ASIN, SKU) trong kỳ'),
        ('Profit_Phase2_summary_campaigns',        '[P2·Transform·Mart] Hiệu quả + lợi nhuận theo campaign quảng cáo'),
        ('Profit_Phase2_summary_reimbursements',   '[P2·Transform·Mart] Money Back/Lost & Damaged theo kỳ (từ Profit_Phase1_fin_adjustments)'),

        -- ── P2 · View ─────────────────────────────────────────────────
        ('Profit_v_order_items_csv',         '[P2·View·CSV] Tái tạo cấu trúc CSV "Order Items" Sellerboard'),
        ('Profit_v_daily_sales_localized',   '[P2·View·Daily] Doanh số theo ngày Pacific'),
        ('Profit_v_daily_refunds_localized', '[P2·View·Daily] Refund theo ngày Pacific'),
        ('Profit_v_daily_fees_localized',    '[P2·View·Daily] Phí Amazon theo ngày Pacific'),

        -- ── P3 · Application (DB sống web app app.tap2soul.com) ───────
        ('users',                 '[P3·Application·Auth] Tài khoản người dùng web app'),
        ('products',              '[P3·Application·Catalog] Sản phẩm hiển thị UI (per-owner)'),
        ('inventory_batches',     '[P3·Application·Inventory] Lô hàng nhập kho (FIFO COGS phía app)'),
        ('orders',                '[P3·Application·Orders] Đơn hàng hiển thị UI'),
        ('order_items',           '[P3·Application·Orders] Line items đơn hàng hiển thị UI'),
        ('listing_snapshots',     '[P3·Application·Catalog] Snapshot listing theo thời điểm'),
        ('bsr_snapshots',         '[P3·Application·Catalog] Snapshot BSR theo thời điểm'),
        ('alerts',                '[P3·Application·Ops] Cảnh báo cho user'),
        ('reimbursement_cases',   '[P3·Application·Ops] Case hoàn tiền/đền bù phát hiện được'),
        ('settlement_entries',    '[P3·Application·Finance] Dòng settlement report (raw)'),
        ('aggregated_daily',      '[P3·Application·Mart] Tổng hợp theo ngày cho dashboard UI'),
        ('alembic_version',       '[P3·Infra] Bookkeeping version migration alembic')
    ) AS t(obj, cmt)
    LOOP
        SELECT c.relkind INTO k
        FROM pg_class c
        WHERE c.oid = to_regclass('public."' || r.obj || '"');

        IF k IN ('r', 'p') THEN
            EXECUTE format('COMMENT ON TABLE %I IS %L', r.obj, r.cmt);
        ELSIF k = 'v' THEN
            EXECUTE format('COMMENT ON VIEW %I IS %L', r.obj, r.cmt);
        ELSE
            RAISE NOTICE 'Bỏ qua (không tồn tại): %', r.obj;
        END IF;
    END LOOP;
END $$;


-- ============================================================
-- BLOCK 2: FUNCTION (cần chữ ký đầy đủ)
-- ============================================================
DO $$
BEGIN
    IF to_regprocedure('"Profit_fn_daily_summary"(date)') IS NOT NULL THEN
        COMMENT ON FUNCTION "Profit_fn_daily_summary"(date) IS
            '[P2·Function] Tái tạo Dashboard Card 1 ngày kiểu Sellerboard';
    ELSE
        RAISE NOTICE 'Bỏ qua (không tồn tại): Profit_fn_daily_summary(date)';
    END IF;
END $$;
