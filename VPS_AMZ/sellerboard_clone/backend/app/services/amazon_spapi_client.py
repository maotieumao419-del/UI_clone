import hashlib, hmac, json, time, threading
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, urlencode
import requests

_LWA_URL   = "https://api.amazon.com/auth/o2/token"
_STS_URL   = "https://sts.amazonaws.com/"
_SPAPI_BASE= "https://sellingpartnerapi-na.amazon.com"
_ENDPOINTS = {
    "ATVPDKIKX0DER": "https://sellingpartnerapi-na.amazon.com",
    "A2EUQ1WTGCTBG2": "https://sellingpartnerapi-na.amazon.com",
}


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def _signing_key(secret, date, region, service):
    k = _sign(("AWS4" + secret).encode(), date)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")

def _sigv4(method, url, headers, body, key, secret, token, region="us-east-1", service="execute-api"):
    parsed = urlparse(url)
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    ch = {k.lower(): v.strip() for k, v in headers.items()}
    ch["host"] = parsed.netloc
    ch["x-amz-date"] = amz_date
    if token:
        ch["x-amz-security-token"] = token
    sh_list = sorted(ch.keys())
    canon_h = "".join(f"{k}:{ch[k]}\n" for k in sh_list)
    sh = ";".join(sh_list)
    ph = hashlib.sha256(body.encode()).hexdigest()
    cr = "\n".join([method, quote(parsed.path or "/", safe="/-_.~"), parsed.query, canon_h, sh, ph])
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(cr.encode()).hexdigest()])
    sig = hmac.new(_signing_key(secret, date_stamp, region, service), sts.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={key}/{scope}, SignedHeaders={sh}, Signature={sig}"
    result = {**ch, "Authorization": auth}
    return result


class AmazonSPAPIClient:
    def __init__(self, client_id, client_secret, refresh_token, marketplace_id,
                 aws_access_key, aws_secret_key, role_arn, aws_region="us-east-1"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.marketplace_id = marketplace_id
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.role_arn = role_arn
        self.aws_region = aws_region
        self.base_url = _ENDPOINTS.get(marketplace_id, _SPAPI_BASE)
        self._lwa_token = None
        self._lwa_expiry = 0
        self._sts_key = self._sts_secret = self._sts_token = None
        self._sts_expiry = 0
        self._lock = threading.Lock()

    def _get_lwa_token(self):
        with self._lock:
            if self._lwa_token and time.time() < self._lwa_expiry - 60:
                return self._lwa_token
            resp = requests.post(_LWA_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self._lwa_token = data["access_token"]
            self._lwa_expiry = time.time() + data.get("expires_in", 3600)
            return self._lwa_token

    def _get_sts(self):
        with self._lock:
            if self._sts_key and time.time() < self._sts_expiry - 60:
                return self._sts_key, self._sts_secret, self._sts_token
            params = {"Action":"AssumeRole","RoleArn":self.role_arn,
                      "RoleSessionName":"SPAPISession","DurationSeconds":"3600","Version":"2011-06-15"}
            body_str = urlencode(params)
            signed = _sigv4("POST", _STS_URL, {"content-type":"application/x-www-form-urlencoded"},
                            body_str, self.aws_access_key, self.aws_secret_key, "", "us-east-1", "sts")
            resp = requests.post(_STS_URL, data=body_str, headers=signed, timeout=15)
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            ns = {"s": "https://sts.amazonaws.com/doc/2011-06-15/"}
            creds = root.find(".//s:Credentials", ns)
            self._sts_key    = creds.find("s:AccessKeyId", ns).text
            self._sts_secret = creds.find("s:SecretAccessKey", ns).text
            self._sts_token  = creds.find("s:SessionToken", ns).text
            self._sts_expiry = time.time() + 3500
            return self._sts_key, self._sts_secret, self._sts_token

    def _request(self, method, path, params=None, json_body=None):
        url = f"{self.base_url}{path}"
        lwa = self._get_lwa_token()
        sk, ss, st = self._get_sts()
        body_str = json.dumps(json_body) if json_body else ""
        signed = _sigv4(method, url, {"x-amz-access-token": lwa, "content-type": "application/json"},
                        body_str, sk, ss, st, self.aws_region, "execute-api")
        if params:
            url = f"{url}?{urlencode(params)}"
        for attempt in range(8):
            resp = requests.request(method, url, headers=signed, data=body_str or None, timeout=30)
            if resp.status_code == 429 and attempt < 7:
                # Amazon lam moi quota cho getOrders ~60s/lan; cho it se bi 429 lap lai.
                wait = max(float(resp.headers.get("Retry-After", 20)), 20) + attempt * 10
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp

    def get_orders(self, created_after=None, created_before=None, next_token=None):
        params = {"MarketplaceIds": self.marketplace_id, "MaxResultsPerPage": 100}
        if next_token:
            params["NextToken"] = next_token
        else:
            if created_after:
                params["CreatedAfter"] = created_after
            if created_before:
                params["CreatedBefore"] = created_before
        return self._request("GET", "/orders/v0/orders", params=params).json()

    def get_inventory(self):
        return self._request("GET", "/fba/inventory/v1/summaries", params={
            "granularityType": "Marketplace", "granularityId": self.marketplace_id,
            "marketplaceIds": self.marketplace_id}).json()

    def get_sales_metrics(self, interval, granularity="Day"):
        return self._request("GET", "/sales/v1/orderMetrics", params={
            "marketplaceIds": self.marketplace_id,
            "interval": interval, "granularity": granularity}).json()

    # ── Settlement Reports API ────────────────────────────────────────────────

    def get_latest_settlement_report_document_id(self) -> str:
        """Lấy documentId của Settlement Report mới nhất đã được Amazon sinh sẵn.

        Settlement reports được Amazon tạo tự động theo chu kỳ thanh toán (~2 tuần).
        Không thể tạo on-demand bằng POST — report type này trả 400 nếu dùng POST.
        """
        resp = self._request("GET", "/reports/2021-06-30/reports", params={
            "reportTypes": "GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE",
            "processingStatuses": "DONE",
            "pageSize": 1,
        })
        reports = resp.json().get("reports", [])
        if not reports:
            return ""
        return reports[0].get("reportDocumentId", "")

    def get_report_status(self, report_id: str) -> dict:
        """Poll trạng thái report. processingStatus: IN_QUEUE / IN_PROGRESS / DONE / FATAL."""
        return self._request("GET", f"/reports/2021-06-30/reports/{report_id}").json()

    def get_report_document_url(self, document_id: str) -> str:
        """Lấy URL S3 presigned để tải file report về."""
        data = self._request("GET", f"/reports/2021-06-30/documents/{document_id}").json()
        return data.get("url", "")

    def download_report_text(self, url: str) -> str:
        """Tải nội dung file TSV report từ S3 (không cần ký SigV4 — URL đã presigned)."""
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        # Amazon có thể nén bằng gzip
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            return gzip.decompress(resp.content).decode("utf-8")
        return resp.text


def get_spapi_client():
    from ..config import settings
    return AmazonSPAPIClient(
        client_id=settings.AMAZON_SPI_CLIENT_ID,
        client_secret=settings.AMAZON_SPI_CLIENT_SECRET,
        refresh_token=settings.AMAZON_SPI_REFRESH_TOKEN,
        marketplace_id=settings.AMAZON_SPI_MARKETPLACE_ID,
        aws_access_key=settings.AWS_ACCESS_KEY_ID,
        aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
        role_arn=settings.AWS_ROLE_ARN,
        aws_region=settings.AWS_REGION,
    )
