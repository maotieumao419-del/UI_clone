# Profit Dashboard — Pipeline 3 Phase

Đây là **tài liệu định vị** cho Profit Dashboard. Toàn bộ code pipeline nằm ở:

```
sellerboard_clone/
├── Phase1_Ingestion/        ← Ingest từ Amazon SP-API + Ads API
├── Phase2_Transformation/   ← Transform → summary tables (NEW_summary_*)
├── Phase3_Application/      ← Bridge/Patch sang web app app.tap2soul.com
├── backend/                 ← FastAPI app (production)
└── frontend/                ← Frontend (production)
```

## Kiến trúc

```
Amazon API ──(Phase1)──► Supabase NEW_* (bảng đệm)
Supabase   ──(Phase2)──► NEW_summary_order_items / NEW_summary_products / NEW_summary_campaigns
Summary    ──(Phase3)──► Web App app.tap2soul.com
```

## Lệnh chạy

### Phase 1 — Ingest
```bash
cd sellerboard_clone/Phase1_Ingestion
python direct_stream_pipeline.py --all --date 2026-06-15
python direct_stream_pipeline.py --all --from 2026-06-01 --to 2026-06-15
```

### Phase 2 — Transform
```bash
cd sellerboard_clone/Phase2_Transformation
python transform_engine.py --days 7
python transform_engine.py --date 2026-06-15
```

### Phase 3 — Bridge/Patch
```bash
cd sellerboard_clone/Phase3_Application/data_bridge/patch_scripts
python patch_dashboard.py --check   # kiểm tra trước khi apply
python patch_dashboard.py           # apply (có backup + rollback)
```

## Bảng Supabase (prefix NEW_)

| Bảng | Mô tả |
|------|-------|
| NEW_sp_orders | Orders từ SP-API |
| NEW_sp_order_items | Order items |
| NEW_fin_item_fees | Phí Amazon (Referral + FBA) |
| NEW_fin_refunds | Hoàn tiền |
| NEW_fin_adjustments | Điều chỉnh |
| NEW_ads_campaigns_daily | Ads campaign level (SP/SB/SD) |
| NEW_ads_sp_asin_daily | Ads advertised product level (SKU/ASIN) |
| NEW_summary_order_items | Summary đơn hàng |
| NEW_summary_products | Summary theo SKU/ASIN |
| NEW_summary_campaigns | Summary campaign |
| NEW_summary_reimbursements | Hoàn bù |
| NEW_product_price | Giá đơn vị (persistent) |
| NEW_product_cogs | COGS (persistent) |
| NEW_fee_cache | Cache phí thật per-SKU (persistent) |

## Tài liệu chi tiết

- [`../docs/SESSION_HANDOFF.md`](../docs/SESSION_HANDOFF.md) — bàn giao, baseline Sellerboard
- [`../PIPELINE_3PHASE_README.md`](../PIPELINE_3PHASE_README.md) — kiến trúc đầy đủ
