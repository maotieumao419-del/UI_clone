-- ============================================================
-- SUPABASE SCHEMA — Sellerboard Clone (NEW_ prefix)
-- Tái tạo đầy đủ cấu trúc CSV "Order Items" của Sellerboard
--
-- Tất cả bảng mới dùng prefix NEW_ để không xung đột với
-- các bảng hiện có trong project Supabase.
--
-- Chạy file này trong Supabase SQL Editor:
--   supabase.com → project → SQL Editor → Paste → Run
--
-- Thứ tự bảng (FK dependencies):
--   NEW_sp_orders → NEW_sp_order_items, NEW_fin_item_fees, NEW_fin_refunds
--   NEW_fin_adjustments, NEW_ads_campaigns_daily,
--   NEW_product_cogs, NEW_indirect_expenses  (độc lập)
-- ============================================================


-- ============================================================
-- BẢNG 1: NEW_sp_orders
-- SP-API Orders — 1 row per Amazon order
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_sp_orders" (
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

CREATE INDEX IF NOT EXISTS "idx_NEW_sp_orders_purchase_date"
    ON "NEW_sp_orders" (purchase_date);

CREATE INDEX IF NOT EXISTS "idx_NEW_sp_orders_status"
    ON "NEW_sp_orders" (order_status);


-- ============================================================
-- BẢNG 2: NEW_sp_order_items
-- SP-API Order Items — 1 row per (order_id, asin, sku)
-- Source: /orders/v0/orders/{id}/orderItems
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_sp_order_items" (
    id                  BIGSERIAL PRIMARY KEY,
    order_id            TEXT NOT NULL REFERENCES "NEW_sp_orders"(order_id),
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

CREATE INDEX IF NOT EXISTS "idx_NEW_sp_order_items_order_id"
    ON "NEW_sp_order_items" (order_id);

CREATE INDEX IF NOT EXISTS "idx_NEW_sp_order_items_sku"
    ON "NEW_sp_order_items" (sku);


-- ============================================================
-- BẢNG 3: NEW_fin_item_fees
-- Finances API — Phí Amazon từng order item
-- Source: ShipmentEventList → ShipmentItemList → ItemFeeList
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_fin_item_fees" (
    id              BIGSERIAL PRIMARY KEY,
    order_id        TEXT NOT NULL REFERENCES "NEW_sp_orders"(order_id),
    posted_date     TIMESTAMPTZ NOT NULL,
    asin            TEXT,
    sku             TEXT,
    quantity        INTEGER,
    fee_type        TEXT NOT NULL,
    -- FBAPerUnitFulfillmentFee | Commission | ...
    amount          NUMERIC(10,2) NOT NULL,
    -- số âm
    synced_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (order_id, sku, asin, fee_type)
);

CREATE INDEX IF NOT EXISTS "idx_NEW_fin_item_fees_order_id"
    ON "NEW_fin_item_fees" (order_id);

CREATE INDEX IF NOT EXISTS "idx_NEW_fin_item_fees_posted_date"
    ON "NEW_fin_item_fees" (posted_date);


-- ============================================================
-- BẢNG 4: NEW_fin_refunds
-- Finances API — Hoàn hàng (returns)
-- Source: RefundEventList → ShipmentItemAdjustmentList
--
-- KEY: posted_date = ngày refund ĐƯỢC XỬ LÝ bởi Amazon
--      Sellerboard dùng cái này để gán return vào ngày dashboard
--      (KHÔNG phải ngày đặt hàng gốc)
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_fin_refunds" (
    id                      BIGSERIAL PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES "NEW_sp_orders"(order_id),
    posted_date             TIMESTAMPTZ NOT NULL,
    asin                    TEXT,
    sku                     TEXT,
    quantity_returned       INTEGER DEFAULT 1,
    refund_principal        NUMERIC(10,2) DEFAULT 0,
    -- tiền hoàn cho khách (âm)
    refund_commission       NUMERIC(10,2) DEFAULT 0,
    -- phí xử lý hoàn (âm)
    refunded_referral_fee   NUMERIC(10,2) DEFAULT 0,
    -- Amazon hoàn lại referral fee (DƯƠNG — hay bị bỏ sót!)
    -- refund_cost = refund_principal + refund_commission + refunded_referral_fee
    synced_at               TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (order_id, sku, posted_date)
);

CREATE INDEX IF NOT EXISTS "idx_NEW_fin_refunds_posted_date"
    ON "NEW_fin_refunds" (posted_date);

CREATE INDEX IF NOT EXISTS "idx_NEW_fin_refunds_order_id"
    ON "NEW_fin_refunds" (order_id);


-- ============================================================
-- BẢNG 5: NEW_fin_adjustments
-- Finances API — Điều chỉnh tài khoản
-- Source: AdjustmentEventList
-- FBAInventoryReimbursement | FBADisposalFee | FBAStorageFee | ...
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_fin_adjustments" (
    id              BIGSERIAL PRIMARY KEY,
    posted_date     TIMESTAMPTZ NOT NULL,
    adjustment_type TEXT NOT NULL,
    sku             TEXT,
    asin            TEXT,
    quantity        INTEGER,
    amount          NUMERIC(10,2) NOT NULL,
    synced_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_NEW_fin_adjustments_posted_date"
    ON "NEW_fin_adjustments" (posted_date);


