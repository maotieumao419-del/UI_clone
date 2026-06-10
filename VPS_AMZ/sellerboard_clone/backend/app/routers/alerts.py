"""Router cảnh báo & bồi thường."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Alert, ReimbursementCase, User
from ..schemas.schemas import AlertOut, ReimbursementOut
from ..services import alerts as alerts_service

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return db.scalars(
        select(Alert).where(Alert.owner_id == current.id).order_by(Alert.created_at.desc())
    ).all()


@router.post("/alerts/scan", response_model=list[AlertOut])
def scan_alerts(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """Quét thay đổi listing ngay (production: Celery worker chạy định kỳ)."""
    return alerts_service.scan_listing_changes(db, current.id)


@router.post("/alerts/{alert_id}/read", response_model=AlertOut)
def mark_read(alert_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    a = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.owner_id == current.id))
    if a:
        a.is_read = True
        db.commit()
        db.refresh(a)
    return a


@router.get("/reimbursements", response_model=list[ReimbursementOut])
def list_reimbursements(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return db.scalars(
        select(ReimbursementCase).where(ReimbursementCase.owner_id == current.id)
        .order_by(ReimbursementCase.detected_at.desc())
    ).all()


@router.post("/reimbursements/scan", response_model=list[ReimbursementOut])
def scan_reimbursements(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return alerts_service.build_reimbursement_report(db, current.id)
