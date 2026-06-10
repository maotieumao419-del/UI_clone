from __future__ import annotations
import time
from typing import Any
import requests
from ..config import settings

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
_sp_token_cache: dict[str, Any] = {"token": None, "expires_at": 0}
_ads_token_cache: dict[str, Any] = {"token": None, "expires_at": 0}

class AmazonAPIError(RuntimeError):
    pass

def _fetch_access_token(refresh_token: str) -> tuple[str, float]:
    resp = requests.post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.AMAZON_CLIENT_ID,
            "client_secret": settings.AMAZON_CLIENT_SECRET,
        },
        timeout=15,
    )
    if not resp.ok:
        raise AmazonAPIError(f"LWA token error {resp.status_code}: {resp.text}")
    body = resp.json()
    return body["access_token"], time.time() + body.get("expires_in", 3600) - 60

def get_sp_access_token() -> str:
    if not settings.AMAZON_CLIENT_ID or not settings.SPI_REFRESH_TOKEN:
        raise AmazonAPIError("Chua cau hinh AMAZON_CLIENT_ID hoac SPI_REFRESH_TOKEN trong .env")
    if time.time() < _sp_token_cache["expires_at"] and _sp_token_cache["token"]:
        return _sp_token_cache["token"]
    token, exp = _fetch_access_token(settings.SPI_REFRESH_TOKEN)
    _sp_token_cache["token"] = token
    _sp_token_cache["expires_at"] = exp
    return token

def get_ads_access_token() -> str:
    if not settings.AMAZON_CLIENT_ID or not settings.ADS_REFRESH_TOKEN:
        raise AmazonAPIError("Chua cau hinh AMAZON_CLIENT_ID hoac ADS_REFRESH_TOKEN trong .env")
    if time.time() < _ads_token_cache["expires_at"] and _ads_token_cache["token"]:
        return _ads_token_cache["token"]
    token, exp = _fetch_access_token(settings.ADS_REFRESH_TOKEN)
    _ads_token_cache["token"] = token
    _ads_token_cache["expires_at"] = exp
    return token

def sp_get(path: str, params: dict | None = None) -> Any:
    token = get_sp_access_token()
    url = settings.SPI_API_BASE.rstrip("/") + path
    resp = requests.get(
        url,
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
        params=params,
        timeout=30,
    )
    if not resp.ok:
        raise AmazonAPIError(f"SP-API {path} loi {resp.status_code}: {resp.text[:300]}")
    return resp.json()

def ads_get(path: str, params: dict | None = None) -> Any:
    token = get_ads_access_token()
    url = settings.ADS_API_BASE.rstrip("/") + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Amazon-Advertising-API-ClientId": settings.AMAZON_CLIENT_ID,
        "Content-Type": "application/json",
    }
    if settings.ADS_PROFILE_ID:
        headers["Amazon-Advertising-API-Scope"] = settings.ADS_PROFILE_ID
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if not resp.ok:
        raise AmazonAPIError(f"Ads API {path} loi {resp.status_code}: {resp.text[:300]}")
    return resp.json()
