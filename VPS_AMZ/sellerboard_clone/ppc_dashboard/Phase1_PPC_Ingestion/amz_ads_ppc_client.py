"""PPC Phase 1 — Ads API v3 HTTP client (Reports + Campaign Management).

Extends pattern từ profit_dashboard Phase1 amz_ads_client.py:
  - Reports API: POST /reporting/reports -> poll -> download GZIP_JSON
  - Campaign Mgmt: GET /sp/campaigns, /sp/adGroups, /sp/keywords, /sp/targets
  - Portfolio API: GET /portfolios
  - Bid Recommendations: POST /sp/keywords/bidRecommendations
  - Placement-segmented report: spCampaigns với segment=placement

Auth: Bearer LWA token + Amazon-Advertising-API-Scope (profile ID).
KHÔNG dùng AWS SigV4 cho Ads API.
Retry 429 với Retry-After + backoff (giống Phase1 gốc).
"""
import gzip
import io
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

# Cho phép import shared/ từ thư mục gốc sellerboard_clone
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.config import (
    ADS_BASE, ADS_CLIENT_ID, ADS_PROFILE_ID,
    POLL_INTERVAL, POLL_TIMEOUT, REQUEST_GAP,
)
from shared.amz_auth import get_ads_token

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


# ── Headers ────────────────────────────────────────────────────────────────────

def _headers(lwa_ads: str, profile_id: str = None) -> dict:
    h = {
        "Authorization":                   f"Bearer {lwa_ads}",
        "Amazon-Advertising-API-ClientId": ADS_CLIENT_ID,
        "Content-Type":                    "application/json",
    }
    pid = profile_id or ADS_PROFILE_ID
    if pid:
        h["Amazon-Advertising-API-Scope"] = str(pid)
    return h


# ── HTTP wrappers ──────────────────────────────────────────────────────────────

def ads_get(path: str, lwa_ads: str, profile_id: str = None,
            params: dict = None, api_version: str = None) -> dict | list:
    """GET /advertising-api-.*. api_version dùng cho endpoint v3 style header."""
    hdrs = _headers(lwa_ads, profile_id)
    if api_version:
        hdrs["Amazon-Advertising-API-Version"] = api_version
    r = requests.get(f"{ADS_BASE}{path}", headers=hdrs, params=params or {}, timeout=30)
    if not r.ok:
        print(f"  [ADS GET] ❌ {r.status_code} {path}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def ads_post(path: str, lwa_ads: str, body: dict | list,
             retries: int = 7, api_version: str = None) -> dict | list:
    hdrs = _headers(lwa_ads)
    if api_version:
        hdrs["Amazon-Advertising-API-Version"] = api_version
    for attempt in range(retries):
        r = requests.post(f"{ADS_BASE}{path}", headers=hdrs,
                          data=json.dumps(body), timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            wait = max(float(r.headers.get("Retry-After", 0) or 0), 15.0) + attempt * 15
            print(f"  [ADS POST] ⚠️  429 → đợi {wait:.0f}s (lần {attempt + 1})")
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"  [ADS POST] ❌ {r.status_code} {path}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Hết retry cho {path}")


# ── Reports API v3 ─────────────────────────────────────────────────────────────

def request_report(lwa_ads: str, config: dict, name: str, report_date: str) -> str:
    """POST /reporting/reports -> reportId. Xử lý 425 duplicate."""
    body = {
        "name":          f"{name} {report_date}",
        "startDate":     report_date,
        "endDate":       report_date,
        "configuration": config,
    }
    try:
        resp = ads_post("/reporting/reports", lwa_ads, body)
    except requests.HTTPError as exc:
        r = exc.response
        if r is not None and r.status_code == 425:
            import re
            m = re.search(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                r.text
            )
            if m:
                print(f"  [ADS] {name}: 425 duplicate → dùng lại reportId={m.group(0)[:12]}...")
                return m.group(0)
        raise
    print(f"  [ADS] {name}: reportId={resp.get('reportId','')[:12]}... status={resp.get('status','')}")
    return resp.get("reportId", "")


def poll_until_done(lwa_ads: str, report_id: str, name: str) -> str | None:
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
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    try:
        with gzip.open(io.BytesIO(resp.content)) as f:
            return json.load(f)
    except Exception:
        return resp.json()


# ── Report configs cho PPC (5 cấp) ────────────────────────────────────────────

def make_sp_campaigns_config(segment: str = None) -> dict:
    """spCampaigns report. segment='placement' cho topOfSearch breakdown."""
    cfg = {
        "adProduct":    "SPONSORED_PRODUCTS",
        "reportTypeId": "spCampaigns",
        "groupBy":      ["campaign"],
        "columns": [
            "campaignId", "campaignName", "campaignStatus", "campaignBiddingStrategy",
            "impressions", "clicks", "cost",
            "purchases1d", "purchases7d", "purchases14d", "purchases30d",
            "sales1d", "sales7d", "sales14d", "sales30d",
            "unitsSoldClicks1d", "unitsSoldClicks7d", "unitsSoldClicks14d",
            "attributedSalesSameSku14d",
            "roasClicks14d",
        ],
        "timeUnit": "DAILY",
        "format":   "GZIP_JSON",
    }
    if segment == "placement":
        cfg["groupBy"] = ["campaign", "placement"]
        cfg["columns"].append("placementClassification")
    return cfg


