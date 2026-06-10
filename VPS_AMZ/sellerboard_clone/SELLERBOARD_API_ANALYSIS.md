# Sellerboard Clone — Phân tích API & Thông số

> Mục đích: Tài liệu tham chiếu toàn diện để clone các thông số Sellerboard.
> Cấu trúc: SP-API → ADS-API → Map thông số → Dashboard formula.

---

## 1. SP-API (Selling Partner API)

SP-API gồm nhiều endpoint con. Với Sellerboard, ta cần 3 nhóm chính:

---

### 1.1 Orders API

**Endpoint:** `GET /orders/v0/orders` + `GET /orders/v0/orders/{orderId}/orderItems`

**Response trả về (Orders):**
```json
{
  "AmazonOrderId": "113-9240893-4241801",
  "PurchaseDate": "2026-06-08T08:43:00Z",
  "LastUpdateDate": "2026-06-08T09:10:00Z",
  "OrderStatus": "Shipped",            // Unshipped | Shipped | Canceled | Pending
  "FulfillmentChannel": "AFN",          // AFN=FBA, MFN=FBM
  "SalesChannel": "Amazon.com",
  "NumberOfItemsShipped": 2,
  "NumberOfItemsUnshipped": 0,
  "OrderTotal": {
    "CurrencyCode": "USD",
    "Amount": "27.98"
  },
  "BuyerInfo": { "BuyerEmail": "..." },
  "IsReplacementOrder": false,
  "PaymentMethod": "Other"
}
```

**Response trả về (Order Items):**
```json
{
  "ASIN": "B0F9PGKBX2",
  "SellerSKU": "POSITIVEJAR_TURTLE",
  "Title": "Musemory 60 Positive Cards Turtle Jar...",
  "QuantityOrdered": 2,
  "QuantityShipped": 2,
  "ItemPrice": { "Amount": "27.98", "CurrencyCode": "USD" },
  "ItemTax": { "Amount": "0.00", "CurrencyCode": "USD" },
  "PromotionDiscount": { "Amount": "0.00", "CurrencyCode": "USD" },
  "PromotionDiscountTax": { "Amount": "0.00" },
  "IsGift": false,
  "ConditionId": "New"
}
```

**Thông số lấy được từ Orders API:**

| Thông số Sellerboard | Field trong API | Công thức |
|---|---|---|
| Order number | `AmazonOrderId` | Raw |
| Order date | `PurchaseDate` | Parse ISO8601 → date |
| Status | `OrderStatus` | Shipped/Unshipped/Canceled |
| FBA/FBM | `FulfillmentChannel` | AFN=FBA, MFN=FBM |
| ASIN | `ASIN` (từ orderItems) | Raw |
| SKU | `SellerSKU` (từ orderItems) | Raw |
| Units | `QuantityOrdered` | Raw |
| Sales | `ItemPrice.Amount` | Raw (= Price × Units) |
| Promo | `PromotionDiscount.Amount` | Raw (âm nếu có) |

> ⚠️ **Orders API KHÔNG có:** Amazon fees, COG, Refund data — phải lấy từ Finances API.

---

### 1.2 Finances API

**Endpoint:** `GET /finances/v0/financialEvents` (theo date range)
hoặc `GET /finances/v0/orders/{orderId}/financialEvents` (theo order)

**Response trả về — ShipmentEventList (đơn hàng bình thường):**
```json
{
  "ShipmentEventList": [
    {
      "AmazonOrderId": "113-9240893-4241801",
      "PostedDate": "2026-06-08T12:00:00Z",
      "ShipmentItemList": [
        {
          "ASIN": "B0F9PGKBX2",
          "SellerSKU": "POSITIVEJAR_TURTLE",
          "QuantityShipped": 2,
          "ItemChargeList": [
            { "ChargeType": "Principal", "ChargeAmount": { "Amount": "27.98" } },
            { "ChargeType": "Tax",       "ChargeAmount": { "Amount": "0.00"  } }
          ],
          "ItemFeeList": [
            { "FeeType": "FBAPerUnitFulfillmentFee", "FeeAmount": { "Amount": "-6.20" } },
            { "FeeType": "Commission",               "FeeAmount": { "Amount": "-4.20" } }
          ],
          "PromotionList": [
            { "PromotionType": "...", "PromotionAmount": { "Amount": "0.00" } }
          ]
        }
      ]
    }
  ]
}
```

