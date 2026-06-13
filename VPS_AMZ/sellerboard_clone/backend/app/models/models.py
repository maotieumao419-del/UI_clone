"""Mô hình dữ liệu quan hệ (RDBMS) cho hệ thống SellerVision.

Các bảng cần tính toàn vẹn giao dịch (ACID): user, product, order, inventory...
Dữ liệu linh hoạt/biến động (listing changes, log) lưu ở cột JSON -
trong production có thể tách sang MongoDB như đề xuất trong Structure.md.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def _utcnow() -> datetime:
    from ..timeutils import now_utc
    return now_utc()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Lớp đạo đức: người dùng chủ động đồng ý từng loại dữ liệu (meaningful choice)
    consent: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    products: Mapped[list["Product"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    asin: Mapped[str] = mapped_column(String(20), index=True)
    sku: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    marketplace: Mapped[str] = mapped_column(String(20), default="amazon")  # amazon/shopify/walmart/ebay
    category: Mapped[str] = mapped_column(String(128), default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)

    # Tham số chuỗi cung ứng (dùng cho mô-đun dự báo tồn kho)
    current_stock: Mapped[int] = mapped_column(Integer, default=0)
    inbound_stock: Mapped[int] = mapped_column(Integer, default=0)
    lead_time_manufacture_days: Mapped[int] = mapped_column(Integer, default=20)
    lead_time_shipping_days: Mapped[int] = mapped_column(Integer, default=25)
    lead_time_prep_days: Mapped[int] = mapped_column(Integer, default=5)
    safety_stock_days: Mapped[int] = mapped_column(Integer, default=14)

    # Phí tham chiếu của Amazon (đơn giản hoá - thực tế tách >100 loại phí)
    referral_fee_pct: Mapped[float] = mapped_column(Float, default=0.15)
    fba_fee_per_unit: Mapped[float] = mapped_column(Float, default=3.5)

    # Ảnh chính từ SP-API Catalog Items (Phase 1 — fetch_product_images.py)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    owner: Mapped["User"] = relationship(back_populates="products")
    batches: Mapped[list["InventoryBatch"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")


class InventoryBatch(Base):
    """Lô hàng nhập - phục vụ tính COGS theo FIFO."""
    __tablename__ = "inventory_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[float] = mapped_column(Float)  # giá vốn / đơn vị (đã gồm vận chuyển vào kho)

    product: Mapped["Product"] = relationship(back_populates="batches")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    marketplace: Mapped[str] = mapped_column(String(20), default="amazon")
    # ID khách hàng đã ẩn danh (hash) - phục vụ LTV mà vẫn tôn trọng quyền riêng tư
    customer_ref: Mapped[str] = mapped_column(String(64), index=True, default="")
    purchased_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="shipped")  # shipped/refunded

    ppc_cost: Mapped[float] = mapped_column(Float, default=0.0)  # chi phí quảng cáo phân bổ
    promo_discount: Mapped[float] = mapped_column(Float, default=0.0)
    is_refunded: Mapped[bool] = mapped_column(Boolean, default=False)
    refund_returned: Mapped[bool] = mapped_column(Boolean, default=True)  # hoàn tiền có trả hàng không

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)  # giá bán thực thu / đơn vị

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="order_items")


class ListingSnapshot(Base):
    """Ảnh chụp listing để giám sát thay đổi 24/7 (cột JSON linh hoạt)."""
    __tablename__ = "listing_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    data: Mapped[dict] = mapped_column(JSON)  # title, main_image, dimensions, referral_fee_pct, buybox_owner, sellers[]


class BsrSnapshot(Base):
    """Theo dõi Best Seller Rank theo thời gian."""
    __tablename__ = "bsr_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    bsr: Mapped[int] = mapped_column(Integer)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(40), index=True)  # buybox_lost / hijacker / image_changed ...
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info/warning/critical
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class ReimbursementCase(Base):
    """Hồ sơ yêu cầu bồi thường FBA (mất/hư hàng, hoàn tiền không trả hàng)."""
    __tablename__ = "reimbursement_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    reason: Mapped[str] = mapped_column(String(40))  # lost / damaged / refund_no_return
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    estimated_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open/submitted/recovered
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class SettlementEntry(Base):
    """Một dòng giao dịch từ Settlement Report của Amazon.

    Amazon thanh toán theo kỳ (~2 tuần/lần). Mỗi kỳ có một file TSV chứa
    tất cả giao dịch: doanh thu, phí FBA, referral fee, hoàn tiền, v.v.
    Bảng này lưu từng dòng đó để tính PnL chính xác thay vì dùng phí ước tính.
    """
    __tablename__ = "settlement_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    settlement_id: Mapped[str] = mapped_column(String(64), index=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    transaction_type: Mapped[str] = mapped_column(String(64), index=True)  # Order/Refund/Transfer/...
    amount_type: Mapped[str] = mapped_column(String(64), default="")       # ItemPrice/ItemFees/...
    amount_description: Mapped[str] = mapped_column(String(128), default="")  # Principal/FBAPerUnitFulfillmentFee/...
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    posted_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    sku: Mapped[str] = mapped_column(String(64), default="", index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)


class AggregatedDaily(Base):
    """Tổng hợp doanh thu, phí, lợi nhuận theo ngày — nguồn dữ liệu cho dashboard PnL.

    Được tính lại sau mỗi lần sync (Settlement + Orders). Dashboard đọc từ
    bảng này thay vì tính real-time trên raw data — nhanh hơn và tránh
    gọi API Amazon mỗi lần load trang.
    """
    __tablename__ = "aggregated_daily"
    __table_args__ = (
        UniqueConstraint("owner_id", "date", name="uq_aggregated_daily_owner_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, index=True)  # chỉ phần ngày, giờ=00:00:00

    # Doanh thu (từ Orders)
    gross_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    units_sold: Mapped[int] = mapped_column(Integer, default=0)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    refunds_amount: Mapped[float] = mapped_column(Float, default=0.0)
    refunds_count: Mapped[int] = mapped_column(Integer, default=0)

    # Phí Amazon (từ Settlement — chính xác hơn phí ước tính)
    amazon_fees: Mapped[float] = mapped_column(Float, default=0.0)

    # Chi phí (COGS từ InventoryBatch, PPC từ Ads API)
    cogs: Mapped[float] = mapped_column(Float, default=0.0)
    ppc_cost: Mapped[float] = mapped_column(Float, default=0.0)

    # Lợi nhuận tính sẵn
    net_revenue: Mapped[float] = mapped_column(Float, default=0.0)   # gross - refunds - amazon_fees
    net_profit: Mapped[float] = mapped_column(Float, default=0.0)    # net_revenue - cogs - ppc_cost

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SummaryProduct(Base):
    __tablename__ = "NEW_summary_products"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    product: Mapped[str | None] = mapped_column(Text, nullable=True)
    asin: Mapped[str] = mapped_column(String(20), primary_key=True, default='')
    sku: Mapped[str] = mapped_column(String(64), primary_key=True, default='')

    units: Mapped[int] = mapped_column(Integer, default=0)
    refunds: Mapped[int] = mapped_column(Integer, default=0)
    sales: Mapped[float] = mapped_column(Float, default=0.0)
    promo: Mapped[float] = mapped_column(Float, default=0.0)
    ads: Mapped[float] = mapped_column(Float, default=0.0)
    sponsored_products: Mapped[float] = mapped_column(Float, default=0.0)
    sponsored_display: Mapped[float] = mapped_column(Float, default=0.0)
    sponsored_brands: Mapped[float] = mapped_column(Float, default=0.0)
    sponsored_brands_video: Mapped[float] = mapped_column(Float, default=0.0)
    google_ads: Mapped[float] = mapped_column(Float, default=0.0)
    facebook_ads: Mapped[float] = mapped_column(Float, default=0.0)
    refunds_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sellable_quota: Mapped[float | None] = mapped_column(Float, nullable=True)
    refund_cost: Mapped[float] = mapped_column(Float, default=0.0)
    amazon_fees: Mapped[float] = mapped_column(Float, default=0.0)
    cost_of_goods: Mapped[float] = mapped_column(Float, default=0.0)
    shipping: Mapped[float] = mapped_column(Float, default=0.0)
    gross_profit: Mapped[float] = mapped_column(Float, default=0.0)
    net_profit: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_payout: Mapped[float] = mapped_column(Float, default=0.0)
    expenses: Mapped[float] = mapped_column(Float, default=0.0)
    margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi: Mapped[float | None] = mapped_column(Float, nullable=True)
    bsr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    real_acos: Mapped[float | None] = mapped_column(Float, nullable=True)
    sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_session_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_sales_price: Mapped[float] = mapped_column(Float, default=0.0)
    fee_state: Mapped[str] = mapped_column(String(20), default='NONE')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

