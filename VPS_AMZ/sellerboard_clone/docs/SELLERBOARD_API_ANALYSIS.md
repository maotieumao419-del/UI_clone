# Sellerboard Clone — Phân tích API & Thông số

> Mục đích: Tài liệu tham chiếu toàn diện để clone các thông số Sellerboard.
> Nguồn: Phân tích từ CSV export + screenshots Sellerboard ngày 08.06.2026.
> Cấu trúc: SP-API → ADS-API → Map thông số → Dashboard formula → Thứ tự call.

---

## 1. SP-API (Selling Partner API)

SP-API gồm nhiều endpoint con. Với Sellerboard, cần 4 nhóm chính:

---

### 1.1 Orders API

**Endpoint:**
- `GET /orders/v0/orders` — danh sách đơn hàng
- `GET /orders/v0/orders/{orderId}/orderItems` — chi tiết từng đơn

**Rate limit:** 0.0167 req/s (1 req/60s) burst 20 cho orders; 0.5 req/s burst 30 cho orderItems

**Response — Orders:**
```json
{
  "AmazonOrderId":          "113-9240893-4241801",
  "PurchaseDate":           "2026-06-08T08:43:00Z",
  "LastUpdateDate":         "2026-06-08T09:10:00Z",
  "OrderStatus":            "Shipped",
  "FulfillmentChannel":     "AFN",
  "SalesChannel":           "Amazon.com",
  "NumberOfItemsShipped":   2,
  "NumberOfItemsUnshipped": 0,
  "OrderTotal": {
    "CurrencyCode": "USD",
    "Amount":       "27.98"
  },
  "IsReplacementOrder": false
}
```

> `FulfillmentChannel`: AFN = FBA, MFN = FBM
> `OrderStatus`: Pending | Unshipped | PartiallyShipped | Shipped | Canceled | Unfulfillable

**Response — Order Items:**
```json
{
  "ASIN":               "B0F9PGKBX2",
  "SellerSKU":          "POSITIVEJAR_TURTLE",
  "Title":              "Musemory 60 Positive Cards Turtle Jar...",
  "QuantityOrdered":    2,
  "QuantityShipped":    2,
  "ItemPrice":          { "Amount": "27.98", "CurrencyCode": "USD" },
  "ItemTax":            { "Amount": "0.00",  "CurrencyCode": "USD" },
  "PromotionDiscount":  { "Amount": "0.00",  "CurrencyCode": "USD" },
  "IsGift":             false,
  "ConditionId":        "New"
}
```

**Thông số lấy được từ Orders API:**

| Thông số Sellerboard | Field trong API | Ghi chú |
|---|---|---|
| Order number | `AmazonOrderId` | Raw |
| Order date | `PurchaseDate` | Parse ISO8601 → date |
| Status | `OrderStatus` | Shipped / Unshipped / Canceled |
| FBA / FBM | `FulfillmentChannel` | AFN = FBA, MFN = FBM |
| ASIN | `ASIN` (từ orderItems) | Raw |
| SKU | `SellerSKU` (từ orderItems) | Raw |
| Units | `QuantityOrdered` | Raw |
| Sales | `ItemPrice.Amount` | = Price × Units |
| Promo | `PromotionDiscount.Amount` | Âm nếu có khuyến mãi |

> ⚠️ **Orders API KHÔNG có:** Amazon fees, Refund data, COG — phải lấy từ Finances API.

---

### 1.2 Finances API

**Endpoint:** `GET /finances/v0/financialEvents`

**Rate limit:** 0.5 req/s, burst 30

**Tham số:**
- `PostedAfter` / `PostedBefore`: ISO8601 datetime (ngày refund được xử lý)
- `MaxResultsPerPage`: tối đa 100
- `NextToken`: phân trang

