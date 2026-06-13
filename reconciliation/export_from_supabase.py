"""Export 2 bảng Master từ Supabase ra xlsx (để so với Sellerboard).
Dùng: python export_from_supabase.py 2026-06-03
Ghi vào reconciliation/data/input/:
  Order_Items-<ddmmyy>.xlsx   (sheet 'NEW_summary_order_items_rows')
  Products-<ddmmyy>.xlsx      (sheet 'NEW_summary_products_rows')
"""
import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import dotenv_values

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "data", "input")
os.makedirs(OUT, exist_ok=True)

# DATABASE_URL từ backend/.env
env = dotenv_values(os.path.join(ROOT, "VPS_AMZ", "sellerboard_clone", "backend", ".env"))
URL = env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

date_arg = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
tag = datetime.strptime(date_arg, "%Y-%m-%d").strftime("%d%m%y")

import psycopg
conn = psycopg.connect(URL, connect_timeout=20)


def read(sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


# Lọc theo ĐÚNG ngày (cho phép giữ nhiều ngày trong bảng, export riêng từng ngày)
items = read('select * from "NEW_summary_order_items" where order_date = %s '
             'order by order_number, sku', (date_arg,))
prods = read('select * from "NEW_summary_products" where period_start = %s '
             'order by net_profit desc', (date_arg,))
conn.close()

f_items = os.path.join(OUT, f"Order_Items-{tag}.xlsx")
f_prods = os.path.join(OUT, f"Products-{tag}.xlsx")
with pd.ExcelWriter(f_items, engine="openpyxl") as w:
    items.to_excel(w, sheet_name="NEW_summary_order_items_rows", index=False)
with pd.ExcelWriter(f_prods, engine="openpyxl") as w:
    prods.to_excel(w, sheet_name="NEW_summary_products_rows", index=False)

print(f"✅ Order_Items: {len(items)} dòng -> {f_items}")
print(f"✅ Products:    {len(prods)} dòng -> {f_prods}")
# Tóm tắt nhanh
fee_actual = items.loc[items["fee_state"] == "ACTUAL", "amazon_fees"].sum()
fee_est = items.loc[items["fee_state"] == "ESTIMATED", "amazon_fees"].sum()
print(f"   amazon_fees: ACTUAL={fee_actual:.2f}  ESTIMATED={fee_est:.2f}  "
      f"TỔNG={items['amazon_fees'].sum():.2f}")
print(f"   sales={items['sales'].sum():.2f}  net={items['net_profit'].sum():.2f}")
