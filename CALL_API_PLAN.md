# Kế hoạch Call API Amazon — Chi tiết trước triển khai

> **11 thông số đang có:**
> SP-API: `Client ID` · `Client Secret` · `Refresh Token`
> ADS-API: `Client ID` · `Client Secret` · `Refresh Token` · `Profile ID`
> Common: `Marketplace ID`
> AWS: `Access Key ID` · `Secret Access Key` · `Role ARN`

---

## 1. Bản đồ 11 thông số → dùng vào đâu

```
┌─────────────────────────────────────────────────────────────────────┐
│                        11 THÔNG SỐ                                  │
├──────────────────────────┬──────────────────────────────────────────┤
│  SP-API (3 thông số)     │  ADS-API (4 thông số)                   │
│  ─ Client ID             │  ─ Client ID       (thường CÙNG SP)     │
│  ─ Client Secret         │  ─ Client Secret   (thường CÙNG SP)     │
│  ─ SP Refresh Token      │  ─ ADS Refresh Token                    │
│                          │  ─ Profile ID      (riêng ADS)          │
├──────────────────────────┴──────────────────────────────────────────┤
│  AWS (3 thông số) — chỉ dùng cho SP-API, ADS không cần             │
│  ─ Access Key ID                                                     │
│  ─ Secret Access Key                                                 │
│  ─ Role ARN                                                          │
├─────────────────────────────────────────────────────────────────────┤
│  Common (1 thông số)                                                 │
│  ─ Marketplace ID  (ATVPDKIKX0DER = US)                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Auth Flow — 2 luồng khác nhau hoàn toàn

### Luồng A: SP-API (Orders, Finances, Catalog, Inventory)

```
Bước A1: Đổi Refresh Token → Access Token (LWA)
─────────────────────────────────────────────────
POST https://api.amazon.com/auth/o2/token
Body:
  grant_type    = refresh_token
  refresh_token = SP_REFRESH_TOKEN        ← thông số SP
  client_id     = SP_CLIENT_ID            ← thông số SP
  client_secret = SP_CLIENT_SECRET        ← thông số SP

Response:
  access_token  = "Atza|xxxx"    ← dùng làm header x-amz-access-token
  expires_in    = 3600           ← dùng 1 giờ, sau đó lấy lại
─────────────────────────────────────────────────

Bước A2: Assume AWS Role → Temp Credentials (STS)
─────────────────────────────────────────────────
POST https://sts.amazonaws.com/
Action=AssumeRole
  RoleArn          = AWS_ROLE_ARN         ← thông số AWS
  RoleSessionName  = any_string
  DurationSeconds  = 3600

Ký request này bằng SigV4 dùng:
  AWS_ACCESS_KEY_ID                       ← thông số AWS
  AWS_SECRET_ACCESS_KEY                   ← thông số AWS

Response:
  TempAccessKeyId     ← thay thế AWS_ACCESS_KEY_ID
  TempSecretAccessKey ← thay thế AWS_SECRET_ACCESS_KEY
  TempSessionToken    ← dùng thêm
─────────────────────────────────────────────────

Bước A3: Gọi SP-API
─────────────────────────────────────────────────
GET https://sellingpartnerapi-na.amazon.com/...

Headers:
  x-amz-access-token: Atza|xxxx          ← từ Bước A1
  [AWS SigV4 signature]                   ← ký bằng Temp Credentials từ Bước A2

Nếu không có AWS creds → chỉ gửi x-amz-access-token → thường 403 Forbidden
─────────────────────────────────────────────────
```

**Lý do cần cả 2 bước A1 + A2:**
- `x-amz-access-token` (LWA): chứng minh bạn là seller hợp lệ
- `SigV4` (AWS): chứng minh request xuất phát từ app đã đăng ký với Amazon

---

### Luồng B: ADS-API (Advertising Reports)

```
Bước B1: Đổi Refresh Token → Access Token (LWA)
─────────────────────────────────────────────────
POST https://api.amazon.com/auth/o2/token
Body:
  grant_type    = refresh_token
  refresh_token = ADS_REFRESH_TOKEN       ← thông số ADS
  client_id     = ADS_CLIENT_ID           ← thông số ADS (thường = SP)
  client_secret = ADS_CLIENT_SECRET       ← thông số ADS (thường = SP)

