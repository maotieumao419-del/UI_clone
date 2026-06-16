# Session Handoff — SellerVision Phase2: Fix Refund Netting (Issue 1) + Money Back Module (Issue 4)

## 🎯 Mục tiêu tổng thể
Sửa pipeline Phase2 (`Phase2_Transformation/transform_engine.py`) để khớp đúng mô hình
Sellerboard ở 2 điểm còn lệch:
- **Issue 1**: dòng refund/return đang "đảo dấu" vào `sales/promo/amazon_fees/cost_of_goods`
  khiến `Sales` tổng kỳ bị netting sai (lệch so với Sellerboard).
- **Issue 4**: chưa có báo cáo "Money Back" (FBA reimbursement cho hàng mất/hỏng kho,
  và clawback khi Amazon thu hồi lại) — Sellerboard có tab riêng cho cái này.

Issue 2 (PPC attribution) và Issue 3 (COGS/Expenses từ file Amazon order_items/Product)
đã được xác nhận **giữ nguyên / không động tới** trong scope này.

## ✅ Đã hoàn thành

### Issue 1 — Fix refund/sales netting
- File: `Phase2_Transformation/aggregation_models.py`, `Phase2_Transformation/transform_engine.py`
- Mô hình mới cho dòng `row_type='return'` trong `NEW_summary_order_items`:
  - `sales = promo = amazon_fees = cost_of_goods = shipping = 0`
  - `refund_cost` = TOÀN BỘ tác động kinh tế của refund:
    `refund_principal(âm) + refund_promo(dương) + refund_fees(dương, = hoàn referral
    - phạt admin 20%/cap $5) + refund_cogs(dương nếu disposition=Sellable, else 0)`
  - `gross_profit = 0`, `net_profit = refund_cost` cho dòng return.
- Code block return-row construction (đã viết, nằm trong `transform()` ở khu vực xử lý
  `ref_agg` — tìm theo biến `refund_principal`, `refund_fees`, `refund_cogs`,
  `refund_cost` trong `transform_engine.py`).
- `_aggregate_products`: đổi `estimated_payout = round(p.net_profit - p.cost_of_goods, 2)`
  (trước đây = `sales + promo + amazon_fees + refund_cost`, khớp với công thức đã ghi
  trong `backend/app/services/profit.py` từ commit `29f391e`).
- **Invariant đã chứng minh**: tổng `Net_Profit`/`Estimated_payout` của kỳ KHÔNG đổi
  (chỉ là tái phân loại field) — `validate_rollup()` vẫn pass.

### Issue 4 — "Money Back" (Mart 4 mới)
- Nguồn dữ liệu: bảng `NEW_fin_adjustments` (đã có sẵn từ trước, Phase1
  `direct_stream_pipeline.py` ghi từ `AdjustmentEventList` của Finances API,
  schema `(posted_date, adjustment_type, sku, asin, quantity, amount, synced_at)`)
  — **không cần ingest API mới**.
- Thêm dataclass `SummaryReimbursement` trong `aggregation_models.py`:
  ```python
  @dataclass
  class SummaryReimbursement:
      period_start: str = ""
      period_end: str = ""
      adjustment_type: str = ""
      category: str = "reimbursement"   # reimbursement | clawback
      product: str = ""
      asin: str = ""
      sku: str = ""
      quantity: int = 0
      amount: float = 0.0
  ```
- Bảng mới `NEW_summary_reimbursements` — DDL đã thêm vào
  `Phase2_Transformation/sql/supabase_schema.sql` (Bảng 15, sau bảng
  `NEW_summary_campaigns`, gồm CREATE TABLE + 2 index + COMMENT).
- `T_SUMMARY_REIMBURSEMENTS = "NEW_summary_reimbursements"` thêm vào hằng số
  trong `aggregation_models.py`.
- Trong `transform_engine.py`, thêm `T_ADJUSTMENTS = "NEW_fin_adjustments"` và 3 hàm mới:
  - `_classify_adjustment(adj_type, amount)` — phân loại
    `category='reimbursement'` (Amazon trả tiền: `WAREHOUSE_DAMAGE`, `WAREHOUSE_LOST`,
    `WAREHOUSE_THEFT`, `REVERSAL_REIMBURSEMENT`, `FREE_REPLACEMENT_REFUND_ITEMS`,
    `MISSING_FROM_INBOUND`, `FBAInventoryReimbursement`) vs `category='clawback'`
    (Amazon thu hồi: `COMPENSATED_CLAWBACK`, `REIMBURSEMENT_CLAWBACK`,
    `ReimbursementClawback`).
  - `_fetch_adjustments(sb, start_utc, end_utc)` — đọc `NEW_fin_adjustments` qua PostREST
    (`fetch_all()`).
  - `_build_reimbursements(adjustments, period_start, period_end, title_by_key)` — gộp
    theo `(adjustment_type, asin, sku)` → list `SummaryReimbursement.to_row()`.
