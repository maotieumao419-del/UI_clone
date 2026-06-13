# Phase 3 — API tổng hợp tài chính + Ma trận hiệu suất sản phẩm (kiểu Sellerboard)

> Thư mục: `VPS/VPS_AMZ/sellerboard_clone/Phase3/` (trên VPS: `~/VPS_AMZ/sellerboard_clone/Phase3/`)
>
> Tiếp nối [Phase 1](../../../test_lwa_spapi/Phase%201/Phase_1.md) (debug tool gọi SP-API/Ads-API)
> và [Phase 2](../../../test_lwa_spapi/Phase%202/Phase_2.md) (pipeline ghi thẳng vào Supabase `NEW_*`).

## Công việc chính

Nâng cấp hệ thống live **app.tap2soul.com** (mã nguồn `sellerboard_clone`: FastAPI
backend + frontend JS thuần, có đăng nhập JWT riêng):

1. **Backend**: xây module tổng hợp tài chính — hợp nhất dữ liệu đệm trên Supabase
   (orders, order items, phí Amazon thật, hoàn hàng, COGS, quảng cáo) thành mảng
   `top_products` theo từng (ASIN, SKU) trong N ngày (7/30/90), trả qua
   `GET /api/analytics/dashboard?days=N`.
2. **Frontend**: render bảng `#top-products` thành ma trận hiệu suất chi tiết kiểu
   Sellerboard — ảnh thumb, badge ASIN/SKU click-để-copy, định dạng tiền tệ `$`,
   màu động cho Net Profit/Margin (dương = xanh `+`, âm = đỏ `-`), empty-state sạch.
3. **Quản trị tài khoản**: CLI đổi email/mật khẩu user (backend không có endpoint
   đổi mật khẩu) — phục vụ thống nhất đăng nhập cho store MUSEMORY.

**Quy tắc an toàn (bắt buộc):** toàn bộ code mới nằm trong `Phase3/`; KHÔNG sửa tay
file gốc nào — hai file gốc (`backend/app/routers/dashboard.py`, `frontend/index.html`)
chỉ được sửa qua script vá `try_replace` có backup + rollback, và chỉ chạy khi
người dùng chủ động kích hoạt.

## Công thức tính cho từng SKU/ASIN

```
Net_Profit = (Price × Quantity) − Product_Cost − Commission − FBA_Fee
             − Promo − Ad_Spend ± Other_Fees
Margin     = Net_Profit / (Price × Quantity) × 100
```

- **Price** = tổng doanh thu SKU / số lượng (`item_price / quantity_ordered`).
- **Product_Cost (COGS FIFO)** = `NEW_product_cogs`: đơn mua ngày nào áp mức
  `cog_per_unit` có `effective_date` lớn nhất ≤ ngày mua.
- **Commission / FBA_Fee** = phí THẬT từ Finances API (`NEW_fin_item_fees`,
  match theo order_id + sku; lấy trị tuyệt đối vì DB lưu số âm).
- **Promo** = `promotion_discount`; **Other_Fees** = phí khác giữ nguyên dấu
  + chi phí hoàn hàng trong kỳ (`NEW_fin_refunds`, gán theo `posted_date`).
- **Ad_Spend** = `NEW_ads_campaigns_daily` (fallback `raw_amazon_campaign_reports`),
  phân bổ 3 tầng: ① trùng SKU/ASIN → gán thẳng; ② tên campaign chứa SKU;
  ③ phần còn lại chia theo tỉ trọng doanh thu.
- **Timezone**: mọi phép lọc N ngày đi qua `to_marketplace_local()` /
  `marketplace_local_to_utc()` (Pacific Time `America/Los_Angeles`) để khớp
  số liệu Amazon Seller Central.

## Tương thích ngược (không gãy UI hiện tại)

- Payload giữ nguyên `kpis`, `timeseries`, `marketplace_breakdown` (chart cũ
  không đổi); thêm `status`, `period_days`, `range`, `totals`.
