# ⚠️ LEGACY — Phase1_Ingestion (chỉ còn để THAM KHẢO)

Thư mục này là **pipeline ingestion thế hệ cũ**: gọi Amazon API và **stream
trực tiếp** vào Supabase `NEW_*` trong cùng 1 lần chạy (`direct_stream_pipeline.py`).

## Đã được thay thế bởi (kiến trúc Fetch ↔ Upload tách rời)

| Việc cũ làm | Giờ làm ở đâu |
|-------------|---------------|
| Gọi SP-API Orders/Finances | [`../Phase1_Fetch/fetch_spapi.py`](../Phase1_Fetch/fetch_spapi.py) |
| Gọi Ads API reports | [`../Phase1_Fetch/fetch_ads_reports.py`](../Phase1_Fetch/fetch_ads_reports.py) |
| Lưu raw (backup) | `Phase1_Fetch/data/YYYY/MM/DD/*.gz` |
| Đẩy raw → Supabase | [`../profit_dashboard/Phase1_Upload/`](../profit_dashboard/Phase1_Upload/) |
| Dedup hậu xử lý | `process_buffer_cleanup.py` (gọi qua `Phase1_Upload/run_upload.py --cleanup`) |

## Khác biệt cốt lõi

- **Cũ**: API → Supabase trực tiếp. Lỗi giữa chừng = mất data, phải gọi lại API (tốn quota).
- **Mới**: API → file `.json.gz` (backup bất biến) → Supabase. Replay không gọi lại API.
- **Cũ** ghi bảng `NEW_*`. **Mới** ghi `Profit_Phase1_*` (profit) / `PPC_Phase1_*` (ppc).
- **Mới** gọi API **1 lần dùng chung** cho cả profit + ppc (Phase1_Fetch).

## Có nên xóa?

CHƯA. Giữ để:
1. Đối chiếu logic transform khi nghi ngờ bản port ở `Phase1_Upload` sai.
2. App production `app.tap2soul.com` hiện vẫn có thể đang đọc bảng `NEW_*` qua
   Phase3 bridge — chỉ gỡ bỏ folder này SAU khi đã chuyển hẳn website sang đọc
   bảng `Profit_Phase2_*` và xác nhận không còn job nào gọi `direct_stream_pipeline.py`.

**Không thêm tính năng mới vào đây.** Mọi thay đổi ingestion → sửa ở `Phase1_Fetch/`
+ `Phase1_Upload/`.
