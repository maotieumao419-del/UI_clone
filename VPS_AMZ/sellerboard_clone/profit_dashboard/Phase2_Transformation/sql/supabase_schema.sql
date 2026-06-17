-- ============================================================
-- SUPABASE SCHEMA — Sellerboard Clone (NEW_ prefix)
-- Consolidated SQL script to initialize all tables, indexes, 
-- views, and functions for Phase 1 (Ingestion) & Phase 2 (Transformation).
--
-- Running this script in the Supabase SQL Editor:
--   supabase.com → project → SQL Editor → Paste → Run
-- ============================================================

-- ============================================================
-- BẢNG 1: Profit_Phase1_sp_orders
-- SP-API Orders — 1 row per Amazon order
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_sp_orders" (
    order_id            TEXT PRIMARY KEY,
    purchase_date       TIMESTAMPTZ NOT NULL,
    last_update_date    TIMESTAMPTZ,
    order_status        TEXT NOT NULL,
    -- Unshipped | Shipped | Canceled | Pending | PartiallyShipped
    fulfillment_channel TEXT DEFAULT 'AFN',
    -- AFN = FBA, MFN = FBM
    sales_channel       TEXT,
    marketplace_id      TEXT,
    synced_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_sp_orders_purchase_date"
    ON "Profit_Phase1_sp_orders" (purchase_date);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_sp_orders_status"
    ON "Profit_Phase1_sp_orders" (order_status);


-- ============================================================
-- BẢNG 2: Profit_Phase1_sp_order_items
-- SP-API Order Items — 1 row per (order_id, asin, sku)
-- Source: /orders/v0/orders/{id}/orderItems
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_sp_order_items" (
    id                  BIGSERIAL PRIMARY KEY,
    order_id            TEXT NOT NULL REFERENCES "Profit_Phase1_sp_orders"(order_id),
    asin                TEXT NOT NULL,
    sku                 TEXT NOT NULL,
    title               TEXT,
    quantity_ordered    INTEGER NOT NULL DEFAULT 0,
    unit_price          NUMERIC(10,2) DEFAULT 0,
    -- ItemPrice.Amount / quantity_ordered
    item_price          NUMERIC(10,2) DEFAULT 0,
    -- = unit_price × quantity = cột "Sales" trong CSV
    item_tax            NUMERIC(10,2) DEFAULT 0,
    promotion_discount  NUMERIC(10,2) DEFAULT 0,
    -- Promo (số âm hoặc 0)
    synced_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (order_id, asin, sku)
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_sp_order_items_order_id"
    ON "Profit_Phase1_sp_order_items" (order_id);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_sp_order_items_sku"
    ON "Profit_Phase1_sp_order_items" (sku);


-- ============================================================
-- BẢNG 3: Profit_Phase1_product_price
-- BẢNG GIÁ PERSISTENT (impute giá cho đơn Pending)
-- Lưu đơn giá đã biết của mỗi SKU từ đơn Shipped (Phase 1 tự ghi nhận)
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_product_price" (
    sku         TEXT PRIMARY KEY,
    unit_price  NUMERIC(12,2) NOT NULL,
    source      TEXT DEFAULT 'order',   -- 'order' (từ đơn Shipped) | 'manual' (nhập tay)
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- BẢNG 4: Profit_Phase1_fin_item_fees
-- Finances API — Phí Amazon từng order item
-- Source: ShipmentEventList → ShipmentItemList → ItemFeeList
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_fin_item_fees" (
    id              BIGSERIAL PRIMARY KEY,
    order_id        TEXT NOT NULL,
    -- KHÔNG FK -> Profit_Phase1_sp_orders: Finances lọc theo posted_date, Orders lọc
    -- theo purchase_date -> 2 cửa sổ ngày độc lập, order_id có thể chưa
    -- tồn tại ở Profit_Phase1_sp_orders tại thời điểm ingest.
    posted_date     TIMESTAMPTZ NOT NULL,
    asin            TEXT,
    sku             TEXT,
    quantity        INTEGER,
    fee_type        TEXT NOT NULL,
    -- FBAPerUnitFulfillmentFee | Commission | ...
    amount          NUMERIC(10,2) NOT NULL,
    -- số âm
    principal       NUMERIC(10,2) DEFAULT 0,
    -- ItemChargeList ChargeType=Principal (giá bán THẬT, để calibrate referral=commission/principal)
    synced_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (order_id, sku, asin, fee_type)
);
-- Phòng trường hợp bảng đã tồn tại từ trước (không có cột principal / còn FK cũ)
ALTER TABLE "Profit_Phase1_fin_item_fees" ADD COLUMN IF NOT EXISTS principal NUMERIC(10,2) DEFAULT 0;
ALTER TABLE "Profit_Phase1_fin_item_fees" DROP CONSTRAINT IF EXISTS "Profit_Phase1_fin_item_fees_order_id_fkey";

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_fin_item_fees_order_id"
    ON "Profit_Phase1_fin_item_fees" (order_id);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_fin_item_fees_posted_date"
    ON "Profit_Phase1_fin_item_fees" (posted_date);


