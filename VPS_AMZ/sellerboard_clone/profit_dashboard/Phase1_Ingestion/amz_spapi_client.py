"""Phase 1 — SP-API client (Orders / Order Items / Finances).

Hợp nhất logic auth đã kiểm chứng của pipeline test_lwa_spapi/Phase 2
(_auth.py + fetch_24h_orders.py) thành 1 module import được:

  - LWA OAuth2 (refresh token -> access token)
  - AWS STS AssumeRole + SigV4 (tuỳ chọn — thiếu AWS creds thì LWA-only)
  - spapi_get(): GET có retry 429 (Retry-After + backoff)
  - iter_orders_pages():           generator, mỗi lần yield 1 TRANG orders (<=100)
  - fetch_order_items():           items của 1 đơn (giãn cách rate-limit)
  - iter_financial_events_pages(): generator, mỗi lần yield 1 TRANG FinancialEvents

QUY TẮC MEMORY-SAFETY: module này KHÔNG BAO GIỜ tích lũy nhiều trang vào
1 list — caller (direct_stream_pipeline.py) chịu trách nhiệm upsert từng
trang vào Supabase rồi `del` + `gc.collect()`.
"""
import hashlib
import hmac
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID      = os.getenv("AMAZON_SPI_CLIENT_ID", "")
CLIENT_SECRET  = os.getenv("AMAZON_SPI_CLIENT_SECRET", "")
SP_REFRESH     = os.getenv("AMAZON_SPI_REFRESH_TOKEN", "")
MARKETPLACE_ID = os.getenv("AMAZON_SPI_MARKETPLACE_ID", "ATVPDKIKX0DER")
AWS_KEY        = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET     = os.getenv("AWS_SECRET_ACCESS_KEY", "")
ROLE_ARN       = os.getenv("AWS_ROLE_ARN", "")
AWS_REGION     = os.getenv("AWS_REGION", "us-east-1")

SP_BASE = "https://sellingpartnerapi-na.amazon.com"
LWA_URL = "https://api.amazon.com/auth/o2/token"
STS_URL = "https://sts.amazonaws.com/"

PAGE_SIZE = 100                                       # chunk <=100 records/trang
ORDER_ITEMS_DELAY = float(os.getenv("ORDER_ITEMS_DELAY_SECONDS", "1.0"))
FINANCES_PAGE_DELAY = float(os.getenv("FINANCES_PAGE_DELAY_SECONDS", "1.0"))


# ── LWA ───────────────────────────────────────────────────────────────────────

def get_lwa_token(refresh_token: str = None, client_id: str = None,
                  client_secret: str = None) -> str:
    r = requests.post(LWA_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token or SP_REFRESH,
        "client_id":     client_id or CLIENT_ID,
        "client_secret": client_secret or CLIENT_SECRET,
    }, timeout=15)
    if not r.ok:
        print(f"  [LWA] ❌ {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"  [LWA] OK: {token[:20]}...")
    return token


# ── SigV4 + STS ───────────────────────────────────────────────────────────────

def _sign(key, msg):
    return hmac.new(key if isinstance(key, bytes) else key.encode(),
                    msg.encode(), hashlib.sha256).digest()


def _signing_key(secret, date, region, service):
    k = _sign(("AWS4" + secret).encode(), date)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")


def _sigv4_headers(method, url, extra_headers, body, key, secret, token,
                   region, service="execute-api"):
    parsed     = urlparse(url)
    now        = datetime.now(timezone.utc)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    h = {k.lower(): v.strip() for k, v in extra_headers.items()}
    h["host"]       = parsed.netloc
    h["x-amz-date"] = amz_date
    if token:
        h["x-amz-security-token"] = token
    sh_list = sorted(h.keys())
    canon_h = "".join(f"{k}:{h[k]}\n" for k in sh_list)
    sh      = ";".join(sh_list)
    ph      = hashlib.sha256(body.encode()).hexdigest()
    cr      = "\n".join([method, quote(parsed.path or "/", safe="/-_.~"),
                         parsed.query, canon_h, sh, ph])
    scope   = f"{date_stamp}/{region}/{service}/aws4_request"
    sts_str = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(cr.encode()).hexdigest()])
    sig     = hmac.new(_signing_key(secret, date_stamp, region, service),
                       sts_str.encode(), hashlib.sha256).hexdigest()
    h["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={key}/{scope}, "
                          f"SignedHeaders={sh}, Signature={sig}")
    return h


