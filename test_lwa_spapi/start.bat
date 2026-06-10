@echo off
chcp 65001 >nul
cd /d C:\Users\nnh16\ads-trading-system\VPS\test_lwa_spapi

echo.
echo ========================================
echo   SELLERBOARD API DEBUG
echo   Thu muc: %CD%
echo ========================================

echo.
echo [1/3] Cai thu vien (neu chua co)...
pip install requests python-dotenv --quiet

echo.
echo [1/3] Fetch Orders...
python fetch_24h_orders.py
if %errorlevel% neq 0 (
    echo.
    echo *** FAILED: fetch_24h_orders.py ***
    echo Kiem tra .env va ket noi internet.
    pause
    exit /b 1
)

echo.
echo [2/3] Fetch Financial Events...
python fetch_24h_finances.py
if %errorlevel% neq 0 (
    echo.
    echo *** FAILED: fetch_24h_finances.py ***
    pause
    exit /b 1
)

echo.
echo [3/3] Fetch Ads Reports (mat 1-5 phut)...
python fetch_24h_ads.py
if %errorlevel% neq 0 (
    echo.
    echo *** FAILED: fetch_24h_ads.py ***
    pause
)

echo.
echo ========================================
echo   XONG!
echo   Xem ket qua trong thu muc:
echo   %CD%\raw_data\
echo ========================================
echo.
echo   Files quan trong nhat:
echo   - finances_summary.txt  (tong phi Amazon)
echo   - ads_summary.txt       (tong chi phi quang cao)
echo.
pause
