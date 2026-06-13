@echo off
REM Phase 1 — Direct-Stream Ingestion (Amazon -> Supabase)
REM Double-click de chay. Khong co --date => script se HOI ban chon
REM "24h gan nhat" hay "1 ngay cu the (gio Seller Central / Pacific)".
cd /d "%~dp0"
python direct_stream_pipeline.py --all
echo.
pause