-- ============================================================
-- BẢNG 5: Profit_Phase1_fin_refunds
-- Finances API — Hoàn hàng (returns)
-- Source: RefundEventList → ShipmentItemAdjustmentList
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_fin_refunds" (
    id                      BIGSERIAL PRIMARY KEY,
    order_id                TEXT NOT NULL,
    -- KHÔNG FK -> Profit_Phase1_sp_orders (xem giải thích ở Profit_Phase1_fin_item_fees)
    posted_date             TIMESTAMPTZ NOT NULL,
    asin                    TEXT,
    sku                     TEXT,
    quantity_returned       INTEGER DEFAULT 1,
    refund_principal        NUMERIC(10,2) DEFAULT 0,
    -- tiền hoàn cho khách (âm)
    refund_commission       NUMERIC(10,2) DEFAULT 0,
    -- phí xử lý hoàn (âm)
    refunded_referral_fee   NUMERIC(10,2) DEFAULT 0,
    -- Amazon hoàn lại referral fee (DƯƠNG)
    synced_at               TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (order_id, sku, posted_date)
);
-- Phòng trường hợp bảng đã tồn tại từ trước (còn FK cũ)
ALTER TABLE "Profit_Phase1_fin_refunds" DROP CONSTRAINT IF EXISTS "Profit_Phase1_fin_refunds_order_id_fkey";

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_fin_refunds_posted_date"
    ON "Profit_Phase1_fin_refunds" (posted_date);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_fin_refunds_order_id"
    ON "Profit_Phase1_fin_refunds" (order_id);


-- ============================================================
-- BẢNG 6: Profit_Phase1_fin_adjustments
-- Finances API — Điều chỉnh tài khoản
-- Source: AdjustmentEventList
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_fin_adjustments" (
    id              BIGSERIAL PRIMARY KEY,
    posted_date     TIMESTAMPTZ NOT NULL,
    adjustment_type TEXT NOT NULL,
    sku             TEXT,
    asin            TEXT,
    quantity        INTEGER,
    amount          NUMERIC(10,2) NOT NULL,
    synced_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_fin_adjustments_posted_date"
    ON "Profit_Phase1_fin_adjustments" (posted_date);


-- ============================================================
-- BẢNG 7: Profit_Phase1_ads_campaigns_daily
-- Ads API — Kết quả campaign theo ngày
-- Source: SP + SB + SD Reports (async flow)
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_ads_campaigns_daily" (
    id              BIGSERIAL PRIMARY KEY,
    report_date     DATE NOT NULL,
    campaign_id     TEXT NOT NULL,
    campaign_name   TEXT,
    ad_product      TEXT NOT NULL,
    -- SPONSORED_PRODUCTS | SPONSORED_BRANDS | SPONSORED_DISPLAY
    campaign_type   TEXT,
    -- sponsoredProducts | sponsoredBrands | sponsoredBrandsVideo | sponsoredDisplay
    asin            TEXT,
    sku             TEXT,
    impressions     INTEGER DEFAULT 0,
    clicks          INTEGER DEFAULT 0,
    cost            NUMERIC(10,2) DEFAULT 0,
    -- lưu số DƯƠNG, khi tính profit thì trừ đi
    purchases_1d    INTEGER DEFAULT 0,
    purchases_7d    INTEGER DEFAULT 0,
    purchases_14d   INTEGER DEFAULT 0,
    sales_1d        NUMERIC(10,2) DEFAULT 0,
    sales_7d        NUMERIC(10,2) DEFAULT 0,
    sales_14d       NUMERIC(10,2) DEFAULT 0,
    units_sold_1d   INTEGER DEFAULT 0,
    synced_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (report_date, campaign_id, ad_product)
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_ads_campaigns_daily_date"
    ON "Profit_Phase1_ads_campaigns_daily" (report_date);


