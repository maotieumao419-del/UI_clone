# Session Handoff — SellerVision Phase 3 (app.tap2soul.com / sellerboard_clone)

## 🎯 Mục tiêu tổng thể
Nâng cấp hệ thống live **app.tap2soul.com** (mã nguồn `sellerboard_clone`: FastAPI
backend + frontend JS thuần) lên **Giai đoạn 3**:
1. Backend: API tổng hợp tài chính `GET /api/analytics/dashboard?days=N` — hợp nhất
   dữ liệu đệm Supabase (`NEW_*`) thành mảng `top_products` theo từng (ASIN, SKU).
2. Frontend: render bảng `#top-products` thành **Ma trận hiệu suất sản phẩm** chi
   tiết kiểu Sellerboard (ảnh thumb, badge ASIN/SKU, màu động Net Profit/Margin).
3. Hỗ trợ mở rộng multi-store qua API, có đăng nhập tài khoản/mật khẩu riêng.

**Quy tắc CRITICAL (do user chốt):** toàn bộ code mới CHỈ nằm trong thư mục
`Phase3/`. TUYỆT ĐỐI không sửa tay file gốc (`backend/app/routers/dashboard.py`,
`frontend/app.js`, `frontend/index.html`) — chỉ can thiệp qua script vá độc lập
dùng `try_replace` + backup + rollback, và phải thông báo trước khi chạy.

## ✅ Đã hoàn thành
- Đọc & hiểu Phase 1 (`VPS/test_lwa_spapi/Phase 1/Phase_1.md`) và Phase 2
  (`VPS/test_lwa_spapi/Phase 2/Phase_2.md`) — pipeline ghi Supabase `NEW_*`.
- Tạo đầy đủ thư mục `VPS/VPS_AMZ/sellerboard_clone/Phase3/` với các file:
  - `analytics_aggregator.py` — module tính toán lõi (Net Profit/Margin/COGS FIFO/
    phân bổ Ads 3 tầng/timezone Pacific). **Đã chạy thật với Supabase**: 7 ngày
    (03→10/06/2026) = 63 đơn, 35 SKU, doanh thu $263.68.
  - `render_performance.js` — JS thuần, ghi đè `App.loadDashboard`, bảng 8 cột
    TailwindCSS, màu động xanh `+`/đỏ `-`, empty-state, fallback renderer gốc.
  - `patch_dashboard.py` / `patch_frontend.py` — script vá try_replace + backup +
    `--check` + auto compile-check. **Đã dry-run `--check` PASS** trên file gốc thật.
  - `rollback.py` — khôi phục file gốc từ backup, xoá file Phase 3 thêm vào.
  - `manage_user.py` — CLI quản trị tài khoản (`--list`/`--set`/`--create`).
    **Đã test e2e** trên DB tạm: tạo → đổi email/mật khẩu → login OK.
  - `test_render.html` — trang test UI độc lập (case normal/empty/legacy).
  - `README.md`, `Phase_3.md` — tài liệu kích hoạt + tóm tắt công việc.
- Kiểm chứng UI trong trình duyệt (qua `test_render.html` + preview server port 8731):
  bảng 8 cột render đúng, Net Profit/Margin đúng class màu (`text-green-600`/
  `text-red-600`), escape HTML đúng, dòng tổng đúng, empty + fallback hoạt động.
- `py_compile` toàn bộ `.py` + `node --check` file JS: không lỗi cú pháp.
- Ghi memory: `sellervision-phase3-layout.md` + cập nhật `MEMORY.md`.

## 🔄 Đang dở / Chưa hoàn thiện
- **CHƯA chạy patch thật** trên VPS (mới chỉ `--check`). Đúng nguyên tắc "thông
  báo trước khi chạy" — chờ user kích hoạt.
- **CHƯA đưa thư mục `Phase3/` lên VPS** (vẫn ở máy local).
- **CHƯA thống nhất tài khoản store MUSEMORY** — cần chạy `manage_user.py` trên VPS.
- Dữ liệu thật: COGS/phí/ads trong bảng `NEW_*` phần lớn còn trống → margin hiện
  hiển thị 100% cho tới khi user nhập `NEW_product_cogs` + chạy fetch finances/ads.

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)
1. **Đưa Phase3 lên VPS**:
   `scp -i ~/.ssh/sellervision_vps -r "VPS/VPS_AMZ/sellerboard_clone/Phase3" sellervision@REDACTED_VPS_IP:~/VPS_AMZ/sellerboard_clone/`
