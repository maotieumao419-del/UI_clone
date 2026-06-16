# Session Handoff — Debug Tool gọi Amazon SP-API & Ads-API để đối chiếu Sellerboard

## 🎯 Mục tiêu tổng thể

Sellerboard clone (FastAPI backend tại `VPS/VPS_AMZ/sellerboard_clone/backend/`) hiển thị
số liệu (Sales, Amazon fees, Refund cost, Advertising cost, Net profit...) khác với
Sellerboard thật. Để tìm nguyên nhân chênh lệch, xây dựng một bộ script Python độc lập
(`VPS/test_lwa_spapi/`) gọi **trực tiếp** Amazon SP-API + Advertising API, lấy dữ liệu
thô 24h gần nhất, tổng hợp thành số liệu có thể đối chiếu 1:1 với dashboard Sellerboard
→ từ đó sửa logic tính toán trong code chính.

> Lưu ý: đây là **track song song** với việc migration SQLite → Supabase (xem
> `HANDOFF_SUPABASE_MIGRATION.md` ở root project) — track đó đang tạm dừng chờ
> connection string từ user.

---

## ✅ Đã hoàn thành

### 1. Bộ script debug tại `VPS/test_lwa_spapi/` — cả 3 chạy thành công, lấy được data thật

- **`_auth.py`** — module dùng chung: `get_lwa_token()`, `get_sts_creds()`,
  `_sigv4_headers()`, `spapi_get()`, `ads_get()`, `ads_post()`, `collect_fields()`,
  `write_fields_map()`.
- **`fetch_24h_orders.py`** — SP-API `GET /orders/v0/orders` + `/orderItems`.
  Kết quả: **71 orders** trong 24h → `raw_data/orders_24h_raw.json` + `fields_map.txt`.
- **`fetch_24h_finances.py`** — SP-API `GET /finances/v0/financialEvents`.
  Kết quả: **68 events** → `raw_data/finances_24h_raw.json` + `finances_summary.txt`
  (số liệu chi tiết ở mục "Thông số kỹ thuật" bên dưới).
- **`fetch_24h_ads.py`** — Advertising API v3 async reports (SP Campaigns, SP by ASIN,
  SB Campaigns gồm SBV, SD Campaigns). Kết quả: 4 report COMPLETED →
  `raw_data/ads_sp_raw.json`, `ads_sp_asin_raw.json`, `ads_sb_raw.json`, `ads_sd_raw.json`
  + `ads_summary.txt`.
- **`discover_columns.py`** — script phụ tra schema cột Ads API (chưa cần dùng tới vì
  đã fix bằng error message của Amazon).
- `.env` đã điền đủ: SP-API creds, AWS IAM (SigV4/STS), ADS-API creds riêng
  (`AMAZON_ADS_CLIENT_ID/SECRET/REFRESH_TOKEN`), `ADS_PROFILE_ID=REDACTED_ADS_PROFILE_ID`.

### 2. Kiểm tra Model Mapping (`models.py` của Sellerboard clone)

- Đã xác nhận: bảng `orders` (model `Order`) **KHÔNG có** field `total_amount` hay
  `currency` — đây **không phải lỗi đặt tên sai**, model được thiết kế không lưu tổng
  tiền đơn trực tiếp (tính từ `OrderItem.unit_price × quantity`).
- `spapi_sync.py` map `ItemPrice.Amount` (SP-API Orders) → `OrderItem.unit_price`
  (đã chia cho quantity) — **đúng**, vì Orders API dùng field `Amount`, khác với
  Finances API dùng `CurrencyAmount`.
- Đã xác minh bằng raw data thật: `OrderTotal: {"CurrencyCode":"USD","Amount":"10.81"}`,
  `ItemPrice: {"CurrencyCode":"USD","Amount":"9.99"}`.
- **Chưa quyết định**: có nên thêm `total_amount` + `currency` vào `Order` model để lưu
  trực tiếp `OrderTotal` làm nguồn đối chiếu, và để hỗ trợ marketplace ngoài US (non-USD)?
  → Đã hỏi user, **chưa có câu trả lời**.