**Response trả về — RefundEventList (đơn trả hàng):**
```json
{
  "RefundEventList": [
    {
      "AmazonOrderId": "113-9083928-4094605",
      "PostedDate": "2026-06-08T15:00:00Z",   // ← ngày REFUND được xử lý
      "ShipmentItemAdjustmentList": [
        {
          "ASIN": "B0F9PGKBX2",
          "SellerSKU": "POSITIVEJAR_TURTLE",
          "QuantityShipped": 1,
          "ItemChargeAdjustmentList": [
            { "ChargeType": "Principal", "ChargeAmount": { "Amount": "-13.99" } }  // hoàn tiền cho khách
          ],
          "ItemFeeAdjustmentList": [
            { "FeeType": "Commission",            "FeeAmount": { "Amount": "-1.09" } },  // phí hoàn hàng
            { "FeeType": "RefundCommission",      "FeeAmount": { "Amount": "5.45"  } }   // refund referral fee (DƯƠNG)
          ]
        }
      ]
    }
  ]
}
```

**Response trả về — AdjustmentEventList (phí điều chỉnh):**
```json
{
  "AdjustmentEventList": [
    {
      "AdjustmentType": "FBAInventoryReimbursement",   // = Compensated clawback
      "PostedDate": "2026-06-08",
      "AdjustmentItemList": [
        {
          "SellerSKU": "...",
          "Quantity": "1",
          "PerUnitAmount": { "Amount": "-9.60" }       // Amazon bồi hoàn khi mất hàng
        }
      ]
    },
    {
      "AdjustmentType": "FBADisposalFee",              // phí hủy hàng
      "AdjustmentItemList": [
        { "PerUnitAmount": { "Amount": "-2.52" } }
      ]
    }
  ]
}
```

**Thông số lấy được từ Finances API:**

| Thông số Sellerboard | ChargeType / FeeType | Ghi chú |
|---|---|---|
| Sales (cross-check) | `Principal` trong ItemChargeList | Xác nhận với Orders API |
| FBA fulfillment fee | `FBAPerUnitFulfillmentFee` | Âm |
| Referral fee | `Commission` trong ItemFeeList | Âm |
| Compensated clawback | `AdjustmentType: FBAInventoryReimbursement` | Amazon bồi khi mất/hỏng |
| FBA disposal fee | `AdjustmentType: FBADisposalFee` | Phí hủy hàng tồn |
| Refunded amount | `Principal` trong ItemChargeAdjustmentList | Âm (tiền hoàn cho khách) |
| Refund commission | `Commission` trong ItemFeeAdjustmentList | Âm |
| Refunded referral fee | `RefundCommission` trong ItemFeeAdjustmentList | **DƯƠNG** — Amazon hoàn lại |

**Công thức Finances:**
```
Amazon fees    = FBA_fulfillment + Referral + Clawback + Disposal
               = -193.33 + (-113.40) + (-9.60) + (-2.52) = -$318.85

Refund cost    = Refunded_amount + Refund_commission + Refunded_referral_fee
               = -32.96 + (-1.09) + 5.45 = -$28.60
```

> ⚠️ **Key:** `RefundCommission` là **dương** — nhiều clone bỏ sót làm Refund cost nặng hơn thực tế.

> ⚠️ **Return date:** Sellerboard gán return theo `PostedDate` trong `RefundEventList` (ngày refund được xử lý), **KHÔNG phải** ngày đặt hàng gốc.

---

### 1.3 Catalog Items API

**Endpoint:** `GET /catalog/2022-04-01/items/{asin}`

**Response trả về:**
```json
{
  "asin": "B0F9PGKBX2",
  "summaries": [{ "itemName": "Musemory 60 Positive...", "brandName": "Musemory" }],
  "salesRanks": [
    { "classificationId": "...", "displayGroupRanks": [{ "rank": 53815 }] }
  ],
  "images": [{ "images": [{ "link": "https://...", "height": 500, "width": 500 }] }]
}
```

**Thông số lấy được:**