**Response — ShipmentEventList (đơn bình thường):**
```json
{
  "AmazonOrderId": "113-9240893-4241801",
  "PostedDate":    "2026-06-08T12:00:00Z",
  "ShipmentItemList": [
    {
      "ASIN":      "B0F9PGKBX2",
      "SellerSKU": "POSITIVEJAR_TURTLE",
      "QuantityShipped": 2,
      "ItemChargeList": [
        { "ChargeType": "Principal", "ChargeAmount": { "Amount": "27.98" } },
        { "ChargeType": "Tax",       "ChargeAmount": { "Amount": "0.00"  } }
      ],
      "ItemFeeList": [
        { "FeeType": "FBAPerUnitFulfillmentFee", "FeeAmount": { "Amount": "-6.20"  } },
        { "FeeType": "Commission",               "FeeAmount": { "Amount": "-4.20"  } }
      ],
      "PromotionList": []
    }
  ]
}
```

**Response — RefundEventList (trả hàng):**
```json
{
  "AmazonOrderId": "113-9083928-4094605",
  "PostedDate":    "2026-06-08T15:00:00Z",
  "ShipmentItemAdjustmentList": [
    {
      "ASIN":      "B0F9PGKBX2",
      "SellerSKU": "POSITIVEJAR_TURTLE",
      "QuantityShipped": 1,
      "ItemChargeAdjustmentList": [
        { "ChargeType": "Principal", "ChargeAmount": { "Amount": "-13.99" } }
      ],
      "ItemFeeAdjustmentList": [
        { "FeeType": "Commission",       "FeeAmount": { "Amount": "-1.09" } },
        { "FeeType": "RefundCommission", "FeeAmount": { "Amount":  "5.45" } }
      ]
    }
  ]
}
```

**Response — AdjustmentEventList (điều chỉnh):**
```json
{
  "AdjustmentType": "FBAInventoryReimbursement",
  "PostedDate":     "2026-06-08",
  "AdjustmentItemList": [
    {
      "SellerSKU":     "POSITIVEJAR_TURTLE",
      "Quantity":      "1",
      "PerUnitAmount": { "Amount": "-9.60" }
    }
  ]
}
```

**Các `AdjustmentType` quan trọng:**

| AdjustmentType | Ý nghĩa | Dấu |
|---|---|---|
| `FBAInventoryReimbursement` | Amazon bồi hoàn khi mất/hỏng hàng trong kho | ± |
| `FBADisposalFee` | Phí hủy hàng tồn kho | Âm |
| `FBAInboundTransportationFee` | Phí vận chuyển hàng vào kho | Âm |
| `FBAStorageFee` | Phí lưu kho | Âm |

**Thông số lấy được từ Finances API:**

| Thông số Sellerboard | FeeType / ChargeType | Dấu | Ghi chú |
|---|---|---|---|
| Sales (cross-check) | `Principal` trong ItemChargeList | Dương | Xác nhận với Orders API |
| FBA fulfillment fee | `FBAPerUnitFulfillmentFee` | Âm | Phí pick/pack/ship |
| Referral fee | `Commission` trong ItemFeeList | Âm | % hoa hồng Amazon |
| Compensated clawback | `AdjustmentType: FBAInventoryReimbursement` | ± | Amazon bồi khi mất hàng |
| FBA disposal fee | `AdjustmentType: FBADisposalFee` | Âm | Phí hủy tồn kho |
| Refunded amount | `Principal` trong ItemChargeAdjustmentList | Âm | Tiền hoàn cho khách |
| Refund commission | `Commission` trong ItemFeeAdjustmentList | Âm | Phí xử lý hoàn |
| Refunded referral fee | `RefundCommission` trong ItemFeeAdjustmentList | **DƯƠNG** | Amazon hoàn lại referral |

**Công thức Finances:**
```
Amazon fees  = FBA_fulfillment + Referral_fee + Clawback + Disposal
             = -193.33 + (-113.40) + (-9.60) + (-2.52)
             = -$318.85  ✓ (khớp Sellerboard ngày 08.06.2026)

Refund cost  = Refunded_amount + Refund_commission + Refunded_referral_fee
             = -32.96 + (-1.09) + 5.45
             = -$28.60  ✓
```

