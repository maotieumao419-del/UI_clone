"""
Gọi Amazon SP-API lấy orders 24h gần nhất — LWA + SigV4 + STS Role.
Lưu toàn bộ dữ liệu thô ra file JSON để phân tích schema.

Chạy:
    pip install requests python-dotenv
    python fetch_24h_orders.py

Output:
    raw_data/orders_24h_raw.json   — toàn bộ orders + order_items
    raw_data/fields_map.txt        — danh sách field xuất hiện
"""
import hashlib, hmac, json, time, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse, urlencode
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Credentials từ .env ──────────────────────────────────────────────────────
CLIENT_ID      = os.getenv("AMAZON_SPI_CLIENT_ID", "")
CLIENT_SECRET  = os.getenv("AMAZON_SPI_CLIENT_SECRET", "")
REFRESH_TOKEN  = os.getenv("AMAZON_SPI_REFRESH_TOKEN", "")
MARKETPLACE_ID = os.getenv("AMAZON_SPI_MARKETPLACE_ID", "ATVPDKIKX0DER")
AWS_KEY        = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET     = os.getenv("AWS_SECRET_ACCESS_KEY", "")
ROLE_ARN       = os.getenv("AWS_ROLE_ARN", "")
AWS_REGION     = os.getenv("AWS_REGION", "us-east-1")

SP_BASE   = "https://sellingpartnerapi-na.amazon.com"
LWA_URL   = "https://api.amazon.com/auth/o2/token"
STS_URL   = "https://sts.amazonaws.com/"
OUT_DIR   = Path("raw_data")
OUT_DIR.mkdir(exist_ok=True)

# ── SigV4 ────────────────────────────────────────────────────────────────────
def _sign(key, msg):
    return hmac.new(key if isinstance(key, bytes) else key.encode(), msg.encode(), hashlib.sha256).digest()

def _signing_key(secret, date, region, service):
    k = _sign(("AWS4" + secret).encode(), date)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")

def _sigv4_headers(method, url, extra_headers, body, key, secret, token, region, service="execute-api"):
    parsed = urlparse(url)
    now = datetime.now(timezone.utc)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    h = {k.lower(): v.strip() for k, v in extra_headers.items()}
    h["host"]       = parsed.netloc
    h["x-amz-date"] = amz_date
    if token:
        h["x-amz-security-token"] = token
    sh_list  = sorted(h.keys())
    canon_h  = "".join(f"{k}:{h[k]}\n" for k in sh_list)
    sh       = ";".join(sh_list)
    ph       = hashlib.sha256(body.encode()).hexdigest()
    qs       = parsed.query
    cr       = "\n".join([method, quote(parsed.path or "/", safe="/-_.~"), qs, canon_h, sh, ph])
    scope    = f"{date_stamp}/{region}/{service}/aws4_request"
    sts_str  = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(cr.encode()).hexdigest()])
    sig      = hmac.new(_signing_key(secret, date_stamp, region, service), sts_str.encode(), hashlib.sha256).hexdigest()
    h["Authorization"] = f"AWS4-HMAC-SHA256 Credential={key}/{scope}, SignedHeaders={sh}, Signature={sig}"
    return h

# ── Auth ─────────────────────────────────────────────────────────────────────
def get_lwa_token():
    print("  [Auth] Lấy LWA access token...")
    r = requests.post(LWA_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }, timeout=15)
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"  [Auth] LWA OK: {token[:20]}...")
    return token

def get_sts_creds():
    print("  [Auth] Assume STS Role...")
    params   = {"Action": "AssumeRole", "RoleArn": ROLE_ARN,
                "RoleSessionName": "InspectSession", "DurationSeconds": "3600", "Version": "2011-06-15"}
    body_str = urlencode(params)
    signed   = _sigv4_headers("POST", STS_URL,
                               {"content-type": "application/x-www-form-urlencoded"},
                               body_str, AWS_KEY, AWS_SECRET, "", "us-east-1", "sts")
    r = requests.post(STS_URL, data=body_str, headers=signed, timeout=15)
    r.raise_for_status()
    import xml.etree.ElementTree as ET
    root  = ET.fromstring(r.text)
    ns    = {"s": "https://sts.amazonaws.com/doc/2011-06-15/"}
    creds = root.find(".//s:Credentials", ns)
    sk    = creds.find("s:AccessKeyId",     ns).text
    ss    = creds.find("s:SecretAccessKey",  ns).text
    st    = creds.find("s:SessionToken",     ns).text
    print(f"  [Auth] STS OK: key={sk[:10]}...")
    return sk, ss, st

