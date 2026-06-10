import time, threading, requests

_ADS_ENDPOINTS = {
    "NA": "https://advertising-api.amazon.com",
    "EU": "https://advertising-api-eu.amazon.com",
    "FE": "https://advertising-api-fe.amazon.com",
}
_LWA_URL = "https://api.amazon.com/auth/o2/token"


class AmazonAdsClient:
    def __init__(self, client_id, client_secret, refresh_token, profile_id, region="NA"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.profile_id = str(profile_id)
        self.base_url = _ADS_ENDPOINTS.get(region.upper(), _ADS_ENDPOINTS["NA"])
        self._access_token = None
        self._token_expiry = 0
        self._lock = threading.Lock()

    def _get_access_token(self):
        with self._lock:
            if self._access_token and time.time() < self._token_expiry - 60:
                return self._access_token
            resp = requests.post(_LWA_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expiry = time.time() + data.get("expires_in", 3600)
            return self._access_token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Amazon-Advertising-API-ClientId": self.client_id,
            "Amazon-Advertising-API-Scope": self.profile_id,
            "Content-Type": "application/json",
        }

    def get(self, path, **kwargs):
        return requests.get(f"{self.base_url}{path}", headers=self._headers(), timeout=30, **kwargs)

    def post(self, path, **kwargs):
        return requests.post(f"{self.base_url}{path}", headers=self._headers(), timeout=30, **kwargs)

    def list_profiles(self):
        r = requests.get(f"{self.base_url}/v2/profiles", headers={
            "Authorization": f"Bearer {self._get_access_token()}",
            "Amazon-Advertising-API-ClientId": self.client_id,
        }, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_campaigns(self, state_filter="enabled,paused"):
        r = self.get("/v2/sp/campaigns", params={"stateFilter": state_filter})
        r.raise_for_status()
        return r.json()

    def get_keywords(self, ad_group_id=None):
        params = {"stateFilter": "enabled,paused,archived"}
        if ad_group_id:
            params["adGroupIdFilter"] = ad_group_id
        r = self.get("/v2/sp/keywords", params=params)
        r.raise_for_status()
        return r.json()

    def request_report(self, record_type, metrics, report_date, segment=None):
        body = {"reportDate": report_date, "metrics": ",".join(metrics)}
        if segment:
            body["segment"] = segment
        r = self.post(f"/v2/sp/{record_type}/report", json=body)
        r.raise_for_status()
        return r.json()

    def get_report(self, report_id):
        r = self.get(f"/v2/reports/{report_id}")
        r.raise_for_status()
        return r.json()

    def download_report(self, location):
        r = requests.get(location, timeout=60)
        r.raise_for_status()
        return r.content


def get_ads_client():
    from ..config import settings
    return AmazonAdsClient(
        client_id=settings.AMAZON_ADS_CLIENT_ID,
        client_secret=settings.AMAZON_ADS_CLIENT_SECRET,
        refresh_token=settings.AMAZON_ADS_REFRESH_TOKEN,
        profile_id=settings.AMAZON_ADS_PROFILE_ID,
        region=settings.AMAZON_ADS_REGION,
    )
