"""Giải ngược mô hình fee ước lượng của Sellerboard từ file Order Items 03/06.

Giả thiết: SB_fees = -(referral × sales + fba_sku × units).
Thử referral 15% và 16.5% -> implied_fba per-unit per SKU; so với FBA THẬT
(median lịch sử settle NEW_fin_item_fees) và FBA_thật/1.1 (bỏ VAT)."""
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import os
import pandas as pd
from dotenv import dotenv_values
import psycopg

SB_FILE = r"C:\Users\nnh16\ads-trading-system\VPS\Dr_Hai_Craft_Order_Items-030626.xlsx"
df = pd.read_excel(SB_FILE)
df = df[["SKU", "Units", "Sales", "Amazon fees", "Promo"]].copy()
for c in ("Units", "Sales", "Amazon fees", "Promo"):
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df = df[(df["Units"] > 0) & (df["Sales"] > 0)]

for r in (0.15, 0.165):
    df[f"impl_fba_{r}"] = (df["Amazon fees"].abs() - r * df["Sales"]) / df["Units"]

g = df.groupby("SKU").agg(
    units=("Units", "sum"), sales=("Sales", "sum"),
    impl_15=("impl_fba_0.15", "median"), impl_165=("impl_fba_0.165", "median"),
).reset_index()

script_dir = os.path.dirname(os.path.abspath(__file__))
env = dotenv_values(os.path.join(script_dir, "backend", ".env"))
URL = env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
conn = psycopg.connect(URL, connect_timeout=20)
cur = conn.cursor()
cur.execute('''
  select sku,
         percentile_cont(0.5) within group (order by abs(amount)/quantity)
  from "NEW_fin_item_fees"
  where fee_type='FBAPerUnitFulfillmentFee' and quantity > 0
  group by sku
''')
fba_act = {r[0]: float(r[1]) for r in cur.fetchall()}

# referral thật per SKU (commission/principal)
cur.execute('''
  select sku, percentile_cont(0.5) within group (order by abs(amount)/principal)
  from "NEW_fin_item_fees"
  where fee_type='Commission' and principal > 0
  group by sku
''')
ref_act = {r[0]: float(r[1]) for r in cur.fetchall()}
conn.close()

g["fba_actual"] = g["SKU"].map(fba_act)
g["ref_actual"] = g["SKU"].map(ref_act)
g["fba_act_noVAT"] = (g["fba_actual"] / 1.1).round(3)

print(f"{'SKU':<32} {'un':>3} {'impl@15%':>9} {'impl@16.5%':>10} {'FBA_thật':>9} {'FBA/1.1':>8} {'ref_thật':>8}")
for _, r in g.sort_values("units", ascending=False).iterrows():
    fa = f"{r['fba_actual']:.2f}" if pd.notna(r["fba_actual"]) else "-"
    fn = f"{r['fba_act_noVAT']:.2f}" if pd.notna(r["fba_actual"]) else "-"
    ra = f"{r['ref_actual']:.4f}" if pd.notna(r["ref_actual"]) else "-"
    print(f"{str(r['SKU']):<32} {int(r['units']):>3} {r['impl_15']:>9.2f} {r['impl_165']:>10.2f} {fa:>9} {fn:>8} {ra:>8}")

both = g.dropna(subset=["fba_actual"])
if len(both):
    err15 = (both["impl_15"] - both["fba_actual"]).abs().median()
    err15n = (both["impl_15"] - both["fba_act_noVAT"]).abs().median()
    err165 = (both["impl_165"] - both["fba_actual"]).abs().median()
    err165n = (both["impl_165"] - both["fba_act_noVAT"]).abs().median()
    print(f"\nMedian |sai số| ({len(both)} SKU khớp được):")
    print(f"  SB = 15%   + FBA_thật      : {err15:.3f}")
    print(f"  SB = 15%   + FBA_thật/1.1  : {err15n:.3f}")
    print(f"  SB = 16.5% + FBA_thật      : {err165:.3f}")
    print(f"  SB = 16.5% + FBA_thật/1.1  : {err165n:.3f}")