- Wiring trong `transform()`:
  - `adjustments = _fetch_adjustments(...)` (sau `_fetch_refunds()`)
  - `reimbursement_rows = _build_reimbursements(...)` (SAU `_aggregate_products(...)`
    để `title_by_key` đã đầy đủ)
  - `totals["reimbursements"]`, `totals["reimbursements_received"]`,
    `totals["reimbursements_clawback"]` thêm vào dict `totals`
  - `result["reimbursement_rows"] = reimbursement_rows` thêm vào return dict
- `truncate_summaries()`: loop qua `(T_SUMMARY_ITEMS, T_SUMMARY_PRODUCTS,
  T_SUMMARY_CAMPAIGNS, T_SUMMARY_REIMBURSEMENTS)`.
- `write_summaries()`: thêm owner_id injection cho `reimbursement_rows` +
  `load_to_supabase_robust(result["reimbursement_rows"], T_SUMMARY_REIMBURSEMENTS, sb,
  "owner_id,period_start,period_end,adjustment_type,asin,sku")`.
- CLI `main()`: thêm block in "MONEY BACK (Lost & Damaged / Reimbursements)" ra stderr,
  cập nhật message cuối cùng để báo cả số dòng reimbursements đã ghi.

### Verify (dry-run `--no-write`, đọc Supabase production thật)
Lệnh: `python transform_engine.py --date 2026-06-15 --days 15 --no-write`
Kết quả MTD 01–15/06/2026:
```
794 đơn, 552 SKU, 1636 campaign, sales $9,938.78, net $2,547.21
Amazon fees: -$4,383.56 (ACTUAL -$1,050.75 / 202 dòng; ESTIMATED -$3,332.81 / 602 dòng)
Cost of goods: -$244.50
Net profit: $2,547.21
Margin: 25.63%

MONEY BACK:
  Reimbursement nhận: $564.73 (38 dòng)
  Clawback bị thu hồi: -$34.33 (9 dòng)
  Net: $530.40
```
- `Sales = $9,938.78` khớp đúng "pure gross sales" kỳ vọng (trước fix SV netted =
  $9,626.27, lệch -$312.51 do return rows trừ vào sales).
