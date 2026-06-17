# Vòng đời dữ liệu — Local archive ↔ Supabase (cửa sổ trượt 62 ngày)

Áp dụng CHUNG cho cả `profit_dashboard` lẫn `ppc_dashboard`. Engine ở `shared/`
(`retention.py`, `summary_archive.py`); mỗi dashboard chỉ có 1 CLI mỏng
`manage_supabase.py` khai báo registry tên bảng riêng.

## Nguyên tắc

```
                  fetch          upload          transform        archive
  Amazon API ──► local raw ──► Supabase raw ──► Supabase summary ──► local summary
                 (giữ mãi)     (62 ngày)        (62 ngày)            (giữ mãi)
                                   │                  │
                                 prune ◄──────────────┘  (xóa phần > 62 ngày)
                                          UI đọc summary 62 ngày gần nhất
```

- **Supabase = chỉ giữ cửa sổ 62 ngày** (raw + summary). Không phình theo thời gian.
- **Local = nguồn chân lý đầy đủ**: raw (`orders/finances/ads_*.json.gz`) +
  summary (`summary_*.json.gz`). Giữ mãi, gzip rất nhẹ.
- **UI đọc summary 62 ngày** trực tiếp từ Supabase → nhanh.
- **Xem khoảng cũ hơn** → `hydrate` từ local summary → xem → `evict`.

→ Không bao giờ tràn 500MB free tier (prune giữ Supabase đứng yên).

## Quy trình hằng ngày (sẽ được orchestrator tự chạy sau này)

```bash
# 1. FETCH — gọi API 1 lần, lưu raw local
cd Phase1_Fetch && python run_fetch.py --date 2026-06-16

# 2. UPLOAD — raw local → Supabase Phase1
cd ../profit_dashboard/Phase1_Upload && python run_upload.py --date 2026-06-16
cd ../../ppc_dashboard/Phase1_Upload && python run_upload.py --date 2026-06-16

# 3. TRANSFORM — Phase1 → Phase2 summary trên Supabase
cd ../../profit_dashboard/Phase2_Transformation && python transform_engine.py --date 2026-06-16
cd ../../ppc_dashboard/Phase2_PPC_Transform && python run_ppc_transform.py --date 2026-06-16

# 4. ARCHIVE — lưu summary ra local (để hydrate khoảng cũ về sau)
cd ../../profit_dashboard && python manage_supabase.py archive --date 2026-06-16
cd ../ppc_dashboard && python manage_supabase.py archive --date 2026-06-16

# 5. PRUNE — dọn Supabase về 62 ngày (chạy định kỳ, vd 1 lần/tuần)
cd ../profit_dashboard && python manage_supabase.py prune
cd ../ppc_dashboard && python manage_supabase.py prune
```

## Xem dữ liệu cũ (ngoài cửa sổ 62 ngày)

Khi UI chọn khoảng > 62 ngày trước (vd tháng 1):

```bash
# Nạp tạm summary tháng đó từ local lên Supabase
python manage_supabase.py hydrate --from 2026-01-01 --to 2026-01-31
# ... UI hiển thị bình thường (đọc summary như mọi khi) ...
# Xem xong, giải phóng:
python manage_supabase.py evict --from 2026-01-01 --to 2026-01-31
```

Bước 5 (Phase 3) sẽ tự động hoá: backend phát hiện khoảng nằm ngoài cửa sổ →
gọi hydrate → trả dữ liệu → evict. (Chưa làm — thuộc giai đoạn Phase 3.)

## Cấu hình cửa sổ (.env của Phase1_Upload)

```
SUPABASE_WINDOW_DAYS=62        # cửa sổ chung
SUPABASE_RAW_WINDOW_DAYS=      # ghi đè riêng raw nếu search terms phình to (vd 30)
```

## Bảng KHÔNG bị prune

- **Profit persistent**: `Profit_Phase1_product_price`, `_product_cogs`, `_fee_cache`
  — dữ liệu tích lũy, không theo ngày.
- **PPC snapshot mgmt**: `PPC_Phase1_portfolios`, `_campaigns_raw`, `_adgroups_raw`,
  `_keywords_raw`, `_targets_raw` — bị ghi đè mỗi fetch (PK = id thực thể),
  dung lượng bounded theo số thực thể, không tăng theo ngày.

## Lưu ý

- `archive` chỉ áp cho bảng SUMMARY (đã tính toán). Raw KHÔNG cần archive riêng —
  đã có sẵn trong file fetch local, tái `upload` được bất cứ lúc nào.
- `prune` an toàn lặp lại (idempotent). `hydrate`/`archive` dùng upsert nên chạy
  lại không nhân đôi.