Response:
  access_token  = "Atza|yyyy"
─────────────────────────────────────────────────

Bước B2: Gọi ADS-API — KHÔNG cần STS, KHÔNG cần SigV4
─────────────────────────────────────────────────
POST https://advertising-api.amazon.com/reporting/reports

Headers:
  Authorization:                   Bearer Atza|yyyy   ← từ Bước B1
  Amazon-Advertising-API-ClientId: ADS_CLIENT_ID      ← thông số ADS
  Amazon-Advertising-API-Scope:    PROFILE_ID         ← thông số ADS

Gọi ADS-API đơn giản hơn SP-API vì không cần AWS
─────────────────────────────────────────────────
```

---

## 3. Kế hoạch call từng API → dữ liệu cụ thể

### Giai đoạn 1 — SP-API: Orders

| # | Endpoint | Method | Thông số dùng | Dữ liệu lấy về | Ghi chú |
|---|---|---|---|---|---|
| 1.1 | `/orders/v0/orders` | GET | LWA + SigV4 + `MARKETPLACE_ID` | Danh sách orders (OrderId, PurchaseDate, Status) | Filter `CreatedAfter` = 24h trước |
| 1.2 | `/orders/v0/orders/{id}/orderItems` | GET | LWA + SigV4 | ASIN, SKU, Qty, Price, Promo | Gọi 1 lần/order, sleep 1s |

**Dữ liệu thu được sau Giai đoạn 1:**
```
AmazonOrderId → PurchaseDate, Status, FulfillmentChannel
  └── ASIN, SellerSKU, QuantityOrdered, ItemPrice, PromotionDiscount
```

**Giới hạn cần xử lý:**
- `/orders/v0/orders`: rate limit 0.0167 req/s → tự phân trang bằng `NextToken`
- `/orderItems`: 0.5 req/s → sleep 1s giữa các call

---

### Giai đoạn 2 — SP-API: Finances

| # | Endpoint | Method | Thông số dùng | Dữ liệu lấy về | Parse từ |
|---|---|---|---|---|---|
| 2.1 | `/finances/v0/financialEvents` | GET | LWA + SigV4 | FBA fee, Referral fee | `ShipmentEventList[].ItemFeeList` |
| 2.2 | (cùng endpoint, cùng response) | | | Refunded amount, Refund commission, +Referral back | `RefundEventList[].ItemFeeAdjustmentList` |
| 2.3 | (cùng endpoint, cùng response) | | | Clawback, Disposal fee | `AdjustmentEventList` |

**Dữ liệu thu được sau Giai đoạn 2:**
```
ShipmentEventList:
  AmazonOrderId → ItemFeeList:
    FBAPerUnitFulfillmentFee → Amazon fees (phần FBA)
    Commission               → Amazon fees (phần Referral)

RefundEventList:
  AmazonOrderId (PostedDate = ngày refund!) → ItemFeeAdjustmentList:
    Principal        (âm) → Refunded amount
    Commission       (âm) → Refund commission
    RefundCommission (DƯƠNG) → Refunded referral fee

AdjustmentEventList:
  FBAInventoryReimbursement → Compensated clawback
  FBADisposalFee            → Disposal fee
```

**Công thức tính từ dữ liệu này:**
```
Amazon fees = FBA_fee + Referral + Clawback + Disposal
Refund cost = Principal_adj + Commission_adj + RefundCommission
              (âm)            (âm)             (DƯƠNG → cộng vào, không trừ)
