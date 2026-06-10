# setup_env.ps1 - Dien thong tin vao .env cho SellerVision
# Chay: powershell -ExecutionPolicy Bypass -File setup_env.ps1

$envPath = Join-Path $PSScriptRoot "backend\.env"

function Ask($prompt, $default = "") {
    $display = if ($default) { "$prompt [$default]" } else { $prompt }
    $val = Read-Host $display
    if (-not $val -and $default) { return $default }
    return $val
}

function AskSecret($prompt) {
    $secure = Read-Host $prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}

Write-Host ""
Write-Host "=== SELLERVISION - Cau hinh .env ===" -ForegroundColor Cyan
Write-Host "Nhan Enter de giu gia tri mac dinh hien thi trong []." -ForegroundColor DarkGray
Write-Host ""

# --- BAO MAT ---
Write-Host "--- BAO MAT ---" -ForegroundColor Yellow
$secretKey = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 64 | ForEach-Object { [char]$_ })
Write-Host "SECRET_KEY tu dong tao: $($secretKey.Substring(0,8))..." -ForegroundColor DarkGray

# --- DOMAIN ---
Write-Host ""
Write-Host "--- DOMAIN ---" -ForegroundColor Yellow
$domain       = Ask "Domain chinh (vd: app.tap2soul.com)" "app.tap2soul.com"
$corsOrigins  = "https://$domain"
$allowedHosts = $domain

# --- SUPABASE ---
Write-Host ""
Write-Host "--- SUPABASE ---" -ForegroundColor Yellow
Write-Host "Lay tu: Supabase Dashboard > Settings > API" -ForegroundColor DarkGray
$supabaseUrl = Ask "SUPABASE_URL (vd: https://xxxx.supabase.co)"
$supabaseKey = AskSecret "SUPABASE_KEY service_role (an toan - khong hien thi)"
Write-Host ""
Write-Host "Lay tu: Settings > Database > Connection string > URI > Transaction mode port 6543" -ForegroundColor DarkGray
$databaseUrl = AskSecret "DATABASE_URL postgresql+psycopg://... (an toan - khong hien thi)"

# --- AMAZON SP-API ---
Write-Host ""
Write-Host "--- AMAZON SP-API ---" -ForegroundColor Yellow
Write-Host "Lay tu: developer.amazonservices.com > Your Apps > View Credentials" -ForegroundColor DarkGray
$spiClientId     = Ask "AMAZON_SPI_CLIENT_ID"
$spiClientSecret = AskSecret "AMAZON_SPI_CLIENT_SECRET (an toan - khong hien thi)"
$spiRefreshToken = AskSecret "AMAZON_SPI_REFRESH_TOKEN Atzr|... (an toan - khong hien thi)"
$spiMarketplace  = Ask "AMAZON_SPI_MARKETPLACE_ID" "ATVPDKIKX0DER"

# --- AMAZON ADS-API ---
Write-Host ""
Write-Host "--- AMAZON ADS-API ---" -ForegroundColor Yellow
Write-Host "Lay tu: advertising.amazon.com > Manage > API access" -ForegroundColor DarkGray
$adsClientId     = Ask "AMAZON_ADS_CLIENT_ID"
$adsClientSecret = AskSecret "AMAZON_ADS_CLIENT_SECRET (an toan - khong hien thi)"
$adsRefreshToken = AskSecret "AMAZON_ADS_REFRESH_TOKEN Atzr|... (an toan - khong hien thi)"
$adsProfileId    = Ask "AMAZON_ADS_PROFILE_ID (so profile ID)"
$adsRegion       = Ask "AMAZON_ADS_REGION" "NA"

# --- AUTO-SYNC ---
Write-Host ""
Write-Host "--- LICH AUTO-SYNC ---" -ForegroundColor Yellow
$syncHours = Ask "AMAZON_AUTO_SYNC_SCHEDULE_HOURS" "1,7,13,19"
$syncDays  = Ask "AMAZON_AUTO_SYNC_DAYS" "3"

# --- GHI FILE ---
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm'
$content = @"
# SELLERVISION .env PRODUCTION - tao luc $ts
# KHONG commit file nay len Git.

APP_NAME=SellerVision
ENV=prod

SECRET_KEY=$secretKey
ACCESS_TOKEN_EXPIRE_MINUTES=1440

CORS_ORIGINS=$corsOrigins
ALLOWED_HOSTS=$allowedHosts

DATABASE_URL=$databaseUrl

PPC_DIR=data/ppc
DATA_SOURCE=file
DATA_RETENTION_DAYS=180
VST_CACHE_TTL=300
VST_VERIFY_SSL=true

SUPABASE_URL=$supabaseUrl
SUPABASE_KEY=$supabaseKey

AMAZON_SPI_CLIENT_ID=$spiClientId
AMAZON_SPI_CLIENT_SECRET=$spiClientSecret
AMAZON_SPI_REFRESH_TOKEN=$spiRefreshToken
AMAZON_SPI_MARKETPLACE_ID=$spiMarketplace

AMAZON_ADS_CLIENT_ID=$adsClientId
AMAZON_ADS_CLIENT_SECRET=$adsClientSecret
AMAZON_ADS_REFRESH_TOKEN=$adsRefreshToken
AMAZON_ADS_PROFILE_ID=$adsProfileId
AMAZON_ADS_REGION=$adsRegion

AMAZON_AUTO_SYNC_ENABLED=true
AMAZON_AUTO_SYNC_SCHEDULE_HOURS=$syncHours
AMAZON_AUTO_SYNC_DAYS=$syncDays

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_ROLE_ARN=
AWS_REGION=us-east-1
"@

$content | Out-File -FilePath $envPath -Encoding utf8 -NoNewline

Write-Host ""
Write-Host "=== XONG! File .env da ghi vao: $envPath ===" -ForegroundColor Green
Write-Host ""
Write-Host "Buoc tiep theo:" -ForegroundColor Cyan
Write-Host "  1. Chay migration SQL tren Supabase"
Write-Host "     File: backend/supabase/migrations/0001_create_raw_amazon_orders.sql"
Write-Host "  2. Upload code + file .env len VPS"
Write-Host "  3. Tren VPS: docker-compose up -d --build"
Write-Host ""
