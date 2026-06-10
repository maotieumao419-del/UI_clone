import gzip, json, time
from datetime import date, timedelta
from .amazon_ads_client import AmazonAdsClient

_CAMPAIGN_METRICS = ["campaignId","campaignName","impressions","clicks","cost","attributedSales14d","attributedUnitsOrdered14d"]
_KEYWORD_METRICS  = ["keywordId","keywordText","matchType","campaignId","impressions","clicks","cost","attributedSales14d","attributedUnitsOrdered14d"]


def _date_range(days):
    today = date.today()
    return [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, days + 1)]


def _poll_report(client, report_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = client.get_report(report_id)
        status = info.get("status", "")
        if status == "SUCCESS":
            loc = info.get("location")
            return client.download_report(loc) if loc else None
        if status == "FAILURE":
            return None
        time.sleep(5)
    return None


def run_full_sync(client, days=7):
    results = {"campaigns": 0, "keywords": 0, "reports": 0, "errors": []}
    try:
        results["campaigns"] = len(client.get_campaigns())
    except Exception as e:
        results["errors"].append(f"campaigns: {e}")
    try:
        results["keywords"] = len(client.get_keywords())
    except Exception as e:
        results["errors"].append(f"keywords: {e}")
    for d in _date_range(min(days, 30)):
        try:
            job = client.request_report("campaigns", _CAMPAIGN_METRICS, d)
            report_id = job.get("reportId")
            if report_id:
                raw = _poll_report(client, report_id)
                if raw:
                    try:
                        data = gzip.decompress(raw)
                    except Exception:
                        data = raw
                    results["reports"] += len(json.loads(data))
        except Exception as e:
            results["errors"].append(f"report {d}: {e}")
    return results