-- ============================================================
-- BẢNG 8: Profit_Phase1_ads_sp_asin_daily
-- Advertised Product Report (cấp SKU/ASIN)
-- Nguồn dữ liệu Tầng 1 của thuật toán phân bổ Ad Spend
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_ads_sp_asin_daily" (
    id              BIGSERIAL PRIMARY KEY,
    report_date     DATE NOT NULL,
    campaign_id     TEXT NOT NULL,
    campaign_name   TEXT,
    ad_group_id     TEXT NOT NULL DEFAULT '',
    advertised_asin TEXT,
    advertised_sku  TEXT NOT NULL DEFAULT '',
    impressions     INTEGER DEFAULT 0,
    clicks          INTEGER DEFAULT 0,
    cost            NUMERIC(10,2) DEFAULT 0,   -- số DƯƠNG
    purchases_1d    INTEGER DEFAULT 0,
    purchases_7d    INTEGER DEFAULT 0,
    sales_1d        NUMERIC(10,2) DEFAULT 0,
    sales_7d        NUMERIC(10,2) DEFAULT 0,
    units_sold_1d   INTEGER DEFAULT 0,
    synced_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (report_date, campaign_id, ad_group_id, advertised_sku)
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_ads_sp_asin_daily_date"
    ON "Profit_Phase1_ads_sp_asin_daily" (report_date);
CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_ads_sp_asin_daily_sku"
    ON "Profit_Phase1_ads_sp_asin_daily" (advertised_sku);


-- ============================================================
-- BẢNG 9: Profit_Phase1_product_cogs
-- Giá vốn hàng hóa — user tự nhập
-- Hỗ trợ nhiều mức giá theo effective_date
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_product_cogs" (
    sku             TEXT NOT NULL,
    cog_per_unit    NUMERIC(10,2) NOT NULL DEFAULT 0,
    effective_date  DATE NOT NULL DEFAULT '2000-01-01',
    notes           TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sku, effective_date)
);


-- ============================================================
-- BẢNG 10: Profit_Phase1_indirect_expenses
-- Chi phí gián tiếp — user tự nhập
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_indirect_expenses" (
    id              BIGSERIAL PRIMARY KEY,
    expense_date    DATE NOT NULL,
    description     TEXT,
    amount          NUMERIC(10,2) NOT NULL,
    -- số âm
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_indirect_expenses_date"
    ON "Profit_Phase1_indirect_expenses" (expense_date);


-- ============================================================
-- BẢNG 11: Profit_Phase1_fee_cache
-- Cấu hình phí tĩnh (category + FBA size tier) do user hoặc calibrated
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase1_fee_cache" (
    sku                  TEXT PRIMARY KEY,
    asin                 TEXT,
    referral_rate        NUMERIC(6,4),     -- vd 0.15 = 15%; NULL = dùng auto/default
    fba_fulfillment_fee  NUMERIC(10,2),    -- phí FBA/đơn vị (số DƯƠNG); NULL = auto-derive
    product_category     TEXT DEFAULT 'Standard',
    fba_size_tier        TEXT DEFAULT 'Large Standard-Size',
    source               TEXT DEFAULT 'manual', -- 'manual' (nhập tay) | 'calibrated' (auto phí thật)
    sample_count         INTEGER DEFAULT 0, -- số dòng fee dùng để calibrate (referral+fba)
    notes                TEXT,
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);
-- Phòng trường hợp bảng đã tồn tại từ trước (thiếu cột sample_count)
ALTER TABLE "Profit_Phase1_fee_cache" ADD COLUMN IF NOT EXISTS sample_count INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase1_fee_cache_sku" ON "Profit_Phase1_fee_cache"(sku);