> ⚠️ **Key:** `RefundCommission` = **DƯƠNG** (+$5.45) — Amazon hoàn lại referral fee khi khách trả.
> Nhiều clone bỏ sót dòng này → Refund cost bị tính nặng hơn thực tế.

> ⚠️ **Return date:** Sellerboard gán return theo `PostedDate` trong `RefundEventList`
> (ngày refund được xử lý), **KHÔNG phải** ngày đặt hàng gốc.

---

### 1.3 Catalog Items API

**Endpoint:** `GET /catalog/2022-04-01/items/{asin}`

**Response:**
```json
{
  "asin": "B0F9PGKBX2",
  "summaries": [
    { "itemName": "Musemory 60 Positive Cards Turtle Jar...", "brandName": "Musemory" }
  ],
  "salesRanks": [
    {
      "classificationId": "...",
      "displayGroupRanks": [ { "rank": 53815, "link": "..." } ]
    }
  ],
  "images": [
    { "images": [ { "link": "https://...", "height": 500, "width": 500 } ] }
  ]
}
```

**Thông số lấy được:**

| Thông số Sellerboard | Field | Ghi chú |
|---|---|---|
| BSR | `salesRanks[].displayGroupRanks[].rank` | Best Seller Rank |
| Product title | `summaries[].itemName` | Tên sản phẩm |
| Product image | `images[].images[].link` | URL ảnh |

---

### 1.4 FBA Inventory API

**Endpoint:** `GET /fba/inventory/v1/summaries`

**Response:**
```json
{
  "inventorySummaries": [
    {
      "asin":                    "B0F9PGKBX2",
      "sellerSku":               "POSITIVEJAR_TURTLE",
      "totalQuantity":           438,
      "fulfillableQuantity":     420,
      "inboundWorkingQuantity":  18,
      "reservedQuantity": {
        "totalReservedQuantity": 0
      }
    }
  ]
}
```

**Thông số lấy được:**

| Thông số Sellerboard | Field | Ghi chú |
|---|---|---|
| FBA stock | `fulfillableQuantity` | Số lượng sẵn sàng bán |
| Inbound | `inboundWorkingQuantity` | Hàng đang về kho |

---

## 2. Amazon Advertising API (ADS-API)

ADS-API dùng hệ thống **Reports bất đồng bộ**: POST request → poll → download.

**Authentication:** Bearer LWA token — **KHÔNG cần AWS SigV4** (khác SP-API).

**Headers bắt buộc:**
```
Authorization:                   Bearer {lwa_access_token}
Amazon-Advertising-API-ClientId: {client_id}
Amazon-Advertising-API-Scope:    {profile_id}
Content-Type:                    application/json
```

**Base URL:** `https://advertising-api.amazon.com`

**profile_id:** ID tài khoản quảng cáo (khác seller_id). Lấy bằng `GET /v2/profiles`.

---

### 2.1 Profiles API

**Endpoint:** `GET /v2/profiles`

**Response:**
```json
[
  {
    "profileId":   1234567890,
    "countryCode": "US",
    "currencyCode":"USD",
    "accountInfo": {
      "marketplaceStringId": "ATVPDKIKX0DER",
      "id":                  "A2916R2QSTXQJC",
      "type":                "seller",
      "name":                "Musemory"
    }
  }
]
```

> Dùng `profileId` của account `type: "seller"` cho header `Amazon-Advertising-API-Scope`.

---

### 2.2 Sponsored Products (SP) Reports

**Flow:**
1. `POST /reporting/reports` → nhận `reportId`
2. `GET /reporting/reports/{reportId}` poll cho đến `status = COMPLETED`
3. Download từ `url` trong response → giải nén gzip → parse JSON

