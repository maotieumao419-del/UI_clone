"""
Module dùng chung: LWA token, STS role, SigV4 — để các script khác import.
fetch_24h_orders.py tự có bản riêng (giữ nguyên), module này dùng cho files mới.
"""
import hashlib, hmac, json, os, time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, urlencode
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID      = os.getenv("AMAZON_SPI_CLIENT_ID",      "")
CLIENT_SECRET  = os.getenv("AMAZON_SPI_CLIENT_SECRET",   "")
SP_REFRESH     = os.getenv("AMAZON_SPI_REFRESH_TOKEN",   "")
ADS_REFRESH    = os.getenv("AMAZON_ADS_REFRESH_TOKEN",   "") or os.getenv("AMAZON_SPI_REFRESH_TOKEN", "")
ADS_CLIENT_ID  = os.getenv("AMAZON_ADS_CLIENT_ID",       "") or os.getenv("AMAZON_SPI_CLIENT_ID",      "")
ADS_CLIENT_SECRET = os.getenv("AMAZON_ADS_CLIENT_SECRET","") or os.getenv("AMAZON_SPI_CLIENT_SECRET",  "")
MARKETPLACE_ID = os.getenv("AMAZON_SPI_MARKETPLACE_ID", "ATVPDKIKX0DER")
AWS_KEY        = os.getenv("AWS_ACCESS_KEY_ID",          "")
AWS_SECRET     = os.getenv("AWS_SECRET_ACCESS_KEY",      "")
ROLE_ARN       = os.getenv("AWS_ROLE_ARN",               "")
AWS_REGION     = os.getenv("AWS_REGION",                 "us-east-1")
ADS_PROFILE_ID = os.getenv("ADS_PROFILE_ID",             "")

SP_BASE  = "https://sellingpartnerapi-na.amazon.com"
ADS_BASE = "https://advertising-api.amazon.com"
LWA_URL  = "https://api.amazon.com/auth/o2/token"
STS_URL  = "https://sts.amazonaws.com/"


# ── LWA token ─────────────────────────────────────────────────────────────────

def get_lwa_token(refresh_token: str = None, client_id: str = None, client_secret: str = None) -> str:
    rt  = refresh_token or SP_REFRESH
    cid = client_id     or CLIENT_ID
    cs  = client_secret or CLIENT_SECRET
    r = requests.post(LWA_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": rt,
        "client_id":     cid,
        "client_secret": cs,
    }, timeout=15)
    if not r.ok:
        print(f"  [LWA] ❌ {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"  [LWA] OK: {token[:20]}...")
    return token


# ── STS role assumption ────────────────────────────────────────────────────────

def _sign(key, msg):
    return hmac.new(key if isinstance(key, bytes) else key.encode(), msg.encode(), hashlib.sha256).digest()

def _signing_key(secret, date, region, service):
    k = _sign(("AWS4" + secret).encode(), date)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")

def _sigv4_headers(method, url, extra_headers, body, key, secret, token, region, service="execute-api"):
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
    qs      = parsed.query
    cr      = "\n".join([method, quote(parsed.path or "/", safe="/-_.~"), qs, canon_h, sh, ph])
    scope   = f"{date_stamp}/{region}/{service}/aws4_request"
    sts_str = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(cr.encode()).hexdigest()])
    sig     = hmac.new(_signing_key(secret, date_stamp, region, service), sts_str.encode(), hashlib.sha256).hexdigest()
    h["Authorization"] = f"AWS4-HMAC-SHA256 Credential={key}/{scope}, SignedHeaders={sh}, Signature={sig}"
    return h

def get_sts_creds():
    print("  [STS] Assume Role...")
    params   = {"Action": "AssumeRole", "RoleArn": ROLE_ARN,
                "RoleSessionName": "DebugSession", "DurationSeconds": "3600", "Version": "2011-06-15"}
    body_str = urlencode(params)
    signed   = _sigv4_headers("POST", STS_URL,
                               {"content-type": "application/x-www-form-urlencoded"},
                               body_str, AWS_KEY, AWS_SECRET, "", "us-east-1", "sts")
    r = requests.post(STS_URL, data=body_str, headers=signed, timeout=15)
    r.raise_for_status()
    import xml.etree.ElementTree as ET
    ns    = {"s": "https://sts.amazonaws.com/doc/2011-06-15/"}
    root  = ET.fromstring(r.text)
    creds = root.find(".//s:Credentials", ns)
    sk  = creds.find("s:AccessKeyId",    ns).text
    ss  = creds.find("s:SecretAccessKey", ns).text
    st  = creds.find("s:SessionToken",    ns).text
    print(f"  [STS] OK: key={sk[:10]}...")
    return sk, ss, st


