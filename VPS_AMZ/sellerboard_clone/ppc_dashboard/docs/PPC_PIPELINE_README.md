# PPC Dashboard — Pipeline Documentation

## Tổng quan

Pipeline PPC độc lập với Profit Dashboard:
- Không chạm code Phase1/Phase2/Phase3 hiện tại
- Bảng Supabase riêng biệt (prefix `PPC_*`)
- Import shared utilities từ `sellerboard_clone/shared/`

## Cấu trúc

```
ppc_dashboard/
├── Phase1_PPC_Ingestion/
│   ├── amz_ads_ppc_client.py   ← Ads API v3 client (reports + mgmt API)
│   ├── db_writer.py            ← Transform raw -> PPC_* Supabase tables
│   ├── run_ppc_ingest.py       ← Entry point Phase 1
│   ├── .env.example
│   └── requirements.txt
├── Phase2_PPC_Transform/
│   ├── calc_derived_metrics.py ← ACOS, CVR, CPC, topOfSearch%, BE-Bid...
│   ├── transform_campaigns.py
│   ├── transform_adgroups.py
│   ├── transform_keywords.py
│   ├── transform_searchterms.py
│   ├── transform_portfolios.py
│   ├── db_schema.sql           ← CREATE TABLE statements (chạy 1 lần)
│   └── run_ppc_transform.py    ← Entry point Phase 2
└── docs/
    └── PPC_PIPELINE_README.md  (file này)
```

## Setup lần đầu

### 1. Tạo bảng Supabase
Chạy `Phase2_PPC_Transform/db_schema.sql` trên Supabase SQL Editor.

### 2. Tạo file .env
```bash
cp Phase1_PPC_Ingestion/.env.example Phase1_PPC_Ingestion/.env
# Điền AMAZON_ADS_*, ADS_PROFILE_ID, SUPABASE_*
```

### 3. Cài dependencies
```bash
pip install -r Phase1_PPC_Ingestion/requirements.txt
```

## Lệnh chạy

### Phase 1 — Ingest (user tự chạy)

```bash
cd sellerboard_clone/ppc_dashboard/Phase1_PPC_Ingestion

# Chạy tất cả (reports + mgmt snapshot + bid recommendations) cho hôm qua
python run_ppc_ingest.py --all

# Chỉ lấy daily metrics cho 1 ngày cụ thể
python run_ppc_ingest.py --reports --date 2026-06-15

# Lấy khoảng ngày
python run_ppc_ingest.py --reports --from 2026-06-01 --to 2026-06-15

# Chỉ cập nhật management snapshot (campaigns/keywords/portfolios hiện tại)
python run_ppc_ingest.py --mgmt

# Chỉ lấy bid recommendations (cần chạy --mgmt trước để có keyword_ids)
python run_ppc_ingest.py --bid-recs
```

### Phase 2 — Transform (user tự chạy)

```bash
cd sellerboard_clone/ppc_dashboard/Phase2_PPC_Transform

# Transform 1 ngày
python run_ppc_transform.py --date 2026-06-15

# Transform 7 ngày gần nhất
python run_ppc_transform.py --days 7

# Transform khoảng ngày
python run_ppc_transform.py --from 2026-06-01 --to 2026-06-15

# Chỉ log, không ghi DB (kiểm tra)
python run_ppc_transform.py --date 2026-06-15 --no-write
```

## Workflow điển hình (hàng ngày)

```
1. python run_ppc_ingest.py --reports          # lấy metrics hôm qua
2. python run_ppc_ingest.py --mgmt             # cập nhật trạng thái hiện tại
3. python run_ppc_ingest.py --bid-recs         # bid recommendations
4. python run_ppc_transform.py                 # transform hôm qua
```

## Nguồn dữ liệu API

| Data | API | Endpoint |
|------|-----|----------|
| Campaign metrics | Ads Reports API v3 | POST /reporting/reports (spCampaigns) |
| Ad Group metrics | Ads Reports API v3 | POST /reporting/reports (spAdGroups) |
| Keyword metrics | Ads Reports API v3 | POST /reporting/reports (spKeywords) |
| Target metrics | Ads Reports API v3 | POST /reporting/reports (spTargeting) |
| Search Term metrics | Ads Reports API v3 | POST /reporting/reports (spSearchTerm) |
| Placement breakdown | Ads Reports API v3 | spCampaigns với segment=placement |
| Campaign status/budget | Campaign Mgmt API | GET /sp/campaigns |
| Keyword bid | Campaign Mgmt API | GET /sp/keywords |
| Bid recommendations | Campaign Mgmt API | POST /sp/keywords/bidRecommendations |
| Portfolios | Portfolio API | GET /portfolios |

## Mapping cột Sellervision PPC CSV -> bảng Supabase

| CSV Column | Nguồn | Bảng PPC_* |
|------------|-------|------------|
| Name | API name field | campaigns/adgroups/keywords_raw.name |
| Status | Campaign Mgmt API | campaigns_raw.state |
| Ad spend | Report metrics | *_daily.cost |
| Clicks | Report metrics | *_daily.clicks |
| Impressions | Report metrics | *_daily.impressions |
| Orders | purchases_14d | summary_*.orders |
| Units | units_sold_14d | summary_*.units |
| PPC sales | sales_14d | summary_*.sales_14d |
| Same SKU | attributedSalesSameSku14d | summary_*.same_sku_pct |
| Conversion | purchases/clicks | summary_*.cvr |
| CPC | cost/clicks | summary_*.cpc |
| ACOS | cost/sales*100 | summary_*.acos |
| Profit | Cần COGS (từ NEW_product_cogs) | — (Phase 3) |
| topOfSearch% | Placement report | summary_campaigns.top_of_search_pct |
| dailyBudget | Campaign Mgmt API | campaigns_raw.daily_budget |
| BudgetUtilization | cost/budget*100 | summary_campaigns.budget_utilization |
| Break even ACOS | (ASP-COGS-Ref)/ASP*100 | summary_keywords.break_even_acos |
| Break-Even-Bid | BE_ACOS * CPC / ACOS | summary_keywords.break_even_bid |
| Current bid | Campaign Mgmt API | keywords_raw.bid |
| Bid recommendation | Bid Recs API | bid_recommendations.suggested_bid |
| Strategy | ⚠️ Sellervision-only | NULL (không có từ API) |
| Automation status | ⚠️ Sellervision-only | NULL (không có từ API) |

**Ghi chú:** `Strategy` và `Automation status` là tính năng riêng của Sellervision
(rules engine nội bộ), không có trong Amazon API.

## Timezone

- report_date: Pacific (America/Los_Angeles), tự động DST (UTC-7/UTC-8)
- synced_at: UTC (TIMESTAMPTZ)
- Ads report_date từ Amazon ĐÃ là Pacific — không quy đổi lần 2

## Memory-safety

- Mỗi report download xong: upsert ngay, `del data`, `gc.collect()`
- Phân trang management API: <=100 records/lần, upsert từng batch
- Không accumulate list lớn trong RAM