- Mỗi dòng `top_products` chứa **cả khoá mới** (`sku, quantity, price,
  product_cost, commission, fba_fee, promo, ad_spend, net_profit, margin`)
  **lẫn khoá cũ** (`units, refunds, sales, avg_selling_price, cogs, fees, ppc,
  gross_profit, margin_pct, roi_pct, bsr`).
- `render_performance.js` tự phát hiện payload cũ / lỗi bất kỳ → fallback về
  renderer gốc của `app.js`. Aggregator lỗi → backend trả nguyên payload cũ.

## File tạo ra trong `Phase3/` và nhiệm vụ

| File | Nhiệm vụ |
|---|---|
| `analytics_aggregator.py` | **Module tính toán lõi.** Đọc Supabase `NEW_sp_orders`, `NEW_sp_order_items`, `NEW_fin_item_fees`, `NEW_fin_refunds`, `NEW_product_cogs`, `NEW_ads_campaigns_daily` → tính Net Profit/Margin/COGS FIFO/phân bổ Ads theo công thức trên, trả `{status, period_days, range, totals, top_products}`. Ưu tiên dùng `app.timeutils` + Supabase client của backend, có fallback nội bộ để **chạy độc lập được**: `python Phase3/analytics_aggregator.py --days 7`. Toàn bộ I/O bọc try-except, lỗi từng nguồn (ads, refunds...) chỉ ghi warning chứ không sập. |
| `render_performance.js` | **Phần mở rộng giao diện, JS thuần.** Ghi đè `App.loadDashboard` lúc runtime (không sửa `app.js`): fetch 1 lần, vẫn vẽ chart + thẻ kỳ như cũ, thay bảng `#top-products` bằng layout 8 cột TailwindCSS (Sản phẩm / Số lượng / Doanh thu / COGS / Phí sàn / Quảng cáo / Lợi nhuận ròng / Biên LN). Màu động `text-green-600` `+` / `text-red-600` `-`, ảnh thumb theo ASIN có fallback chữ cái đầu, badge ASIN/SKU click-để-copy, escape HTML chống vỡ template, mảng rỗng → "Không có dữ liệu hiệu suất cho khoảng thời gian này". |
| `patch_dashboard.py` | **Script vá backend.** Sửa `backend/app/routers/dashboard.py` bằng `try_replace` (khớp chuỗi chính xác đúng 1 lần, không khớp → dừng không ghi gì): bỏ `response_model` (để Pydantic không cắt khoá mới), gọi aggregator merge vào payload, aggregator lỗi → trả nguyên payload cũ. Tự backup vào `Phase3/backups/`, tự compile-check sau khi ghi (lỗi → tự khôi phục). Có `--check` chạy khô. |
| `patch_frontend.py` | **Script vá frontend.** Copy `render_performance.js` → `frontend/` (serve tại `/static/`) và chèn `<script src="/static/render_performance.js">` vào `index.html` sau `app.js`. Cùng cơ chế try_replace + backup + `--check`. |
| `rollback.py` | Khôi phục `dashboard.py` + `index.html` từ backup mới nhất, xoá `frontend/render_performance.js`. `--list` xem backup hiện có. |
| `manage_user.py` | **CLI quản trị tài khoản (chạy TRÊN VPS).** `--list`: liệt kê user kèm số sản phẩm/đơn hàng để biết user nào giữ dữ liệu store; `--set --id N --new-email ... --password ...`: đổi email/mật khẩu user hiện có (GIỮ NGUYÊN id → dữ liệu store còn nguyên, tự verify mật khẩu sau khi ghi); `--create`: tạo user mới (cảnh báo dashboard trống). Dùng chính `hash_password` PBKDF2 + `DATABASE_URL` của backend. Không cần restart backend sau khi đổi. |
| `test_render.html` | Trang kiểm thử UI độc lập (stub `App`/`api`, không cần backend): case `normal` / `empty` / `legacy` để xem bảng render đúng layout, màu sắc, fallback. |
| `README.md` | Hướng dẫn kích hoạt từng bước: chạy thử aggregator → `--check` 2 patch → vá thật → restart backend; cách rollback; ghi chú dữ liệu. |
| `Phase_3.md` | Tài liệu này. |
| `backups/` | Backup tự động trước mỗi lần vá (tự tạo khi chạy patch). |