-- ============================================================
-- BẢNG 12: Profit_Phase2_summary_order_items
-- Bảng Master chi tiết theo đơn hàng (CSV Sellerboard)
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase2_summary_order_items" (
    owner_id        INTEGER NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
    order_number    TEXT NOT NULL,
    order_date      DATE,                      -- theo giờ local marketplace (Pacific)
    product         TEXT,
    asin            TEXT NOT NULL DEFAULT '',
    sku             TEXT NOT NULL DEFAULT '',
    units           INTEGER DEFAULT 0,
    refunds         INTEGER DEFAULT 0,
    sales           NUMERIC(12,2) DEFAULT 0,
    promo           NUMERIC(12,2) DEFAULT 0,   -- âm
    sellable_quota  NUMERIC(12,2),             -- chưa có nguồn API
    refund_cost     NUMERIC(12,2) DEFAULT 0,   -- âm
    amazon_fees     NUMERIC(12,2) DEFAULT 0,   -- Referral + FBA (THẬT, âm)
    cost_of_goods   NUMERIC(12,2) DEFAULT 0,   -- COGS FIFO (âm)
    shipping        NUMERIC(12,2) DEFAULT 0,   -- âm
    gross_profit    NUMERIC(12,2) DEFAULT 0,
    expenses        NUMERIC(12,2) DEFAULT 0,   -- âm
    net_profit      NUMERIC(12,2) DEFAULT 0,
    margin          NUMERIC(8,2),              -- %
    roi             NUMERIC(8,2),              -- %
    coupon          NUMERIC(12,2) DEFAULT 0,   -- chưa có nguồn API
    row_type        TEXT NOT NULL DEFAULT 'normal',  -- normal | return
    order_status    TEXT NOT NULL DEFAULT '',  -- Shipped | Pending | ... (Canceled đã bị loại)
    price_source    TEXT NOT NULL DEFAULT 'ACTUAL',  -- ACTUAL | ESTIMATED
    fee_state       TEXT DEFAULT 'NONE',        -- ACTUAL | ESTIMATED | NONE
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (owner_id, order_number, asin, sku, row_type)
);
-- Phòng trường hợp bảng đã tồn tại từ trước (thiếu các cột này)
ALTER TABLE "Profit_Phase2_summary_order_items" ADD COLUMN IF NOT EXISTS order_status TEXT NOT NULL DEFAULT '';
ALTER TABLE "Profit_Phase2_summary_order_items" ADD COLUMN IF NOT EXISTS price_source TEXT NOT NULL DEFAULT 'ACTUAL';
ALTER TABLE "Profit_Phase2_summary_order_items" ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES "users"("id") ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase2_summary_order_items_date"
    ON "Profit_Phase2_summary_order_items" (order_date);
CREATE INDEX IF NOT EXISTS "idx_Profit_Phase2_summary_order_items_sku"
    ON "Profit_Phase2_summary_order_items" (sku);


-- ============================================================
-- BẢNG 13: Profit_Phase2_summary_products
-- Bảng Master 31 chỉ số theo (ASIN, SKU) trong kỳ
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase2_summary_products" (
    owner_id                INTEGER NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
    period_start            DATE NOT NULL,
    period_end              DATE NOT NULL,
    product                 TEXT,
    asin                    TEXT NOT NULL DEFAULT '',
    sku                     TEXT NOT NULL DEFAULT '',
    units                   INTEGER DEFAULT 0,
    refunds                 INTEGER DEFAULT 0,
    sales                   NUMERIC(12,2) DEFAULT 0,
    promo                   NUMERIC(12,2) DEFAULT 0,
    ads                     NUMERIC(12,2) DEFAULT 0,   -- tổng spend phân bổ (âm)
    sponsored_products      NUMERIC(12,2) DEFAULT 0,   -- PPC (âm)
    sponsored_display       NUMERIC(12,2) DEFAULT 0,
    sponsored_brands        NUMERIC(12,2) DEFAULT 0,   -- HSA
    sponsored_brands_video  NUMERIC(12,2) DEFAULT 0,
    google_ads              NUMERIC(12,2) DEFAULT 0,   -- chưa có nguồn API
    facebook_ads            NUMERIC(12,2) DEFAULT 0,   -- chưa có nguồn API
    refunds_pct             NUMERIC(8,2),
    sellable_quota          NUMERIC(12,2),             -- chưa có nguồn API
    refund_cost             NUMERIC(12,2) DEFAULT 0,
    amazon_fees             NUMERIC(12,2) DEFAULT 0,
    cost_of_goods           NUMERIC(12,2) DEFAULT 0,
    shipping                NUMERIC(12,2) DEFAULT 0,
    gross_profit            NUMERIC(12,2) DEFAULT 0,
    net_profit              NUMERIC(12,2) DEFAULT 0,
    estimated_payout        NUMERIC(12,2) DEFAULT 0,
    expenses                NUMERIC(12,2) DEFAULT 0,
    margin                  NUMERIC(8,2),
    roi                     NUMERIC(8,2),
    bsr                     INTEGER,                   -- chưa có nguồn API
    real_acos               NUMERIC(8,2),
    sessions                INTEGER,                   -- chưa có nguồn API
    unit_session_pct        NUMERIC(8,2),              -- chưa có nguồn API
    average_sales_price     NUMERIC(12,2) DEFAULT 0,
    fee_state               TEXT DEFAULT 'NONE',        -- ACTUAL | ESTIMATED | MIXED
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (owner_id, period_start, period_end, asin, sku)
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase2_summary_products_sku"
    ON "Profit_Phase2_summary_products" (sku);