# ── SP-API HTTP wrapper ────────────────────────────────────────────────────────

def spapi_get(path, params, lwa, sk=None, ss=None, st=None, retries=6):
    url      = f"{SP_BASE}{path}"
    # SigV4 yêu cầu query string phải SORTED alphabetically và được ký cùng URL
    full_url = f"{url}?{urlencode(sorted(params.items()))}" if params else url
    if sk and ss:
        signed = _sigv4_headers("GET", full_url,   # ← ký full_url (có sorted params)
                                 {"x-amz-access-token": lwa, "content-type": "application/json"},
                                 "", sk, ss, st, AWS_REGION)
    else:
        signed = {"x-amz-access-token": lwa, "content-type": "application/json"}
    for attempt in range(retries):
        r = requests.get(full_url, headers=signed, timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            wait = max(float(r.headers.get("Retry-After", 2.0)), 2.0) + attempt * 2
            print(f"    ⚠️  429 {path} → đợi {wait:.0f}s (lần {attempt+1})")
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"    ❌ HTTP {r.status_code} {path}")
            print(f"    Response: {r.text[:500]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Hết retry cho {path}")


# ── ADS-API HTTP wrapper ───────────────────────────────────────────────────────

def ads_get(path, lwa_ads, profile_id=None, params=None):
    pid = profile_id or ADS_PROFILE_ID
    headers = {
        "Authorization":                    f"Bearer {lwa_ads}",
        "Amazon-Advertising-API-ClientId":  ADS_CLIENT_ID,
        "Content-Type":                     "application/json",
    }
    if pid:
        headers["Amazon-Advertising-API-Scope"] = str(pid)
    r = requests.get(f"{ADS_BASE}{path}", headers=headers, params=params or {}, timeout=30)
    if not r.ok:
        print(f"    [ADS GET] ❌ {r.status_code} {path}: {r.text}")
    r.raise_for_status()
    return r.json()

def ads_post(path, lwa_ads, body, profile_id=None, retries=5):
    pid = profile_id or ADS_PROFILE_ID
    headers = {
        "Authorization":                    f"Bearer {lwa_ads}",
        "Amazon-Advertising-API-ClientId":  ADS_CLIENT_ID,
        "Content-Type":                     "application/json",
    }
    if pid:
        headers["Amazon-Advertising-API-Scope"] = str(pid)
    for attempt in range(retries):
        r = requests.post(f"{ADS_BASE}{path}", headers=headers,
                          data=json.dumps(body), timeout=30)
        if r.status_code == 429 and attempt < retries - 1:
            wait = float(r.headers.get("Retry-After", 5)) + attempt * 3
            print(f"    [ADS POST] ⚠️  429 → đợi {wait:.0f}s (lần {attempt+1})")
            time.sleep(wait)
            continue
        if not r.ok:
            print(f"    [ADS POST] ❌ {r.status_code} {path}: {r.text}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Hết retry cho {path}")


# ── Field schema collector ────────────────────────────────────────────────────

def collect_fields(obj, prefix="", result=None):
    if result is None:
        result = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{prefix}.{k}" if prefix else k
            t    = type(v).__name__
            if full not in result:
                result[full] = {"type": t, "example": str(v)[:80] if not isinstance(v, (dict, list)) else "..."}
            collect_fields(v, full, result)
    elif isinstance(obj, list) and obj:
        collect_fields(obj[0], f"{prefix}[]", result)
    return result

def write_fields_map(fields: dict, out_path, label="FIELDS"):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"=== {label} ({len(fields)} fields) ===\n")
        f.write(f"{'Field':<55} {'Type':<10} Example\n")
        f.write("-" * 110 + "\n")
        for k, v in sorted(fields.items()):
            f.write(f"{k:<55} {v['type']:<10} {v['example']}\n")
    print(f"  → Fields map: {out_path}")