| Thông số Sellerboard | Field | Ghi chú |
|---|---|---|
| BSR | `salesRanks[].displayGroupRanks[].rank` | Best Seller Rank |
| Product title | `summaries[].itemName` | |
| Product image | `images[].images[].link` | |

---

### 1.4 FBA Inventory API

**Endpoint:** `GET /fba/inventory/v1/summaries`

**Response trả về:**
```json
{
  "inventorySummaries": [
    {
      "asin": "B0F9PGKBX2",
      "sellerSku": "POSITIVEJAR_TURTLE",
      "totalQuantity": 438,
      "fulfillableQuantity": 420,
      "inboundWorkingQuantity": 18,
      "reservedQuantity": { "totalReservedQuantity": 0 }
    }
  ]
}
```

**Thông số lấy được:**

| Thông số Sellerboard | Field | Ghi chú |
|---|---|---|
| FBA stock | `fulfillableQuantity` | Số lượng có thể bán |
| Inbound | `inboundWorkingQuantity` | Hàng đang về kho |

---

## 2. Amazon Advertising API (ADS-API)

ADS-API dùng hệ thống **Reports** (bất đồng bộ): request → poll → download CSV/JSON.

**Authentication:** Khác SP-API — cần thêm `profile_id` (ID tài khoản quảng cáo).

**Base URL:** `https://advertising-api.amazon.com`

---

### 2.1 Sponsored Products (SP) Reports

**Endpoint:** `POST /reporting/reports` (v3)

**Request body:**
```json
{
  "name": "SP Daily Report",
  "startDate": "2026-06-08",
  "endDate": "2026-06-08",
  "configuration": {
    "adProduct": "SPONSORED_PRODUCTS",
    "groupBy": ["campaign", "adGroup", "targeting"],
    "columns": [
      "campaignId", "campaignName",
      "adGroupId", "adGroupName",
      "impressions", "clicks", "cost",
      "purchases1d", "purchases7d", "purchases14d", "purchases30d",
      "purchasesSameSku1d", "purchasesSameSku7d",
      "sales1d", "sales7d", "sales14d", "sales30d",
      "unitsSoldClicks1d", "unitsSoldClicks7d"
    ],
    "reportTypeId": "spCampaigns",
    "timeUnit": "DAILY",
    "format": "GZIP_JSON"
  }
}
```

**Response trả về (sau khi download):**
```json
[
  {
    "campaignId": "123456789",
    "campaignName": "SP - POSITIVEJAR_TURTLE - Exact",
    "adGroupId": "987654321",
    "date": "2026-06-08",
    "impressions": 5420,
    "clicks": 87,
    "cost": 166.79,
    "purchases1d": 19,
    "purchases7d": 23,
    "sales1d": 221.73,
    "sales7d": 268.40,
    "unitsSoldClicks1d": 19,
    "unitsSoldClicks7d": 23
  }
]
```

**Thông số lấy được từ SP:**

| Thông số Sellerboard | Field API | Ghi chú |
|---|---|---|
| Sponsored Products spend | `cost` | Tiền quảng cáo SP tiêu trong ngày |
| SP attributed sales (same day) | `sales1d` | Doanh thu được gán cho SP trong 1 ngày |
| SP attributed units (same day) | `purchases1d` / `unitsSoldClicks1d` | Đơn được gán cho SP click |
| Clicks | `clicks` | |
| Impressions | `impressions` | |

**Công thức ACOS:**
```
ACOS = cost / sales1d × 100
```

---

### 2.2 Sponsored Brands Video (SBV) Reports

**Request body (khác adProduct):**
```json
{
  "configuration": {
    "adProduct": "SPONSORED_BRANDS",
    "reportTypeId": "sbPurchasedProduct",    // hoặc sbCampaigns
    "columns": ["cost", "sales14d", "purchases14d", "impressions", "clicks"]
  }
}
```

**Response trả về:**
```json
[
  {
    "campaignId": "...",
    "campaignType": "sponsoredBrandsVideo",
    "cost": 12.47,
    "sales14d": 45.20,
    "purchases14d": 4,
    "impressions": 8900,
    "clicks": 23
  }
]
```

**Thông số lấy được:**