**Request body:**
```json
{
  "name":      "SP Daily 2026-06-08",
  "startDate": "2026-06-08",
  "endDate":   "2026-06-08",
  "configuration": {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
      "campaignId", "campaignName", "campaignStatus",
      "impressions", "clicks", "cost",
      "purchases1d",  "purchases7d",  "purchases14d",
      "sales1d",      "sales7d",      "sales14d",
      "unitsSoldClicks1d", "unitsSoldClicks7d"
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON"
  }
}
```

**Report body (sau khi download):**
```json
[
  {
    "campaignId":         "123456789",
    "campaignName":       "SP - POSITIVEJAR_TURTLE - Exact",
    "campaignStatus":     "ENABLED",
    "date":               "2026-06-08",
    "impressions":        5420,
    "clicks":             87,
    "cost":               166.79,
    "purchases1d":        19,
    "sales1d":            221.73,
    "unitsSoldClicks1d":  19,
    "purchases7d":        23,
    "sales7d":            268.40
  }
]
```

**Thông số lấy được từ SP:**

| Thông số Sellerboard | Field API | Ghi chú |
|---|---|---|
| Sponsored Products spend | `cost` | Tiền SP tiêu trong ngày |
| SP attributed sales (same day) | `sales1d` | Doanh thu gán cho SP click (1 ngày) |
| SP attributed units (same day) | `purchases1d` / `unitsSoldClicks1d` | Đơn gán cho SP |
| Clicks | `clicks` | |
| Impressions | `impressions` | |

> **"Same day" attribution** = `purchases1d` / `sales1d` (window 1 ngày)
> Sellerboard dùng `same day` cho cột Units/Sales attribution trong Products view.

---

### 2.3 Sponsored Brands (SB + SBV) Reports

**Request body (khác adProduct và reportTypeId):**
```json
{
  "configuration": {
    "adProduct":    "SPONSORED_BRANDS",
    "reportTypeId": "sbCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
      "campaignId", "campaignName", "campaignType",
      "campaignStatus", "impressions", "clicks", "cost",
      "purchases14d", "sales14d", "unitsSoldClicks14d"
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON"
  }
}
```

**Report body:**
```json
[
  {
    "campaignId":    "...",
    "campaignName":  "SBV - TURTLE JAR",
    "campaignType":  "sponsoredBrandsVideo",
    "cost":          12.47,
    "sales14d":      45.20,
    "purchases14d":  4
  },
  {
    "campaignId":    "...",
    "campaignName":  "SB - Brand Defense",
    "campaignType":  "sponsoredBrands",
    "cost":          0.00,
    "sales14d":      0.00
  }
]
```

**Phân biệt SB vs SBV:** dùng field `campaignType`:
- `sponsoredBrands` → SB spend
- `sponsoredBrandsVideo` → SBV spend

---

### 2.4 Sponsored Display (SD) Reports

```json
{
  "configuration": {
    "adProduct":    "SPONSORED_DISPLAY",
    "reportTypeId": "sdCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
      "campaignId", "campaignName", "campaignStatus",
      "impressions", "clicks", "cost",
      "purchases14d", "sales14d", "unitsSoldClicks14d"
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON"
  }
}
```

---

### 2.5 Tổng hợp Advertising Cost (verified ngày 08.06.2026)

```
Advertising cost = SP_cost + SBV_cost + SD_cost + SB_cost
                 = 166.79  + 12.47    + 0.00    + 0.00
                 = $179.26  ✓ (khớp Sellerboard)
```

---

## 3. Dữ liệu KHÔNG có trong API — Phải tự quản lý

| Thông số | Lưu ở đâu | Ghi chú |
|---|---|---|
| **Cost of Goods (COG) per SKU** | Bảng DB `product_cogs` | User nhập tay |
| **Indirect expenses** | Bảng DB `expenses` | Chi phí ngoài Amazon |
| **Active subscriptions (SnS)** | Subscribe & Save API (riêng) | Ít dùng |

