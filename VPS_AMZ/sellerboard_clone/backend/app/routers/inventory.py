"""Router chuỗi cung ứng: gợi ý nhập hàng (restock)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas.schemas import RestockSuggestion
from ..services import inventory

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/restock", response_model=list[RestockSuggestion])
def restock(monthly_growth_target: float = Query(0.05, ge=-0.5, le=2.0),
            db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return inventory.restock_suggestions(db, current.id, monthly_growth_target=monthly_growth_target)
