"""So phí Sellerboard báo (file 03/06) vs phí THẬT đã settle trong NEW_fin_item_fees."""
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd
import os
from dotenv import dotenv_values
import psycopg
# ... (rest of imports or setup)
SB_FILE = r"C:\Users\nnh16\ads-trading-system\VPS\Dr_Hai_Craft_Order_Items-030626.xlsx"
df = pd.read_excel(SB_FILE)
print("Cột:", list(df.columns))
print("Số dòng:", len(df))

# Tìm cột order id và amazon fees
col_order = next(c for c in df.columns if "rder" in str(c))
col_fees = next(c for c in df.columns if "mazon" in str(c).lower() and "fee" in str(c).lower())
col_units = next((c for c in df.columns if str(c).strip().lower() in ("units", "quantity", "qty")), None)
print(f"-> order col: {col_order!r}, fees col: {col_fees!r}, units col: {col_units!r}")

sb = df[[col_order, col_fees] + ([col_units] if col_units else [])].copy()
sb.columns = ["order_id", "sb_fees"] + (["units"] if col_units else [])
sb["sb_fees"] = pd.to_numeric(sb["sb_fees"], errors="coerce").fillna(0.0)
sb = sb.groupby("order_id", as_index=False).agg({"sb_fees": "sum", **({"units": "sum"} if col_units else {})})
print(f"Đơn trong file SB: {len(sb)}, tổng SB amazon_fees: {round(sb['sb_fees'].sum(), 2)}")

script_dir = os.path.dirname(os.path.abspath(__file__))
env = dotenv_values(os.path.join(script_dir, "backend", ".env"))
URL = env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
conn = psycopg.connect(URL, connect_timeout=20)
cur = conn.cursor()
ids = list(sb["order_id"].astype(str))
cur.execute('''
  select order_id,
         round(sum(amount) filter (where fee_type='Commission'), 2)               as comm,
         round(sum(amount) filter (where fee_type='FBAPerUnitFulfillmentFee'), 2) as fba
  from "NEW_fin_item_fees" where order_id = any(%s) group by 1
''', (ids,))
act = pd.DataFrame(cur.fetchall(), columns=["order_id", "comm", "fba"])
act["comm"] = pd.to_numeric(act["comm"], errors="coerce").fillna(0.0)
act["fba"] = pd.to_numeric(act["fba"], errors="coerce").fillna(0.0)
act["actual_fees"] = act["comm"] + act["fba"]
conn.close()

m = sb.merge(act, on="order_id", how="left")
m["settled"] = m["actual_fees"].notna()
print(f"\nCoverage: {int(m['settled'].sum())}/{len(m)} đơn 03/06 đã có phí thật")

s = m[m["settled"]]
print(f"\n== Phần đã settle ({len(s)} đơn) ==")
print(f"  SB báo   : {round(s['sb_fees'].sum(), 2)}")
print(f"  Thật     : {round(s['actual_fees'].sum(), 2)}  (comm {round(s['comm'].sum(),2)}, fba {round(s['fba'].sum(),2)})")
print(f"  Tỷ lệ thật/SB: {round(s['actual_fees'].sum() / s['sb_fees'].sum(), 4) if s['sb_fees'].sum() else '?'}")

print("\n== Per-order (15 dòng đầu, lệch giảm dần) ==")
s = s.copy()
s["diff"] = (s["actual_fees"] - s["sb_fees"]).round(2)
s = s.sort_values("diff", key=lambda x: x.abs(), ascending=False)
for _, r in s.head(15).iterrows():
    print(f"  {r['order_id']}  SB={r['sb_fees']:<8} thật={round(r['actual_fees'],2):<8} diff={r['diff']}")

ns = m[~m["settled"]]
if len(ns):
    print(f"\nChưa settle ({len(ns)} đơn): SB báo tổng {round(ns['sb_fees'].sum(), 2)}")
