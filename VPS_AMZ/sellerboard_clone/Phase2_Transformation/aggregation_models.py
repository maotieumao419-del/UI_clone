"""Phase 2 — Mô hình dữ liệu 2 bảng Master phục vụ Dashboard.

  Summary_Order_Items  (NEW_summary_order_items)  — chi tiết theo đơn hàng,
      đúng cấu trúc cột file CSV "Order Items" mẫu của Sellerboard.
  Summary_Products     (NEW_summary_products)     — tổng hợp theo (ASIN, SKU),
      đủ 31 chỉ số hiệu suất của bảng Products mẫu.

Quy tắc cộng dồn (Roll-up Logic): số liệu tổng hợp theo kỳ PHẢI bằng tổng
các hạt thành phần — validate_rollup() kiểm tra Sales/Units/Net Profit của
Summary_Products khớp SUM(Summary_Order_Items) theo từng SKU.

Các chỉ số chưa có nguồn dữ liệu API (Sellable Quota, BSR, Sessions,
Unit Session %, Google/Facebook ads, Coupon) giữ chỗ = None/0 — cột vẫn
tồn tại trong schema để Dashboard render đúng ma trận, điền sau khi có nguồn.
"""
from dataclasses import dataclass, field, fields

T_SUMMARY_ITEMS     = "NEW_summary_order_items"
T_SUMMARY_PRODUCTS  = "NEW_summary_products"
T_SUMMARY_CAMPAIGNS = "NEW_summary_campaigns"

ROLLUP_TOLERANCE = 0.01      # sai số làm tròn cho phép khi đối chiếu roll-up ($)


