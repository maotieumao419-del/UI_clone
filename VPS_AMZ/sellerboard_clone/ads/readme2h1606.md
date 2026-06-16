# README — Module ADS (chỉ số quảng cáo) · ~2h 16/06/2026

> Bàn giao cho đồng nghiệp đọc tiếp. Tóm tắt phiên xây **trang chỉ số Amazon Ads**
> (ACOS/ROAS/TACOS/CTR/CVR/CPC) cho SellerVision. Code nằm ở folder `ads/` này +
> 1 file backend. Đọc kèm `CLAUDE.md` (guardrails) và `docs/0003_RESTRUCTURE_RUNBOOK.md`.

## TL;DR
Thêm **một trang/module MỚI** đọc dữ liệu ADS *đã được pipeline xử lý sẵn* trong Supabase
(`NEW_ads_*`) rồi tính & hiển thị KPI quảng cáo. **Additive 100%** — KHÔNG refactor pipeline,
KHÔNG sửa `app.js`, chỉ thêm endpoint mỏng vào router `ads` đã mount sẵn.

## Vì sao làm kiểu "consumer đọc DB" (không mổ code cũ)
ADS là **lát cắt ngang** (đan xuyên pull → transform → API → UI), không tách dọc ra 1 folder được
mà không gãy PnL. Nên: dữ liệu đã xử lý nằm trong DB → ADS chỉ là **trang mới đọc DB** → tính chỉ số
→ hiển thị; thiếu gì query thêm. Đây là tách theo **vai trò logic** (1=xử lý dữ liệu Phase1/2,
2=dashboard PnL backend/frontend, 3=ADS mới), không phải dời file.

## Đã thêm / sửa gì

| File | Vai trò |
|---|---|
| `ads/ads_aggregator.py` (MỚI) | Logic chỉ số: query `NEW_ads_*` qua SQLAlchemy session, tính KPI ở 3 cấp: `get_ads_overview` / `get_campaign_performance` / `get_sku_ads_performance`. Raw SQL `text()` (các bảng này không có ORM model). |
| `ads/render_ads.js` (MỚI) | Frontend trang `📣 Amazon Ads`: thẻ KPI + bảng campaign + bảng SKU + chọn ngày/cửa sổ. Ghi đè `App.loadAmazonAds` lúc runtime — **KHÔNG sửa app.js**. |
| `ads/patch_ads_page.py` (MỚI) | Copy `render_ads.js` → `frontend/` + chèn `<script>` vào `index.html` (mirror `patch_frontend.py`, có `--check`/backup). |
| `ads/__init__.py` (MỚI) | Đánh dấu package (để `from ads.ads_aggregator import ...`). |
| `backend/app/routers/ads.py` (SỬA, additive) | + 3 endpoint `GET /api/ads/analytics/overview\|campaigns\|skus?start&end&window`. Router `ads` đã được mount sẵn → **không đụng `main.py`**. |

## Luồng dữ liệu
```
Amazon API ─(Phase1/2 pipeline đã có)─► Supabase: NEW_ads_campaigns_daily / NEW_ads_sp_asin_daily
                                                   (+ NEW_ad_campaigns, NEW_products nếu đã áp 0003)
   ads_aggregator.py  ──query+tính KPI──►  routers/ads.py (/api/ads/analytics/*)
                                                   │
                              render_ads.js ◄──────┘  → trang 📣 Amazon Ads (thẻ KPI + 2 bảng)
```
App DB sống = **chính Supabase Postgres** chứa `NEW_*` (xem `CLAUDE.md` §2) → backend query thẳng,
không cần kết nối riêng. Bắt chước y `Phase3_Application/data_bridge/analytics_aggregator.py`.

## API (đọc DB, KHÔNG gọi Amazon)
- `GET /api/ads/analytics/overview?start&end&window` → thẻ KPI tổng.
- `GET /api/ads/analytics/campaigns?...` → mảng theo campaign (sort spend ↓).
- `GET /api/ads/analytics/skus?...` → mảng theo SKU/ASIN.
- `window` ∈ {`1d`,`7d`,`14d`} (mặc định `7d`; bảng SKU chỉ có 1d/7d). `start`/`end` thiếu → 30 ngày gần nhất (giờ Pacific).

## Công thức KPI (chuẩn Sellerboard; cost/sales lưu DƯƠNG ở `NEW_ads_*`)
`ACOS = spend/ad_sales` · `ROAS = ad_sales/spend` · `TACOS = spend/tổng_sales`
`CTR = clicks/impr` · `CPC = spend/clicks` · `CVR = orders/clicks`.
Mẫu số = 0 → trả `null` (UI hiện "—", không bịa số). `tổng_sales` lấy từ `NEW_summary_products`.

## Bật trên app (đồng bộ domain thật)
```bash
cd ~/VPS_AMZ/sellerboard_clone
python ads/patch_ads_page.py        # chèn render_ads.js vào frontend (có --check / backup)
# restart backend → mở app.tap2soul.com → 📣 Amazon Ads
```
**Prereq (tùy chọn, để enrich):** áp `Phase2_Transformation/sql/0003_*.sql` (entity tree) + chạy
`Phase1_Ingestion/direct_stream_pipeline.py --entities` → khi đó có thêm cột **State/Budget/Targeting**
(campaign) và **Title** (SKU). Chưa áp vẫn chạy — code tự bỏ qua phần enrich (guard `_table_exists`).

## Verify nhanh
```bash
python ads/ads_aggregator.py --days 30      # in KPI từ DB; tự kiểm ACOS×ad_sales≈spend, ROAS=1/ACOS
# hoặc curl: /api/ads/analytics/overview → JSON đủ 6 KPI
```

## Lưu ý / giả định (đọc kỹ)
- Endpoint `/api/ads/analytics/*` **không bắt auth** — đồng nhất với các endpoint khác trong
  `routers/ads.py`. Muốn khóa sau login: thêm `Depends(get_current_user)` mỗi endpoint.
- **TACOS** lấy tổng sales `NEW_summary_products` **không lọc owner** (pipeline single-seller hiện tại).
  Multi-seller sau này cần thêm lọc `owner_id`.
- `_table_exists()` dùng SQLAlchemy `inspect().has_table()` (chạy cả Postgres prod lẫn SQLite dev) —
  KHÔNG dùng `to_regclass` (chỉ Postgres).
- **Code preview giao diện là TẠM THỜI**, nằm ở `/tmp/ads_preview/` (ngoài repo, không commit) — chỉ
  để xem mắt bằng SQLite demo. Đồ thật chạy backend thật + Supabase thật.

## Việc tiếp theo (chưa làm)
Drilldown keyword/ad_group · biểu đồ timeseries ADS · TACOS-per-SKU (nối organic sales) · Khối E
(Automation) — sau khi trang ADS cơ bản được duyệt.