```

---

### Giai đoạn 3 — ADS-API: Reports (Async)

| # | Report Type | adProduct | reportTypeId | Dữ liệu lấy về |
|---|---|---|---|---|
| 3.1 | SP Campaigns | `SPONSORED_PRODUCTS` | `spCampaigns` | spend, impressions, clicks, attributed sales/units 1d/7d |
| 3.2 | SP by ASIN | `SPONSORED_PRODUCTS` | `spAdvertisedProduct` | spend + sales/units **per SKU** → gán Ads vào từng sản phẩm |
| 3.3 | SB Campaigns | `SPONSORED_BRANDS` | `sbCampaigns` | spend, `campaignType` (SB vs SBV), attributed 14d |
| 3.4 | SD Campaigns | `SPONSORED_DISPLAY` | `sdCampaigns` | spend, attributed 14d |

**Thứ tự gọi ADS-API:**
```
B1: Gửi 4 report requests cùng lúc → nhận 4 reportId
    (gửi cùng lúc để chạy song song, không đợi từng cái)

B2: Poll từng reportId mỗi 15 giây cho đến status = COMPLETED
    Thường mất 1-5 phút/report

B3: Download từ url trong response → decompress gzip → parse JSON

B4: Tổng hợp:
    SP Campaigns: SUM(cost) = Sponsored Products spend
    SB Campaigns: GROUP BY campaignType:
      sponsoredBrands      → SB spend
      sponsoredBrandsVideo → SBV spend
    SD Campaigns: SUM(cost) = SD spend
    SP ASIN: cost per advertisedSku → gán vào Products view
```

**Dữ liệu thu được sau Giai đoạn 3:**
```
Advertising cost breakdown:
  SP spend  = SUM(spCampaigns.cost)    = $166.79
  SBV spend = SUM(sbCampaigns.cost where campaignType=sponsoredBrandsVideo) = $12.47
  SB spend  = SUM(sbCampaigns.cost where campaignType=sponsoredBrands) = $0.00
  SD spend  = SUM(sdCampaigns.cost)    = $0.00
  TỔNG      = $179.26  ✓

Attribution:
  SP attributed units (same day) = SUM(spCampaigns.purchases1d) = 19
  SP attributed sales (same day) = SUM(spCampaigns.sales1d)     = $221.73
  → Organic units = Total units (62) - SP attributed (19) = 43  ✓
```

---

### Giai đoạn 4 — Tính toán & Tổng hợp

```
INPUT:
  orders_data   (từ Giai đoạn 1)
  finances_data (từ Giai đoạn 2)
  ads_data      (từ Giai đoạn 3)
  cog_table     (từ DB — user nhập tay per SKU)

TÍNH Order Items view (per order):
  For each order:
    sales        = ItemPrice.Amount
    amazon_fees  = FBA_fee + Referral_fee  (từ finances theo OrderId)
    cog          = cog_per_sku × QuantityOrdered
    gross_profit = sales + amazon_fees + cog
    net_profit   = gross_profit  (+ expenses nếu có)
    margin       = net_profit / sales × 100
    roi          = net_profit / abs(cog) × 100

  For each return:
    refund_cost  = refunded_amount + refund_commission + refunded_referral_fee
    net_profit   = refund_cost

TÍNH Products view (per SKU):
  For each SKU:
    sales        = SUM(order.sales)
    units        = SUM(order.qty)
    refunds      = COUNT(return events for this SKU)
    ads          = SUM(spASIN.cost where sku = this_sku)
    gross_profit = SUM(order.net_profit + return.net_profit) + ads
    net_profit   = gross_profit
    margin       = net_profit / sales × 100

TÍNH Daily Summary:
  sales           = SUM(all order sales)
  adv_cost        = -(SP + SBV + SB + SD)
  refund_cost     = SUM(all return net_profits)
  amazon_fees     = SUM(FBA + Referral + Clawback + Disposal)
  cog             = SUM(all order cog)
  gross_profit    = sales + adv_cost + refund_cost + amazon_fees + cog
  net_profit      = gross_profit
  est_payout      = sales + amazon_fees + refund_cost + adv_cost  [không có COG]
  real_acos       = abs(adv_cost) / sales × 100
  pct_refunds     = refund_count / unit_count × 100
  margin          = net_profit / sales × 100
  roi             = net_profit / abs(cog) × 100
