"""Module ADS — trang chỉ số quảng cáo (consumer ĐỌC dữ liệu đã xử lý từ DB).

Không đụng pipeline (Phase1/2/3) cũng không refactor backend/frontend: chỉ ĐỌC
các bảng NEW_ads_* / entity tree / NEW_products đã có trong Supabase rồi tính
KPI (ACOS/ROAS/TACOS/CTR/CVR/CPC) cho trang "📣 Amazon Ads".
"""
