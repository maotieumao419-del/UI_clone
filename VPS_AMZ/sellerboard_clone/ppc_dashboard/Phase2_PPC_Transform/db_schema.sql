-- PPC Dashboard — Supabase table definitions (prefix PPC_*)
-- Chạy lần đầu trên Supabase SQL Editor để tạo bảng
-- KHÔNG xóa/sửa bảng NEW_* hoặc bảng sống của web app

-- ════════════════════════════════════════════════════════════════
-- PHASE 1 — Raw / Snapshot tables
-- ════════════════════════════════════════════════════════════════

-- Portfolios snapshot
CREATE TABLE IF NOT EXISTS PPC_Phase1_portfolios (
    portfolio_id    TEXT PRIMARY KEY,
    name            TEXT,
    state           TEXT,
    budget_amount   NUMERIC(12,2),
    budget_currency TEXT,
    budget_policy   TEXT,
    in_budget       BOOLEAN,
    synced_at       TIMESTAMPTZ
);

-- Campaigns management snapshot (current state)
CREATE TABLE IF NOT EXISTS PPC_Phase1_campaigns_raw (
    campaign_id       TEXT PRIMARY KEY,
    name              TEXT,
    state             TEXT,
    targeting_type    TEXT,
    daily_budget      NUMERIC(10,2),
    start_date        TEXT,
    end_date          TEXT,
    premium_bid_adj   BOOLEAN,
    bidding_strategy  TEXT,
    portfolio_id      TEXT,
    synced_at         TIMESTAMPTZ
);

-- Ad Groups management snapshot
CREATE TABLE IF NOT EXISTS PPC_Phase1_adgroups_raw (
    adgroup_id   TEXT PRIMARY KEY,
    campaign_id  TEXT,
    name         TEXT,
    state        TEXT,
    default_bid  NUMERIC(10,4),
    synced_at    TIMESTAMPTZ
);

-- Keywords management snapshot
CREATE TABLE IF NOT EXISTS PPC_Phase1_keywords_raw (
    keyword_id   TEXT PRIMARY KEY,
    adgroup_id   TEXT,
    campaign_id  TEXT,
    keyword_text TEXT,
    match_type   TEXT,
    state        TEXT,
    bid          NUMERIC(10,4),
    synced_at    TIMESTAMPTZ
);

-- Targets management snapshot (product/ASIN targeting)
CREATE TABLE IF NOT EXISTS PPC_Phase1_targets_raw (
    target_id      TEXT PRIMARY KEY,
    adgroup_id     TEXT,
    campaign_id    TEXT,
    targeting_type TEXT,
    expression     TEXT,
    bid            NUMERIC(10,4),
    state          TEXT,
    synced_at      TIMESTAMPTZ
);

-- Campaign-level daily metrics (from report)
CREATE TABLE IF NOT EXISTS PPC_Phase1_campaigns_daily (
    report_date         DATE,
    campaign_id         TEXT,
    campaign_name       TEXT,
    campaign_status     TEXT,
    bidding_strategy    TEXT,
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    purchases_1d        INTEGER,
    purchases_7d        INTEGER,
    purchases_14d       INTEGER,
    sales_1d            NUMERIC(12,2),
    sales_7d            NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    units_sold_1d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    roas_14d            NUMERIC(10,4),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, campaign_id)
);

-- Ad Group daily metrics
CREATE TABLE IF NOT EXISTS PPC_Phase1_adgroups_daily (
    report_date         DATE,
    adgroup_id          TEXT,
    campaign_id         TEXT,
    adgroup_name        TEXT,
    adgroup_status      TEXT,
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    purchases_1d        INTEGER,
    purchases_14d       INTEGER,
    sales_1d            NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    units_sold_1d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, adgroup_id)
);

-- Keyword daily metrics
CREATE TABLE IF NOT EXISTS PPC_Phase1_keywords_daily (
    report_date         DATE,
    keyword_id          TEXT,
    campaign_id         TEXT,
    adgroup_id          TEXT,
    keyword_text        TEXT,
    keyword_status      TEXT,
    match_type          TEXT,
    bid                 NUMERIC(10,4),
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    purchases_1d        INTEGER,
    purchases_14d       INTEGER,
    sales_1d            NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    units_sold_1d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, keyword_id)
);

-- Target daily metrics
CREATE TABLE IF NOT EXISTS PPC_Phase1_targets_daily (
    report_date     DATE,
    target_id       TEXT,
    campaign_id     TEXT,
    adgroup_id      TEXT,
    targeting_text  TEXT,
    targeting_type  TEXT,
    bid             NUMERIC(10,4),
    impressions     INTEGER,
    clicks          INTEGER,
    cost            NUMERIC(12,2),
    purchases_1d    INTEGER,
    purchases_14d   INTEGER,
    sales_1d        NUMERIC(12,2),
    sales_14d       NUMERIC(12,2),
    units_sold_1d   INTEGER,
    synced_at       TIMESTAMPTZ,
    PRIMARY KEY (report_date, target_id)
);