CREATE INDEX IF NOT EXISTS "idx_Profit_Phase2_summary_products_period"
    ON "Profit_Phase2_summary_products" (period_start, period_end);


-- ============================================================
-- BẢNG 14: Profit_Phase2_summary_campaigns
-- Bảng hiệu quả + lợi nhuận theo từng Campaign quảng cáo
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase2_summary_campaigns" (
    period_start      date         not null,
    period_end        date         not null,
    campaign_id       text         not null,
    campaign_name     text,
    status            text,
    marketplace       text,
    ad_product        text,
    ad_spend          numeric(12, 2) default 0,
    clicks            integer        default 0,
    impressions       integer        default 0,
    orders            integer        default 0,
    units             integer        default 0,
    conversion_rate   numeric(8, 2),
    cpc               numeric(8, 2),
    ppc_sales         numeric(12, 2) default 0,
    cost_per_order    numeric(8, 2),
    acos              numeric(8, 2),
    profit            numeric(12, 2),
    break_even_acos   numeric(8, 2),
    current_bid       numeric(8, 2),
    strategy          text,
    automation_status text,
    updated_at        timestamptz    default now(),
    primary key (period_start, period_end, campaign_id)
);

COMMENT ON TABLE "Profit_Phase2_summary_campaigns" IS
    'Phase 2 Mart 3: hiệu quả + lợi nhuận per campaign (GPU x units + ad_spend)';


-- ============================================================
-- BẢNG 15: Profit_Phase2_summary_reimbursements
-- "Money Back" kiểu Sellerboard — gộp Profit_Phase1_fin_adjustments (AdjustmentEventList
-- của Finances API: WAREHOUSE_DAMAGE/WAREHOUSE_LOST/REVERSAL_REIMBURSEMENT/...)
-- theo (adjustment_type, asin, sku) cho cả kỳ.
--   category = 'reimbursement' (Amazon trả tiền cho hàng mất/hỏng tại kho FBA,
--               amount DƯƠNG) | 'clawback' (Amazon thu hồi 1 khoản đã hoàn
--               trước đó, amount ÂM).
-- ============================================================
CREATE TABLE IF NOT EXISTS "Profit_Phase2_summary_reimbursements" (
    owner_id        INTEGER NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    adjustment_type TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'reimbursement',  -- reimbursement | clawback
    product         TEXT,
    asin            TEXT NOT NULL DEFAULT '',
    sku             TEXT NOT NULL DEFAULT '',
    quantity        INTEGER DEFAULT 0,
    amount          NUMERIC(12,2) DEFAULT 0,    -- + = Amazon trả seller, - = thu hồi
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (owner_id, period_start, period_end, adjustment_type, asin, sku)
);

CREATE INDEX IF NOT EXISTS "idx_Profit_Phase2_summary_reimbursements_period"
    ON "Profit_Phase2_summary_reimbursements" (period_start, period_end);
CREATE INDEX IF NOT EXISTS "idx_Profit_Phase2_summary_reimbursements_sku"
    ON "Profit_Phase2_summary_reimbursements" (sku);

COMMENT ON TABLE "Profit_Phase2_summary_reimbursements" IS
    'Phase 2 — Money Back/Lost & Damaged (Sellerboard): tổng hợp Profit_Phase1_fin_adjustments theo kỳ';