**Schema gợi ý cho bảng COG:**
```sql
CREATE TABLE product_cogs (
    sku         VARCHAR PRIMARY KEY,
    cog         DECIMAL(10,2) NOT NULL DEFAULT 0,
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

> Sellerboard cho phép nhập nhiều mức COG theo thời gian (effective date).
> Clone có thể đơn giản hóa: 1 giá trị duy nhất per SKU.

---

## 4. Map toàn bộ thông số Dashboard → API Source

### 4.1 Order Items View (= file CSV export của Sellerboard)

| Cột CSV | Nguồn API | Công thức |
|---|---|---|
| Order number | Orders API | `AmazonOrderId` |
| Order date | Orders API | `PurchaseDate` |
| ASIN | Orders API (Items) | `ASIN` |
| SKU | Orders API (Items) | `SellerSKU` |
| Units | Orders API (Items) | `QuantityOrdered` |
| Sales | Orders API (Items) | `ItemPrice.Amount` |
| Promo | Orders API (Items) | `PromotionDiscount.Amount` |
| Amazon fees | Finances API | `FBA_fee + Commission + Adjustments` |
| Refund cost | Finances API | `Principal_adj + Commission_adj - RefundCommission` |
| Cost of Goods | DB | `cog_per_unit × QuantityOrdered` |
| Gross profit | Tính toán | `Sales + Amazon_fees + COG` |
| Expenses | DB | User-defined |
| Net profit | Tính toán | `Gross_profit + Expenses` |
| Margin | Tính toán | `Net_profit / Sales × 100` |
| ROI | Tính toán | `Net_profit / abs(COG) × 100` |

---

### 4.2 Products View (gộp theo SKU)

| Cột | Nguồn | Công thức |
|---|---|---|
| Units sold | Orders API | `SUM(QuantityOrdered)` cho SKU này |
| Refunds | Finances API | `COUNT(RefundEventList)` cho SKU này |
| Sales | Orders API | `SUM(ItemPrice.Amount)` |
| **Ads** | **Advertising API** | `SP + SBV + SD + SB` (gán theo ASIN/SKU) |
| Gross profit | Tính toán | `SUM(order_net_profits) + Ads` |
| Net profit | Tính toán | `Gross_profit + Indirect_expenses` |
| Margin | Tính toán | `Net_profit / Sales × 100` |
| ROI | Tính toán | `Net_profit / abs(COG_total) × 100` |
| BSR | Catalog API | `salesRanks[].displayGroupRanks[].rank` |
| Avg price | Tính toán | `Sales / Units` |

**Cross-check Products view — SKU POSITIVEJAR_TURTLE ngày 08.06.2026:**
```
Từ CSV (Order Items):
  Đơn bán: rows 2,10,19,39,42,45 → Net profits: 13.18+6.60+6.60+6.62+6.60+6.60 = 46.20
  Return:  row 63 → Net profit: -12.14
  SUM      = 46.20 - 12.14 = 34.06

  + Ads    = -18.55  (từ Advertising API)
  Gross profit = 34.06 - 18.55 = $15.51  ✓ (khớp Sellerboard Products view)
