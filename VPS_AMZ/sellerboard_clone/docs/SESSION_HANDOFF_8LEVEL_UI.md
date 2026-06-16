---

# Session Handoff — SellerVision Phase 3: 8-Level Progressive Disclosure UI

## 🎯 Mục tiêu tổng thể
Đập đi xây lại giao diện Dashboard (`render_performance.js`) và data contract
(`analytics_aggregator.py`) theo kiến trúc **Progressive Disclosure 8 cấp độ**:

- **Mức 4** (Dashboard View & Global Control): Top Panel (Search SKU/ASIN/Campaign
  + Date Picker) + View Switcher (Tiles/Chart/P&L/Trends/Map).
- **Mức 5** (KPI Tiles): 5 thẻ tổng quan (Today/Yesterday/MTD/Forecast/Last month).
- **Mức 6** (Drill-down): 6A = popover "More"/"..." hiện cây P&L đệ quy (JSON
  Tree, toggle `{>}`); 6B = click tiêu đề tile -> đổ dữ liệu kỳ đó xuống Bottom
  Panel.
- **Mức 7** (Data Grid Container): TabSwitcher Products / Order Items, tiêu đề
  động theo kỳ đang chọn.
- **Mức 8** (Row level): Products row = Thumbnail+Title+ASIN/SKU/FBA label +
  Sales/COGS/Fees/Net profit/ROI, có sub-row `{>}` breakdown phí Amazon; Order
  Items row = parse `order_number_raw` ("OrderID / Status / COG / FBA") +
  badge màu theo status.

Backend phải trả **JSON lồng nhau** (`product_info` / `metrics` / `detailed_pnl`)
thay cho flat dict cũ.

## ✅ Đã hoàn thành
- **`analytics_aggregator.py`** (`Phase3_Application/data_bridge/`): refactor
  `get_sku_performance()` trả nested schema (`product_info.{asin,sku,title,
  image_url,fulfillment_channel,fba_stock}` / `metrics.{...}` /
  `detailed_pnl.{sales,cogs,amazon_fees{total,children:{referral_fee,fba_fee}},
  ads,promo,refund_cost,shipping,net_profit}`). Thêm `_product_lookup()` (join
  bảng `products` lấy `image_url`/`current_stock`) và `_split_amazon_fees()`
  (ước tính referral 16.5% sales, phần còn lại = fba_fee). `get_order_items_details()`
  thêm field `order_number_raw = "{order_number} / {status} / COG: {cogs} / FBA"`.
- **`backend/app/routers/dashboard.py`**: đã ở phiên bản Phase 3
  (`GET /api/analytics/dashboard/summary?tab=products|orders&start=&end=`,
  `GET /api/analytics/periods`) — `patch_dashboard.py --check` xác nhận idempotent.
- **`render_performance.js`** (`Phase3_Application/data_bridge/patch_scripts/`):
  viết đầy đủ Mức 4-8 (IIFE thuần JS, không framework) — `ensureTopPanel()`,
  `renderTiles()`/`tileCard()`, `showPopover()`/`renderPnlTree()` (đệ quy +
  toggle), `SV8.selectPeriod()`, `ensureGridContainer()`/`SV8.renderTab()`,
  `renderProductRow()`/`renderOrderRow()` (parse `order_number_raw`, badge
  status theo regex Shipped/Return/Cancel/Pending).
- **Đã chạy `patch_frontend.py`** (bước này TRƯỚC ĐÓ BỊ BỎ QUÊN — là nguyên
  nhân chính UI không đổi): copy `render_performance.js` → `frontend/`
  (served qua `/static`) + chèn `<script src="/static/render_performance.js">`
  ngay sau `app.js` trong `frontend/index.html`.
- **FIX BUG NGHIÊM TRỌNG (commit `8c1f4cf`)**: `install()` trong
  `render_performance.js` check `window.App`, nhưng `app.js` khai báo
  `const App = {...}` ở top-level (classic script) → **`const`/`let` không
  gắn vào `window`** → `window.App` luôn `undefined` → `install()` luôn
  return `false` → UI 8-Level **không bao giờ được kích hoạt**, code
  `App.loadProductPerf` cũ vẫn chạy và render "undefined" (vì backend đã trả
  schema lồng nhau mới, không còn field flat `p.product/p.asin/...`).
  Fix: đổi check sang `typeof App === 'undefined'`.
- **Commit `29f391e`**: sửa công thức `Est. payout = Net_profit - Cost_of_goods`
  trong `backend/app/services/profit.py` (đối chiếu Sellerboard 13/06/2026,
  lệch ~1% so với lệch $244 của công thức cũ).