-- ============================================================
-- BẢNG 6: NEW_ads_campaigns_daily
-- Ads API — Kết quả campaign theo ngày
-- Source: SP + SB + SD Reports (async flow)
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_ads_campaigns_daily" (
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

CREATE INDEX IF NOT EXISTS "idx_NEW_ads_campaigns_daily_date"
    ON "NEW_ads_campaigns_daily" (report_date);


-- ============================================================
-- BẢNG 7: NEW_product_cogs
-- Giá vốn hàng hóa — user tự nhập
-- Hỗ trợ nhiều mức giá theo effective_date
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_product_cogs" (
    sku             TEXT NOT NULL,
    cog_per_unit    NUMERIC(10,2) NOT NULL DEFAULT 0,
    effective_date  DATE NOT NULL DEFAULT '2000-01-01',
    notes           TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sku, effective_date)
);


-- ============================================================
-- BẢNG 8: NEW_indirect_expenses
-- Chi phí gián tiếp — user tự nhập
-- ============================================================
CREATE TABLE IF NOT EXISTS "NEW_indirect_expenses" (
    id              BIGSERIAL PRIMARY KEY,
    expense_date    DATE NOT NULL,
    description     TEXT,
    amount          NUMERIC(10,2) NOT NULL,
    -- số âm
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_NEW_indirect_expenses_date"
    ON "NEW_indirect_expenses" (expense_date);


-- ============================================================
-- VIEW: NEW_v_order_items_csv
-- Tái tạo đúng cấu trúc file CSV "Order Items" của Sellerboard
-- Gồm cả normal orders và returns
--
-- Lọc normal orders theo ngày:
--   WHERE order_date = '2026-06-08' AND row_type = 'normal'
-- Lọc returns (dùng posted_date):
--   WHERE sort_ts::date = '2026-06-08' AND row_type = 'return'
-- ============================================================
CREATE OR REPLACE VIEW "NEW_v_order_items_csv" AS

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
    -- Gross profit = Sales + Amazon fees (âm) + COG (âm)
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

FROM "NEW_sp_orders" o
JOIN "NEW_sp_order_items" oi ON o.order_id = oi.order_id

LEFT JOIN LATERAL (
    SELECT SUM(amount) AS total_fees
    FROM "NEW_fin_item_fees"
    WHERE order_id = o.order_id
      AND sku       = oi.sku
      AND asin      = oi.asin
) fees ON true

LEFT JOIN LATERAL (
    SELECT cog_per_unit
    FROM "NEW_product_cogs"
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

FROM "NEW_fin_refunds" r
JOIN "NEW_sp_orders" o ON r.order_id = o.order_id
LEFT JOIN "NEW_sp_order_items" oi
    ON r.order_id = oi.order_id AND r.sku = oi.sku AND r.asin = oi.asin;


-- ============================================================
-- FUNCTION: NEW_fn_daily_summary(p_date DATE)
-- Tái tạo Dashboard Card của Sellerboard cho 1 ngày cụ thể
--
-- Gọi: SELECT * FROM "NEW_fn_daily_summary"('2026-06-08');
-- ============================================================
CREATE OR REPLACE FUNCTION "NEW_fn_daily_summary"(p_date DATE)
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
    refund_rate_pct     NUMERIC,
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
    FROM "NEW_sp_orders" o
    JOIN "NEW_sp_order_items" oi ON o.order_id = oi.order_id
    WHERE o.purchase_date::date = p_date
      AND o.order_status NOT IN ('Canceled', 'Cancelled')
),
fees AS (
    SELECT COALESCE(SUM(amount), 0) AS total_fees
    FROM "NEW_fin_item_fees"
    WHERE posted_date::date = p_date
),
adj AS (
    SELECT COALESCE(SUM(amount), 0) AS total_adj
    FROM "NEW_fin_adjustments"
    WHERE posted_date::date = p_date
),
ref AS (
    SELECT
        COUNT(*)        AS ref_count,
        COALESCE(SUM(
            refund_principal + refund_commission + refunded_referral_fee
        ), 0)           AS ref_cost
    FROM "NEW_fin_refunds"
    WHERE posted_date::date = p_date
),
ads AS (
    SELECT COALESCE(SUM(cost), 0) AS total_ads
    FROM "NEW_ads_campaigns_daily"
    WHERE report_date = p_date
),
cog AS (
    SELECT COALESCE(SUM(
        oi.quantity_ordered * COALESCE(pc.cog_per_unit, 0)
    ), 0) AS total_cog
    FROM "NEW_sp_orders" o
    JOIN "NEW_sp_order_items" oi ON o.order_id = oi.order_id
    LEFT JOIN LATERAL (
        SELECT cog_per_unit
        FROM "NEW_product_cogs"
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
    FROM "NEW_indirect_expenses"
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
        ROUND(ref.ref_count::numeric / ord.total_units * 100, 2) END AS refund_rate_pct,
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