2. **Thống nhất tài khoản** (trên VPS): `python3 Phase3/manage_user.py --list` để
   tìm user giữ dữ liệu store (sản phẩm/đơn > 0 + biết email thật), rồi
   `python3 Phase3/manage_user.py --set --id <id> --new-email musemory@sellervision.io --password '<mật khẩu mới>'`.
3. **Vá & deploy** (trên VPS): `python3 Phase3/patch_dashboard.py && python3 Phase3/patch_frontend.py`
   → restart backend → Ctrl+F5 trình duyệt. Lùi lại bằng `python3 Phase3/rollback.py`.
4. (Tuỳ chọn) Nhập COGS vào `NEW_product_cogs` + chạy fetch finances/ads (Phase 2)
   để số liệu margin chính xác.
5. (Đề xuất) Vá thêm cờ `ALLOW_REGISTER` để khoá `/api/auth/register` đang mở công khai.

## 🏗️ Kiến trúc / Cấu trúc hệ thống
- **Live app.tap2soul.com** = `sellerboard_clone` (xác nhận qua `/api/health` →
  `{"app":"SellerVision","env":"prod"}`). FastAPI backend + frontend JS thuần
  (serve tại `/static`, index tại `/`). DB: **SQLite** (qua SQLAlchemy,
  `DATABASE_URL` trong `backend/.env`) cho users/orders/products; **Supabase**
  (`NEW_*`) cho dữ liệu đệm SP-API/Ads-API.
- **Pipeline dữ liệu (Phase 2)**: `VPS/test_lwa_spapi/Phase 2/fetch_24h_*.py` gọi
  Amazon SP-API/Ads-API → ghi thẳng Supabase bảng `NEW_*`.
- **Phase 3 backend flow**: route `/api/analytics/dashboard` → `profit.dashboard()`
  (kpis/timeseries/chart, GIỮ NGUYÊN) + merge `aggregate_product_performance()`
  từ `Phase3/analytics_aggregator.py` (đọc Supabase) → `top_products`.
- **Phase 3 frontend flow**: `render_performance.js` nạp sau `app.js`, ghi đè
  `App.loadDashboard` lúc runtime, gọi cùng endpoint (đường dẫn tương đối).
- Có **bản Phase 3 standalone CŨ HƠN** tại `VPS/test_lwa_spapi/Phase3/` (FastAPI
  riêng port 8003, auth riêng bảng `NEW_app_users`) — `services/profit.py` của bản
  đó là NGUỒN GỐC của `analytics_aggregator.py`. KHÔNG nhầm với bản đang làm.

## 📁 Cấu trúc thư mục quan trọng
```
VPS/VPS_AMZ/sellerboard_clone/          ← LIVE app.tap2soul.com (đang làm Phase 3)
├── backend/
│   ├── .env                            ← SUPABASE_URL/KEY, DATABASE_URL, Amazon creds
│   └── app/
│       ├── main.py                     ← mount /static, serve index.html tại /
│       ├── routers/
│       │   ├── auth.py                 ← login OAuth2 form-encoded (username/password)
│       │   └── dashboard.py            ← GỐC (patch_dashboard.py sẽ vá file này)
│       ├── core/security.py            ← hash_password PBKDF2 + JWT (SECRET_KEY)
│       ├── models/models.py            ← User(id,email,hashed_password,is_active), Order, Product
│       ├── timeutils.py                ← to_marketplace_local, now_marketplace (Pacific)
│       └── services/
│           ├── profit.py              ← dashboard() cũ (kpis/timeseries/top_products)
│           └── supabase_client.py
├── frontend/
│   ├── index.html                      ← GỐC (patch_frontend.py chèn <script>)
│   └── app.js                          ← GỐC (KHÔNG sửa, ghi đè runtime)
└── Phase3/                             ← ★ TẤT CẢ CODE MỚI Ở ĐÂY
    ├── analytics_aggregator.py         ← module tính toán lõi (chạy độc lập được)
    ├── render_performance.js           ← render bảng mới (JS thuần)
    ├── patch_dashboard.py              ← vá backend (try_replace+backup+--check)
    ├── patch_frontend.py               ← vá frontend (try_replace+backup+--check)
    ├── rollback.py                     ← khôi phục từ backups/
    ├── manage_user.py                  ← CLI quản trị tài khoản (chạy TRÊN VPS)
    ├── test_render.html                ← test UI độc lập (?case=normal|empty|legacy)
    ├── README.md / Phase_3.md          ← tài liệu
    ├── __init__.py                     ← cho "from Phase3.analytics_aggregator import"
    └── backups/                        ← backup tự động (tạo khi chạy patch)

VPS/test_lwa_spapi/Phase 2/            ← pipeline fetch_24h_*.py + supabase_schema.sql
VPS/test_lwa_spapi/Phase3/             ← bản standalone CŨ (port 8003) — tham khảo
```

