"""So khớp TOÀN BỘ cột giữa file hệ thống (NEW_) và Sellerboard.
Xử lý: bug Excel ép số -> datetime trên MỌI cột, header Cyrillic, key order+sku."""
import os
import re
import sys
from datetime import datetime

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "data", "input", "Order_Items-030626.xlsx")
SB = os.path.join(HERE, "data", "input", "Dr_Hai_Craft_Order_Items-030626.xlsx")

# Cyrillic nhìn giống Latin -> chuẩn hoá header
_CYR = str.maketrans({"с": "c", "о": "o", "а": "a", "е": "e", "р": "p", "у": "y", "х": "x"})


def norm(s):
    return str(s).translate(_CYR).strip().lower()


def clean_num(v):
    """$,/ , Cyrillic, và bug Excel: datetime(2026,m,d) <- số d.mm gốc."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (datetime, pd.Timestamp)):
        return round(v.day + v.month / 100, 2)   # 18-Jan -> 18.01 ; 5-Oct -> 5.10
    s = str(v).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def order_id(v):
    m = re.search(r"\d{3}-\d{7}-\d{7}", str(v))
    return m.group(0) if m else str(v).split(" / ")[0].strip()


api = pd.read_excel(API, sheet_name="NEW_summary_order_items_rows")
sb = pd.read_excel(SB, sheet_name=0)
sb.columns = [c for c in sb.columns]

# map: nhãn -> (cột API, cột SB) tìm theo norm
SBcols = {norm(c): c for c in sb.columns}
APIcols = {norm(c): c for c in api.columns}

METRICS = [
    ("units", "units", "units"),
    ("refunds", "refunds", "refunds"),
    ("sales", "sales", "sales"),
    ("promo", "promo", "promo"),
    ("refund_cost", "refund_cost", "refund cost"),
    ("amazon_fees", "amazon_fees", "amazon fees"),
    ("cost_of_goods", "cost_of_goods", "cost of goods"),
    ("shipping", "shipping", "shipping"),
    ("gross_profit", "gross_profit", "gross profit"),
    ("net_profit", "net_profit", "net profit"),
    ("margin", "margin", "margin"),
    ("roi", "roi", "roi"),
]

api["k_order"] = api["order_number"].apply(order_id)
api["k_sku"] = api["sku"].fillna("").astype(str).str.strip()
sb["k_order"] = sb["Order number"].apply(order_id)
sb["k_sku"] = sb["SKU"].fillna("").astype(str).str.strip()

# Gom theo (order, sku) — cộng dồn (API có dòng return tách riêng)
def agg(df, cols_map, side):
    use = {}
    for label, acol, scol in METRICS:
        col = cols_map.get(label if side == "api" else label)
    # build numeric columns
    out = df[["k_order", "k_sku"]].copy()
    for label, acol, scol in METRICS:
        src = acol if side == "api" else None
        if side == "api":
            col = APIcols.get(norm(acol))
        else:
            col = SBcols.get(norm(scol))
        out[label] = df[col].apply(clean_num) if col is not None else 0.0
    return out.groupby(["k_order", "k_sku"], as_index=False).sum()


A = agg(api, APIcols, "api")
S = agg(sb, SBcols, "sb")
m = pd.merge(A, S, on=["k_order", "k_sku"], how="outer", suffixes=("_api", "_sb")).fillna(0.0)

print(f"API rows={len(api)} | SB rows={len(sb)} | matched keys={len(m)}\n")
print(f"{'CỘT':<16}{'API':>12}{'SELLERBOARD':>14}{'DELTA':>12}  {'#dòng lệch':>10}")
print("-" * 70)
for label, _, _ in METRICS:
    a, s = m[f"{label}_api"], m[f"{label}_sb"]
    ta, ts = round(a.sum(), 2), round(s.sum(), 2)
    d = round(ta - ts, 2)
    nbad = int(((a - s).abs() > 0.01).sum())
    flag = "OK" if abs(d) < 0.01 and nbad == 0 else ("≈" if abs(d) < 0.01 else "❌")
    print(f"{label:<16}{ta:>12}{ts:>14}{d:>+12}  {nbad:>10}  {flag}")

# Liệt kê dòng lệch cho các cột KHÁC amazon_fees (tìm lỗi ẩn)
print("\n=== Dòng lệch ở cột KHÁC amazon_fees (top 15) ===")
others = [l for l, _, _ in METRICS if l not in ("amazon_fees", "net_profit", "gross_profit")]
m["bad_other"] = False
for l in others:
    m["bad_other"] |= (m[f"{l}_api"] - m[f"{l}_sb"]).abs() > 0.01
bad = m[m["bad_other"]].head(15)
if bad.empty:
    print("  (không có — các cột khác amazon_fees đều khớp)")
else:
    for _, r in bad.iterrows():
        diffs = []
        for l in others:
            dv = round(r[f"{l}_api"] - r[f"{l}_sb"], 2)
            if abs(dv) > 0.01:
                diffs.append(f"{l}: {r[f'{l}_api']} vs {r[f'{l}_sb']} (Δ{dv:+})")
        print(f"  {r['k_order']} / {r['k_sku']}: " + "; ".join(diffs))
