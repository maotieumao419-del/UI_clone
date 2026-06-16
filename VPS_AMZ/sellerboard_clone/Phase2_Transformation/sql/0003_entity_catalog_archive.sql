-- ============================================================
-- 0003 — ADDITIVE: Catalog hub + Ads entity tree (dimension) + Raw archive log
--
-- Bổ sung "phần call_API làm tốt hơn" vào pipeline NEW_*:
--   1. NEW_products            — Catalog hub (Ads ASIN ↔ Ops SKU gặp nhau)
--   2. NEW_ad_portfolios/_ad_campaigns/_ad_groups/_ad_keywords — cây hồ sơ ads
--      (DIMENSION: state/budget/bid hiện tại — TÁCH khỏi NEW_ads_*_daily là perf)
--   3. NEW_raw_archive_log     — sổ con trỏ tới object raw đã đẩy lên R2 (bronze)
--
-- CHỈ THÊM. KHÔNG drop/sửa bảng nào đang sống. Idempotent: CREATE ... IF NOT EXISTS.
-- Chạy: Supabase SQL Editor → Paste → Run.
-- ============================================================

-- ── 1) Catalog hub ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS "NEW_products" (
    sku         TEXT PRIMARY KEY,
    asin        TEXT,
    fnsku       TEXT,
    title       TEXT,
    first_seen  DATE,
    last_seen   DATE,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_NEW_products_asin" ON "NEW_products"(asin);


-- ── 2) Ads entity tree (dimension cha→con) ──────────────────
CREATE TABLE IF NOT EXISTS "NEW_ad_portfolios" (
    portfolio_id   TEXT PRIMARY KEY,
    name           TEXT,
    budget_amount  NUMERIC(12,2),
    budget_policy  TEXT,
    state          TEXT,
    synced_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "NEW_ad_campaigns" (
    campaign_id      TEXT PRIMARY KEY,
    portfolio_id     TEXT,
    name             TEXT,
    state            TEXT,
    targeting_type   TEXT,
    budget_amount    NUMERIC(12,2),
    budget_type      TEXT,
    bidding_strategy TEXT,
    advertised_asin  TEXT,   -- parse từ tên campaign (regex B0[A-Z0-9]{8}) → nối NEW_products.asin
    start_date       DATE,
    synced_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_NEW_ad_campaigns_portfolio" ON "NEW_ad_campaigns"(portfolio_id);
CREATE INDEX IF NOT EXISTS "idx_NEW_ad_campaigns_asin"      ON "NEW_ad_campaigns"(advertised_asin);

CREATE TABLE IF NOT EXISTS "NEW_ad_groups" (
    ad_group_id   TEXT PRIMARY KEY,
    campaign_id   TEXT,
    name          TEXT,
    state         TEXT,
    default_bid   NUMERIC(12,2),
    synced_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_NEW_ad_groups_campaign" ON "NEW_ad_groups"(campaign_id);

CREATE TABLE IF NOT EXISTS "NEW_ad_keywords" (
    keyword_id    TEXT PRIMARY KEY,
    ad_group_id   TEXT,
    campaign_id   TEXT,
    keyword_text  TEXT,
    match_type    TEXT,
    state         TEXT,
    bid           NUMERIC(12,2),
    synced_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_NEW_ad_keywords_ad_group" ON "NEW_ad_keywords"(ad_group_id);


-- ── 3) Raw archive log (con trỏ R2; KHÔNG chứa data) ────────
CREATE TABLE IF NOT EXISTS "NEW_raw_archive_log" (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,
    archive_date DATE,
    object_key   TEXT NOT NULL,
    rows         INTEGER DEFAULT 0,
    bytes        BIGINT  DEFAULT 0,
    synced_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_NEW_raw_archive_log_source_date"
    ON "NEW_raw_archive_log"(source, archive_date);


-- ── 4) Seed Catalog hub từ dữ liệu sẵn có (idempotent) ──────
-- Gom asin↔sku từ order items (Ops) + advertised product report (Ads) → NEW_products.
-- first_seen giữ nguyên khi đã tồn tại; chỉ cập nhật last_seen/asin/title nếu thiếu.
CREATE OR REPLACE FUNCTION "NEW_fn_seed_products"() RETURNS void LANGUAGE SQL AS $$
    INSERT INTO "NEW_products" (sku, asin, title, first_seen, last_seen, updated_at)
    SELECT s.sku, MAX(s.asin) AS asin, MAX(s.title) AS title,
           CURRENT_DATE, CURRENT_DATE, NOW()
    FROM (
        SELECT sku, asin, title
        FROM "NEW_sp_order_items"
        WHERE sku IS NOT NULL AND sku <> ''
        UNION ALL
        SELECT advertised_sku AS sku, advertised_asin AS asin, NULL::text AS title
        FROM "NEW_ads_sp_asin_daily"
        WHERE advertised_sku IS NOT NULL AND advertised_sku <> ''
    ) s
    GROUP BY s.sku
    ON CONFLICT (sku) DO UPDATE
       SET asin       = COALESCE("NEW_products".asin, EXCLUDED.asin),
           title      = COALESCE("NEW_products".title, EXCLUDED.title),
           last_seen  = CURRENT_DATE,
           updated_at = NOW();
$$;

-- Chạy seed 1 lần ngay khi áp migration (backfill từ data đã có):
SELECT "NEW_fn_seed_products"();
