-- ============================================================
-- FIX 1: Bỏ FK order_id -> Profit_Phase1_sp_orders trên Profit_Phase1_fin_item_fees / Profit_Phase1_fin_refunds
--
-- Lý do: Orders ingestion lọc theo purchase_date (--from/--to), còn Finances
-- ingestion lọc theo posted_date (PostedAfter/PostedBefore). Một sự kiện phí/
-- refund có thể "posted" trong kỳ hiện tại nhưng order gốc lại "purchased"
-- ở kỳ trước (ngoài cửa sổ Orders đang ingest) -> Profit_Phase1_sp_orders chưa có
-- order_id đó -> FK violation 23503, làm crash toàn bộ batch upsert.
-- Đây là 2 stream độc lập theo thiết kế Direct-Stream Ingestion, không nên
-- ràng buộc referential integrity cross-stream.
-- (Profit_Phase1_sp_order_items giữ FK vì cùng nguồn Orders API, cùng cửa sổ ngày.)
-- ============================================================
ALTER TABLE "Profit_Phase1_fin_item_fees" DROP CONSTRAINT IF EXISTS "Profit_Phase1_fin_item_fees_order_id_fkey";
ALTER TABLE "Profit_Phase1_fin_refunds"   DROP CONSTRAINT IF EXISTS "Profit_Phase1_fin_refunds_order_id_fkey";


-- ============================================================
-- FIX 2: Profit_Phase2_summary_order_items thiếu 2 cột có trong SummaryOrderItem
-- dataclass (aggregation_models.py) nhưng chưa từng được thêm vào schema:
--   - order_status (Shipped | Pending | ... )
--   - price_source (ACTUAL | ESTIMATED)
-- Thiếu cột này làm write_summaries() lỗi PGRST204 ngay từ Mart 1 (items),
-- khiến Mart 2 (products) và Mart 3 (campaigns) không được viết theo.
-- ============================================================
ALTER TABLE "Profit_Phase2_summary_order_items" ADD COLUMN IF NOT EXISTS order_status TEXT NOT NULL DEFAULT '';
ALTER TABLE "Profit_Phase2_summary_order_items" ADD COLUMN IF NOT EXISTS price_source TEXT NOT NULL DEFAULT 'ACTUAL';
