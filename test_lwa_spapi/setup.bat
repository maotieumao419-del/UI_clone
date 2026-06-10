@echo off
echo ================================================
echo  SETUP: Amazon SP-API Inspector
echo ================================================

:: Kiem tra Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Python chua duoc cai dat.
    echo      Tai tai: https://python.org/downloads
    pause
    exit /b 1
)

echo [OK] Python da co

:: Cai thu vien
echo.
echo Dang cai thu vien...
pip install -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai dat that bai. Kiem tra ket noi internet.
    pause
    exit /b 1
)

:: Tao file .env neu chua co
if not exist .env (
    copy .env.example .env >nul
    echo [OK] Da tao file .env tu .env.example
    echo.
    echo >>> QUAN TRONG: Mo file .env va dien credentials vao <<<
) else (
    echo [OK] File .env da ton tai
)

:: Tao thu muc output
if not exist raw_data mkdir raw_data
echo [OK] Thu muc raw_data san sang

echo.
echo ================================================
echo  Setup hoan tat!
echo  Buoc tiep theo:
echo    1. Mo file .env va dien credentials
echo    2. Chay: python fetch_24h_orders.py
echo ================================================
pause