## Đã kiểm chứng

- **Aggregator chạy với Supabase thật**: 7 ngày (03→10/06/2026 Pacific) = 63 đơn,
  35 SKU, doanh thu $263.68. COGS/phí/ads = 0 vì các bảng `NEW_product_cogs`,
  `NEW_fin_item_fees`, ads chưa có dữ liệu trong kỳ → margin tạm 100% cho tới
  khi nhập COGS + chạy fetch finances/ads (Phase 2).
- **Dry-run 2 patch** trên file gốc thật: khớp chuỗi chính xác, sẵn sàng vá.
- **UI test trình duyệt 3 case** (qua `test_render.html`): bảng 8 cột đúng,
  Net Profit/Margin xanh `+`/đỏ `-` đúng class, escape HTML đúng, dòng tổng đúng,
  case rỗng + fallback payload cũ hoạt động.
- **manage_user.py test end-to-end** trên DB tạm: tạo → đổi email/mật khẩu →
  giả lập đúng logic login backend → `LOGIN_OK`.
- `py_compile` toàn bộ file Python + `node --check` file JS: không lỗi cú pháp.

## Phát hiện trong quá trình làm

- Live `app.tap2soul.com` = sellerboard_clone (`/api/health` → `SellerVision, prod`).
  Login là **OAuth2 form-encoded** (`username`/`password`), so khớp email
  **phân biệt hoa thường**.
- Cặp test `musemory@sellervision.io / MUSEMORY1234` qua API trả 401 — tài khoản
  thật trên VPS dùng chuỗi khác → dùng `manage_user.py --list` + `--set` để
  thống nhất lại.
- `/api/auth/register` của app đang **mở công khai** — nên cân nhắc vá thêm cờ
  `ALLOW_REGISTER` để khoá (việc đề xuất cho lần sau).
- Domain đã cấu hình sẵn trong `backend/.env` (`CORS_ORIGINS`/`ALLOWED_HOSTS` =
  app.tap2soul.com); Phase 3 **không cần thêm cấu hình domain** (frontend gọi
  đường dẫn tương đối, aggregator chạy server-side với SUPABASE_URL/KEY có sẵn).
- Tồn tại một bản Phase 3 standalone CŨ HƠN tại `VPS/test_lwa_spapi/Phase3/`
  (FastAPI riêng port 8003, auth riêng bảng `NEW_app_users`) — logic
  `services/profit.py` của bản đó là nguồn gốc của `analytics_aggregator.py`.

## Các bước kích hoạt (tóm tắt — chi tiết xem README.md)

```bash
# Đưa Phase3 lên VPS
scp -i ~/.ssh/sellervision_vps -r Phase3 sellervision@REDACTED_VPS_IP:~/VPS_AMZ/sellerboard_clone/

# Trên VPS
cd ~/VPS_AMZ/sellerboard_clone
python3 Phase3/analytics_aggregator.py --days 7      # chạy thử aggregator
python3 Phase3/patch_dashboard.py --check            # kiểm tra khô
python3 Phase3/patch_frontend.py  --check
python3 Phase3/patch_dashboard.py                    # vá thật (có backup)
python3 Phase3/patch_frontend.py
# restart backend, Ctrl+F5 trình duyệt

# Thống nhất tài khoản store MUSEMORY
python3 Phase3/manage_user.py --list
python3 Phase3/manage_user.py --set --id <id> --new-email musemory@sellervision.io --password '<mật khẩu mới>'

# Lùi lại bất kỳ lúc nào
python3 Phase3/rollback.py
```
