"""Phase 1 — Advertising API client (SP / SP-ASIN / SB / SD reports).

Flow bất đồng bộ của Ads API v3:
  1. POST /reporting/reports            -> reportId
  2. Poll GET /reporting/reports/{id}   -> chờ status COMPLETED
  3. Download pre-signed URL (GZIP_JSON) -> list rows

Auth riêng biệt với SP-API: Bearer LWA token + Amazon-Advertising-API-Scope
(profile id), KHÔNG cần AWS SigV4. Retry 429 với Retry-After + backoff.

Report SP-ASIN (spAdvertisedProduct) là "Advertised Product Report" — nguồn
dữ liệu cấp SKU/ASIN cho Tầng 1 của thuật toán phân bổ Ad Spend ở Phase 2.
"""
import gzip
import io
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

ADS_CLIENT_ID     = os.getenv("AMAZON_ADS_CLIENT_ID", "") or os.getenv("AMAZON_SPI_CLIENT_ID", "")
ADS_CLIENT_SECRET = os.getenv("AMAZON_ADS_CLIENT_SECRET", "") or os.getenv("AMAZON_SPI_CLIENT_SECRET", "")
ADS_REFRESH       = os.getenv("AMAZON_ADS_REFRESH_TOKEN", "") or os.getenv("AMAZON_SPI_REFRESH_TOKEN", "")
ADS_PROFILE_ID    = os.getenv("ADS_PROFILE_ID", "")

ADS_BASE = "https://advertising-api.amazon.com"
LWA_URL  = "https://api.amazon.com/auth/o2/token"

POLL_INTERVAL = int(os.getenv("ADS_POLL_INTERVAL_SECONDS", "15"))
POLL_TIMEOUT  = int(os.getenv("ADS_POLL_TIMEOUT_SECONDS", "600"))
REQUEST_GAP   = float(os.getenv("ADS_REQUEST_GAP_SECONDS", "20"))


# ── Cấu hình 4 loại report (columns đã kiểm chứng với Amazon) ─────────────────

SP_CONFIG = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
        "campaignId", "campaignName", "campaignStatus", "campaignBiddingStrategy",
        "impressions", "clicks", "cost",
        "purchases1d", "purchases7d", "purchases14d", "purchases30d",
        "sales1d", "sales7d", "sales14d", "sales30d",
        "unitsSoldClicks1d",
        "attributedSalesSameSku1d", "attributedSalesSameSku7d", "attributedSalesSameSku14d",
        "roasClicks14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# Advertised Product Report — spend cấp SKU/ASIN (Tầng 1 phân bổ Ad Spend)