```

---

## 4. Timeline thực thi (1 lần chạy)

```
t=0s    A1: Lấy LWA token SP-API      (~1-2s)
t=2s    A2: STS AssumeRole            (~1-2s)
t=4s    B1: Lấy LWA token ADS-API    (~1s, nếu cùng refresh token thì dùng lại)
t=5s    Giai đoạn 1: Orders API
          - GET /orders (page 1..N)   (~30-60s tùy số đơn + rate limit)
          - GET /orderItems per order (~1s/đơn)
t=90s   Giai đoạn 2: Finances API
          - GET /financialEvents      (~10-30s)
t=120s  Giai đoạn 3: ADS-API
          - POST 4 report requests    (~5s)
          - Poll mỗi 15s...           (1-5 phút)
          - Download 4 files          (~10s)
t=420s  Giai đoạn 4: Tính toán       (<1s)

TỔNG: 5-10 phút (phụ thuộc chủ yếu vào ADS report generation)
```

---

## 5. Điểm cần xử lý đặc biệt (potential issues)

| Vấn đề | Nguyên nhân | Cách xử lý |
|---|---|---|
| 403 Forbidden ở SP-API | STS thất bại → rơi về LWA-only | Kiểm tra AWS_ROLE_ARN, đảm bảo STS thành công |
| 429 Too Many Requests | Orders API rate limit 0.0167 req/s | Script tự retry với `Retry-After` header |
| ADS report `FAILED` | Tên cột không hợp lệ trong config | Xem message trong response, bỏ cột đó |
| `RefundCommission` dương | Nhầm dấu khi tính Refund cost | CỘNG vào (không trừ): refund_cost = principal + commission + refund_commission |
| Return gán sai ngày | Dùng PurchaseDate thay PostedDate | Dùng `RefundEventList[].PostedDate` cho return |
| COG = 0 nhiều SKU | Chưa nhập COG vào DB | Cần bảng `product_cogs`, user nhập tay |

---

## 6. Checklist trước khi chạy

```
✅ .env đã điền đủ 11 thông số
✅ Python + requests + python-dotenv đã cài
✅ Chạy test_spapi.py xem LWA token lấy được không
✅ Nếu STS thành công → SP-API sẽ trả 200
✅ Nếu STS thất bại  → cần kiểm tra:
     - AWS_ROLE_ARN đúng format: arn:aws:iam::123456789012:role/TenRole
     - IAM user có quyền sts:AssumeRole cho role đó
     - Role trust policy cho phép IAM user assume
✅ ADS_PROFILE_ID đã điền (hoặc để trống để script tự in danh sách)
```

---

## 7. Tóm tắt 1 trang

```
┌────────────────────────────────────────────────────────────────────┐
│  THÔNG SỐ          DÙNG Ở BƯỚC NÀO           KẾT QUẢ             │
├────────────────────────────────────────────────────────────────────┤
│  SP Client ID      A1: LWA token SP           access_token SP     │
│  SP Client Secret  A1: LWA token SP                               │
│  SP Refresh Token  A1: LWA token SP                               │
│                                                                    │
│  AWS Access Key    A2: STS AssumeRole         temp credentials    │
│  AWS Secret Key    A2: STS AssumeRole                             │
│  AWS Role ARN      A2: STS AssumeRole                             │
│                                                                    │
│  [LWA token SP]    A3: Header x-amz-access-token  SP-API calls   │
│  [Temp AWS creds]  A3: SigV4 signing              SP-API calls   │
│  Marketplace ID    A3: Query param MarketplaceIds                 │
│                                                                    │
│  ADS Client ID     B1: LWA token ADS          access_token ADS   │
│  ADS Client Secret B1: LWA token ADS                             │
│  ADS Refresh Token B1: LWA token ADS                             │
│                                                                    │
│  [LWA token ADS]   B2: Header Authorization: Bearer              │
│  ADS Client ID     B2: Header API-ClientId                       │
│  Profile ID        B2: Header API-Scope       ADS-API calls      │
└────────────────────────────────────────────────────────────────────┘

SP-API data:   Orders, Finances (fees + refunds), Catalog, Inventory
ADS-API data:  Ad spend (SP/SB/SBV/SD), Attributed sales/units per SKU

Kết hợp 2 nguồn + COG từ DB → ra đúng số liệu như Sellerboard
```
