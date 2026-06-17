# ⚠️ LEGACY — Thư mục tham khảo, KHÔNG dùng để chạy

Thư mục `Phase1_PPC_Ingestion/` là **bản nháp đầu tiên** (gọi API + ghi Supabase
trong cùng 1 bước). Nó đã được **thay thế hoàn toàn** bởi kiến trúc Fetch↔Upload:

| Việc cần làm | File MỚI thay thế |
|--------------|-------------------|
| Gọi Ads API lưu raw | [`../../Phase1_Fetch/fetch_ads_reports.py`](../../Phase1_Fetch/fetch_ads_reports.py), [`fetch_ads_mgmt.py`](../../Phase1_Fetch/fetch_ads_mgmt.py), [`fetch_bid_recs.py`](../../Phase1_Fetch/fetch_bid_recs.py) |
| Map raw → bảng PPC_Phase1_* | [`../Phase1_Upload/db_writer.py`](../Phase1_Upload/db_writer.py) |
| Đẩy raw lên Supabase | [`../Phase1_Upload/run_upload.py`](../Phase1_Upload/run_upload.py) |

## Vì sao thay thế?
- Gọi API liên tục cần delay/quota → tách bước Fetch (lưu file JSON.gz) khỏi Upload.
- Profit + PPC gọi `spCampaigns` chung → gộp về `Phase1_Fetch/` gọi 1 lần.
- Có backup raw local trước khi đẩy Supabase → replay không tốn quota.

## Giữ lại để làm gì?
Tham khảo logic report config + mapping cột. `amz_ads_ppc_client.py` chứa các
`make_*_config()` đã được port sang [`../../Phase1_Fetch/ads_report_configs.py`](../../Phase1_Fetch/ads_report_configs.py).

**KHÔNG chạy các script trong thư mục này.** Dùng `Phase1_Fetch/` + `Phase1_Upload/`.