- **Commit `1009979`**: sửa `splitAmazonFees()` trong `render_performance.js`
  trả `{referral_fee: {total: n}, fba_fee: {total: n}}` (trước trả số trần →
  `renderPnlTree` đọc `node.total` ra `undefined` → luôn hiện $0.00).
- Tất cả đã **commit + push lên GitHub**, `origin/main` = local `HEAD` =
  `1009979` (branch `main`, repo
  `https://github.com/maotieumao419-del/UI_clone.git`).
- Đã làm rõ cấu trúc VPS (xem mục Thông số kỹ thuật) và xác nhận
  **DB Supabase đã ở alembic revision `0002`** (cột `Product.image_url` đã
  tồn tại) — không cần chạy migration thêm.

## 🔄 Đang dở / Chưa hoàn thiện
- **CHƯA XÁC NHẬN**: user chưa báo lại đã `git pull` + `systemctl restart
  sellervision` trên VPS với các commit mới nhất (đặc biệt `8c1f4cf`,
  `29f391e`, `1009979`) và chưa xác nhận UI 8-Level hiển thị đúng (Top Panel +
  Grid Products/Order Items với số liệu thật, không còn "undefined").
- View Switcher (Mức 4) — tab **Chart/Trends/Map** hiện chỉ là placeholder
  ("Backend Phase 3 chưa trả dữ liệu theo ngày/sàn, sẽ bổ sung ở Phase 4") —
  CHƯA implement thật (cần `timeseries`/`marketplace_breakdown` trong
  `analytics_aggregator.py`).
- Cột `bsr` trong Products row hiện lấy `func.max(SummaryProduct.bsr)` —
  CHƯA kiểm tra có data thật hay luôn `null`/"·".
- **Working tree local còn 3 file Phase2 đang sửa, KHÔNG thuộc session UI
  này** (đã có từ trước session, không động vào):
  `Phase2_Transformation/aggregation_models.py`,
  `Phase2_Transformation/sql/supabase_schema.sql`,
  `Phase2_Transformation/transform_engine.py` (modified, chưa stage) +
  untracked `Phase2_Transformation/sql/comment_schema.sql`, `_out.txt` (file
  rác ở root repo). Cần hỏi user trước khi commit/xoá.

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)
1. **User chạy trên VPS** (đúng thư mục `~/UI_clone_deploy/VPS_AMZ/sellerboard_clone`):
   ```bash
   git pull
   sudo systemctl restart sellervision
   ```
   rồi **Ctrl+Shift+R** trên `app.tap2soul.com`.
2. Xác nhận trực quan: Top Panel (search + date picker + view switcher) hiện
   phía trên 5 thẻ KPI; bảng "Hiệu suất sản phẩm chi tiết" cũ được thay bằng
   Data Grid Products/Order Items mới, dữ liệu KHÔNG còn "undefined". Click
   "More" trên tile và "..." trên row để test popover P&L (Referral/FBA fee
   phải hiện số, không phải $0.00).
3. Nếu còn lỗi: F12 → Console xem có log
   `[Phase3] render_performance.js đã kích hoạt (8-Level Progressive
   Disclosure).` không, và Network xem `render_performance.js` +
   `dashboard/summary?tab=...` trả 200.
4. Sau khi UI mới hoạt động ổn: hỏi user về 3 file Phase2 đang dở + `_out.txt`
   (commit riêng, hay đang là rác cần xoá).
5. (Phase 4 — chưa ưu tiên) Implement timeseries cho tab Chart và
   marketplace_breakdown cho tab Map trong `analytics_aggregator.py`.

## 🏗️ Kiến trúc / Cấu trúc hệ thống
```
Amazon API ──(Phase1: Direct-Stream)──► Supabase NEW_* (bảng đệm)
Supabase   ──(Phase2: Transform)──────► NEW_summary_order_items / NEW_summary_products
Summary    ──(Phase3: Bridge/Patch)───► Web App app.tap2soul.com (FastAPI + vanilla JS SPA)
```
- Backend: FastAPI (Python), SQLAlchemy ORM, Postgres (Supabase) qua
  `DATABASE_URL`, Alembic migrations.
- Frontend: vanilla JS SPA (`app.js` = core, `render_performance.js` = patch
  Phase 3 nạp SAU `app.js`, override `App.loadDashboard/loadPeriods/
  loadProductPerf` lúc runtime — KHÔNG sửa `app.js` gốc). Tailwind CDN +
  Chart.js CDN.
