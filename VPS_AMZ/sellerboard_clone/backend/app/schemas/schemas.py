"""Pydantic schemas - hợp đồng dữ liệu của REST API (validate + serialize)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    consent: dict
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Product ----------
class ProductBase(BaseModel):
    asin: str
    sku: str
    title: str
    marketplace: str = "amazon"
    category: str = ""
    price: float = 0.0
    current_stock: int = 0
    inbound_stock: int = 0
    lead_time_manufacture_days: int = 20
    lead_time_shipping_days: int = 25
    lead_time_prep_days: int = 5
    safety_stock_days: int = 14
    referral_fee_pct: float = 0.15
    fba_fee_per_unit: float = 3.5


class ProductCreate(ProductBase):
    pass


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Dashboard ----------
class Kpi(BaseModel):
    label: str
    value: float
    unit: str = ""
    delta_pct: float | None = None


class TimePoint(BaseModel):
    date: str
    sales: float
    profit: float
    units: int


class ProductPerf(BaseModel):
    product_id: int
    asin: str
    title: str
    units: int
    refunds: int
    sales: float
    avg_selling_price: float
    cogs: float
    fees: float
    ppc: float
    gross_profit: float
    net_profit: float
    margin_pct: float
    roi_pct: float
    bsr: int | None = None


class DashboardResponse(BaseModel):
    kpis: list[Kpi]
    timeseries: list[TimePoint]
    top_products: list[ProductPerf]
    marketplace_breakdown: dict[str, float]


class PeriodCard(BaseModel):
    key: str
    label: str
    range_label: str
    sales: float
    sales_delta_pct: float | None = None
    orders: int
    units: int
    refunds: int
    adv_cost: float
    est_payout: float
    net_profit: float
    net_profit_delta_pct: float | None = None


class PeriodOverview(BaseModel):
    periods: list[PeriodCard]


# ---------- Inventory ----------
class RestockSuggestion(BaseModel):
    product_id: int
    asin: str
    title: str
    daily_velocity: float
    current_stock: int
    inbound_stock: int
    days_of_stock: float
    reorder_point: int
    suggested_order_qty: int
    stockout_date: str | None
    urgency: str


# ---------- Alerts / Reimbursements ----------
class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    severity: str
    message: str
    is_read: bool
    product_id: int | None
    created_at: datetime


class ReimbursementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    reason: str
    quantity: int
    estimated_amount: float
    status: str
    detected_at: datetime