```

---

### 4.3 Daily Summary — Dashboard Card (verified 08.06.2026)

| Thông số | Nguồn | Công thức | Giá trị thực |
|---|---|---|---|
| Sales | Orders API | `SUM(ItemPrice)` ngày đó | $709.12 |
| Orders | Orders API | `COUNT(orders)` không đếm returns | 61 |
| Units | Orders API | `SUM(QuantityOrdered)` | 62 |
| Refunds | Finances API | `COUNT(RefundEventList)` theo `PostedDate` | 3 |
| Promo | Orders API | `SUM(PromotionDiscount)` | $0.00 |
| **Advertising cost** | **Ads API** | `-(SP + SBV + SD + SB)` | -$179.26 |
| Refund cost | Finances API | `SUM(refund_principal + commission - referral_back)` | -$28.60 |
| Amazon fees | Finances API | `SUM(FBA + Commission + Clawback + Disposal)` | -$318.85 |
| Cost of goods | DB + Orders | `SUM(cog_per_unit × qty)` | -$31.90 |
| Gross profit | Tính toán | `Sales + Adv + Refund + AmazonFees + COG` | $150.51 |
| Indirect expenses | DB | User-defined | $0.00 |
| Net profit | Tính toán | `Gross_profit + Indirect_expenses` | $150.51 |
| **Est. payout** | Tính toán | `Sales + Amazon_fees + Refund_cost + Adv_cost` | $182.41 |
| Real ACOS | Tính toán | `abs(Adv_cost) / Sales × 100` | 25.28% |
| % Refunds | Tính toán | `Refunds / Units × 100` | 4.84% |
| Margin | Tính toán | `Net_profit / Sales × 100` | 21.22% |
| ROI | Tính toán | `Net_profit / abs(COG) × 100` | 471.82% |

**Full cross-check ngày 08.06.2026:**
```
Gross profit = 709.12 + (-179.26) + (-28.60) + (-318.85) + (-31.90) = $150.51 ✓
Net profit   = 150.51 + 0 = $150.51 ✓
Est. payout  = 709.12 - 318.85 - 28.60 - 179.26 = $182.41 ✓  (không có COG)
Real ACOS    = 179.26 / 709.12 × 100 = 25.28% ✓
% Refunds    = 3 / 62 × 100 = 4.84% ✓
Margin       = 150.51 / 709.12 × 100 = 21.22% ✓
ROI          = 150.51 / 31.90 × 100 = 471.82% ✓
```

---

### 4.4 Sales Attribution (Units Breakdown)

| Loại | Units | Sales | Nguồn |
|---|---|---|---|
| Organic | 43 | $487.39 | Tổng SP-API − SP attributed |
| Sponsored Products (same day) | 19 | $221.73 | `purchases1d` từ Ads API |
| Sponsored Display (same day) | 0 | $0.00 | `purchases1d` SD |
| **Direct units** | **62** | **$709.12** | Tổng SP-API |

```
Organic units  = Direct_units - SP_attributed_units - SD_attributed_units
               = 62 - 19 - 0 = 43  ✓

Organic sales  = Direct_sales - SP_attributed_sales - SD_attributed_sales
               = 709.12 - 221.73 - 0 = $487.39  ✓
```

---

## 5. Amazon fees — 4 thành phần chi tiết

```
Amazon fees = FBA_fulfillment + Referral_fee + Compensated_clawback + FBA_disposal
            = (-193.33) + (-113.40) + (-9.60) + (-2.52)
            = -$318.85  ✓
```

| Phí | FeeType / AdjustmentType | Ý nghĩa |
|---|---|---|
| FBA fulfillment | `FBAPerUnitFulfillmentFee` | Phí Amazon pick/pack/ship |
| Referral fee | `Commission` trong ItemFeeList | % hoa hồng (8-15% tùy category) |
| Compensated clawback | `FBAInventoryReimbursement` | Amazon bồi khi mất/hỏng hàng trong kho |
| FBA disposal | `FBADisposalFee` | Phí hủy hàng tồn kho theo yêu cầu |

---

## 6. Refund cost — 3 thành phần chi tiết

```
Refund cost = Refunded_amount + Refund_commission + Refunded_referral_fee
            = (-32.96) + (-1.09) + (+5.45)
            = -$28.60  ✓
```

| Thành phần | ChargeType / FeeType | Dấu | Ý nghĩa |
|---|---|---|---|
| Refunded amount | `Principal` trong ItemChargeAdjustmentList | Âm | Tiền hoàn lại cho khách |
| Refund commission | `Commission` trong ItemFeeAdjustmentList | Âm | Phí xử lý hoàn hàng |
| Refunded referral fee | `RefundCommission` trong ItemFeeAdjustmentList | **DƯƠNG** | Amazon trả lại referral fee |

> **Lưu ý:** `Refunded_referral_fee` là **dương** — không phải chi phí mà là khoản được hoàn lại.
> Clone bỏ sót dòng này → Refund cost bị tính âm hơn $5.45.

---

## 7. Est. Payout — Giải thích

```
Est. payout = Sales + Amazon_fees + Refund_cost + Advertising_cost
            = 709.12 - 318.85 - 28.60 - 179.26
            = $182.41  ✓
