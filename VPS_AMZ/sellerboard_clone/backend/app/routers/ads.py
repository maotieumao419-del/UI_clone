from fastapi import APIRouter, HTTPException
from ..config import settings
from ..services.amazon_ads_client import get_ads_client
from ..services.ads_sync import run_full_sync

router = APIRouter(prefix="/api/ads", tags=["ads"])

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