SP_ASIN_CONFIG = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spAdvertisedProduct",
    "groupBy":      ["advertiser"],
    "columns": [
        "campaignId", "campaignName", "adGroupId", "adGroupName",
        "advertisedAsin", "advertisedSku",
        "impressions", "clicks", "cost",
        "purchases1d", "sales1d", "unitsSoldClicks1d",
        "purchases7d", "sales7d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

SB_CONFIG = {
    "adProduct":    "SPONSORED_BRANDS",
    "reportTypeId": "sbCampaigns",
    "groupBy":      ["campaign"],
    # SB KHÔNG có suffix 14d cho purchases/sales — tên cột khác SP
    "columns": [
        "campaignId", "campaignName", "campaignStatus",
        "impressions", "clicks", "cost", "date",
        "purchases", "purchasesPromoted",
        "detailPageViews", "brandedSearches", "brandStorePageView",
        "newToBrandPurchases", "newToBrandSales",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

SD_CONFIG = {
    "adProduct":    "SPONSORED_DISPLAY",
    "reportTypeId": "sdCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
        "campaignId", "campaignName", "campaignStatus",
        "impressions", "clicks", "cost", "date",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# (label, config, ad_product để ghi Supabase — None = bảng riêng SP-ASIN)
REPORT_JOBS = [
    ("SP-Campaigns", SP_CONFIG,      "SPONSORED_PRODUCTS"),
    ("SP-ASIN",      SP_ASIN_CONFIG, None),
    ("SB-Campaigns", SB_CONFIG,      "SPONSORED_BRANDS"),
    ("SD-Campaigns", SD_CONFIG,      "SPONSORED_DISPLAY"),
]


# ── Auth + HTTP ───────────────────────────────────────────────────────────────

def get_ads_token() -> str:
    missing = [k for k, v in {"AMAZON_ADS_CLIENT_ID": ADS_CLIENT_ID,
                              "AMAZON_ADS_CLIENT_SECRET": ADS_CLIENT_SECRET,
                              "AMAZON_ADS_REFRESH_TOKEN": ADS_REFRESH,
                              "ADS_PROFILE_ID": ADS_PROFILE_ID}.items() if not v]
    if missing:
        raise ValueError(f"Thiếu credentials Ads API trong .env: {missing}")
    r = requests.post(LWA_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": ADS_REFRESH,
        "client_id":     ADS_CLIENT_ID,
        "client_secret": ADS_CLIENT_SECRET,
    }, timeout=15)
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"  [ADS LWA] OK: {token[:20]}...")
    return token


def _headers(lwa_ads, profile_id=None):
    h = {
        "Authorization":                   f"Bearer {lwa_ads}",
        "Amazon-Advertising-API-ClientId": ADS_CLIENT_ID,
        "Content-Type":                    "application/json",
    }
    pid = ADS_PROFILE_ID if profile_id is None else profile_id
    if pid:
        h["Amazon-Advertising-API-Scope"] = str(pid)
    return h


def ads_get(path, lwa_ads, profile_id=None, params=None):
    r = requests.get(f"{ADS_BASE}{path}", headers=_headers(lwa_ads, profile_id),
                     params=params or {}, timeout=30)
    if not r.ok:
        print(f"    [ADS GET] ❌ {r.status_code} {path}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def ads_post(path, lwa_ads, body, retries=7):
    for attempt in range(retries):
        r = requests.post(f"{ADS_BASE}{path}", headers=_headers(lwa_ads),
                          data=json.dumps(body), timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            # Throttle tạo report của Ads API rất chặt — backoff dài hẳn
            wait = max(float(r.headers.get("Retry-After", 0) or 0), 15.0) + attempt * 15
            print(f"    [ADS POST] ⚠️  429 → đợi {wait:.0f}s (lần {attempt + 1})")
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"    [ADS POST] ❌ {r.status_code} {path}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Hết retry cho {path}")


# ── Report flow ───────────────────────────────────────────────────────────────

def request_report(lwa_ads, config: dict, name: str, report_date: str) -> str:
    body = {"name": f"{name} {report_date}", "startDate": report_date,
            "endDate": report_date, "configuration": config}
    try:
        resp = ads_post("/reporting/reports", lwa_ads, body)
    except requests.HTTPError as exc:
        # 425 = report y hệt đã tồn tại — Amazon trả luôn reportId cũ trong detail
        r = exc.response
        if r is not None and r.status_code == 425:
            import re
            m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                          r.text)
            if m:
                print(f"  [ADS] {name}: 425 duplicate → dùng lại reportId={m.group(0)[:12]}...")
                return m.group(0)
        raise
    print(f"  [ADS] {name}: reportId={resp.get('reportId', '')[:12]}... "
          f"status={resp.get('status', '')}")
    return resp.get("reportId", "")


def poll_until_done(lwa_ads, report_id: str, name: str) -> str | None:
    print(f"  [ADS] Polling {name}...", end="", flush=True)
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        resp = ads_get(f"/reporting/reports/{report_id}", lwa_ads)
        status = resp.get("status", "")
        print(f" {status}({elapsed}s)", end="", flush=True)
        if status == "COMPLETED":
            print()
            return resp.get("url", "")
        if status in ("FAILED", "CANCELLED"):
            print(f"\n  ❌ Report {name} {status}: {resp}")
            return None
    print(f"\n  ❌ Timeout sau {POLL_TIMEOUT}s")
    return None


def download_report(url: str) -> list:
    """Download pre-signed S3 URL, giải nén GZIP_JSON -> list rows."""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    try:
        with gzip.open(io.BytesIO(resp.content)) as f:
            return json.load(f)
    except Exception:                                  # noqa: BLE001 — không gzip
        return resp.json()


# ── Entity listing (DIMENSION: portfolio → campaign → ad_group → keyword) ──────
# Khác report (perf theo ngày): đây là HỒ SƠ hiện tại (state/budget/bid) để Khối E
# sau này NHẮM hành động. SP v3 list endpoints cần Content-Type/Accept vnd riêng
# + phân trang nextToken (≤ maxResults/trang). Portfolios dùng v2 (trả full list).

# kind -> (path, content_type vnd, key trong response)
SP_LIST_ENDPOINTS = {
    "campaigns": ("/sp/campaigns/list", "application/vnd.spCampaign.v3+json", "campaigns"),
    "adGroups":  ("/sp/adGroups/list",  "application/vnd.spAdGroup.v3+json",  "adGroups"),
    "keywords":  ("/sp/keywords/list",  "application/vnd.spKeyword.v3+json",  "keywords"),
}

_LIST_STATE_FILTER = {"include": ["ENABLED", "PAUSED", "ARCHIVED"]}


def _ads_post_typed(path, lwa_ads, body, content_type, retries=7):
    """POST với Content-Type/Accept = vnd riêng (các endpoint /sp/.../list v3)."""
    headers = _headers(lwa_ads)
    headers["Content-Type"] = content_type
    headers["Accept"] = content_type
    for attempt in range(retries):
        r = requests.post(f"{ADS_BASE}{path}", headers=headers,
                          data=json.dumps(body), timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            wait = max(float(r.headers.get("Retry-After", 0) or 0), 5.0) + attempt * 5
            print(f"    [ADS LIST] ⚠️  429 → đợi {wait:.0f}s (lần {attempt + 1})")
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"    [ADS LIST] ❌ {r.status_code} {path}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Hết retry cho {path}")


def _iter_sp_list(kind, lwa_ads, page_size=100):
    """Generator phân trang cho /sp/{campaigns,adGroups,keywords}/list — yield TỪNG TRANG
    (list ≤ page_size) để pipeline upsert + del + gc ngay (memory-safe)."""
    path, content_type, key = SP_LIST_ENDPOINTS[kind]
    next_token = None
    while True:
        body = {"maxResults": page_size, "stateFilter": _LIST_STATE_FILTER}
        if next_token:
            body["nextToken"] = next_token
        resp = _ads_post_typed(path, lwa_ads, body, content_type)
        items = resp.get(key, []) or []
        if items:
            yield items
        next_token = resp.get("nextToken")
        if not next_token:
            break


def iter_sp_campaigns(lwa_ads, page_size=100):
    yield from _iter_sp_list("campaigns", lwa_ads, page_size)


def iter_sp_ad_groups(lwa_ads, page_size=100):
    yield from _iter_sp_list("adGroups", lwa_ads, page_size)


def iter_sp_keywords(lwa_ads, page_size=100):
    yield from _iter_sp_list("keywords", lwa_ads, page_size)


def list_portfolios(lwa_ads):
    """Portfolios (v2 /v2/portfolios/extended) — trả về full list, không phân trang.
    Lỗi → trả [] (portfolio không bắt buộc; không chặn cây entity)."""
    try:
        data = ads_get("/v2/portfolios/extended", lwa_ads)
        return data if isinstance(data, list) else []
    except Exception as exc:                           # noqa: BLE001
        print(f"  ⚠️  Không lấy được portfolios (bỏ qua): {exc}")
        return []