```

> **Tại sao không có COG?**
> COG bạn trả cho supplier trực tiếp — Amazon không liên quan.
> Amazon chỉ deposit/deduct: doanh thu − phí của họ − hoàn tiền − chi phí quảng cáo.

---

## 8. Nguyên nhân sai lệch clone vs Sellerboard

| # | Vấn đề | Ảnh hưởng số liệu | Mức độ ưu tiên |
|---|---|---|---|
| 1 | **Chưa call Ads API** | Net profit cao hơn ~$179/ngày | 🔴 Cao |
| 2 | **Bỏ qua `RefundCommission` (+$5.45)** | Refund cost nặng hơn thực | 🟡 Trung bình |
| 3 | **COG = 0 nhiều SKU** | Gross profit cao hơn ~$31/ngày | 🟡 Trung bình |
| 4 | **Return date dùng ngày order gốc** | Count refund sai ngày | 🟡 Trung bình |
| 5 | **Units attribution không tính Ads** | Organic/SP units sai | 🟢 Thấp (cosmetic) |

---

## 9. Thứ tự call API để build dữ liệu 1 ngày

```
Bước 1: Orders API
        GET /orders/v0/orders  (filter CreatedAfter/Before)
        GET /orders/v0/orders/{id}/orderItems  (mỗi order 1 call)
        → Lấy: OrderId, date, ASIN, SKU, Units, Sales, Promo

Bước 2: Finances API
        GET /finances/v0/financialEvents  (filter PostedAfter/Before)
        → Parse ShipmentEventList     (FBA fee, Referral fee)
        → Parse RefundEventList        (Refund cost, dùng PostedDate)
        → Parse AdjustmentEventList    (Clawback, Disposal)
        → Parse ServiceFeeEventList    (phí khác)

Bước 3: Advertising API  ← cần profile_id riêng, không cần AWS SigV4
        POST /reporting/reports  (SP campaigns)
        POST /reporting/reports  (SP advertised product — theo ASIN)
        POST /reporting/reports  (SB campaigns — phân biệt SB vs SBV)
        POST /reporting/reports  (SD campaigns)
        Poll GET /reporting/reports/{id} cho đến COMPLETED
        Download → decompress gzip → parse JSON

Bước 4: DB lookup
        Lấy COG per SKU từ bảng product_cogs
        Lấy indirect expenses

Bước 5: Catalog API (optional, không cần realtime)
        GET /catalog/2022-04-01/items/{asin}
        → BSR, product image (có thể cache, không cần mỗi ngày)

Bước 6: FBA Inventory API (optional)
        GET /fba/inventory/v1/summaries
        → FBA stock count

Bước 7: Tính toán & tổng hợp
        → Order Items view (theo từng đơn)
        → Products view (gộp theo SKU + Ads)
        → Daily summary (dashboard card)
```

---

## 10. SP-API Rate Limits tham khảo

| Endpoint | Rate limit | Burst | Ghi chú |
|---|---|---|---|
| GET /orders/v0/orders | 0.0167 req/s | 20 | ~1 req/60s |
| GET /orders/{id}/orderItems | 0.5 req/s | 30 | Sleep 1s giữa các lần |
| GET /finances/v0/financialEvents | 0.5 req/s | 30 | |
| GET /catalog/items | 2 req/s | 2 | |
| GET /fba/inventory/summaries | 2 req/s | 2 | |

> Ads API Reports không có rate limit cứng nhưng mỗi report mất **1-5 phút** để generate.
> Gửi tất cả request tạo report TRƯỚC, sau đó poll song song thay vì request-wait-request.
