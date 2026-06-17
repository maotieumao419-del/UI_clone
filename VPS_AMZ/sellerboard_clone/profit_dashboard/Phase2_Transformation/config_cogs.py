"""Phase 2 — Cấu hình dùng chung: COGS FIFO, Shipping, Timezone Pacific.

COGS FIFO theo effective_date (bảng Profit_Phase1_product_cogs, user tự nhập):
  đơn mua ngày nào áp mức `cog_per_unit` có `effective_date` LỚN NHẤT
  nhưng <= ngày mua (tính theo giờ local marketplace).

Timezone: mọi phép lọc N ngày/1 ngày quy đổi nhất quán về Pacific Time
(America/Los_Angeles, đổi qua SELLER_TIMEZONE trong .env) — khớp số liệu
Amazon Seller Central / Sellerboard.
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

T_COGS = "Profit_Phase1_product_cogs"

SELLER_TZ = ZoneInfo(os.getenv("SELLER_TIMEZONE", "America/Los_Angeles"))

# Shipping/đơn vị: mặc định 0 (chưa có nguồn dữ liệu tự động). Cấu hình qua .env:
#   SHIPPING_COST_PER_UNIT=0.45                 → áp chung mọi SKU
#   SHIPPING_COST_PER_SKU={"SKU-A": 0.5}        → JSON map riêng từng SKU (ưu tiên)
_SHIPPING_DEFAULT = float(os.getenv("SHIPPING_COST_PER_UNIT", "0") or 0)
try:
    _SHIPPING_PER_SKU = json.loads(os.getenv("SHIPPING_COST_PER_SKU", "{}") or "{}")
except (TypeError, ValueError):
    _SHIPPING_PER_SKU = {}


# ── Timezone helpers ──────────────────────────────────────────────────────────

def to_marketplace_local(dt: datetime) -> datetime:
    """UTC (naive/aware) -> giờ local marketplace, trả về naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SELLER_TZ).replace(tzinfo=None)


def marketplace_local_to_utc(local_dt: datetime) -> datetime:
    """Mốc giờ local (naive) -> UTC naive — dùng lọc cột TIMESTAMPTZ lưu UTC."""
    return (local_dt.replace(tzinfo=SELLER_TZ)
            .astimezone(timezone.utc).replace(tzinfo=None))


def now_marketplace() -> datetime:
    return to_marketplace_local(datetime.now(timezone.utc))


def parse_iso(value) -> datetime | None:
    """Chuỗi ISO của Supabase ('...+00:00' / '...Z') -> UTC naive."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ── COGS FIFO ─────────────────────────────────────────────────────────────────

def load_cogs_map(sb) -> dict[str, list[tuple[str, float]]]:
    """Đọc Profit_Phase1_product_cogs -> {sku: [(effective_date ISO, cog_per_unit), ...]
    sort tăng dần theo effective_date}."""
    rows = []
    offset, page = 0, 1000
    while True:
        resp = (sb.table(T_COGS).select("sku,cog_per_unit,effective_date")
                .range(offset, offset + page - 1).execute())
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        if r.get("sku"):
            try:
                cog = float(r.get("cog_per_unit") or 0)
            except (TypeError, ValueError):
                cog = 0.0
            out[r["sku"]].append((r.get("effective_date") or "2000-01-01", cog))
    for sku in out:
        out[sku].sort()
    return dict(out)


def unit_cogs(cogs_map: dict, sku: str, purchase_local: datetime) -> float:
    """Mức giá vốn hiệu lực tại thời điểm mua: effective_date LỚN NHẤT <= ngày mua."""
    tiers = cogs_map.get(sku)
    if not tiers:
        return 0.0
    day = purchase_local.date().isoformat()
    cost = 0.0
    for eff, cog in tiers:               # đã sort tăng dần
        if eff <= day:
            cost = cog
        else:
            break
    return cost


def shipping_per_unit(sku: str) -> float:
    """Chi phí shipping/đơn vị theo cấu hình .env (mặc định 0)."""
    try:
        return float(_SHIPPING_PER_SKU.get(sku, _SHIPPING_DEFAULT))
    except (TypeError, ValueError):
        return _SHIPPING_DEFAULT
