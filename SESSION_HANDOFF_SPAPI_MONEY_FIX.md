# Session Handoff — Fix bug đọc tiền (CurrencyAmount) trong test_lwa_spapi Phase 2

## 🎯 Mục tiêu tổng thể
Sửa các bug đọc sai key tiền tệ từ Amazon SP-API trong module ingest
`test_lwa_spapi/Phase 2/_supabase_ingest.py` (dùng để đẩy dữ liệu Orders/Finances/Ads
từ SP-API lên Supabase bảng `NEW_*`). Bug khiến mọi giá trị fee/refund/adjustment đọc
từ Finances API bị tính ra **0**.

## ✅ Đã hoàn thành
- Phát hiện nguyên nhân: Finances API của Amazon SP-API trả số tiền dưới key
  `"CurrencyAmount"`, nhưng code cũ chỉ đọc `.get("Amount")` (key này chỉ đúng cho
  Orders API). Kết quả: `_float((...).get("Amount"))` luôn ra `0.0` cho dữ liệu
  Finances → `fees_rows` bị `continue` bỏ qua (vì `amount == 0`), và
  `refund_principal` / `refund_commission` / `refunded_referral_fee` luôn = 0.
- Thêm helper `_money(obj)` vào `test_lwa_spapi/Phase 2/_supabase_ingest.py`
  (đặt ngay sau `_int`), copy logic chuẩn từ
  `VPS_AMZ/sellerboard_clone/Phase1_Ingestion/direct_stream_pipeline.py`:
  ```python
  def _money(obj) -> float:
      """Số tiền từ object tiền tệ của Amazon. Finances API dùng key
      'CurrencyAmount', Orders API dùng 'Amount' — đọc cả hai."""
      o = obj or {}
      return _float(o.get("CurrencyAmount", o.get("Amount")))
  ```
- Thay toàn bộ 7 chỗ đọc tiền trong file sang dùng `_money(...)`:
  - `ingest_orders_page()`: `ItemPrice`, `ItemTax`, `PromotionDiscount`
    (Orders API — vẫn đúng vì `_money` fallback về `Amount`).
  - `ingest_finance_events_page()` — **đây là chỗ sửa bug chính**:
    - `ShipmentEventList[].ShipmentItemList[].ItemFeeList[].FeeAmount` (fee_type/amount
      → `NEW_fin_item_fees`, không còn bị skip do amount=0).
    - `RefundEventList[].ShipmentItemAdjustmentList[].ItemChargeAdjustmentList[].ChargeAmount`
      (Principal → `refund_principal`).
    - `RefundEventList[]...ItemFeeAdjustmentList[].FeeAmount` (Commission/RefundCommission
      → `refund_commission` / `refunded_referral_fee`).
    - `AdjustmentEventList[].AdjustmentItemList[].PerUnitAmount` → `adj_rows.amount`.
- Verify: `python -m py_compile "test_lwa_spapi/Phase 2/_supabase_ingest.py"` →
  exit code 0, không lỗi syntax.

## 🔄 Đang dở / Chưa hoàn thiện
- **Chưa test thực tế với data Finances API thật** — chỉ verify bằng `py_compile`
  (syntax check), chưa chạy `ingest_finance_events_page()` với payload mẫu để confirm
  `fees_rows` / `refunds_rows` / `adj_rows` giờ có giá trị non-zero đúng kỳ vọng.
- Chưa kiểm tra liệu các file khác trong `test_lwa_spapi/Phase 2/` (script gọi
  `ingest_finance_events_page` — ví dụ `fetch_24h_finances.py` hoặc tương đương) có
  giả định/transform thêm dựa trên việc "amount luôn = 0" hay không (ví dụ logic
  downstream dựa vào việc fees_rows rỗng).
- Chưa đối chiếu số liệu `NEW_fin_item_fees` / `NEW_fin_refunds` / `NEW_fin_adjustments`
  trên Supabase sau khi sync lại — vẫn còn dữ liệu cũ (toàn 0 hoặc bị skip) từ các lần
  ingest trước khi sửa.

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)
1. Chạy lại `ingest_finance_events_page()` với một trang `FinancialEvents` thật (hoặc
   sample JSON đã lưu) để xác nhận `fees_upserted` / `refunds_upserted` /
   `adjustments_inserted` > 0 và giá trị `amount`/`refund_principal`/...
   không còn = 0.
2. Kiểm tra/làm sạch dữ liệu cũ trong `NEW_fin_item_fees`, `NEW_fin_refunds`,
   `NEW_fin_adjustments` trên Supabase nếu đã từng ingest trước khi sửa (có thể cần
   re-sync lại finance events trong khoảng thời gian đã chạy với code lỗi).
3. Grep toàn bộ `test_lwa_spapi/Phase 2/` (và các file gọi vào
   `_supabase_ingest.py`) xem có nơi khác cũng dùng pattern
   `(...).get("Amount")` trên dữ liệu Finances API mà chưa được rà — đảm bảo không
   còn chỗ nào sót cùng loại bug.
4. Nếu `test_lwa_spapi` là bản test/nháp của pipeline chính thức
   (`VPS_AMZ/sellerboard_clone/Phase1_Ingestion/`), xác nhận với user xem có cần
   merge logic này về pipeline chính hay đây chỉ là môi trường test riêng.

## 🏗️ Kiến trúc / Cấu trúc hệ thống
- `test_lwa_spapi/Phase 2/_supabase_ingest.py` là module dùng chung, được import bởi
  các script `fetch_24h_orders.py` / `fetch_24h_finances.py` / `fetch_24h_ads.py` để
  transform dữ liệu trả về từ Amazon SP-API rồi upsert trực tiếp lên Supabase, ghi
  theo từng trang/chunk (CHUNK_SIZE=100) để tránh tích lũy list lớn trong RAM.
