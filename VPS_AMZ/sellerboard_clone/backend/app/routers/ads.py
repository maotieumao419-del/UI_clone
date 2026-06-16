import sys
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..services.amazon_ads_client import get_ads_client
from ..services.ads_sync import run_full_sync

# Module ADS (đọc chỉ số từ DB) nằm ngoài backend/ — nạp qua _ROOT (giống dashboard.py)
_ROOT = Path(__file__).resolve().parents[3]            # .../sellerboard_clone
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from ads.ads_aggregator import (  # noqa: E402
    get_ads_overview, get_campaign_performance, get_sku_ads_performance,
)

try:
    from ..timeutils import now_marketplace            # mốc "hôm nay" theo giờ marketplace
except Exception:                                      # noqa: BLE001 — fallback chạy ngoài app
    from datetime import datetime, timezone

    def now_marketplace():
        return datetime.now(timezone.utc)

router = APIRouter(prefix="/api/ads", tags=["ads"])


def _range(start: str | None, end: str | None):
    """Phân giải khoảng ngày; mặc định 30 ngày gần nhất (đến hôm nay giờ marketplace)."""
    try:
        e = date.fromisoformat(end) if end else now_marketplace().date()
        s = date.fromisoformat(start) if start else e - timedelta(days=29)
    except ValueError:
        raise HTTPException(422, "start/end phải dạng YYYY-MM-DD")
    if s > e:
        raise HTTPException(422, "start phải <= end")
    return s, e

def _client():
    if not settings.AMAZON_ADS_CLIENT_ID:
        raise HTTPException(503, "Amazon Ads API chua duoc cau hinh")
    return get_ads_client()

@router.get("/status")
def ads_status():
    missing = [f for f in ("AMAZON_ADS_CLIENT_ID","AMAZON_ADS_CLIENT_SECRET",
               "AMAZON_ADS_REFRESH_TOKEN","AMAZON_ADS_PROFILE_ID") if not getattr(settings, f, "")]
    return {"configured": len(missing)==0, "profile_id": settings.AMAZON_ADS_PROFILE_ID,
            "region": settings.AMAZON_ADS_REGION, "missing_fields": missing}

@router.get("/profiles")
def list_profiles():
    try: return _client().list_profiles()
    except Exception as e: raise HTTPException(502, str(e))

@router.get("/campaigns")
def list_campaigns():
    try: return _client().get_campaigns()
    except Exception as e: raise HTTPException(502, str(e))

@router.get("/keywords")
def list_keywords():
    try: return _client().get_keywords()
    except Exception as e: raise HTTPException(502, str(e))

@router.post("/sync")
def sync_ads(days: int = 7):
    if days < 1 or days > 60: raise HTTPException(422, "days phai tu 1-60")
    try:
        result = run_full_sync(_client(), days)
        return {"ok": True, "days": days, **result}
    except Exception as e: raise HTTPException(502, str(e))

@router.post("/token-test")
def test_token():
    try:
        token = _client()._get_access_token()
        return {"ok": True, "token_prefix": token[:20] + "..."}
    except Exception as e: raise HTTPException(502, f"LWA error: {e}")


# ── Analytics: chỉ số ADS đọc từ DB (NEW_ads_*), KHÔNG gọi Amazon ─────────────
# Trang "📣 Amazon Ads": ACOS/ROAS/TACOS/CTR/CVR/CPC ở cấp overview/campaign/SKU.
@router.get("/analytics/overview")
def ads_overview(start: str | None = None, end: str | None = None,
                 window: str = "7d", db: Session = Depends(get_db)):
    s, e = _range(start, end)
    try:
        return get_ads_overview(db, s, e, window)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"ads overview: {ex}")

@router.get("/analytics/campaigns")
def ads_campaigns_perf(start: str | None = None, end: str | None = None,
                       window: str = "7d", db: Session = Depends(get_db)):
    s, e = _range(start, end)
    try:
        return get_campaign_performance(db, s, e, window)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"ads campaigns: {ex}")

@router.get("/analytics/skus")
def ads_skus_perf(start: str | None = None, end: str | None = None,
                  window: str = "7d", db: Session = Depends(get_db)):
    s, e = _range(start, end)
    try:
        return get_sku_ads_performance(db, s, e, window)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"ads skus: {ex}")
