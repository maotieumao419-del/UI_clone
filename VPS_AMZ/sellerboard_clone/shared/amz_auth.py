"""Shared — Amazon LWA OAuth2 token refresh (dùng chung cho SP-API và Ads API).

Import:
    from shared.amz_auth import get_lwa_token, get_ads_token
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

LWA_URL = "https://api.amazon.com/auth/o2/token"

_token_cache: dict[str, tuple[str, float]] = {}  # key -> (token, expires_at)


def get_lwa_token(
    client_id: str = None,
    client_secret: str = None,
    refresh_token: str = None,
    cache_key: str = "spapi",
) -> str:
    """Lấy LWA access_token cho SP-API. Cache 55 phút (token thật hết hạn 60 phút)."""
    cid = client_id or os.getenv("AMAZON_SPI_CLIENT_ID", "") or os.getenv("AMAZON_ADS_CLIENT_ID", "")
    csec = client_secret or os.getenv("AMAZON_SPI_CLIENT_SECRET", "") or os.getenv("AMAZON_ADS_CLIENT_SECRET", "")
    rt = refresh_token or os.getenv("AMAZON_SPI_REFRESH_TOKEN", "") or os.getenv("AMAZON_ADS_REFRESH_TOKEN", "")

    cached = _token_cache.get(cache_key)
    if cached and time.time() < cached[1]:
        return cached[0]

    if not all([cid, csec, rt]):
        missing = [k for k, v in {
            "CLIENT_ID": cid, "CLIENT_SECRET": csec, "REFRESH_TOKEN": rt
        }.items() if not v]
        raise ValueError(f"Thiếu LWA credentials [{cache_key}]: {missing}")

    r = requests.post(LWA_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": rt,
        "client_id":     cid,
        "client_secret": csec,
    }, timeout=15)
    if not r.ok:
        raise RuntimeError(f"[LWA {cache_key}] ❌ {r.status_code}: {r.text[:300]}")
    token = r.json()["access_token"]
    expires_in = r.json().get("expires_in", 3600)
    _token_cache[cache_key] = (token, time.time() + expires_in - 300)
    print(f"  [LWA {cache_key}] OK: {token[:20]}...")
    return token


def get_ads_token(
    client_id: str = None,
    client_secret: str = None,
    refresh_token: str = None,
) -> str:
    """Lấy LWA access_token riêng cho Ads API (cache key='ads')."""
    cid = client_id or os.getenv("AMAZON_ADS_CLIENT_ID", "") or os.getenv("AMAZON_SPI_CLIENT_ID", "")
    csec = client_secret or os.getenv("AMAZON_ADS_CLIENT_SECRET", "") or os.getenv("AMAZON_SPI_CLIENT_SECRET", "")
    rt = refresh_token or os.getenv("AMAZON_ADS_REFRESH_TOKEN", "") or os.getenv("AMAZON_SPI_REFRESH_TOKEN", "")
    return get_lwa_token(cid, csec, rt, cache_key="ads")
