"""Router phân tích: dashboard tổng hợp (SQLite/Postgres local), LTV, BSR monitor."""
import sys
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services import profit

_ROOT = Path(__file__).resolve().parents[3]            # .../sellerboard_clone
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Phase3_Application.data_bridge.analytics_aggregator import (  # noqa: E402
    get_dashboard_kpis, get_order_items_details, get_sku_performance,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard/summary")
def get_dashboard_summary(
    tab: str = Query("products"),
    start: date = Query(...),
    end: date = Query(...),
    compare_start: date | None = Query(None),
    compare_end: date | None = Query(None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """All-in-One Dashboard: thẻ KPI (so sánh kỳ trước) + bảng chi tiết theo tab.

    - tab=products (mặc định) -> bảng SKU performance (GROUP BY asin, sku).
    - tab=orders               -> ledger giao dịch thô NEW_summary_order_items.
    """
    result = {
        "kpis": get_dashboard_kpis(db, current.id, start, end, compare_start, compare_end),
    }
    if tab == "orders":
        result["orders"] = get_order_items_details(db, current.id, start, end)
    else:
        result["products"] = get_sku_performance(db, current.id, start, end)
    return result


@router.get("/periods")
def get_periods(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """5 thẻ tổng quan kiểu Sellerboard (Today/Yesterday/MTD/Forecast/Last month)."""
    return profit.period_overview(db, current.id)


@router.get("/ltv")
def get_ltv(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.customer_ltv(db, current.id)


@router.get("/bsr")
def get_bsr(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return profit.bsr_monitor(db, current.id)