-- Search Term daily metrics
CREATE TABLE IF NOT EXISTS PPC_Phase1_searchterms_daily (
    report_date         DATE,
    campaign_id         TEXT,
    adgroup_id          TEXT,
    keyword_id          TEXT,
    keyword_text        TEXT,
    match_type          TEXT,
    query               TEXT,
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    purchases_1d        INTEGER,
    purchases_14d       INTEGER,
    sales_1d            NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    units_sold_1d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, campaign_id, adgroup_id, keyword_id, query)
);

-- Placement-segmented daily (cho topOfSearch%)
CREATE TABLE IF NOT EXISTS PPC_Phase1_placement_daily (
    report_date   DATE,
    campaign_id   TEXT,
    placement     TEXT,    -- TOP_OF_SEARCH | REST_OF_SEARCH | PRODUCT_PAGE
    impressions   INTEGER,
    clicks        INTEGER,
    cost          NUMERIC(12,2),
    purchases_14d INTEGER,
    sales_14d     NUMERIC(12,2),
    synced_at     TIMESTAMPTZ,
    PRIMARY KEY (report_date, campaign_id, placement)
);

-- Bid recommendations snapshot
CREATE TABLE IF NOT EXISTS PPC_Phase1_bid_recommendations (
    snapshot_date  DATE,
    keyword_id     TEXT,
    placement      TEXT,
    suggested_bid  NUMERIC(10,4),
    range_start    NUMERIC(10,4),
    range_end      NUMERIC(10,4),
    synced_at      TIMESTAMPTZ,
    PRIMARY KEY (snapshot_date, keyword_id, placement)
);

-- ════════════════════════════════════════════════════════════════
-- PHASE 2 — Summary / Derived tables
-- ════════════════════════════════════════════════════════════════

-- Campaign summary (đủ 25 cột Sellervision PPC CSV)
CREATE TABLE IF NOT EXISTS PPC_Phase2_summary_campaigns (
    report_date         DATE,
    campaign_id         TEXT,
    campaign_name       TEXT,
    status              TEXT,
    bidding_strategy    TEXT,
    daily_budget        NUMERIC(10,2),
    portfolio_id        TEXT,
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    purchases_14d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    -- Derived
    acos                NUMERIC(8,2),
    cvr                 NUMERIC(8,2),
    cpc                 NUMERIC(10,4),
    ctr                 NUMERIC(10,4),
    roas                NUMERIC(10,4),
    orders              INTEGER,
    units               INTEGER,
    cost_per_order      NUMERIC(10,4),
    same_sku_pct        NUMERIC(8,2),
    budget_utilization  NUMERIC(8,2),
    top_of_search_pct   NUMERIC(8,2),
    break_even_acos     NUMERIC(8,2),
    break_even_bid      NUMERIC(10,4),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, campaign_id)
);

-- Ad Group summary
CREATE TABLE IF NOT EXISTS PPC_Phase2_summary_adgroups (
    report_date         DATE,
    adgroup_id          TEXT,
    adgroup_name        TEXT,
    status              TEXT,
    campaign_id         TEXT,
    default_bid         NUMERIC(10,4),
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    purchases_14d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    acos                NUMERIC(8,2),
    cvr                 NUMERIC(8,2),
    cpc                 NUMERIC(10,4),
    ctr                 NUMERIC(10,4),
    roas                NUMERIC(10,4),
    orders              INTEGER,
    units               INTEGER,
    cost_per_order      NUMERIC(10,4),
    same_sku_pct        NUMERIC(8,2),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, adgroup_id)
);

-- Keyword summary (có bid + bid recommendation)
CREATE TABLE IF NOT EXISTS PPC_Phase2_summary_keywords (
    report_date         DATE,
    keyword_id          TEXT,
    keyword_text        TEXT,
    match_type          TEXT,
    status              TEXT,
    campaign_id         TEXT,
    adgroup_id          TEXT,
    current_bid         NUMERIC(10,4),
    bid_recommendation  NUMERIC(10,4),
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    purchases_14d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    acos                NUMERIC(8,2),
    cvr                 NUMERIC(8,2),
    cpc                 NUMERIC(10,4),
    ctr                 NUMERIC(10,4),
    roas                NUMERIC(10,4),
    orders              INTEGER,
    units               INTEGER,
    cost_per_order      NUMERIC(10,4),
    same_sku_pct        NUMERIC(8,2),
    break_even_acos     NUMERIC(8,2),
    break_even_bid      NUMERIC(10,4),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, keyword_id)
);

-- Search Term summary
CREATE TABLE IF NOT EXISTS PPC_Phase2_summary_searchterms (
    report_date         DATE,
    campaign_id         TEXT,
    adgroup_id          TEXT,
    keyword_id          TEXT,
    keyword_text        TEXT,
    match_type          TEXT,
    query               TEXT,
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    purchases_14d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    acos                NUMERIC(8,2),
    cvr                 NUMERIC(8,2),
    cpc                 NUMERIC(10,4),
    ctr                 NUMERIC(10,4),
    roas                NUMERIC(10,4),
    orders              INTEGER,
    units               INTEGER,
    cost_per_order      NUMERIC(10,4),
    same_sku_pct        NUMERIC(8,2),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, campaign_id, adgroup_id, keyword_id, query)
);

