"""Shared — Amazon Ads API v3 HTTP flow (Reports + Campaign Management).

Tách riêng phần HTTP thuần (auth header, request/poll/download report, GET/POST
mgmt endpoints) để CẢ Phase1_Fetch (gọi API lưu file) lẫn các module khác dùng
chung — không lặp code, không gọi API 2 lần.

Auth: Bearer LWA token + Amazon-Advertising-API-Scope (profile ID).
KHÔNG dùng AWS SigV4 cho Ads API. Retry 429 với Retry-After + backoff.

Import:
    from shared.ads_api import (request_report, poll_until_done, download_report,
                                ads_get, ads_post)
"""
import gzip
import io
import json
import time

import requests

from shared.config import ADS_BASE, ADS_CLIENT_ID, ADS_PROFILE_ID, POLL_INTERVAL, POLL_TIMEOUT


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

def ads_get(path: str, lwa_ads: str, profile_id: str = None, params: dict = None):
    r = requests.get(f"{ADS_BASE}{path}", headers=_headers(lwa_ads, profile_id),
                     params=params or {}, timeout=30)
    if not r.ok:
        print(f"  [ADS GET] ❌ {r.status_code} {path}: {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def ads_post(path: str, lwa_ads: str, body, retries: int = 7):
    for attempt in range(retries):
        r = requests.post(f"{ADS_BASE}{path}", headers=_headers(lwa_ads),
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


# ── Reports API v3 (async flow) ───────────────────────────────────────────────

def request_report(lwa_ads: str, config: dict, name: str, report_date: str) -> str:
    """POST /reporting/reports -> reportId. Xử lý 425 duplicate (trả lại id cũ)."""
    body = {"name": f"{name} {report_date}", "startDate": report_date,
            "endDate": report_date, "configuration": config}
    try:
        resp = ads_post("/reporting/reports", lwa_ads, body)
    except requests.HTTPError as exc:
        r = exc.response
        if r is not None and r.status_code == 425:
            import re
            m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                          r.text)
            if m:
                print(f"  [ADS] {name}: 425 duplicate → dùng lại reportId={m.group(0)[:12]}...")
                return m.group(0)
        raise
    print(f"  [ADS] {name}: reportId={resp.get('reportId','')[:12]}... "
          f"status={resp.get('status','')}")
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