-- ============================================================
-- VIEW 1: Profit_v_order_items_csv
-- Tái tạo cấu trúc file CSV "Order Items" của Sellerboard
-- ============================================================
CREATE OR REPLACE VIEW "Profit_v_order_items_csv" AS
-- ── NORMAL ORDERS ───────────────────────────────────────────
SELECT
    o.order_id,
    o.order_status,
    o.purchase_date::date                                           AS order_date,
    o.fulfillment_channel,
    oi.title,
    oi.asin,
    oi.sku,
    oi.unit_price,
    oi.quantity_ordered                                             AS units,
    NULL::integer                                                   AS refunds,
    oi.item_price                                                   AS sales,
    oi.promotion_discount                                           AS promo,
    NULL::numeric                                                   AS refund_cost,
    COALESCE(fees.total_fees, 0)                                    AS amazon_fees,
    -(oi.quantity_ordered * COALESCE(cog.cog_per_unit, 0))          AS cost_of_goods,
    cog.cog_per_unit,
    oi.item_price
        + COALESCE(fees.total_fees, 0)
        - (oi.quantity_ordered * COALESCE(cog.cog_per_unit, 0))     AS gross_profit,
    0::numeric                                                      AS indirect_expenses,
    oi.item_price
        + COALESCE(fees.total_fees, 0)
        - (oi.quantity_ordered * COALESCE(cog.cog_per_unit, 0))     AS net_profit,
    CASE WHEN oi.item_price > 0 THEN
        ROUND(
            (oi.item_price + COALESCE(fees.total_fees,0)
             - (oi.quantity_ordered * COALESCE(cog.cog_per_unit,0)))
            / oi.item_price * 100
        , 2)
    END                                                             AS margin_pct,
    CASE WHEN COALESCE(cog.cog_per_unit, 0) > 0 THEN
        ROUND(
            (oi.item_price + COALESCE(fees.total_fees,0)
             - (oi.quantity_ordered * COALESCE(cog.cog_per_unit,0)))
            / (oi.quantity_ordered * cog.cog_per_unit) * 100
        , 2)
    END                                                             AS roi_pct,
    o.purchase_date                                                 AS sort_ts,
    'normal'                                                        AS row_type

FROM "Profit_Phase1_sp_orders" o
JOIN "Profit_Phase1_sp_order_items" oi ON o.order_id = oi.order_id

LEFT JOIN LATERAL (
    SELECT SUM(amount) AS total_fees
    FROM "Profit_Phase1_fin_item_fees"
    WHERE order_id = o.order_id
      AND sku       = oi.sku
      AND asin      = oi.asin
) fees ON true

LEFT JOIN LATERAL (
    SELECT cog_per_unit
    FROM "Profit_Phase1_product_cogs"
    WHERE sku = oi.sku
      AND effective_date <= o.purchase_date::date
    ORDER BY effective_date DESC
    LIMIT 1
) cog ON true

WHERE o.order_status NOT IN ('Canceled', 'Cancelled')

UNION ALL

-- ── RETURNS ─────────────────────────────────────────────────
SELECT
    r.order_id,
    'Return'                                                        AS order_status,
    o.purchase_date::date                                           AS order_date,
    o.fulfillment_channel,
    oi.title,
    r.asin,
    r.sku,
    NULL::numeric                                                   AS unit_price,
    NULL::integer                                                   AS units,
    r.quantity_returned                                             AS refunds,
    NULL::numeric                                                   AS sales,
    NULL::numeric                                                   AS promo,
    (r.refund_principal + r.refund_commission + r.refunded_referral_fee) AS refund_cost,
    NULL::numeric                                                   AS amazon_fees,
    NULL::numeric                                                   AS cost_of_goods,
    NULL::numeric                                                   AS cog_per_unit,
    (r.refund_principal + r.refund_commission + r.refunded_referral_fee) AS gross_profit,
    0::numeric                                                      AS indirect_expenses,
    (r.refund_principal + r.refund_commission + r.refunded_referral_fee) AS net_profit,
    NULL::numeric                                                   AS margin_pct,
    NULL::numeric                                                   AS roi_pct,
    r.posted_date                                                   AS sort_ts,
    'return'                                                        AS row_type

FROM "Profit_Phase1_fin_refunds" r
JOIN "Profit_Phase1_sp_orders" o ON r.order_id = o.order_id
LEFT JOIN "Profit_Phase1_sp_order_items" oi
    ON r.order_id = oi.order_id AND r.sku = oi.sku AND r.asin = oi.asin;