def spapi_get(path, params, lwa, sk=None, ss=None, st=None):
    url      = f"{SP_BASE}{path}"
    # SigV4 yêu cầu query string phải SORTED alphabetically và được ký cùng URL
    full_url = f"{url}?{urlencode(sorted(params.items()))}" if params else url
    if sk and ss:
        signed = _sigv4_headers("GET", full_url,   # ← ký full_url (có sorted params)
                                 {"x-amz-access-token": lwa, "content-type": "application/json"},
                                 "", sk, ss, st, AWS_REGION)
    else:
        signed = {"x-amz-access-token": lwa, "content-type": "application/json"}
    
    for attempt in range(6):
        r = requests.get(full_url, headers=signed, timeout=30)
        if r.status_code == 429 and attempt < 5:
            retry_after = float(r.headers.get("Retry-After", 2.0))
            wait_time = max(retry_after, 2.0) + attempt * 2.0
            print(f"\n    ⚠️  [Rate Limit] Gặp lỗi 429 khi gọi {path}. Đang đợi {wait_time}s rồi thử lại (lần {attempt + 1})...")
            time.sleep(wait_time)
            continue
        r.raise_for_status()
        return r.json()

# ── Flatten fields (đệ quy) ──────────────────────────────────────────────────
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

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("FETCH AMAZON ORDERS — 24H — LWA + SigV4 + STS")
    print("=" * 60)

    lwa_missing = [k for k, v in {
        "CLIENT_ID": CLIENT_ID, "CLIENT_SECRET": CLIENT_SECRET,
        "REFRESH_TOKEN": REFRESH_TOKEN
    }.items() if not v]
    if lwa_missing:
        print(f"❌ Thiếu credentials LWA: {lwa_missing}")
        return

    use_sigv4 = all([AWS_KEY, AWS_SECRET, ROLE_ARN])

    lwa = get_lwa_token()
    if use_sigv4:
        print("  [Auth] Sử dụng AWS SigV4 + STS...")
        try:
            sk, ss, st  = get_sts_creds()
        except Exception as e:
            print(f"  ❌ Lỗi khi Assume STS Role: {e}")
            print("  Thử tự động chuyển sang chế độ LWA-only...")
            sk = ss = st = None
    else:
        print("  [Auth] Sử dụng chế độ LWA-only (không dùng AWS SigV4)...")
        sk = ss = st = None

    created_after = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\nKéo orders từ: {created_after}")

    # ── Kéo orders ──────────────────────────────────────────────────────────
    all_orders  = []
    next_token  = None
    page        = 0

    while True:
        page += 1
        params = {"MarketplaceIds": MARKETPLACE_ID, "MaxResultsPerPage": 100}
        if next_token:
            params["NextToken"] = next_token
        else:
            params["CreatedAfter"] = created_after

        print(f"  Trang {page}...", end=" ")
        resp        = spapi_get("/orders/v0/orders", params, lwa, sk, ss, st)
        payload     = resp.get("payload", {})
        orders      = payload.get("Orders", [])
        next_token  = payload.get("NextToken")
        print(f"{len(orders)} orders (NextToken: {bool(next_token)})")

        # ── Lấy OrderItems cho từng order ───────────────────────────────────
        for o in orders:
            oid = o.get("AmazonOrderId", "")
            try:
                items_resp   = spapi_get(f"/orders/v0/orders/{oid}/orderItems", {}, lwa, sk, ss, st)
                o["_items"] = items_resp.get("payload", {}).get("OrderItems", [])
            except Exception as e:
                print(f"    ⚠️  OrderItems {oid}: {e}")
                o["_items"] = []
            time.sleep(1.0)

        all_orders.extend(orders)
        if not next_token:
            break

    print(f"\nTổng: {len(all_orders)} orders trong 24h")

    # ── Lưu raw JSON ─────────────────────────────────────────────────────────
    raw_file = OUT_DIR / "orders_24h_raw.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(all_orders, f, ensure_ascii=False, indent=2, default=str)
    print(f"→ Raw data: {raw_file}  ({raw_file.stat().st_size // 1024} KB)")

    # ── Phân tích fields ─────────────────────────────────────────────────────
    order_fields = {}
    item_fields  = {}
    for o in all_orders:
        items = o.pop("_items", [])
        collect_fields(o, "", order_fields)
        for item in items:
            collect_fields(item, "", item_fields)

    fields_file = OUT_DIR / "fields_map.txt"
    with open(fields_file, "w", encoding="utf-8") as f:
        f.write("=== ORDER FIELDS ===\n")
        f.write(f"{'Field':<45} {'Type':<10} Example\n")
        f.write("-" * 90 + "\n")
        for k, v in sorted(order_fields.items()):
            f.write(f"{k:<45} {v['type']:<10} {v['example']}\n")
        f.write("\n=== ORDER ITEM FIELDS ===\n")
        f.write(f"{'Field':<45} {'Type':<10} Example\n")
        f.write("-" * 90 + "\n")
        for k, v in sorted(item_fields.items()):
            f.write(f"{k:<45} {v['type']:<10} {v['example']}\n")

    print(f"→ Fields map: {fields_file}")

    # In nhanh ra màn hình
    print(f"\n{'─'*45} ORDER FIELDS ({len(order_fields)})")
    for k, v in sorted(order_fields.items()):
        print(f"  {k:<45} {v['type']:<10} {v['example']}")

    print(f"\n{'─'*45} ORDER ITEM FIELDS ({len(item_fields)})")
    for k, v in sorted(item_fields.items()):
        print(f"  {k:<45} {v['type']:<10} {v['example']}")

if __name__ == "__main__":
    main()
