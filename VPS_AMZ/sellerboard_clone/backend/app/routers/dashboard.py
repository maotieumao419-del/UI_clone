"""Router phân tích: dashboard tổng hợp, LTV, BSR monitor."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas.schemas import DashboardResponse, PeriodOverview
from ..services import profit

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(days: int = Query(30, ge=1, le=365),
                  db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.dashboard(db, current.id, days=days)


@router.get("/periods", response_model=PeriodOverview)
def get_periods(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.period_overview(db, current.id)


@router.get("/ltv")
def get_ltv(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.customer_ltv(db, current.id)


@router.get("/bsr")
def get_bsr(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.bsr_monitor(db, current.id)