-- ============================================================
-- VIEW 2: Profit_v_daily_sales_localized
-- Daily Sales theo ngày Pacific (UTC -> America/Los_Angeles)
-- ============================================================
CREATE OR REPLACE VIEW "Profit_v_daily_sales_localized" AS
SELECT
    (o.purchase_date AT TIME ZONE 'UTC'
                     AT TIME ZONE 'America/Los_Angeles')::date AS localized_date,
    COUNT(DISTINCT o.order_id)              AS orders,
    COALESCE(SUM(oi.quantity_ordered), 0)   AS units,
    COALESCE(SUM(oi.item_price), 0)         AS sales,
    COALESCE(SUM(oi.promotion_discount), 0) AS promo
FROM "Profit_Phase1_sp_orders" o
JOIN "Profit_Phase1_sp_order_items" oi ON o.order_id = oi.order_id
WHERE o.order_status NOT IN ('Canceled', 'Cancelled')
GROUP BY 1
ORDER BY 1;


-- ============================================================
-- VIEW 3: Profit_v_daily_refunds_localized
-- Refund theo ngày Pacific (posted_date)
-- ============================================================
CREATE OR REPLACE VIEW "Profit_v_daily_refunds_localized" AS
SELECT
    (r.posted_date AT TIME ZONE 'UTC'
                   AT TIME ZONE 'America/Los_Angeles')::date AS localized_date,
    COUNT(*)                                                  AS refund_events,
    COALESCE(SUM(r.quantity_returned), 0)                     AS units_returned,
    COALESCE(SUM(r.refund_principal + r.refund_commission
                 + r.refunded_referral_fee), 0)               AS refund_cost
FROM "Profit_Phase1_fin_refunds" r
GROUP BY 1
ORDER BY 1;


-- ============================================================
-- VIEW 4: Profit_v_daily_fees_localized
-- Phí Amazon theo ngày Pacific (posted_date)
-- ============================================================
CREATE OR REPLACE VIEW "Profit_v_daily_fees_localized" AS
SELECT
    (f.posted_date AT TIME ZONE 'UTC'
                   AT TIME ZONE 'America/Los_Angeles')::date AS localized_date,
    COALESCE(SUM(f.amount), 0)  AS amazon_fees   -- số âm
FROM "Profit_Phase1_fin_item_fees" f
GROUP BY 1
ORDER BY 1;


