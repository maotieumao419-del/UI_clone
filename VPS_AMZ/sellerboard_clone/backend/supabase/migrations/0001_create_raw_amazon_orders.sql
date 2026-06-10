-- ============================================================================
-- SellerVision · Tầng đệm dữ liệu (Data Buffer / Staging Area) trên Supabase
-- Module: Đồng bộ dữ liệu Amazon SP-API (Giai đoạn 1: Inbound Streaming)
--
-- Mục đích: chứa Raw JSON đơn hàng từ Amazon SP-API trước khi FastAPI xử lý
-- và ghi dữ liệu tinh gọn xuống SQLite local (sellervision.db).
--
-- Mô hình Đa tài khoản (Multi-account): mỗi gian hàng (seller) có dữ liệu
-- tách biệt hoàn toàn. Khoá chính phức hợp (seller_id, amazon_order_id) đảm
-- bảo Idempotency khi Bulk Upsert nhiều lần — chạy lại không tạo trùng dòng.
-- ============================================================================

-- BẢNG: Bộ đệm chứa dữ liệu Đơn hàng thô từ Amazon SP-API
CREATE TABLE IF NOT EXISTS raw_amazon_orders (
    seller_id        VARCHAR(50)  NOT NULL,
    amazon_order_id  VARCHAR(50)  NOT NULL,
    order_status     VARCHAR(30),
    purchase_date    TIMESTAMPTZ,
    raw_json         JSONB        NOT NULL,
    updated_at       TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (seller_id, amazon_order_id)
);

-- Chỉ mục tối ưu hoá truy vấn phân trang ngược (Giai đoạn 2: đọc theo
-- seller_id, sắp xếp theo purchase_date giảm dần để lấy đơn mới nhất trước)
CREATE INDEX IF NOT EXISTS idx_raw_orders_seller_date
    ON raw_amazon_orders (seller_id, purchase_date DESC);
