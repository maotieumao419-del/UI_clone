# Phase1_Fetch — Tầng gọi API dùng chung (Landing Zone)

Gọi Amazon API **1 LẦN DUY NHẤT** cho cả `profit_dashboard` lẫn `ppc_dashboard`,
lưu toàn bộ raw response vào `data/` dạng JSON.gz làm **backup**. Sau đó mỗi
dashboard chạy `Phase1_Upload` riêng để đẩy lên bảng Supabase của mình — **không
gọi lại API**.

## Tại sao tách Fetch ↔ Upload?

```
TRƯỚC:  Amazon API ──stream trực tiếp──► Supabase   (lỗi = mất data, gọi lại API)

SAU:    Amazon API ──fetch──► data/*.json.gz ──upload──► Supabase
                              (backup bất biến)
```

- **Replay không tốn quota**: schema đổi / bug upload → chạy lại upload từ file, không gọi API.
- **Gọi API 1 lần**: `spCampaigns` cả 2 dashboard đều cần → 1 file, 2 upload đọc chung.
- **Disaster recovery**: Supabase sự cố vẫn còn raw local.
- **Debug dễ**: mở thẳng file `.json.gz`.

## Cấu trúc

```
Phase1_Fetch/
├── fetch_spapi.py          SP-API: Orders (+items) + Finances
├── fetch_ads_reports.py    Ads Reports: 9 report types (SP/SB/SD + placement)
├── fetch_ads_mgmt.py       Ads Mgmt snapshot: campaigns/adgroups/keywords/targets/portfolios
├── fetch_bid_recs.py       Bid recommendations (cần mgmt trước)
├── ads_report_configs.py   Định nghĩa tất cả report config 1 nơi
├── paths.py                Helper định vị file (upload scripts import)
├── run_fetch.py            Orchestrator gọi tất cả
├── .env.example            CHỈ Amazon credentials (không cần Supabase)
└── data/                   Raw JSON.gz (KHÔNG commit — xem .gitignore)
    ├── orders/YYYY-MM-DD_orders.jsonl.gz
    ├── finances/YYYY-MM-DD_finances.jsonl.gz
    ├── ads_reports/YYYY-MM-DD_<report>.json.gz
    └── ads_mgmt/<snapshot_date>_<type>.json.gz
```

## Report types (consumer)

| file_key | report | profit | ppc |
|----------|--------|:---:|:---:|
| sp_campaigns | spCampaigns | ✓ | ✓ |
| sp_placement | spCampaigns + placement | | ✓ |
| sp_advertised_product | spAdvertisedProduct (SKU/ASIN) | ✓ | |
| sp_adgroups | spAdGroups | | ✓ |
| sp_keywords | spKeywords | | ✓ |
| sp_targeting | spTargeting | | ✓ |
| sp_searchterm | spSearchTerm | | ✓ |
| sb_campaigns | sbCampaigns | ✓ | |
| sd_campaigns | sdCampaigns | ✓ | |

## Workflow đầy đủ

```bash
# ── BƯỚC 1: FETCH (gọi API 1 lần, lưu raw) ──────────────────
cd Phase1_Fetch
cp .env.example .env   # điền Amazon credentials
python run_fetch.py --date 2026-06-15

# Chỉ profit cần (bỏ mgmt + bid recs của ppc):
python run_fetch.py --date 2026-06-15 --skip-mgmt --skip-bidrecs

# Khoảng ngày:
python run_fetch.py --from 2026-06-01 --to 2026-06-15

# ── BƯỚC 2: UPLOAD (đọc raw → Supabase, không gọi API) ──────
cd ../profit_dashboard/Phase1_Upload
cp .env.example .env   # điền Supabase
python run_upload.py --date 2026-06-15

cd ../../ppc_dashboard/Phase1_Upload
cp .env.example .env
python run_upload.py --date 2026-06-15
```

## Chạy lẻ từng nguồn

```bash
python fetch_spapi.py --date 2026-06-15            # chỉ Orders+Finances
python fetch_ads_reports.py --date 2026-06-15 --consumer ppc   # chỉ report ppc cần
python fetch_ads_reports.py --date 2026-06-15 --only sp_campaigns,sp_keywords
python fetch_ads_mgmt.py                           # snapshot trạng thái hiện tại
python fetch_bid_recs.py                           # cần mgmt trước
```

## Replay (không gọi lại API)

File đã tồn tại → fetch tự **skip**. Muốn ghi đè: `--force`.
Upload luôn đọc lại file hiện có → chạy bao nhiêu lần cũng được (idempotent upsert).

## Định dạng file

- **orders/finances**: JSONL.gz (1 dòng = 1 order / 1 page events) — stream được, memory-safe.
- **ads_reports / ads_mgmt**: JSON.gz (1 list) — report Amazon vốn trả nguyên khối.

## Credentials

- `Phase1_Fetch/.env`: chỉ Amazon (SP-API + Ads API). **Không** cần Supabase.
- `*/Phase1_Upload/.env`: chỉ Supabase. **Không** cần Amazon.

Tách bạch để máy chạy fetch (cần ra Internet Amazon) và máy chạy upload (cần
Supabase) có thể khác nhau, và rủi ro lộ credential được khoanh vùng.
