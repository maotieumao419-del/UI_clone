"""Liệt kê cột các bảng liên quan (products, ads, summary)."""
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import os
from dotenv import dotenv_values
import psycopg

script_dir = os.path.dirname(os.path.abspath(__file__))
env = dotenv_values(os.path.join(script_dir, "backend", ".env"))
URL = env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
conn = psycopg.connect(URL, connect_timeout=20, prepare_threshold=None)
cur = conn.cursor()
for t in ("products", "NEW_ads_campaigns_daily", "NEW_ads_sp_asin_daily",
          "NEW_summary_order_items", "NEW_summary_products", "NEW_sp_order_items"):
    cur.execute("select column_name, data_type from information_schema.columns "
                "where table_name=%s order by ordinal_position", (t,))
    cols = cur.fetchall()
    print(f"\n== {t} ({len(cols)} cột) ==")
    print("  " + ", ".join(f"{c}:{d}" for c, d in cols))
cur.execute('select count(*), count(distinct asin) from "NEW_sp_order_items"')
print("\nNEW_sp_order_items rows / distinct asin:", cur.fetchone())
cur.execute("select count(*) from products")
print("products rows:", cur.fetchone()[0])
conn.close()
