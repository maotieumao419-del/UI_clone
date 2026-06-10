from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services.spapi_sync import sync_orders

router = APIRouter(prefix="/api/sync", tags=["sync"])

@router.post("/orders")
def trigger_sync(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = sync_orders(db, current, days=days)
    return {"status": "ok", **result}
