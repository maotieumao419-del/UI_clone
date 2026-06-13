-- ============================================================
-- APP SCHEMA (raw SQL mirror of alembic 0001_initial_schema + 0002_add_product_image_url)
--
-- Dùng khi không có alembic/sqlalchemy cài sẵn trong môi trường (vd. máy dev
-- Windows này) — chạy bằng: python _dbadmin.py sql backend/supabase/migrations/0002_initial_app_schema.sql
-- Trên VPS (có venv đầy đủ) vẫn dùng `alembic upgrade head` như bình thường;
-- file này CHỈ để tái tạo schema tương đương trên Supabase khi DB bị xoá sạch.
-- Idempotent: CREATE TABLE/INDEX IF NOT EXISTS.
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    full_name       VARCHAR(255) NOT NULL DEFAULT '',
    hashed_password VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    consent         JSON NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);


CREATE TABLE IF NOT EXISTS products (
    id                          SERIAL PRIMARY KEY,
    owner_id                    INTEGER NOT NULL REFERENCES users(id),
    asin                        VARCHAR(20) NOT NULL,
    sku                         VARCHAR(64) NOT NULL,
    title                       VARCHAR(512) NOT NULL,
    marketplace                 VARCHAR(20) NOT NULL DEFAULT 'amazon',
    category                    VARCHAR(128) NOT NULL DEFAULT '',
    price                       DOUBLE PRECISION NOT NULL DEFAULT 0,
    current_stock               INTEGER NOT NULL DEFAULT 0,
    inbound_stock               INTEGER NOT NULL DEFAULT 0,
    lead_time_manufacture_days  INTEGER NOT NULL DEFAULT 20,
    lead_time_shipping_days     INTEGER NOT NULL DEFAULT 25,
    lead_time_prep_days         INTEGER NOT NULL DEFAULT 5,
    safety_stock_days           INTEGER NOT NULL DEFAULT 14,
    referral_fee_pct            DOUBLE PRECISION NOT NULL DEFAULT 0.15,
    fba_fee_per_unit            DOUBLE PRECISION NOT NULL DEFAULT 3.5,
    image_url                   TEXT,
    created_at                  TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_products_owner_id ON products (owner_id);
CREATE INDEX IF NOT EXISTS ix_products_asin ON products (asin);
CREATE INDEX IF NOT EXISTS ix_products_sku ON products (sku);


CREATE TABLE IF NOT EXISTS inventory_batches (
    id          SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    received_at TIMESTAMP NOT NULL,
    quantity    INTEGER NOT NULL,
    unit_cost   DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_inventory_batches_product_id ON inventory_batches (product_id);
CREATE INDEX IF NOT EXISTS ix_inventory_batches_received_at ON inventory_batches (received_at);


CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    owner_id        INTEGER NOT NULL REFERENCES users(id),
    external_id     VARCHAR(64) NOT NULL,
    marketplace     VARCHAR(20) NOT NULL DEFAULT 'amazon',
    customer_ref    VARCHAR(64) NOT NULL DEFAULT '',
    purchased_at    TIMESTAMP NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'shipped',
    ppc_cost        DOUBLE PRECISION NOT NULL DEFAULT 0,
    promo_discount  DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_refunded     BOOLEAN NOT NULL DEFAULT FALSE,
    refund_returned BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_orders_owner_id ON orders (owner_id);
CREATE INDEX IF NOT EXISTS ix_orders_external_id ON orders (external_id);
CREATE INDEX IF NOT EXISTS ix_orders_purchased_at ON orders (purchased_at);


CREATE TABLE IF NOT EXISTS order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    unit_price  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items (order_id);
CREATE INDEX IF NOT EXISTS ix_order_items_product_id ON order_items (product_id);


CREATE TABLE IF NOT EXISTS listing_snapshots (
    id          SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    captured_at TIMESTAMP NOT NULL,
    data        JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_listing_snapshots_product_id ON listing_snapshots (product_id);
CREATE INDEX IF NOT EXISTS ix_listing_snapshots_captured_at ON listing_snapshots (captured_at);


CREATE TABLE IF NOT EXISTS bsr_snapshots (
    id          SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    captured_at TIMESTAMP NOT NULL,
    bsr         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bsr_snapshots_product_id ON bsr_snapshots (product_id);
CREATE INDEX IF NOT EXISTS ix_bsr_snapshots_captured_at ON bsr_snapshots (captured_at);


CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    owner_id    INTEGER NOT NULL REFERENCES users(id),
    product_id  INTEGER REFERENCES products(id),
    type        VARCHAR(40) NOT NULL,
    severity    VARCHAR(10) NOT NULL DEFAULT 'info',
    message     TEXT NOT NULL,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alerts_owner_id ON alerts (owner_id);
CREATE INDEX IF NOT EXISTS ix_alerts_type ON alerts (type);
CREATE INDEX IF NOT EXISTS ix_alerts_created_at ON alerts (created_at);


CREATE TABLE IF NOT EXISTS reimbursement_cases (
    id                  SERIAL PRIMARY KEY,
    owner_id            INTEGER NOT NULL REFERENCES users(id),
    product_id          INTEGER NOT NULL REFERENCES products(id),
    reason              VARCHAR(40) NOT NULL,
    quantity            INTEGER NOT NULL DEFAULT 1,
    estimated_amount    DOUBLE PRECISION NOT NULL DEFAULT 0,
    status              VARCHAR(20) NOT NULL DEFAULT 'open',
    detected_at         TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reimbursement_cases_owner_id ON reimbursement_cases (owner_id);
CREATE INDEX IF NOT EXISTS ix_reimbursement_cases_detected_at ON reimbursement_cases (detected_at);


CREATE TABLE IF NOT EXISTS settlement_entries (
    id                  SERIAL PRIMARY KEY,
    owner_id            INTEGER NOT NULL REFERENCES users(id),
    settlement_id       VARCHAR(64) NOT NULL,
    order_id            VARCHAR(64) NOT NULL DEFAULT '',
    transaction_type    VARCHAR(64) NOT NULL,
    amount_type         VARCHAR(64) NOT NULL DEFAULT '',
    amount_description  VARCHAR(128) NOT NULL DEFAULT '',
    amount              DOUBLE PRECISION NOT NULL DEFAULT 0,
    posted_date         TIMESTAMP NOT NULL,
    sku                 VARCHAR(64) NOT NULL DEFAULT '',
    quantity            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_settlement_entries_owner_id ON settlement_entries (owner_id);
CREATE INDEX IF NOT EXISTS ix_settlement_entries_settlement_id ON settlement_entries (settlement_id);
CREATE INDEX IF NOT EXISTS ix_settlement_entries_order_id ON settlement_entries (order_id);
CREATE INDEX IF NOT EXISTS ix_settlement_entries_posted_date ON settlement_entries (posted_date);
CREATE INDEX IF NOT EXISTS ix_settlement_entries_sku ON settlement_entries (sku);


CREATE TABLE IF NOT EXISTS aggregated_daily (
    id              SERIAL PRIMARY KEY,
    owner_id        INTEGER NOT NULL REFERENCES users(id),
    date            TIMESTAMP NOT NULL,
    gross_revenue   DOUBLE PRECISION NOT NULL DEFAULT 0,
    units_sold      INTEGER NOT NULL DEFAULT 0,
    orders_count    INTEGER NOT NULL DEFAULT 0,
    refunds_amount  DOUBLE PRECISION NOT NULL DEFAULT 0,
    refunds_count   INTEGER NOT NULL DEFAULT 0,
    amazon_fees     DOUBLE PRECISION NOT NULL DEFAULT 0,
    cogs            DOUBLE PRECISION NOT NULL DEFAULT 0,
    ppc_cost        DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_revenue     DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_profit      DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP NOT NULL,
    CONSTRAINT uq_aggregated_daily_owner_date UNIQUE (owner_id, date)
);
CREATE INDEX IF NOT EXISTS ix_aggregated_daily_owner_id ON aggregated_daily (owner_id);
CREATE INDEX IF NOT EXISTS ix_aggregated_daily_date ON aggregated_daily (date);


-- Đánh dấu alembic đã ở revision 0002 (để VPS chạy `alembic upgrade head`
-- sau này không cố tạo lại các bảng đã có ở đây).
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);
INSERT INTO alembic_version (version_num) VALUES ('0002')
ON CONFLICT (version_num) DO NOTHING;