| Thông số Sellerboard | Field | Ghi chú |
|---|---|---|
| Sponsored Brands Video spend | `cost` (khi `campaignType = sponsoredBrandsVideo`) | -$12.47 |
| Sponsored Brands spend | `cost` (khi `campaignType = sponsoredBrands`) | -$0.00 |

---

### 2.3 Sponsored Display (SD) Reports

```json
{
  "configuration": {
    "adProduct": "SPONSORED_DISPLAY",
    "columns": ["cost", "sales14d", "purchases14d"]
  }
}
```

**Thông số lấy được:**

| Thông số | Field | Ngày 8/6 |
|---|---|---|
| SD spend | `cost` | $0.00 |
| SD attributed sales | `sales14d` | $0.00 |

---

### 2.4 Tổng hợp Advertising Cost

```
Advertising cost = -(SP_cost + SBV_cost + SD_cost + SB_cost)
                 = -(166.79 + 12.47 + 0 + 0)
                 = -$179.26 ✓
```

---

## 3. Dữ liệu KHÔNG có trong API — Phải tự quản lý

| Thông số | Lưu ở đâu | Ghi chú |
|---|---|---|
| **Cost of Goods (COG) per SKU** | DB tự quản (bảng `products`) | User nhập tay, có thể thay đổi theo thời gian |
| **Indirect expenses** | DB tự quản (bảng `expenses`) | Chi phí ngoài Amazon: warehouse, nhân công... |
| **Active subscriptions (SnS)** | Subscribe & Save API (riêng) | Ít dùng |

---

## 4. Map toàn bộ Dashboard → API Source

### 4.1 Order Items View (= file CSV)

| Cột CSV | Nguồn API | Công thức |
|---|---|---|
| Order number | Orders API | `AmazonOrderId` |
| Order date | Orders API | `PurchaseDate` |
| ASIN | Orders API (Items) | `ASIN` |
| SKU | Orders API (Items) | `SellerSKU` |
| Units | Orders API (Items) | `QuantityOrdered` |
| Sales | Orders API (Items) | `ItemPrice.Amount` |
| Promo | Orders API (Items) | `PromotionDiscount.Amount` |
| Amazon fees | Finances API | `FBAPerUnitFulfillmentFee + Commission + Adjustments` |
| Refund cost | Finances API | `RefundEventList` → `Principal + Commission - RefundCommission` |
| Cost of Goods | DB | `cog_per_unit × QuantityOrdered` |
| Gross profit | Tính toán | `Sales + Amazon_fees + COG` |
| Expenses | DB | User-defined |
| Net profit | Tính toán | `Gross_profit + Expenses` |
| Margin | Tính toán | `Net_profit / Sales × 100` |
| ROI | Tính toán | `Net_profit / abs(COG) × 100` |

### 4.2 Products View

| Cột | Nguồn | Công thức |
|---|---|---|
| Units sold | Orders API | `SUM(QuantityOrdered)` cho SKU này |
| Refunds | Finances API | `COUNT(RefundEventList)` cho SKU này |
| Sales | Orders API | `SUM(ItemPrice.Amount)` |
| **Ads** | **Advertising API** | SP_cost + SBV_cost + SD_cost + SB_cost (gán theo ASIN) |
| Gross profit | Tính toán | `SUM(order_net_profits) + Ads` |
| Net profit | Tính toán | `Gross_profit + Indirect_expenses` |
| Margin | Tính toán | `Net_profit / Sales × 100` |
| ROI | Tính toán | `Net_profit / abs(COG_total) × 100` |
| BSR | Catalog API | `salesRanks[].rank` |
| Avg price | Tính toán | `Sales / Units` |

### 4.3 Daily Summary (Dashboard Card)