- Net_profit/Est.payout tổng KHÔNG đổi như dự đoán (đúng invariant).
- `git diff --stat` xác nhận chỉ 3 file thay đổi, toàn bộ trong
  `Phase2_Transformation/` — KHÔNG động `backend/`/`frontend/` (đúng guardrail #1).

## 🔄 Đang dở / Chưa hoàn thiện
- **CHƯA GHI DB**: code đã verify bằng `--no-write` (read-only), nhưng CHƯA chạy
  write/`--fresh` thật để populate `NEW_summary_order_items/products/reimbursements`
  với data đã sửa. Theo CLAUDE.md guardrail #4, user phải tự chạy.
- **Bảng `NEW_summary_reimbursements` CHƯA được tạo trên Supabase** — DDL mới chỉ có
  trong file `sql/supabase_schema.sql`, chưa apply lên DB thật. Nếu chạy write trước
  khi tạo bảng → `load_to_supabase_robust` cho reimbursements sẽ lỗi (bảng không
  tồn tại).
- **"Money Back" chưa hiển thị trên web app**: data layer (Phase2) đã xong, nhưng
  chưa có API endpoint backend + tab/UI frontend để hiển thị
  `NEW_summary_reimbursements`. Việc này cần `patch_dashboard.py`/`patch_frontend.py`
  (guardrail #1) — CHƯA bắt đầu, đang chờ user xác nhận có muốn làm tiếp không.
- Refund_cost field trong `NEW_summary_order_items`/`products` sẽ populate đúng sau
  khi ghi lại — frontend "Hoàn tiền" trong P&L popover ĐÃ wired sẵn (commit `7d32d63`/
  `1009979`), không cần patch thêm cho Issue 1.

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)
1. **User**: Apply DDL bảng `NEW_summary_reimbursements` (Bảng 15 trong
   `Phase2_Transformation/sql/supabase_schema.sql`) lên Supabase production
   (chỉ CREATE TABLE mới, không đụng bảng cũ).
2. **User**: Chạy backfill cho kỳ 01–15/06/2026 (và có thể các kỳ trước nếu muốn dữ
   liệu lịch sử đúng convention mới):
   ```
   python transform_engine.py --date 2026-06-15 --days 15 --fresh
   ```
   (`--fresh` chỉ xóa `NEW_summary_order_items/products/campaigns/reimbursements` của
   kỳ này theo CLAUDE.md, KHÔNG đụng `NEW_product_cogs`/`NEW_fee_cache`/`NEW_*` raw khác).
3. Sau khi ghi xong, kiểm tra trên web app: P&L popover hiển thị "Hoàn tiền"
   (`refund_cost`) đúng số (trước đó luôn $0.00).
4. **Quyết định**: có làm tiếp UI "Money Back" tab (đọc `NEW_summary_reimbursements`)
   qua `patch_dashboard.py` (backend endpoint mới) + `patch_frontend.py` (UI tab mới)?
   Cần `--check` trước khi apply, có backup/rollback.
5. (Tùy chọn, mở rộng tương lai) "Reimbursement Gap" thật (hàng mất/hỏng CHƯA được
   hoàn) cần thêm ingest FBA Inventory Ledger report
   (`GET_LEDGER_DETAIL_VIEW_DATA`, SP-API Reports async) để so units lost vs units đã
   reimburse — chưa làm, chỉ là ý tưởng follow-up.

## 🏗️ Kiến trúc / Cấu trúc hệ thống
3-phase ETL pipeline (xem `PIPELINE_3PHASE_README.md`):
```
Amazon API ──(Phase1: Direct-Stream)──► Supabase NEW_* (bảng đệm)
Supabase   ──(Phase2: Transform)──────► NEW_summary_order_items / NEW_summary_products
                                          / NEW_summary_campaigns / NEW_summary_reimbursements (mới)
Summary    ──(Phase3: Bridge/Patch)───► Web App app.tap2soul.com
```
- Phase2 "Mart" pattern: Mart1=order_items, Mart2=products, Mart3=campaigns,
  **Mart4=reimbursements (mới, Issue 4)**.
- Quy ước dấu hệ thống (Sellerboard convention, từ CLAUDE.md):
  ```
  Gross_Profit = Sales + Promo + Amazon_fees + COGS + Shipping
  Net_Profit   = Gross_Profit + Ads + Refund_cost + Expenses
  Margin       = Net_Profit / Sales × 100
  amazon_fees  = Referral (16.5% = 15% Amazon + 10% VAT) + FBA Fulfillment
  ```

## 📁 Cấu trúc thư mục quan trọng
```
VPS_AMZ/sellerboard_clone/
├── Phase1_Ingestion/
│   └── direct_stream_pipeline.py   # ghi NEW_fin_adjustments (AdjustmentEventList) — KHÔNG đổi
├── Phase2_Transformation/
│   ├── aggregation_models.py       # MODIFIED: +T_SUMMARY_REIMBURSEMENTS, +SummaryReimbursement,
│   │                                #           sửa comment refund_cost
│   ├── transform_engine.py         # MODIFIED: return-row mới, _aggregate_products payout,
│   │                                #           Mart4 (_fetch_adjustments/_classify_adjustment/
│   │                                #           _build_reimbursements), wiring transform()/
│   │                                #           write_summaries()/truncate_summaries()/CLI
│   └── sql/
│       └── supabase_schema.sql     # MODIFIED: +Bảng 15 NEW_summary_reimbursements DDL
├── backend/app/services/profit.py  # READ ONLY — tham chiếu công thức est_payout
└── docs/
    └── SESSION_HANDOFF_ISSUE1_4_REFUND_REIMBURSEMENT.md  # file này
```

## ⚙️ Biến môi trường & Cấu hình (.env)
Không thay đổi gì về .env trong phiên này. `DATABASE_URL` (Supabase Postgres) và
Supabase REST credentials dùng như cũ (xem `Phase2_Transformation/transform_engine.py`
phần đọc config, và `.env` ở repo root / VPS).

## 🔑 Thông số kỹ thuật quan trọng
- **Bảng mới**: `NEW_summary_reimbursements`
  - Conflict key (upsert): `owner_id,period_start,period_end,adjustment_type,asin,sku`
  - Cột: `period_start, period_end, adjustment_type, category, product, asin, sku,
    quantity, amount, owner_id`
- **Adjustment type classification** (từ data thật 01-15/06/2026, 93 dòng):
  - reimbursement: `WAREHOUSE_DAMAGE` (59 evt, $443.19, 118 units),
    `WAREHOUSE_LOST` (19 evt, $80.49, 20 units),
    `REVERSAL_REIMBURSEMENT` (5 evt, $29.25, 5 units),
    `FREE_REPLACEMENT_REFUND_ITEMS` (1 evt, $11.80, 1 unit)
  - clawback: `COMPENSATED_CLAWBACK` (9 evt, -$34.33, 9 units)
- **Refund fee formula** (return row):
  - `original_referral = abs(refund_principal * rate)` (rate từ `NEW_fee_cache` hoặc
    `DEFAULT_REFERRAL_RATE` = 16.5%)
  - `admin_fee = min(original_referral * 0.20, 5.00)`
  - `refund_fees = round(original_referral - admin_fee, 2)`
  - `refund_cogs = unit_cogs * qty` nếu `disposition.lower() == 'sellable'`, else 0
  - `refund_cost = round(refund_principal + refund_promo + refund_fees + refund_cogs, 2)`
- **Verify numbers MTD 01-15/06/2026** (dry-run, để đối chiếu sau khi write thật):
  sales $9,938.78 / net $2,547.21 / margin 25.63% / fees -$4,383.56
  (ACTUAL -$1,050.75 / ESTIMATED -$3,332.81) / COGS -$244.50 /
  Money Back net $530.40 ($564.73 - $34.33).

## 🐛 Vấn đề đã gặp & Cách giải quyết
- Không có lỗi runtime. Cả 2 dry-run (`--date 2026-06-14 --no-write` và
  `--date 2026-06-15 --days 15 --no-write`) chạy pass lần đầu trên Supabase production
  thật.
- Quan sát phụ (KHÔNG phải lỗi, KHÔNG trong scope Issue 1/4): tỉ lệ `amazon_fees` ngày
  14/06 (-$553.45/$1,176.95 ≈ 47%) có vẻ cao so với mô hình ~16.5%+FBA, với 0/102 dòng
  ACTUAL (đều ESTIMATED — bình thường vì Finances API trễ ~9 ngày). Đã confirm qua
  `git diff --stat` rằng `_resolve_hybrid_fees` (logic ước lượng fee) KHÔNG bị động —
  pre-existing, ngoài scope.

## 🚫 Quyết định đã được xác nhận (không thay đổi)
- Issue 2 (PPC attribution 3-tier trong `_fetch_ads_by_channel`/`_allocate_channel`):
  **SKIP** — đã implement đúng từ trước.
- Issue 3 (COGS/Expenses): **GIỮ NGUYÊN** — tiếp tục lấy từ file Amazon order_items/Product
  report, KHÔNG làm FIFO/amortization overhaul.
- Issue 1 fix là REPHÂN LOẠI THUẦN (không đổi tổng Net_Profit/Est.payout của kỳ) —
  đã chứng minh bằng toán + verify thực tế.
- Issue 4 "Money Back" được tách RIÊNG, KHÔNG cộng vào `Gross_Profit`/`Net_Profit`
  (giống tab Reimbursements riêng của Sellerboard) — chỉ là báo cáo bổ sung.
- Money Back hiện là "tiền đã nhận/bị thu hồi" (từ `NEW_fin_adjustments` đã có), KHÔNG
  phải "Reimbursement Gap" (hàng mất chưa được hoàn) — đó là việc khác, cần ingest mới.

## 💡 Context bổ sung
- Standing instruction: MỌI lệnh terminal đưa cho user phải kèm ghi chú tiếng Việt giải
  thích công dụng + ý nghĩa các flag.
- Workflow chuẩn: sửa local → commit → push (cần user confirm) → `git pull` trên VPS
  (`~/UI_clone_deploy/VPS_AMZ/sellerboard_clone`, remote `UI_clone`,
  GitHub `maotieumao419-del/UI_clone`) → restart service `sellervision`.
- CLAUDE.md guardrails đầy đủ ở `VPS/CLAUDE.md` — đọc lại nếu cần nhắc về quy tắc
  Supabase/`NEW_*`/`--fresh`/timezone (Pacific)/memory-safety.
- Repo root có file scratch `_out.txt` (dùng cho output query psycopg do console
  cp1252 encoding) — đọc bằng Read tool, ghi đè khi cần query mới.
- File này (`SESSION_HANDOFF_ISSUE1_4_REFUND_REIMBURSEMENT.md`) bổ sung, KHÔNG thay thế
  `docs/SESSION_HANDOFF.md` (tổng quan pipeline) — đọc cả 2 nếu cần context đầy đủ.

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