-- Portfolio summary (aggregate từ campaigns)
CREATE TABLE IF NOT EXISTS PPC_Phase2_summary_portfolios (
    report_date         DATE,
    portfolio_id        TEXT,
    portfolio_name      TEXT,
    status              TEXT,
    budget_amount       NUMERIC(12,2),
    campaign_count      INTEGER,
    impressions         INTEGER,
    clicks              INTEGER,
    cost                NUMERIC(12,2),
    sales_14d           NUMERIC(12,2),
    purchases_14d       INTEGER,
    units_sold_14d      INTEGER,
    same_sku_sales_14d  NUMERIC(12,2),
    acos                NUMERIC(8,2),
    cvr                 NUMERIC(8,2),
    cpc                 NUMERIC(10,4),
    ctr                 NUMERIC(10,4),
    roas                NUMERIC(10,4),
    orders              INTEGER,
    units               INTEGER,
    cost_per_order      NUMERIC(10,4),
    same_sku_pct        NUMERIC(8,2),
    budget_utilization  NUMERIC(8,2),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (report_date, portfolio_id)
);

-- ════════════════════════════════════════════════════════════════
-- BULK MIRROR — mô phỏng file "Sponsored Products Bulk Operations" của Amazon
-- (sheet "Sponsored Products Campaigns", 53 cột). 1 dòng = 1 entity
-- (Campaign/Ad Group/Keyword/Product Targeting) với settings (từ Phase1 raw
-- mgmt) + metrics tổng hợp trong khoảng [period_start, period_end] (từ Phase1
-- daily). Dùng để XUẤT/ĐỐI CHIẾU trực tiếp với file tải từ Amazon.
-- ════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS PPC_Phase2_bulk_sp (
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    entity              TEXT NOT NULL,   -- Campaign | Ad Group | Keyword | Product Targeting
    row_key             TEXT NOT NULL,   -- id của entity ở cấp tương ứng
    -- IDs
    portfolio_id        TEXT,
    campaign_id         TEXT,
    adgroup_id          TEXT,
    keyword_id          TEXT,
    target_id           TEXT,
    -- Tên
    campaign_name       TEXT,
    adgroup_name        TEXT,
    portfolio_name      TEXT,
    -- Settings (mirror bulk)
    start_date          TEXT,
    end_date            TEXT,
    targeting_type      TEXT,
    state               TEXT,
    daily_budget        NUMERIC(10,2),
    sku                 TEXT,
    asin                TEXT,
    adgroup_default_bid NUMERIC(10,4),
    bid                 NUMERIC(10,4),
    keyword_text        TEXT,
    match_type          TEXT,
    bidding_strategy    TEXT,
    placement           TEXT,
    percentage          NUMERIC(8,2),
    product_targeting_expression TEXT,
    -- Metrics tổng hợp trong kỳ
    impressions         INTEGER,
    clicks              INTEGER,
    ctr                 NUMERIC(10,4),   -- Click-through Rate %
    spend               NUMERIC(12,2),
    sales               NUMERIC(12,2),
    orders              INTEGER,
    units               INTEGER,
    conversion_rate     NUMERIC(8,2),
    acos                NUMERIC(8,2),
    cpc                 NUMERIC(10,4),
    roas                NUMERIC(10,4),
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (period_start, period_end, entity, row_key)
);

CREATE INDEX IF NOT EXISTS idx_ppc_bulk_period ON PPC_Phase2_bulk_sp(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_ppc_bulk_entity ON PPC_Phase2_bulk_sp(entity);


-- ════════════════════════════════════════════════════════════════
-- Indexes
-- ════════════════════════════════════════════════════════════════

CREATE INDEX IF NOT EXISTS idx_ppc_campaigns_daily_date   ON PPC_Phase1_campaigns_daily(report_date);
CREATE INDEX IF NOT EXISTS idx_ppc_keywords_daily_date    ON PPC_Phase1_keywords_daily(report_date);
CREATE INDEX IF NOT EXISTS idx_ppc_searchterms_daily_date ON PPC_Phase1_searchterms_daily(report_date);
CREATE INDEX IF NOT EXISTS idx_ppc_summary_camp_date      ON PPC_Phase2_summary_campaigns(report_date);
CREATE INDEX IF NOT EXISTS idx_ppc_summary_kw_date        ON PPC_Phase2_summary_keywords(report_date);
CREATE INDEX IF NOT EXISTS idx_ppc_summary_st_date        ON PPC_Phase2_summary_searchterms(report_date);
CREATE INDEX IF NOT EXISTS idx_ppc_placement_date_camp    ON PPC_Phase1_placement_daily(report_date, campaign_id);
