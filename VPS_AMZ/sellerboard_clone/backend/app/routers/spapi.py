from fastapi import APIRouter, HTTPException
from ..config import settings
from ..services.amazon_spapi_client import get_spapi_client

router = APIRouter(prefix="/api/spapi", tags=["spapi"])

def _client():
    if not settings.AMAZON_SPI_CLIENT_ID:
        raise HTTPException(503, "Amazon SP-API chua duoc cau hinh")
    return get_spapi_client()

@router.get("/status")
def spapi_status():
    missing = [f for f in ("AMAZON_SPI_CLIENT_ID","AMAZON_SPI_CLIENT_SECRET",
               "AMAZON_SPI_REFRESH_TOKEN","AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","AWS_ROLE_ARN")
               if not getattr(settings, f, "")]
    return {"configured": len(missing)==0, "marketplace_id": settings.AMAZON_SPI_MARKETPLACE_ID,
            "missing_fields": missing}

@router.get("/orders")
def get_orders(created_after: str = "2024-01-01T00:00:00Z"):
    try: return _client().get_orders(created_after)
    except Exception as e: raise HTTPException(502, str(e))

@router.get("/inventory")
def get_inventory():
    try: return _client().get_inventory()
    except Exception as e: raise HTTPException(502, str(e))

@router.post("/token-test")
def test_token():
    try:
        token = _client()._get_lwa_token()
        return {"ok": True, "token_prefix": token[:20] + "..."}
    except Exception as e: raise HTTPException(502, f"LWA error: {e}")