### 3. Tổ chức lại tài liệu thành folder `Phase 1/`

Đã tạo `VPS/test_lwa_spapi/Phase 1/` chứa 4 file doc (chỉ doc, KHÔNG move code vì code
đang được Phase 2/3 dùng chung):
- `Phase_1.md` — tóm tắt công việc + cấu trúc file + nhiệm vụ từng script
- `HUONG_DAN_CHAY.md` — hướng dẫn chạy gốc
- `SELLERBOARD_API_ANALYSIS.md` — phân tích schema/công thức Sellerboard
- `CALL_API_PLAN.md` — kế hoạch gọi API ban đầu (mapping 11 credentials)

Đã sửa 2 reference trong `HOW_TO_USE.md` (Phase 2 doc) trỏ tới
`Phase 1/HUONG_DAN_CHAY.md` cho đúng path mới.

---

## 🔄 Đang dở / Chưa hoàn thiện

- **So sánh với Sellerboard thật chưa thực hiện.** Đã có đủ số liệu từ API (xem mục
  "Thông số kỹ thuật"), nhưng user chưa gửi screenshot/dữ liệu Sellerboard cho cùng
  ngày **2026-06-08** để đối chiếu từng dòng.
- **Quyết định thêm `total_amount`/`currency` vào `Order` model** — đã đề xuất, chờ
  user xác nhận có muốn làm hay không.
- Lưu ý: kể từ session này, **một phiên khác (Phase 2)** đã tiếp tục sửa
  `fetch_24h_*.py`, `_auth.py`, `run_all.py` để ghi thẳng vào Supabase (thêm
  `_supabase_ingest.py`, `_time_range.py`). Code hiện tại trong `test_lwa_spapi/` đã
  **khác** so với lúc Phase 1 hoàn thành — nếu cần chạy lại để lấy raw JSON như Phase 1,
  cần kiểm tra lại behavior hiện tại (có thể giờ ghi vào Supabase thay vì file JSON).

---

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)

1. **Lấy số liệu Sellerboard thật cho ngày 2026-06-08** (Sales, Amazon fees, Refund
   cost, Advertising cost, Net profit) — qua screenshot hoặc export CSV.
2. **So sánh từng dòng** với bảng số liệu API thực tế (mục "Thông số kỹ thuật" dưới) →
   xác định chênh lệch cụ thể ở đâu (COG, ngày attribution, dấu +/- của
   RefundCommission, thiếu Ads cost...).
3. **Sửa logic tính toán** trong `VPS/VPS_AMZ/sellerboard_clone/backend/app/services/profit.py`
   (và các service liên quan) dựa trên kết quả đối chiếu.
4. (Phụ) Quyết định + implement thêm `total_amount`/`currency` vào `Order` model nếu
   user xác nhận cần.
5. (Song song, không gấp) Tiếp tục Supabase migration khi có connection string —
   xem `HANDOFF_SUPABASE_MIGRATION.md`.

---

## 🏗️ Kiến trúc / Cấu trúc hệ thống

- **Backend chính**: FastAPI + SQLAlchemy, đang ở `VPS/VPS_AMZ/sellerboard_clone/backend/`
  - `app/models/models.py` — ORM models (`Order`, `OrderItem`, `Product`, ...)
  - `app/services/spapi_sync.py` — sync Orders từ SP-API vào SQLite
  - `app/services/settlement_sync.py`, `profit.py`, `inventory.py`, `alerts.py`
  - Đang migrate sang Supabase (Postgres) — track riêng, đang pause
- **Debug tool** (track của session này): `VPS/test_lwa_spapi/` — standalone scripts,
  KHÔNG phụ thuộc backend, gọi Amazon API trực tiếp bằng `requests` + `.env`.
- **Auth flow**:
  - SP-API: LWA refresh token → access token, + AWS STS AssumeRole → SigV4 sign request
  - Ads API: LWA refresh token (app **riêng**, client ID/secret khác SP-API) → Bearer
    token + header `Amazon-Advertising-API-Scope: {profile_id}` (KHÔNG cần SigV4)