def make_sp_adgroups_config() -> dict:
    return {
        "adProduct":    "SPONSORED_PRODUCTS",
        "reportTypeId": "spAdGroups",
        "groupBy":      ["adGroup"],
        "columns": [
            "campaignId", "campaignName",
            "adGroupId", "adGroupName", "adGroupStatus",
            "impressions", "clicks", "cost",
            "purchases1d", "purchases7d", "purchases14d",
            "sales1d", "sales7d", "sales14d",
            "unitsSoldClicks1d", "unitsSoldClicks14d",
            "attributedSalesSameSku14d",
        ],
        "timeUnit": "DAILY",
        "format":   "GZIP_JSON",
    }


def make_sp_keywords_config() -> dict:
    return {
        "adProduct":    "SPONSORED_PRODUCTS",
        "reportTypeId": "spKeywords",
        "groupBy":      ["keyword"],
        "columns": [
            "campaignId", "campaignName",
            "adGroupId", "adGroupName",
            "keywordId", "keywordText", "keywordStatus", "matchType",
            "bid",
            "impressions", "clicks", "cost",
            "purchases1d", "purchases7d", "purchases14d",
            "sales1d", "sales7d", "sales14d",
            "unitsSoldClicks1d", "unitsSoldClicks14d",
            "attributedSalesSameSku14d",
        ],
        "timeUnit": "DAILY",
        "format":   "GZIP_JSON",
    }


def make_sp_targets_config() -> dict:
    """Product/ASIN targeting (auto + manual product targets)."""
    return {
        "adProduct":    "SPONSORED_PRODUCTS",
        "reportTypeId": "spTargeting",
        "groupBy":      ["targeting"],
        "columns": [
            "campaignId", "campaignName",
            "adGroupId", "adGroupName",
            "targetId", "targetingText", "targetingType", "targetingExpression",
            "bid",
            "impressions", "clicks", "cost",
            "purchases1d", "purchases7d", "purchases14d",
            "sales1d", "sales7d", "sales14d",
            "unitsSoldClicks1d", "unitsSoldClicks14d",
        ],
        "timeUnit": "DAILY",
        "format":   "GZIP_JSON",
    }


def make_sp_searchterm_config() -> dict:
    return {
        "adProduct":    "SPONSORED_PRODUCTS",
        "reportTypeId": "spSearchTerm",
        "groupBy":      ["searchTerm"],
        "columns": [
            "campaignId", "campaignName",
            "adGroupId", "adGroupName",
            "keywordId", "keywordText", "matchType",
            "query",
            "impressions", "clicks", "cost",
            "purchases1d", "purchases7d", "purchases14d",
            "sales1d", "sales7d", "sales14d",
            "unitsSoldClicks1d", "unitsSoldClicks14d",
            "attributedSalesSameSku14d",
        ],
        "timeUnit": "DAILY",
        "format":   "GZIP_JSON",
    }


# ── Campaign Management API (v3) ───────────────────────────────────────────────

def list_portfolios(lwa_ads: str) -> list:
    """GET /portfolios — trả list portfolio objects."""
    resp = ads_get("/portfolios", lwa_ads)
    return resp if isinstance(resp, list) else resp.get("portfolios", [])


def list_sp_campaigns(lwa_ads: str, state_filter: str = "enabled,paused,archived",
                      count: int = 100, start_index: int = 0) -> list:
    """GET /sp/campaigns (v2 management endpoint)."""
    params = {
        "stateFilter": state_filter,
        "count":       count,
        "startIndex":  start_index,
    }
    resp = ads_get("/sp/campaigns", lwa_ads, params=params)
    return resp if isinstance(resp, list) else []


def list_sp_adgroups(lwa_ads: str, campaign_id_filter: str = None,
                     count: int = 100, start_index: int = 0) -> list:
    """GET /sp/adGroups."""
    params: dict = {"count": count, "startIndex": start_index,
                    "stateFilter": "enabled,paused,archived"}
    if campaign_id_filter:
        params["campaignIdFilter"] = campaign_id_filter
    resp = ads_get("/sp/adGroups", lwa_ads, params=params)
    return resp if isinstance(resp, list) else []


def list_sp_keywords(lwa_ads: str, ad_group_id_filter: str = None,
                     count: int = 100, start_index: int = 0) -> list:
    """GET /sp/keywords."""
    params: dict = {"count": count, "startIndex": start_index,
                    "stateFilter": "enabled,paused,archived"}
    if ad_group_id_filter:
        params["adGroupIdFilter"] = ad_group_id_filter
    resp = ads_get("/sp/keywords", lwa_ads, params=params)
    return resp if isinstance(resp, list) else []


def list_sp_targets(lwa_ads: str, ad_group_id_filter: str = None,
                    count: int = 100, start_index: int = 0) -> list:
    """GET /sp/targets (product/ASIN targeting)."""
    params: dict = {"count": count, "startIndex": start_index,
                    "stateFilter": "enabled,paused,archived"}
    if ad_group_id_filter:
        params["adGroupIdFilter"] = ad_group_id_filter
    resp = ads_get("/sp/targets", lwa_ads, params=params)
    return resp if isinstance(resp, list) else []


def get_bid_recommendations(lwa_ads: str, keyword_ids: list[str]) -> list:
    """POST /sp/keywords/bidRecommendations — batch <=100 keywordIds."""
    if not keyword_ids:
        return []
    body = {"keywordIds": [str(k) for k in keyword_ids[:100]]}
    resp = ads_post("/sp/keywords/bidRecommendations", lwa_ads, body)
    return resp.get("bidRecommendationsSuccess", []) if isinstance(resp, dict) else []
