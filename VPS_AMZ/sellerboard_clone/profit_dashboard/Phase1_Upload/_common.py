"""Phase1_Upload (profit) — helpers dùng chung cho các upload script.

Tên bảng đích = Profit_Phase1_* (khớp schema profit_dashboard).
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]   # .../sellerboard_clone
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# ── Tên bảng đích ─────────────────────────────────────────────────────────────
T_ORDERS  = "Profit_Phase1_sp_orders"
T_ITEMS   = "Profit_Phase1_sp_order_items"
T_FEES    = "Profit_Phase1_fin_item_fees"
T_REFUNDS = "Profit_Phase1_fin_refunds"
T_ADJ     = "Profit_Phase1_fin_adjustments"
T_ADS     = "Profit_Phase1_ads_campaigns_daily"
T_ADS_SKU = "Profit_Phase1_ads_sp_asin_daily"
T_PRICE   = "Profit_Phase1_product_price"

CHUNK_SIZE = 100


def f_(val, default=0.0) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return default


def i_(val, default=0) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return default


def money(obj) -> float:
    """Số tiền từ object tiền tệ Amazon (Finances='CurrencyAmount', Orders='Amount')."""
    o = obj or {}
    return f_(o.get("CurrencyAmount", o.get("Amount")))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