---

## 📁 Cấu trúc thư mục quan trọng

```
ads-trading-system/
├── HANDOFF_SUPABASE_MIGRATION.md        ← track song song (Supabase, đang pause)
└── VPS/
    ├── VPS_AMZ/sellerboard_clone/backend/
    │   └── app/
    │       ├── models/models.py          ← Order, OrderItem (không có total_amount/currency)
    │       └── services/spapi_sync.py    ← sync Orders SP-API → SQLite
    │
    └── test_lwa_spapi/
        ├── .env                          ← credentials thật (SP-API + ADS-API + AWS IAM)
        ├── .env.example
        ├── _auth.py                      ← module auth dùng chung (SHARED với Phase 2/3)
        ├── fetch_24h_orders.py           ← SP-API Orders + OrderItems
        ├── fetch_24h_finances.py         ← SP-API Financial Events
        ├── fetch_24h_ads.py              ← Advertising API v3 async reports
        ├── discover_columns.py           ← tra schema cột Ads API
        ├── run_all.py / start.bat        ← chạy cả 3 script
        ├── HOW_TO_USE.md, Phase_2.md     ← tài liệu Phase 2 (Supabase ingest)
        ├── Phase3/backend/                ← (Phase 3, không thuộc scope session này)
        ├── raw_data/                      ← output JSON + summary .txt
        │
        └── Phase 1/                       ← TÀI LIỆU CỦA SESSION NÀY
            ├── SESSION_HANDOFF.md          ← file này
            ├── Phase_1.md
            ├── HUONG_DAN_CHAY.md
            ├── SELLERBOARD_API_ANALYSIS.md
            └── CALL_API_PLAN.md
```

---

## ⚙️ Biến môi trường & Cấu hình (.env)

File: `VPS/test_lwa_spapi/.env` (đã điền giá trị thật, KHÔNG commit/push)

```env
# ── SP-API ───────────────────────────────────────────────
AMAZON_SPI_CLIENT_ID=amzn1.application-oa2-client.xxxx
AMAZON_SPI_CLIENT_SECRET=amzn1.oa2-cs.v1.xxxx
AMAZON_SPI_REFRESH_TOKEN=Atzr|xxxx
AMAZON_SPI_MARKETPLACE_ID=ATVPDKIKX0DER   # US

# ── AWS IAM (SigV4 cho SP-API) ───────────────────────────
AWS_ACCESS_KEY_ID=AKIAxxxx
AWS_SECRET_ACCESS_KEY=xxxx
AWS_ROLE_ARN=arn:aws:iam::xxxx:role/sp-api-role
AWS_REGION=us-east-1

# ── ADS-API (app RIÊNG, khác SP-API!) ────────────────────
AMAZON_ADS_CLIENT_ID=amzn1.application-oa2-client.xxxx
AMAZON_ADS_CLIENT_SECRET=amzn1.oa2-cs.v1.xxxx
AMAZON_ADS_REFRESH_TOKEN=Atzr|xxxx
ADS_PROFILE_ID=REDACTED_ADS_PROFILE_ID             # seller "Dr Hai Craft", US
```

> ⚠️ Quan trọng: `AMAZON_ADS_CLIENT_ID/SECRET` phải khác `AMAZON_SPI_CLIENT_ID/SECRET` —
> nếu dùng chung sẽ ra lỗi `400`/`401` (xem mục Bugs).

---

## 🔑 Thông số kỹ thuật quan trọng

### Endpoints
| Service | Base URL |
|---|---|
| SP-API | `https://sellingpartnerapi-na.amazon.com` |
| Ads API | `https://advertising-api.amazon.com` |
| LWA token | `https://api.amazon.com/auth/o2/token` |
| STS | `https://sts.amazonaws.com/` |