-- ============================================================
-- FUNCTION: Profit_fn_daily_summary(p_date DATE)
-- Tái tạo Dashboard Card của Sellerboard cho 1 ngày cụ thể
-- ============================================================
DROP FUNCTION IF EXISTS "Profit_fn_daily_summary"(date);
CREATE OR REPLACE FUNCTION "Profit_fn_daily_summary"(p_date DATE)
RETURNS TABLE (
    sales               NUMERIC,
    orders_count        BIGINT,
    units               BIGINT,
    refunds_count       BIGINT,
    promo               NUMERIC,
    adv_cost            NUMERIC,
    refund_cost         NUMERIC,
    amazon_fees         NUMERIC,
    cost_of_goods       NUMERIC,
    gross_profit        NUMERIC,
    indirect_expenses   NUMERIC,
    net_profit          NUMERIC,
    est_payout          NUMERIC,
    real_acos_pct       NUMERIC,
    refund_rate_pct     BIGINT,
    margin_pct          NUMERIC,
    roi_pct             NUMERIC
) LANGUAGE SQL AS $$
WITH
ord AS (
    SELECT
        COUNT(DISTINCT o.order_id)              AS order_count,
        COALESCE(SUM(oi.quantity_ordered), 0)   AS total_units,
        COALESCE(SUM(oi.item_price), 0)         AS total_sales,
        COALESCE(SUM(oi.promotion_discount), 0) AS total_promo
    FROM "Profit_Phase1_sp_orders" o
    JOIN "Profit_Phase1_sp_order_items" oi ON o.order_id = oi.order_id
    WHERE o.purchase_date::date = p_date
      AND o.order_status NOT IN ('Canceled', 'Cancelled')
),
fees AS (
    SELECT COALESCE(SUM(amount), 0) AS total_fees
    FROM "Profit_Phase1_fin_item_fees"
    WHERE posted_date::date = p_date
),
adj AS (
    SELECT COALESCE(SUM(amount), 0) AS total_adj
    FROM "Profit_Phase1_fin_adjustments"
    WHERE posted_date::date = p_date
),
ref AS (
    SELECT
        COUNT(*)        AS ref_count,
        COALESCE(SUM(
            refund_principal + refund_commission + refunded_referral_fee
        ), 0)           AS ref_cost
    FROM "Profit_Phase1_fin_refunds"
    WHERE posted_date::date = p_date
),
ads AS (
    SELECT COALESCE(SUM(cost), 0) AS total_ads
    FROM "Profit_Phase1_ads_campaigns_daily"
    WHERE report_date = p_date
),
cog AS (
    SELECT COALESCE(SUM(
        oi.quantity_ordered * COALESCE(pc.cog_per_unit, 0)
    ), 0) AS total_cog
    FROM "Profit_Phase1_sp_orders" o
    JOIN "Profit_Phase1_sp_order_items" oi ON o.order_id = oi.order_id
    LEFT JOIN LATERAL (
        SELECT cog_per_unit
        FROM "Profit_Phase1_product_cogs"
        WHERE sku = oi.sku
          AND effective_date <= p_date
        ORDER BY effective_date DESC
        LIMIT 1
    ) pc ON true
    WHERE o.purchase_date::date = p_date
      AND o.order_status NOT IN ('Canceled', 'Cancelled')
),
exp AS (
    SELECT COALESCE(SUM(amount), 0) AS total_exp
    FROM "Profit_Phase1_indirect_expenses"
    WHERE expense_date = p_date
)
SELECT
    ord.total_sales                                     AS sales,
    ord.order_count                                     AS orders_count,
    ord.total_units                                     AS units,
    ref.ref_count                                       AS refunds_count,
    ord.total_promo                                     AS promo,
    -ads.total_ads                                      AS adv_cost,
    ref.ref_cost                                        AS refund_cost,
    fees.total_fees + adj.total_adj                     AS amazon_fees,
    -cog.total_cog                                      AS cost_of_goods,
    ord.total_sales + (fees.total_fees + adj.total_adj)
        + ref.ref_cost + (-ads.total_ads) + (-cog.total_cog)   AS gross_profit,
    exp.total_exp                                       AS indirect_expenses,
    ord.total_sales + (fees.total_fees + adj.total_adj)
        + ref.ref_cost + (-ads.total_ads) + (-cog.total_cog)
        + exp.total_exp                                 AS net_profit,
    ord.total_sales + (fees.total_fees + adj.total_adj)
        + ref.ref_cost + (-ads.total_ads)               AS est_payout,
    CASE WHEN ord.total_sales > 0 THEN
        ROUND(ads.total_ads / ord.total_sales * 100, 2) END     AS real_acos_pct,
    CASE WHEN ord.total_units > 0 THEN
        ROUND(ref.ref_count::numeric / ord.total_units * 100, 2)::BIGINT END AS refund_rate_pct,
    CASE WHEN ord.total_sales > 0 THEN
        ROUND(
            (ord.total_sales + (fees.total_fees + adj.total_adj)
             + ref.ref_cost + (-ads.total_ads) + (-cog.total_cog) + exp.total_exp)
            / ord.total_sales * 100
        , 2) END                                        AS margin_pct,
    CASE WHEN cog.total_cog > 0 THEN
        ROUND(
            (ord.total_sales + (fees.total_fees + adj.total_adj)
             + ref.ref_cost + (-ads.total_ads) + (-cog.total_cog) + exp.total_exp)
            / cog.total_cog * 100
        , 2) END                                        AS roi_pct
FROM ord, fees, adj, ref, ads, cog, exp;
$$;


-- ============================================================
-- ẢNH SẢN PHẨM (SP-API Catalog Items) — Phase 1 persistent + cột Phase 2
-- ============================================================

-- Bảng ảnh tích luỹ theo ASIN (KHÔNG prune — slowly-changing dimension)
CREATE TABLE IF NOT EXISTS "Profit_Phase1_product_images" (
    asin        TEXT PRIMARY KEY,
    image_url   TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Cột ảnh ở bảng summary Phase 2 (điền bằng update_summary_images.py, join theo asin)
ALTER TABLE "Profit_Phase2_summary_products"    ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE "Profit_Phase2_summary_order_items" ADD COLUMN IF NOT EXISTS image_url TEXT;