@dataclass
class SummaryOrderItem:
    """1 dòng = 1 order item (hoặc 1 dòng return) — khớp CSV Order Items mẫu."""
    order_number:   str = ""
    order_date:     str = ""        # YYYY-MM-DD theo giờ local marketplace
    product:        str = ""        # title
    asin:           str = ""
    sku:            str = ""
    units:          int = 0
    refunds:        int = 0
    sales:          float = 0.0
    promo:          float = 0.0     # số âm (giảm giá)
    sellable_quota: float | None = None     # chưa có nguồn API
    refund_cost:    float = 0.0     # principal + commission + referral hoàn lại (âm)
    amazon_fees:    float = 0.0     # Referral + FBA Fulfillment (THẬT từ Finances API, âm)
    cost_of_goods:  float = 0.0     # COGS FIFO (âm)
    shipping:       float = 0.0     # âm
    gross_profit:   float = 0.0
    expenses:       float = 0.0     # chi phí gián tiếp phân bổ (âm)
    net_profit:     float = 0.0
    margin:         float | None = None     # %
    roi:            float | None = None     # %
    coupon:         float = 0.0     # chưa có nguồn API
    row_type:       str = "normal"  # normal | return
    order_status:   str = ""        # Shipped | Pending | ... (Canceled đã bị loại)
    price_source:   str = "ACTUAL"  # ACTUAL (Amazon trả giá) | IMPUTED (Pending: suy từ giá SKU) | NONE
    fee_state:      str = "NONE"    # ACTUAL (phí thật) | ESTIMATED (ước lượng) | NONE

    def to_row(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class SummaryProduct:
    """1 dòng = 1 (ASIN, SKU) trong kỳ — đủ 31 chỉ số hiệu suất."""
    period_start: str = ""          # YYYY-MM-DD local — thuộc khoá chính
    period_end:   str = ""
    product:      str = ""
    asin:         str = ""
    sku:          str = ""
    units:        int = 0
    refunds:      int = 0
    sales:        float = 0.0
    promo:        float = 0.0
    ads:          float = 0.0       # tổng spend đã phân bổ (âm)
    sponsored_products:     float = 0.0     # PPC
    sponsored_display:      float = 0.0
    sponsored_brands:       float = 0.0     # HSA
    sponsored_brands_video: float = 0.0
    google_ads:   float = 0.0       # chưa có nguồn API
    facebook_ads: float = 0.0       # chưa có nguồn API
    refunds_pct:  float | None = None       # % Refunds = refunds / units * 100
    sellable_quota: float | None = None     # chưa có nguồn API
    refund_cost:  float = 0.0
    amazon_fees:  float = 0.0
    cost_of_goods: float = 0.0
    shipping:     float = 0.0
    gross_profit: float = 0.0
    net_profit:   float = 0.0
    estimated_payout: float = 0.0
    expenses:     float = 0.0
    margin:       float | None = None       # %
    roi:          float | None = None       # %
    bsr:          int | None = None         # chưa có nguồn API (NULL chờ true-up)
    real_acos:    float | None = None       # ads / sales * 100
    sessions:     int = 0                   # = 0 chờ job GET_SALES_AND_TRAFFIC_REPORT true-up
    unit_session_pct: float | None = None   # chưa có nguồn API
    average_sales_price: float = 0.0
    fee_state:    str = "NONE"       # ACTUAL | ESTIMATED | MIXED (gộp nhiều đơn)

    def to_row(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class SummaryCampaign:
    """1 dòng = 1 campaign trong kỳ (Mart 3 — Campaign Profitability).

    Quy ước dấu thống nhất hệ thống: ad_spend ÂM (chi phí), ppc_sales DƯƠNG.
    Các cột chưa có nguồn API (status, current_bid, strategy, automation_status)
    giữ chỗ = None — chờ job Ads Campaign Management API của Phase 1 (Sprint tới)
    true-up, KHÔNG chặn release Phase 2."""
    period_start:  str = ""         # YYYY-MM-DD local — thuộc khoá chính
    period_end:    str = ""
    campaign_id:   str = ""
    campaign_name: str = ""
    status:        str | None = None        # chưa có nguồn API (campaign mgmt)
    marketplace:   str = ""
    ad_product:    str = ""         # SPONSORED_PRODUCTS | SPONSORED_BRANDS | SPONSORED_DISPLAY
    ad_spend:      float = 0.0      # âm
    clicks:        int = 0
    impressions:   int = 0
    orders:        int = 0          # purchases (attributed)
    units:         int = 0          # units attributed
    conversion_rate: float | None = None    # orders / clicks * 100
    cpc:           float | None = None      # |spend| / clicks
    ppc_sales:     float = 0.0
    cost_per_order: float | None = None     # |spend| / orders
    acos:          float | None = None      # |spend| / ppc_sales * 100
    profit:        float | None = None      # GPU(SKU quảng cáo) × units + ad_spend
    break_even_acos: float | None = None    # GPU / avg_sales_price * 100
    current_bid:   float | None = None      # chưa có nguồn API
    strategy:      str | None = None        # chưa có nguồn API
    automation_status: str | None = None    # chưa có nguồn API

    def to_row(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def validate_rollup(item_rows: list[dict], product_rows: list[dict]) -> list[str]:
    """Đối chiếu Roll-up: SUM(Summary_Order_Items) theo SKU phải khớp
    Summary_Products (sales, units, net_profit). Trả về list cảnh báo (rỗng = OK)."""
    by_sku: dict[str, dict] = {}
    for r in item_rows:
        agg = by_sku.setdefault(r["sku"], {"sales": 0.0, "units": 0, "net_profit": 0.0})
        agg["sales"] += r.get("sales") or 0
        agg["units"] += r.get("units") or 0
        agg["net_profit"] += r.get("net_profit") or 0

    warnings = []
    prod_by_sku: dict[str, dict] = {}
    for p in product_rows:
        agg = prod_by_sku.setdefault(p["sku"], {"sales": 0.0, "units": 0, "net_profit": 0.0})
        agg["sales"] += p.get("sales") or 0
        agg["units"] += p.get("units") or 0
        agg["net_profit"] += p.get("net_profit") or 0

    for sku, item_agg in by_sku.items():
        prod = prod_by_sku.get(sku)
        if prod is None:
            warnings.append(f"[Roll-up] SKU {sku} có trong order items nhưng thiếu trong products")
            continue
        for key in ("sales", "units"):
            if abs(item_agg[key] - prod[key]) > ROLLUP_TOLERANCE:
                warnings.append(
                    f"[Roll-up] SKU {sku} lệch {key}: items={item_agg[key]:.2f} "
                    f"vs products={prod[key]:.2f}")
        # net_profit của products gồm thêm ads/refund phân bổ cấp SKU —
        # chỉ cảnh báo khi products LÃI HƠN items (ngược chiều logic trừ chi phí)
        if prod["net_profit"] - item_agg["net_profit"] > ROLLUP_TOLERANCE:
            warnings.append(
                f"[Roll-up] SKU {sku}: net_profit products ({prod['net_profit']:.2f}) "
                f"> items ({item_agg['net_profit']:.2f}) — kiểm tra dấu chi phí")
    return warnings