### Field name khác nhau giữa 2 API (rất dễ nhầm!)
| API | Field tiền | Ví dụ |
|---|---|---|
| Orders API (`OrderTotal`, `ItemPrice`) | `Amount` (string) | `{"CurrencyCode":"USD","Amount":"9.99"}` |
| Finances API (`ChargeAmount`, `FeeAmount`, `PerUnitAmount`) | `CurrencyAmount` (float) | `{"CurrencyCode":"USD","CurrencyAmount":7.98}` |

### Số liệu thực tế thu được — ngày **2026-06-08**

**Từ `finances_summary.txt`:**
| Chỉ số | Giá trị |
|---|---|
| Sales (Principal), 49 orders | +$555.88 |
| FBA Fulfillment fee | -$166.77 |
| Referral fee | -$91.42 |
| Adjustments (WAREHOUSE_DAMAGE reimbursement) | +$4.30 |
| Service fees (FBADisposalFee) | -$1.68 |
| **Tổng Amazon fees** | **-$255.57** |
| Refunded amount (1 return) | -$8.98 |
| Refund commission | +$1.49 |
| Refunded referral fee (RefundCommission) | -$0.30 |
| **Refund cost (tổng)** | **-$7.79** |

**Từ `ads_summary.txt`:**
| Loại quảng cáo | Spend |
|---|---|
| Sponsored Products (526 campaigns, 32,829 impr, 277 clicks, sales1d $243.70) | $166.79 |
| Sponsored Brands + SBV (70 campaigns) | $12.47 |
| Sponsored Display | $0.00 |
| **TỔNG ADS COST** | **$179.26** |

**Gross profit (trước COG)**:
```
= Sales + Amazon fees + Refund cost + Ads cost
= 555.88 + (-255.57) + (-7.79) + (-179.26)
= $113.26
```

### Amazon Advertising API v3 — Columns hợp lệ theo report type (đã verify qua error message)

- **`spCampaigns`**: `campaignId, campaignName, campaignStatus, campaignBiddingStrategy,
  impressions, clicks, cost, purchases1d/7d/14d/30d, sales1d/7d/14d/30d,
  unitsSoldClicks1d, attributedSalesSameSku1d/7d/14d, roasClicks14d`
- **`spAdvertisedProduct`**: `campaignId, campaignName, adGroupId, adGroupName,
  advertisedAsin, advertisedSku, impressions, clicks, cost, purchases1d, sales1d,
  unitsSoldClicks1d, purchases7d, sales7d`
- **`sbCampaigns`**: **KHÔNG có suffix `Nd`** — dùng `campaignId, campaignName,
  campaignStatus, impressions, clicks, cost, date, purchases, purchasesPromoted,
  detailPageViews, brandedSearches, brandStorePageView, newToBrandPurchases,
  newToBrandSales`
- **`sdCampaigns`**: tối thiểu `campaignId, campaignName, campaignStatus, impressions,
  clicks, cost, date` (chưa cần thêm cột vì spend = $0, campaigns = 0)

---

## 🐛 Vấn đề đã gặp & Cách giải quyết

