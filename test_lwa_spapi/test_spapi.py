"""
Test LWA OAuth Only — không cần AWS credentials (Access Key, Secret Key, Role ARN).

Mục đích: kiểm tra xem SP-API có cho phép gọi chỉ với LWA token không.
- 200 OK  → LWA-only hoạt động, có thể bỏ toàn bộ SigV4/AWS
- 403     → SP-API vẫn yêu cầu SigV4, cần giữ AWS credentials
"""
import os
import json
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID      = os.getenv("AMAZON_SPI_CLIENT_ID", "")
CLIENT_SECRET  = os.getenv("AMAZON_SPI_CLIENT_SECRET", "")
REFRESH_TOKEN  = os.getenv("AMAZON_SPI_REFRESH_TOKEN", "")
MARKETPLACE_ID = os.getenv("AMAZON_SPI_MARKETPLACE_ID", "ATVPDKIKX0DER")

SP_API_BASE  = "https://sellingpartnerapi-na.amazon.com"
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


def get_lwa_token() -> str:
    resp = requests.post(LWA_TOKEN_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def call_spapi(token: str, path: str, params: dict = None):
    return requests.get(
        f"{SP_API_BASE}{path}",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        params=params or {},
        timeout=15,
    )


def main():
    print("=" * 60)
    print("TEST: LWA OAuth Only (không dùng AWS SigV4)")
    print("=" * 60)

    # Bước 1: Lấy LWA access token
    print("\n[1] Lấy LWA access token...")
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        print("    ❌ Thiếu credentials trong .env")
        return
    try:
        token = get_lwa_token()
        print(f"    ✅ Token: {token[:30]}...")
    except Exception as e:
        print(f"    ❌ Lỗi: {e}")
        return

    # Bước 2: Gọi getOrders (endpoint phổ biến nhất)
    print("\n[2] Gọi getOrders (7 ngày)...")
    created_after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = call_spapi(token, "/orders/v0/orders", {
        "MarketplaceIds": MARKETPLACE_ID,
        "CreatedAfter":   created_after,
        "MaxResultsPerPage": 3,
    })
    print(f"    HTTP {resp.status_code}")
    if resp.status_code == 200:
        orders = resp.json().get("payload", {}).get("Orders", [])
        print(f"    ✅ LWA-only HOẠT ĐỘNG — lấy được {len(orders)} orders")
        for o in orders:
            print(f"       {o.get('AmazonOrderId')} | {o.get('OrderStatus')}")
    elif resp.status_code == 403:
        print("    ❌ 403 Forbidden — SP-API vẫn yêu cầu SigV4, không bỏ được AWS")
        print(f"    Chi tiết: {resp.text[:200]}")
    else:
        print(f"    ⚠️  {resp.text[:300]}")

    # Bước 3: Gọi getMarketplaceParticipations (endpoint grantless, thường không cần SigV4)
    print("\n[3] Gọi getMarketplaceParticipations (grantless endpoint)...")
    resp2 = call_spapi(token, "/sellers/v1/marketplaceParticipations")
    print(f"    HTTP {resp2.status_code}")
    if resp2.status_code == 200:
        data = resp2.json().get("payload", [])
        print(f"    ✅ OK — {len(data)} marketplace(s)")
        for m in data:
            mp = m.get("marketplace", {})
            print(f"       {mp.get('id')} | {mp.get('name')} | {mp.get('countryCode')}")
    else:
        print(f"    ❌ {resp2.status_code}: {resp2.text[:200]}")

    print("\n" + "=" * 60)
    print("KẾT LUẬN:")
    if resp.status_code == 200:
        print("  → Có thể chuyển hoàn toàn sang LWA-only, bỏ AWS credentials")
    elif resp.status_code == 403:
        print("  → Vẫn cần AWS SigV4. Giữ cách hiện tại hoặc dùng library.")
    print("=" * 60)


if __name__ == "__main__":
    main()