| Thông số | Nguồn | Công thức |
|---|---|---|
| Sales | Orders API | `SUM(Sales)` ngày đó |
| Orders | Orders API | `COUNT(orders)` (không đếm returns) |
| Units | Orders API | `SUM(QuantityOrdered)` |
| Refunds | Finances API | `COUNT(RefundEventList)` gán theo `PostedDate` |
| Promo | Orders API | `SUM(PromotionDiscount)` |
| **Advertising cost** | **Ads API** | `-(SP + SBV + SD + SB)` |
| Refund cost | Finances API | `SUM(refund_amount + refund_commission - refund_referral_fee)` |
| Amazon fees | Finances API | `SUM(FBA + Commission + Clawback + Disposal)` |
| Cost of goods | DB + Orders | `SUM(cog_per_unit × qty)` |
| Gross profit | Tính toán | `Sales + Adv_cost + Refund_cost + Amazon_fees + COG` |
| Indirect expenses | DB | User-defined |
| Net profit | Tính toán | `Gross_profit + Indirect_expenses` |
| **Est. payout** | Tính toán | `Sales + Amazon_fees + Refund_cost + Adv_cost` ← không có COG |
| Real ACOS | Tính toán | `abs(Adv_cost) / Sales × 100` |
| % Refunds | Tính toán | `Refunds / Units × 100` |
| Margin | Tính toán | `Net_profit / Sales × 100` |
| ROI | Tính toán | `Net_profit / abs(COG) × 100` |

**Cross-check ngày 8/6/2026:**
```
Sales          = $709.12
Adv cost       = -$179.26  (SP -166.79 + SBV -12.47)
Refund cost    = -$28.60   (-32.96 - 1.09 + 5.45)
Amazon fees    = -$318.85  (-193.33 - 113.40 - 9.60 - 2.52)
COG            = -$31.90
Gross profit   = 709.12 - 179.26 - 28.60 - 318.85 - 31.90 = $150.51 ✓
Net profit     = $150.51 ✓
Est. payout    = 709.12 - 318.85 - 28.60 - 179.26 = $182.41 ✓
Real ACOS      = 179.26 / 709.12 × 100 = 25.28% ✓
Margin         = 150.51 / 709.12 × 100 = 21.22% ✓
ROI            = 150.51 / 31.90 × 100  = 471.82% ✓
% Refunds      = 3 / 62 × 100          = 4.84% ✓
```

---

## 5. Thứ tự Call API để build 1 ngày dữ liệu

```
Bước 1: Orders API
        → Lấy tất cả orders trong ngày (PurchaseDate filter)
        → Lấy orderItems cho từng order

Bước 2: Finances API
        → Lấy financialEvents theo date range
        → Parse ShipmentEventList (fees cho đơn bình thường)
        → Parse RefundEventList (refund events, dùng PostedDate)
        → Parse AdjustmentEventList (clawback, disposal)

Bước 3: Advertising API  ← cần profile_id riêng
        → Request reports SP + SB + SD (async)
        → Poll đến khi status = COMPLETED
        → Download và parse

Bước 4: DB lookup
        → Lấy COG per SKU từ bảng products
        → Lấy indirect expenses

Bước 5: Tính toán
        → Tổng hợp theo order (Order Items view)
        → Tổng hợp theo SKU (Products view)
        → Tổng hợp theo ngày (Dashboard card)
```

---

## 6. Lưu ý kỹ thuật quan trọng

### SP-API Rate Limits
| Endpoint | Rate limit | Burst |
|---|---|---|
| GET /orders | 0.0167 req/s (1 req/60s) | 20 |
| GET /orderItems | 0.5 req/s | 30 |
| GET /financialEvents | 0.5 req/s | 30 |

### Ads API Reports (Async)
- Request report → nhận `reportId`
- Poll `GET /reporting/reports/{reportId}` cho đến `status = COMPLETED`
- Download từ `url` trong response
- Thời gian: thường 1-5 phút cho báo cáo ngày hôm trước

### Advertising Attribution Window
- **"Same day"** = `purchases1d` / `sales1d` → attribution window 1 ngày
- Sellerboard dùng `same day` cho Units/Sales attribution trong Products view
- `purchases7d`, `purchases14d` = dùng cho ACOS tracking dài hạn

### COG per SKU — Thiết kế DB
```sql
CREATE TABLE product_cogs (
    sku         VARCHAR PRIMARY KEY,
    cog         DECIMAL(10,2) NOT NULL DEFAULT 0,
    updated_at  TIMESTAMP DEFAULT NOW()
);
```
> Sellerboard cho phép nhập nhiều COG theo thời gian (effective date) để tính chính xác khi giá vốn thay đổi. Clone có thể đơn giản hóa bằng 1 giá trị duy nhất.
