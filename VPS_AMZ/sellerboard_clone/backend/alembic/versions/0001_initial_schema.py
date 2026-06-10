"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("consent", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("asin", sa.String(20), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("marketplace", sa.String(20), nullable=False, server_default="amazon"),
        sa.Column("category", sa.String(128), nullable=False, server_default=""),
        sa.Column("price", sa.Float, nullable=False, server_default="0"),
        sa.Column("current_stock", sa.Integer, nullable=False, server_default="0"),
        sa.Column("inbound_stock", sa.Integer, nullable=False, server_default="0"),
        sa.Column("lead_time_manufacture_days", sa.Integer, nullable=False, server_default="20"),
        sa.Column("lead_time_shipping_days", sa.Integer, nullable=False, server_default="25"),
        sa.Column("lead_time_prep_days", sa.Integer, nullable=False, server_default="5"),
        sa.Column("safety_stock_days", sa.Integer, nullable=False, server_default="14"),
        sa.Column("referral_fee_pct", sa.Float, nullable=False, server_default="0.15"),
        sa.Column("fba_fee_per_unit", sa.Float, nullable=False, server_default="3.5"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_products_owner_id", "products", ["owner_id"])
    op.create_index("ix_products_asin", "products", ["asin"])
    op.create_index("ix_products_sku", "products", ["sku"])

    op.create_table(
        "inventory_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("received_at", sa.DateTime, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_cost", sa.Float, nullable=False),
    )
    op.create_index("ix_inventory_batches_product_id", "inventory_batches", ["product_id"])
    op.create_index("ix_inventory_batches_received_at", "inventory_batches", ["received_at"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("marketplace", sa.String(20), nullable=False, server_default="amazon"),
        sa.Column("customer_ref", sa.String(64), nullable=False, server_default=""),
        sa.Column("purchased_at", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="shipped"),
        sa.Column("ppc_cost", sa.Float, nullable=False, server_default="0"),
        sa.Column("promo_discount", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_refunded", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("refund_returned", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_orders_owner_id", "orders", ["owner_id"])
    op.create_index("ix_orders_external_id", "orders", ["external_id"])
    op.create_index("ix_orders_purchased_at", "orders", ["purchased_at"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price", sa.Float, nullable=False),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])

    op.create_table(
        "listing_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )
    op.create_index("ix_listing_snapshots_product_id", "listing_snapshots", ["product_id"])
    op.create_index("ix_listing_snapshots_captured_at", "listing_snapshots", ["captured_at"])

    op.create_table(
        "bsr_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime, nullable=False),
        sa.Column("bsr", sa.Integer, nullable=False),
    )
    op.create_index("ix_bsr_snapshots_product_id", "bsr_snapshots", ["product_id"])
    op.create_index("ix_bsr_snapshots_captured_at", "bsr_snapshots", ["captured_at"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=True),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False, server_default="info"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_alerts_owner_id", "alerts", ["owner_id"])
    op.create_index("ix_alerts_type", "alerts", ["type"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])

    op.create_table(
        "reimbursement_cases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("estimated_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("detected_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_reimbursement_cases_owner_id", "reimbursement_cases", ["owner_id"])
    op.create_index("ix_reimbursement_cases_detected_at", "reimbursement_cases", ["detected_at"])

    op.create_table(
        "settlement_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("settlement_id", sa.String(64), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("transaction_type", sa.String(64), nullable=False),
        sa.Column("amount_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("amount_description", sa.String(128), nullable=False, server_default=""),
        sa.Column("amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("posted_date", sa.DateTime, nullable=False),
        sa.Column("sku", sa.String(64), nullable=False, server_default=""),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_settlement_entries_owner_id", "settlement_entries", ["owner_id"])
    op.create_index("ix_settlement_entries_settlement_id", "settlement_entries", ["settlement_id"])
    op.create_index("ix_settlement_entries_order_id", "settlement_entries", ["order_id"])
    op.create_index("ix_settlement_entries_posted_date", "settlement_entries", ["posted_date"])
    op.create_index("ix_settlement_entries_sku", "settlement_entries", ["sku"])

    op.create_table(
        "aggregated_daily",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("date", sa.DateTime, nullable=False),
        sa.Column("gross_revenue", sa.Float, nullable=False, server_default="0"),
        sa.Column("units_sold", sa.Integer, nullable=False, server_default="0"),
        sa.Column("orders_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("refunds_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("refunds_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("amazon_fees", sa.Float, nullable=False, server_default="0"),
        sa.Column("cogs", sa.Float, nullable=False, server_default="0"),
        sa.Column("ppc_cost", sa.Float, nullable=False, server_default="0"),
        sa.Column("net_revenue", sa.Float, nullable=False, server_default="0"),
        sa.Column("net_profit", sa.Float, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("owner_id", "date", name="uq_aggregated_daily_owner_date"),
    )
    op.create_index("ix_aggregated_daily_owner_id", "aggregated_daily", ["owner_id"])
    op.create_index("ix_aggregated_daily_date", "aggregated_daily", ["date"])


def downgrade() -> None:
    op.drop_table("aggregated_daily")
    op.drop_table("settlement_entries")
    op.drop_table("reimbursement_cases")
    op.drop_table("alerts")
    op.drop_table("bsr_snapshots")
    op.drop_table("listing_snapshots")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("inventory_batches")
    op.drop_table("products")
    op.drop_table("users")
