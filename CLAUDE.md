# SellerVision — Hướng dẫn cho Claude khi code trong repo này

File này TỰ ĐỘNG nạp mỗi session mở trong `VPS\`. Mục tiêu: tránh lặp lại các
guardrails/quy ước đã thống nhất qua nhiều session trước.

Tài liệu sâu (đọc khi cần chi tiết, không cần thuộc):
- [`VPS_AMZ/sellerboard_clone/docs/SESSION_HANDOFF.md`](VPS_AMZ/sellerboard_clone/docs/SESSION_HANDOFF.md) — bàn giao, việc đang dở, baseline đối chiếu Sellerboard. **Đọc đầu mỗi session liên quan đến pipeline/fees.**
- [`VPS_AMZ/sellerboard_clone/PIPELINE_3PHASE_README.md`](VPS_AMZ/sellerboard_clone/PIPELINE_3PHASE_README.md) — kiến trúc pipeline 3 giai đoạn, timezone protocol, memory-safety.

## Kiến trúc tổng quan

```
Amazon API ──(Phase1: Direct-Stream)──► Supabase NEW_* (bảng đệm)
Supabase   ──(Phase2: Transform)──────► NEW_summary_order_items / NEW_summary_products / NEW_summary_campaigns
Summary    ──(Phase3: Bridge/Patch)───► Web App app.tap2soul.com
```
Vị trí: `VPS_AMZ/sellerboard_clone/{Phase1_Ingestion, Phase2_Transformation, Phase3_Application}`.

## Guardrails CỨNG — không vi phạm

1. **KHÔNG sửa tay `backend/` và `frontend/`** (production `app.tap2soul.com`).
   Mọi thay đổi phải qua `Phase3_Application/data_bridge/patch_scripts/`
   (`patch_dashboard.py` / `patch_frontend.py`, có `--check`, backup + rollback).
2. **Supabase Postgres = vừa bảng đệm pipeline (`NEW_*`) vừa DB sống của web app**
   (`users, products, orders, order_items, settlement_entries...`). TUYỆT ĐỐI
   không xóa/drop các bảng không có prefix `NEW_`.
3. **`--fresh` chỉ xóa raw `NEW_*` của nguồn được chọn** — KHÔNG xóa
   `NEW_product_price`, `NEW_product_cogs`, `NEW_fee_cache` (đều là dữ liệu
   tích lũy/persistent). `transform --fresh` xóa summary riêng.
4. **User kiểm soát việc chạy ingest/transform** (tốn quota API + ảnh hưởng dữ
   liệu thật). Claude soạn lệnh, user tự chạy. Chỉ tự chạy: read-only, DB-admin
   qua `_dbadmin.py`, sửa code, hoặc khi user đã cho phép rõ ràng.
5. **Bash thiếu `cat/grep/sed/tail`** trong môi trường này — dùng Python hoặc
   PowerShell (đã có sẵn Bash + PowerShell tool, ưu tiên dùng đúng tool).

## Quy ước dấu & công thức (chuẩn Sellerboard)

Doanh thu DƯƠNG, mọi chi phí ÂM, các cột cộng dồn được:
```
Gross_Profit = Sales + Promo + Amazon_fees + COGS + Shipping
Net_Profit   = Gross_Profit + Ads + Refund_cost + Expenses
Margin       = Net_Profit / Sales × 100
amazon_fees  = Referral (Commission) + FBA Fulfillment  (chỉ 2 thành phần này)
```

## Fee model — ĐÃ KIỂM CHỨNG, đừng "sửa lại"

- **Referral fee thật = 16.5% của principal** (= 15% Amazon + 10% VAT VN trên
  phí dịch vụ). Min fee $0.33 = $0.30 × 1.1. Phân phối cực chụm (p5–p95
  0.1649–0.1660, n=1077). **Kỳ vọng cũ "~14-15%" là SAI, không phải bug
  calibrate.**
- **Sellerboard cũng ước lượng đúng mô hình này**:
  `fees ≈ -(16.5% × sales + FBA_thật_per_SKU × units)` (median sai số $0.003).
  Khi đối chiếu lệch vs Sellerboard real-time, so với MÔ HÌNH này (FBA=0 nếu
  SKU chưa có lịch sử ở SB) — không coi số SB hiển thị là chân lý tuyệt đối,
  vì phí thật trễ ≥9 ngày và cả hai bên đều đang ESTIMATE.
- Hybrid fee (`transform_engine.py`): `fee_state` = ACTUAL (khớp
  `NEW_fin_item_fees` theo order_id+sku) | ESTIMATED (Pending: sales×referral;
  Shipped: + fba×units) | MIXED. Rate: `NEW_fee_cache` override → auto-derive
  từ median phí thật per-SKU → fallback referral mặc định.
- Chi tiết đầy đủ + số liệu calibrate 12/06: xem
  `SESSION_HANDOFF.md` mục 3 & 5 và memory `sellervision-fee-model`.

## Timezone protocol (Pacific = chuẩn Sellerboard)

- Phase 1 lưu nguyên ISO 8601 UTC từ Amazon — KHÔNG quy đổi lúc ghi.
- Phase 2 group-by ngày: ép `UTC → America/Los_Angeles` TRƯỚC khi `.date()`.
  SQL: `(ts AT TIME ZONE 'UTC' AT TIME ZONE 'America/Los_Angeles')::date`.
- Ads `report_date` ĐÃ là Pacific — không quy đổi lần 2.
- Backend: mốc "hôm nay" tính server-side bằng `now_marketplace()`
  (`backend/app/timeutils.py`). Frontend chỉ gửi `days=N`, không tự tính ngày
  theo giờ máy client.
- DST tự động (UTC-7 hè / UTC-8 đông) — không hardcode offset.

## Memory-safety (cả 3 phase, chống OOM Killer)

- Phân trang ≤100 records/chunk; upsert ngay từng trang, không tích lũy list lớn.
- `del payload` + `gc.collect()` sau mỗi chu kỳ ghi.
- Retry 429 với `Retry-After` + backoff.
- Bridge (Phase 3): mỗi đơn 1 savepoint (`db.begin_nested()`) — 1 đơn lỗi
  không sập cả batch. Strict mapping seller→User: không khớp → `ValueError`
  dừng ngay, KHÔNG fallback.

## Đối chiếu file Sellerboard (reconciliation)

- So SỐ với tolerance 0.01, KHÔNG so chuỗi (Excel ép số→ngày kiểu `18.01`→datetime,
  header có ký tự Cyrillic `Refund сost`, `'0.00'` vs ô trống).
- File user export có thể KHÔNG có header → đọc theo vị trí cột.
- `Canceled` loại khỏi summary; `Pending` vẫn tính sales.

## VPS / DB admin

- VPS `sellervision@REDACTED_VPS_IP`, SSH chỉ nhận password (paramiko, không có
  key). `sudo -S` + password. Service systemd `sellervision`, venv `backend/venv`.
- App DB thật = Supabase Postgres qua `DATABASE_URL` (KHÔNG phải SQLite).
- Helper gốc (không commit): `_dbadmin.py` (list/all/count/status/feematch/sql/drop),
  `_vps.py`/`_vps_upload.py` (paramiko).