def get_sts_creds():
    print("  [STS] Assume Role...")
    params   = {"Action": "AssumeRole", "RoleArn": ROLE_ARN,
                "RoleSessionName": "IngestionSession",
                "DurationSeconds": "3600", "Version": "2011-06-15"}
    body_str = urlencode(params)
    signed   = _sigv4_headers("POST", STS_URL,
                              {"content-type": "application/x-www-form-urlencoded"},
                              body_str, AWS_KEY, AWS_SECRET, "", "us-east-1", "sts")
    r = requests.post(STS_URL, data=body_str, headers=signed, timeout=15)
    r.raise_for_status()
    import xml.etree.ElementTree as ET
    ns    = {"s": "https://sts.amazonaws.com/doc/2011-06-15/"}
    creds = ET.fromstring(r.text).find(".//s:Credentials", ns)
    sk = creds.find("s:AccessKeyId", ns).text
    ss = creds.find("s:SecretAccessKey", ns).text
    st = creds.find("s:SessionToken", ns).text
    print(f"  [STS] OK: key={sk[:10]}...")
    return sk, ss, st


def auth_session():
    """Trả về (lwa, sk, ss, st). Thiếu AWS creds / STS lỗi -> LWA-only."""
    missing = [k for k, v in {"AMAZON_SPI_CLIENT_ID": CLIENT_ID,
                              "AMAZON_SPI_CLIENT_SECRET": CLIENT_SECRET,
                              "AMAZON_SPI_REFRESH_TOKEN": SP_REFRESH}.items() if not v]
    if missing:
        raise ValueError(f"Thiếu credentials SP-API trong .env: {missing}")
    lwa = get_lwa_token()
    if all([AWS_KEY, AWS_SECRET, ROLE_ARN]):
        try:
            return (lwa, *get_sts_creds())
        except Exception as exc:                       # noqa: BLE001
            print(f"  ⚠️  STS thất bại: {exc} → chuyển LWA-only")
    else:
        print("  [Auth] LWA-only mode (không dùng AWS SigV4)")
    return lwa, None, None, None


# ── HTTP wrapper (retry 429) ──────────────────────────────────────────────────

def spapi_get(path, params, lwa, sk=None, ss=None, st=None, retries=6):
    url = f"{SP_BASE}{path}"
    # SigV4 yêu cầu query string SORTED alphabetically và ký cùng URL
    full_url = f"{url}?{urlencode(sorted(params.items()))}" if params else url
    if sk and ss:
        headers = _sigv4_headers("GET", full_url,
                                 {"x-amz-access-token": lwa,
                                  "content-type": "application/json"},
                                 "", sk, ss, st, AWS_REGION)
    else:
        headers = {"x-amz-access-token": lwa, "content-type": "application/json"}
    for attempt in range(retries):
        r = requests.get(full_url, headers=headers, timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            wait = max(float(r.headers.get("Retry-After", 2.0)), 2.0) + attempt * 2
            print(f"    ⚠️  429 {path} → đợi {wait:.0f}s (lần {attempt + 1})")
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"    ❌ HTTP {r.status_code} {path}: {r.text[:500]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Hết retry cho {path}")


# ── Generators phân trang (mỗi yield = 1 trang <=100 records) ─────────────────

def iter_orders_pages(session, created_after: str, created_before: str = None):
    """Yield từng trang Orders (list <=100 dict) theo NextToken."""
    lwa, sk, ss, st = session
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"MarketplaceIds": MARKETPLACE_ID, "MaxResultsPerPage": PAGE_SIZE}
        if next_token:
            params["NextToken"] = next_token
        else:
            params["CreatedAfter"] = created_after
            if created_before:
                params["CreatedBefore"] = created_before
        resp = spapi_get("/orders/v0/orders", params, lwa, sk, ss, st)
        payload = resp.get("payload", {})
        orders = payload.get("Orders", [])
        next_token = payload.get("NextToken")
        print(f"  [Orders] Trang {page}: {len(orders)} orders (NextToken: {bool(next_token)})")
        yield orders
        if not next_token:
            return


def fetch_order_items(session, order_id: str) -> list:
    """Items của 1 đơn — giãn cách ORDER_ITEMS_DELAY để né rate limit 429."""
    lwa, sk, ss, st = session
    resp = spapi_get(f"/orders/v0/orders/{order_id}/orderItems", {}, lwa, sk, ss, st)
    time.sleep(ORDER_ITEMS_DELAY)
    return resp.get("payload", {}).get("OrderItems", [])


def iter_financial_events_pages(session, posted_after: str, posted_before: str = None):
    """Yield từng trang FinancialEvents (dict các EventList) theo NextToken."""
    lwa, sk, ss, st = session
    next_token = None
    page = 0
    while True:
        page += 1
        if next_token:
            params = {"NextToken": next_token}
        else:
            params = {"PostedAfter": posted_after, "MaxResultsPerPage": PAGE_SIZE}
            if posted_before:
                params["PostedBefore"] = posted_before
        resp = spapi_get("/finances/v0/financialEvents", params, lwa, sk, ss, st)
        payload = resp.get("payload", {})
        events = payload.get("FinancialEvents", {})
        next_token = payload.get("NextToken")
        counts = {k: len(v) for k, v in events.items() if isinstance(v, list) and v}
        print(f"  [Finances] Trang {page}: {counts or 'rỗng'} (NextToken: {bool(next_token)})")
        yield events
        if not next_token:
            return
        time.sleep(FINANCES_PAGE_DELAY)