- 3 nhóm hàm chính trong file:
  - `ingest_orders_page(client, orders)` → `NEW_sp_orders` + `NEW_sp_order_items`
    (conflict key: `order_id` / `order_id,asin,sku`).
  - `ingest_finance_events_page(client, events)` → `NEW_fin_item_fees` (conflict:
    `order_id,sku,asin,fee_type`), `NEW_fin_refunds` (conflict:
    `order_id,sku,posted_date`), `NEW_fin_adjustments` (insert thuần, không upsert).
  - `ingest_ads_report(client, data, ad_product, report_date)` → `NEW_ads_campaigns_daily`
    cho 3 loại ad_product: SPONSORED_PRODUCTS / SPONSORED_BRANDS / SPONSORED_DISPLAY.
- Đây là một nhánh "test" tách biệt (`test_lwa_spapi/`), có khả năng song song với
  pipeline chính thức `VPS_AMZ/sellerboard_clone/Phase1_Ingestion/direct_stream_pipeline.py`
  (file này đã có `_money()` đúng từ trước — dùng làm reference khi sửa).

## 📁 Cấu trúc thư mục quan trọng

```
VPS/
├── CLAUDE.md                                  # guardrails chung toàn repo
├── test_lwa_spapi/
│   └── Phase 2/
│       └── _supabase_ingest.py                # ĐÃ SỬA trong session này
└── VPS_AMZ/
    └── sellerboard_clone/
        └── Phase1_Ingestion/
            └── direct_stream_pipeline.py      # bản tham chiếu, đã có _money() đúng
```

## ⚙️ Biến môi trường & Cấu hình (.env)
`_supabase_ingest.py` đọc qua `dotenv.load_dotenv()`:

```env
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGc...   # service role key
```

## 🔑 Thông số kỹ thuật quan trọng
- Bảng đích (prefix `NEW_`): `NEW_sp_orders`, `NEW_sp_order_items`,
  `NEW_fin_item_fees`, `NEW_fin_refunds`, `NEW_fin_adjustments`,
  `NEW_ads_campaigns_daily`.
- `CHUNK_SIZE = 100` cho upsert theo trang.
- Helper tiền tệ chuẩn:
  ```python
  def _money(obj) -> float:
      o = obj or {}
      return _float(o.get("CurrencyAmount", o.get("Amount")))
  ```
  - **Finances API** (ShipmentEventList, RefundEventList, AdjustmentEventList) →
    luôn dùng key `CurrencyAmount`.
  - **Orders API** (`ItemPrice`, `ItemTax`, `PromotionDiscount`) → dùng key `Amount`
    (vẫn đọc đúng qua `_money` nhờ fallback).
- `ingest_finance_events_page()` skip fee nếu `amount == 0` hoặc `fee_type` rỗng —
  cần đảm bảo `_money` trả giá trị thật chứ không phải 0 mặc định.

## 🐛 Vấn đề đã gặp & Cách giải quyết
- **Bug**: `(fee.get("FeeAmount") or {}).get("Amount")` → luôn `None`/`0` với
  Finances API vì key thật là `CurrencyAmount`.
  → **Fix**: tạo `_money()` đọc `CurrencyAmount` trước, fallback `Amount`, áp dụng
  cho tất cả 7 vị trí đọc tiền trong file (cả Orders và Finances) để nhất quán.
- Ghi chú môi trường: trong môi trường chạy Claude Code hiện tại, `find`/PowerShell
  `Get-ChildItem` không thấy file `test_lwa_spapi/...` từ shell, dù
  Read/Edit/py_compile tool vẫn truy cập và sửa file thành công — có khả năng do khác
  filesystem view giữa tool Edit và Bash/PowerShell shell. Nếu session sau gặp tương
  tự (path "not found" qua Bash/PowerShell nhưng Read tool đọc được), cứ tin tưởng
  Read/Edit/Write tool, không cần lo lắng.

## 🚫 Quyết định đã được xác nhận (không thay đổi)
- Dùng đúng pattern `_money()` đã được verify trong
  `VPS_AMZ/sellerboard_clone/Phase1_Ingestion/direct_stream_pipeline.py` — KHÔNG tự
  nghĩ ra cách đọc tiền khác.
- Áp dụng `_money()` cho cả phần Orders API (ItemPrice/ItemTax/PromotionDiscount) dù
  bug gốc chỉ ở Finances, để toàn file nhất quán 1 cách đọc tiền duy nhất.

## 💡 Context bổ sung
- Repo này (`VPS`) là project SellerVision — đọc `CLAUDE.md` ở root để biết guardrails
  chung (KHÔNG sửa tay `backend/`/`frontend/` production, quy ước dấu Gross/Net
  Profit, fee model referral 16.5%, timezone Pacific, memory-safety pagination...).
  Các guardrails đó áp dụng cho `VPS_AMZ/sellerboard_clone/`, còn `test_lwa_spapi/`
  có vẻ là môi trường test SP-API độc lập — cần hỏi user nếu không chắc phạm vi.
- Việc sửa trong session này CHỈ giới hạn ở
  `test_lwa_spapi/Phase 2/_supabase_ingest.py`, chưa động đến
  `VPS_AMZ/sellerboard_clone/` (file đó vẫn đúng, dùng làm reference).
- Trước khi chạy ingest thật (tốn quota API + ảnh hưởng dữ liệu), theo CLAUDE.md:
  Claude soạn lệnh, user tự chạy — không tự động chạy sync/transform.

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