- Static files served bởi FastAPI `StaticFiles` (mount `/static` →
  `frontend/`), đọc trực tiếp từ đĩa mỗi request — KHÔNG cần restart service
  để thấy thay đổi file tĩnh (chỉ cần restart khi đổi code Python).
- `frontend/` là bản DEPLOY (được serve); `Phase3_Application/data_bridge/
  patch_scripts/render_performance.js` là bản NGUỒN — luôn sync 2 bản qua
  `patch_frontend.py` (KHÔNG sửa tay `frontend/render_performance.js`).

## 📁 Cấu trúc thư mục quan trọng
```
VPS_AMZ/sellerboard_clone/
├── backend/
│   ├── app/
│   │   ├── main.py                  # mount /static=frontend/, serve "/" = index.html
│   │   ├── routers/dashboard.py     # /api/analytics/dashboard/summary, /periods
│   │   ├── services/profit.py       # period_overview() — 5 KPI tiles, Est. payout
│   │   └── models/models.py         # Product, SummaryProduct, SummaryOrderItem
│   └── alembic/versions/
│       ├── 0001_initial_schema.py
│       └── 0002_add_product_image_url.py   # Product.image_url
├── Phase2_Transformation/            # (đang có thay đổi dở, không thuộc session này)
├── Phase3_Application/data_bridge/
│   ├── analytics_aggregator.py       # nested schema product_info/metrics/detailed_pnl
│   └── patch_scripts/
│       ├── render_performance.js     # BẢN NGUỒN 8-Level UI
│       ├── patch_frontend.py          # copy -> frontend/ + chèn <script> vào index.html
│       ├── patch_dashboard.py         # vá dashboard.py (idempotent)
│       └── rollback.py
└── frontend/
    ├── index.html                    # đã có <script src="/static/render_performance.js">
    ├── app.js                        # const App = {...} — KHÔNG tạo window.App!
    └── render_performance.js         # BẢN DEPLOY (copy từ patch_scripts/, đã fix)
```

## ⚙️ Biến môi trường & Cấu hình (.env)
Không có thay đổi env trong session này. Tham khảo `CLAUDE.md` ở root repo:
`DATABASE_URL` (Supabase Postgres pooler) trong `backend/.env`, đọc bằng
`venv/bin/python` (chạy ngoài venv sẽ rơi về SQLite mặc định).

## 🔑 Thông số kỹ thuật quan trọng
- **VPS**: user `sellervision@Megahost` (REDACTED_VPS_IP), `sudo -S` + password
  (paramiko, không có SSH key).
- **2 checkout trên VPS — DỪNG NHẦM LẪN**:
  - `~/UI_clone_deploy/VPS_AMZ/sellerboard_clone` ← **THẬT**, service
    `sellervision` chạy từ đây (`WorkingDirectory=.../backend`,
    `ExecStart=.../venv/bin/gunicorn app.main:app -k
    uvicorn.workers.UvicornWorker -b 127.0.0.1:8000 --workers 2 --timeout 1800`).
  - `~/VPS_AMZ/sellerboard_clone` ← checkout CŨ/rác, KHÔNG liên quan service,
    KHÔNG dùng để alembic/deploy (chỉ có migration `0001`, gây lỗi
    "Can't locate revision '0002'" nếu chạy alembic ở đây).
- **Repo GitHub**: `https://github.com/maotieumao419-del/UI_clone.git`,
  branch `main`. `origin/main` hiện tại = `1009979`.
- **Alembic**: revision hiện tại của DB = `0002` (head) — đã đủ, không cần
  migrate thêm cho session này.
- **API contract mới**:
  - `GET /api/analytics/dashboard/summary?tab=products&start=YYYY-MM-DD&end=YYYY-MM-DD`
    → `{kpis: {...}, products: [{identifier, product_info:{...},
    metrics:{...}, detailed_pnl:{...}}]}`
  - `GET /api/analytics/dashboard/summary?tab=orders&start=...&end=...`
    → `{kpis: {...}, orders: [{...to_dict(), order_number_raw, order_date}]}`
  - `GET /api/analytics/periods` → 5 thẻ KPI (Today/Yesterday/MTD/Forecast/Last month).
- **Fee model** (xem `CLAUDE.md` + memory `sellervision-fee-model`): referral
  fee thật ≈ 16.5% sales (15% Amazon + 10% VAT VN); `_split_amazon_fees()` và
  `splitAmazonFees()` (JS) dùng hệ số này CHỈ để hiển thị cây P&L, không ảnh
  hưởng tổng `amazon_fees`.