## ⚙️ Biến môi trường & Cấu hình (.env)
File chính: `VPS/VPS_AMZ/sellerboard_clone/backend/.env` (đã có sẵn, Phase 3
KHÔNG cần thêm gì):
```env
ENV=prod
CORS_ORIGINS=https://app.tap2soul.com
ALLOWED_HOSTS=app.tap2soul.com
DATA_SOURCE=file
DATABASE_URL=sqlite:///...            # SQLite — chứa bảng users/orders/products
SECRET_KEY=...                         # ký JWT
SUPABASE_URL=https://REDACTED_PROJECT_REF.supabase.co
SUPABASE_KEY=...                       # service key, dùng cho analytics_aggregator
AMAZON_SPI_CLIENT_ID / _SECRET / _REFRESH_TOKEN / _MARKETPLACE_ID
AMAZON_ADS_CLIENT_ID / _SECRET / _REFRESH_TOKEN / _PROFILE_ID / _REGION
AWS_ACCESS_KEY_ID / _SECRET_ACCESS_KEY / _ROLE_ARN / _REGION
ACCESS_TOKEN_EXPIRE_MINUTES=...
```
> Lưu ý: aggregator đọc `SUPABASE_KEY` (bản backend) HOẶC `SUPABASE_SERVICE_KEY`
> (fallback) — đã xử lý cả 2 tên.

## 🔑 Thông số kỹ thuật quan trọng
- **VPS**: `sellervision@REDACTED_VPS_IP`, key `~/.ssh/sellervision_vps`.
  Đường dẫn dự án trên VPS: `~/VPS_AMZ/sellerboard_clone/`.
- **Login API**: `POST /api/auth/login` — **OAuth2 form-encoded** (`username` +
  `password`, KHÔNG phải JSON). Email so khớp **PHÂN BIỆT HOA/THƯỜNG**
  (`User.email == form.username`, không lowercase). Trả JWT Bearer.
- **Dashboard API**: `GET /api/analytics/dashboard?days=N` (N=7/30/90).
- **Bảng Supabase** (schema: `VPS/test_lwa_spapi/Phase 2/supabase_schema.sql`):
  `NEW_sp_orders`(order_id,purchase_date,order_status), `NEW_sp_order_items`
  (order_id,asin,sku,title,quantity_ordered,item_price,promotion_discount),
  `NEW_fin_item_fees`(order_id,sku,fee_type,amount[âm]), `NEW_fin_refunds`
  (posted_date,sku,refund_principal/commission/refunded_referral_fee),
  `NEW_product_cogs`(sku,cog_per_unit,effective_date), `NEW_ads_campaigns_daily`
  (report_date,campaign_name,asin,sku,cost[dương]).
- **Công thức**: `Net_Profit = (Price×Qty) − Product_Cost − Commission − FBA_Fee
  − Promo − Ad_Spend ± Other_Fees`; `Margin = Net_Profit/(Price×Qty)×100`.
  Price = item_price/quantity_ordered. COGS FIFO theo effective_date ≤ ngày mua.
  Commission/FBA lấy abs (DB âm). Ads phân bổ 3 tầng (SKU/ASIN→campaign name→
  tỉ trọng doanh thu). Timezone qua `to_marketplace_local()` (America/Los_Angeles).
- **Payload tương thích ngược**: mỗi dòng `top_products` có CẢ khoá mới (`sku,
  quantity, price, product_cost, commission, fba_fee, promo, ad_spend, net_profit,
  margin`) LẪN khoá cũ (`units, refunds, sales, avg_selling_price, cogs, fees,
  ppc, gross_profit, margin_pct, roi_pct, bsr`). Giữ `kpis/timeseries/
  marketplace_breakdown`. Thêm `status, period_days, range, totals`.