| # | Lỗi | Nguyên nhân | Fix |
|---|---|---|---|
| 1 | `403` Orders API | AWS SigV4 ký `url` không kèm query params, nhưng request gửi `full_url` có params | Build `full_url = url + "?" + urlencode(sorted(params.items()))` **trước**, ký `full_url` |
| 2 | `.env` parse warning | `profile ID=...` sai tên key + có space | Đổi thành `ADS_PROFILE_ID=...` |
| 3 | `400` Finances API | `PostedBefore` quá gần hiện tại → data chưa finalize | Bỏ `PostedBefore`, chỉ dùng `PostedAfter` |
| 4 | `KeyError: 'Amount'` trong `summarize_events` | Truy cập trực tiếp `charge["ChargeAmount"]["Amount"]` | Thêm helper `_amt(obj, key=...)` dùng `.get()` |
| 5 | `_amt()` luôn trả 0.0 | Finances API dùng key **`CurrencyAmount`**, không phải `Amount` (khác Orders API!) | `_amt(obj, key="CurrencyAmount")` |
| 6 | `400` khi lấy LWA token cho Ads API | Dùng `AMAZON_SPI_CLIENT_ID/SECRET` để đổi `AMAZON_ADS_REFRESH_TOKEN` (refresh token thuộc app khác) | Thêm `ADS_CLIENT_ID`/`ADS_CLIENT_SECRET` riêng trong `_auth.py`, truyền vào `get_lwa_token()` |
| 7 | `401` khi gọi `/v2/profiles` | Header `Amazon-Advertising-API-ClientId` vẫn dùng SP-API client ID | Đổi sang `ADS_CLIENT_ID` trong `ads_get`/`ads_post` |
| 8 | `400` cột `attributedUnitsOrderedNewToBrand14d` invalid cho `spCampaigns` | Đoán sai tên cột | Bỏ cột, dùng `roasClicks14d`, `campaignBiddingStrategy`, `attributedSalesSameSku*` |
| 9 | `429 Throttled` khi POST report thứ 3 | 4 report request gửi liên tiếp quá nhanh | Thêm `time.sleep(5)` giữa các POST + retry tự động khi 429 (đọc `Retry-After`) |
| 10 | `400` cột `purchases14d`/`sales14d` invalid cho `sbCampaigns` | SB dùng tên cột khác SP (không có suffix `Nd`) | Đổi sang `purchases`, `purchasesPromoted`, `detailPageViews`, `brandedSearches`, `brandStorePageView`, `newToBrandPurchases`, `newToBrandSales` |

---

## 🚫 Quyết định đã được xác nhận (không thay đổi)

- **Amazon Ads docs (`advertising.amazon.com/API/docs`) là JS SPA** — WebFetch/WebSearch
  không lấy được nội dung thật (chỉ trả về title trang). Cách xác định cột hợp lệ đáng
  tin cậy nhất: đọc full error message `400` của Amazon (luôn liệt kê "Allowed values").
  → Đã tăng giới hạn in error response từ 300 ký tự lên full text trong `_auth.py`.
- **Không move code vào folder `Phase 1/`** — chỉ gom tài liệu (.md). Lý do: `_auth.py`,
  `fetch_24h_*.py`, `run_all.py` hiện là code sống dùng chung cho Phase 2/3 (đã được
  Phase 2 sửa để ghi thẳng Supabase). Move sẽ phá vỡ import paths.
- **`Order` model KHÔNG có `total_amount`/`currency`** là thiết kế có chủ đích (tính từ
  `OrderItem`), không phải bug đặt tên — nhưng có thể là điểm cần cải thiện (xem mục
  "Đang dở").

---

## 💡 Context bổ sung

- **Ràng buộc bảo mật của track Supabase migration** (áp dụng cho toàn project, copy từ
  `HANDOFF_SUPABASE_MIGRATION.md` để tránh quên):
  - ⛔ TUYỆT ĐỐI KHÔNG `git push` cho `main`/`merge-period-cards`/`wip-spapi-sync-backup`
    (commit `27cd7bf` chứa credential thật)
  - KHÔNG SSH trực tiếp — viết lệnh đầy đủ để user tự copy/paste
  - KHÔNG sửa file bằng tay trên VPS — luôn dùng script Python với `try_replace`
    (`assert content.count(...) == 1`, có backup, idempotent)
  - Luôn test qua `https://app.tap2soul.com/api/health` (KHÔNG gọi `127.0.0.1:8000`)
  - Sửa cấu hình → luôn backup + có cách rollback
  - Chỉ chạy MỘT lệnh `sudo systemctl restart sellervision` mỗi lần (không kèm
    daemon-reload)
- Profile Amazon Ads đang dùng: `profileId=REDACTED_ADS_PROFILE_ID`, marketplace US, seller name
  **"Dr Hai Craft"**, account type `seller`.
- Ngày dữ liệu mẫu đã fetch và dùng để tính toán: **2026-06-08** (PostedAfter
  `2026-06-08T18:51:23Z`, 24h gần nhất tính từ lúc chạy script).

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