- **Est. payout** = `Net_profit - Cost_of_goods` (commit `29f391e`, đối chiếu
  Sellerboard 13/06/2026: Net profit $235.45, COGS -$25.40 → Est.payout
  $260.85 vs SB $258.35, lệch ~1%).

## 🐛 Vấn đề đã gặp & Cách giải quyết
- **`patch_frontend.py` chưa từng được chạy** → `frontend/index.html` thiếu
  `<script src="/static/render_performance.js">` và `frontend/
  render_performance.js` không tồn tại → UI hoàn toàn không đổi dù code đã
  viết xong. **Giải pháp**: chạy `patch_frontend.py` (có backup + idempotent).
- **`window.App` luôn `undefined`** vì `app.js` dùng `const App = {...}` ở
  top-level — `const`/`let` không tạo property trên `window` (chỉ
  `var`/function declaration mới có). → `install()` trong
  `render_performance.js` luôn fail im lặng (không log lỗi gì), retry qua
  `DOMContentLoaded` cũng fail mãi. **Giải pháp**: check `typeof App ===
  'undefined'` thay vì `window.App`.
- **`curl http://127.0.0.1:8000/` trả 400** khi test trên VPS — KHÔNG phải
  lỗi thật, do `TrustedHostMiddleware` chặn Host header `127.0.0.1` không
  khớp domain cho phép. Test đúng cách: `curl -H "Host: app.tap2soul.com"
  http://127.0.0.1:8000/...` hoặc test trực tiếp qua domain.
- **`alembic upgrade head` lỗi "Can't locate revision '0002'"** — do chạy ở
  thư mục checkout CŨ (`~/VPS_AMZ/sellerboard_clone/backend`, chỉ có migration
  `0001`) trong khi DB đã được stamp `0002` từ checkout THẬT
  (`~/UI_clone_deploy/...`). Không phải lỗi — DB đã đủ, chỉ cần chạy đúng thư
  mục nếu cần kiểm tra lại.
- **`git push` lỗi SSL `SEC_E_UNTRUSTED_ROOT` (schannel)** trên máy Windows
  local — lỗi tạm thời, retry lần 2 thành công. Nếu lặp lại: kiểm tra
  `git config http.sslbackend` (đang = `schannel`) hoặc network/proxy/clock.

## 🚫 Quyết định đã được xác nhận (không thay đổi)
- Giữ nguyên kiến trúc 8-Level đúng theo spec gốc (Mức 4-8 trong
  `render_performance.js`), KHÔNG dùng framework — vanilla JS IIFE, override
  `App.*` lúc runtime.
- `Est. payout = Net_profit - Cost_of_goods` (đã đối chiếu Sellerboard thực
  tế, lệch ~1% — KHÔNG sửa lại công thức cũ `sales+promo-fees+refund_cost`).
- Referral/FBA fee split trong P&L popover dùng ước tính 16.5% sales — chỉ để
  hiển thị, KHÔNG đổi số tổng `amazon_fees` (theo `_split_amazon_fees` /
  `splitAmazonFees`).
- KHÔNG sửa tay `frontend/render_performance.js` trực tiếp — luôn sửa
  `patch_scripts/render_performance.js` (bản nguồn) rồi chạy
  `patch_frontend.py` để đồng bộ sang `frontend/` (bản deploy).
- `~/VPS_AMZ/sellerboard_clone` trên VPS là checkout cũ, KHÔNG dùng cho deploy
  — chỉ làm việc trong `~/UI_clone_deploy/VPS_AMZ/sellerboard_clone`.

## 💡 Context bổ sung
- Local Windows repo: `C:\Users\nnh16\ads-trading-system\VPS` (root chứa
  `CLAUDE.md` — ĐỌC TRƯỚC khi code, có toàn bộ guardrails: không sửa tay
  backend/frontend production ngoài patch_scripts, quy ước dấu Sellerboard,
  fee model 16.5%, timezone Pacific, memory-safety...).
- Tài liệu sâu khác: `VPS_AMZ/sellerboard_clone/docs/SESSION_HANDOFF.md` (bàn
  giao pipeline 3-phase tổng quát, đọc đầu session liên quan pipeline/fees).
- Khi mở session mới: paste file này, sau đó việc đầu tiên là hỏi user đã
  thực hiện bước "Việc cần làm tiếp theo #1" (pull + restart VPS) chưa, để
  biết tiếp tục từ đâu.

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