- **Hash mật khẩu**: PBKDF2-sha256, 200_000 rounds, format
  `pbkdf2_sha256$rounds$salt_hex$hash_hex`. `manage_user.py` dùng đúng hàm này.
- **Preview test local**: launch config `phase3-test-render` (port 8731,
  `python -m http.server` tại thư mục Phase3); test venv tại
  `C:\Users\TGS\AppData\Local\Temp\sv_test_venv\Scripts\python.exe`.

## 🐛 Vấn đề đã gặp & Cách giải quyết
- **Login test 401**: cặp `musemory@sellervision.io / MUSEMORY1234` API trả 401
  ("Sai email hoặc mật khẩu") dù user đăng nhập được trên trình duyệt → email/
  mật khẩu thật KHÁC chuỗi trong prompt (login phân biệt hoa/thường). → giải pháp:
  dùng `manage_user.py --list` xem email thật + `--set` để thống nhất lại.
- **Backend không có endpoint đổi mật khẩu** → viết `manage_user.py` import trực
  tiếp models + hash_password của backend, ghi đúng SQLite DB. Phải dùng `--set`
  trên user CŨ (giữ id → giữ dữ liệu store), KHÔNG `--create` (user mới = dashboard trống).
- **UnicodeEncodeError cp1252** khi in tiếng Việt trên Windows console → thêm
  `sys.stdout.reconfigure(encoding="utf-8")` đầu mỗi script.
- **node --check lỗi JS** ở chuỗi escape `\\'` trong template thumb → đổi sang
  render fallback div ẩn + onerror toggle class (không dùng escape lồng nhau).
- **preview_screenshot timeout** (Tailwind CDN chậm) → verify bằng `preview_eval`
  đọc DOM/class thay vì screenshot.
- **`raw_amazon_campaign_reports` 404** trên Supabase (bảng fallback ads không tồn
  tại) → đã bọc try-except, chỉ warning, không sập.
- **Thao tác production bị permission classifier chặn** (đăng ký user qua API, SSH
  đọc DB) → KHÔNG workaround; chuyển sang phân tích mã nguồn cùng repo + cung cấp
  CLI cho user tự chạy.

## 🚫 Quyết định đã được xác nhận (không thay đổi)
- **Mọi code mới trong `Phase3/`, không sửa tay file gốc** — chỉ qua patch script
  có backup/rollback. (User chốt là CRITICAL.)
- **Payload tương thích ngược** (khoá cũ + khoá mới) thay vì thay mới hoàn toàn —
  để UI hiện tại không gãy khi backend đã vá nhưng frontend chưa.
- **`manage_user.py --set` trên user cũ** để thống nhất tài khoản store MUSEMORY,
  KHÔNG tạo user mới (vì dữ liệu store gắn owner_id).
- **Phase 3 không cần thêm cấu hình domain** — domain đã có trong `backend/.env`;
  frontend gọi đường dẫn tương đối, aggregator chạy server-side.
- **Aggregator/render fail-safe**: lỗi bất kỳ → fallback payload/renderer cũ,
  dashboard không bao giờ sập.

## 💡 Context bổ sung
- User: Hong Hanh (git), email nt8277992@gmail.com. Giao tiếp tiếng Việt, comment
  code tiếng Việt, bọc I/O trong try-except/try-catch.
- `MUSEMORY1234` đã lộ trong hội thoại/docs → nên đặt mật khẩu mạnh hơn khi chạy
  `--set` thật.
- `/api/auth/register` đang MỞ CÔNG KHAI (ai biết URL cũng tạo được tài khoản) —
  nên vá `ALLOW_REGISTER` (bản standalone Phase3 cũ đã có cờ này tham khảo).
- Repo gốc có RẤT NHIỀU file lạ ở root (deploy_*.py, TASK_SUMMARY_*.md...) — không
  liên quan Phase 3, bỏ qua.
- Memory đã lưu: `C:\Users\TGS\.claude\projects\C--Users-nnh16-ads-trading-system\
  memory\sellervision-phase3-layout.md`.

---
*Session kết thúc lúc: 2026-06-11*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
