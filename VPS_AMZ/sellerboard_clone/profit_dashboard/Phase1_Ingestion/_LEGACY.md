# ⚠️ LEGACY — Direct-stream đã được thay bởi Fetch↔Upload

Thư mục `profit_dashboard/Phase1_Ingestion/` là **bản sao của pipeline gốc**
(direct-stream: gọi API và ghi thẳng Supabase trong 1 bước), đã đổi tên bảng
sang `Profit_Phase1_*`. Nay được thay bởi kiến trúc Fetch↔Upload.

| Việc | File MỚI thay thế |
|------|-------------------|
| Gọi SP-API + Ads API lưu raw | [`../../Phase1_Fetch/`](../../Phase1_Fetch/) (fetch_spapi, fetch_ads_reports) |
| Đẩy raw → Profit_Phase1_* | [`../Phase1_Upload/`](../Phase1_Upload/) (upload_orders, upload_finances, upload_ads) |

## File CÒN dùng trong thư mục này
- **`process_buffer_cleanup.py`** — vẫn được [`../Phase1_Upload/run_upload.py`](../Phase1_Upload/run_upload.py)
  gọi (qua cờ `--cleanup`) để dedup + cluster bảng sau khi upload. GIỮ LẠI.

## File chỉ để tham khảo (KHÔNG chạy)
- `direct_stream_pipeline.py` — logic transform raw→row đã port sang
  `../Phase1_Upload/upload_*.py`. Đọc để hiểu thuật toán gộp dòng trùng SKU,
  cửa sổ finances trễ, ads 3 tầng.
- `amz_ads_client.py`, `amz_spapi_client.py`, `_time_range.py` — HTTP/auth logic
  đã chuyển sang `shared/` (amz_auth, ads_api) + `shared/timeutils.py`.

## Lưu ý
Đây là code của **profit_dashboard** (bảng `Profit_Phase1_*`), KHÁC với
`sellerboard_clone/Phase1_Ingestion/` ở thư mục gốc — đó là **pipeline production
hiện tại** (bảng `NEW_*` đang chạy app.tap2soul.com), KHÔNG đụng tới.
