"""Phân tích rate = |commission| / principal từ phí thật (đã có principal)."""
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
conn = psycopg.connect(URL, connect_timeout=20)
cur = conn.cursor()

# 1) Các fee_type hiện có
cur.execute('select fee_type, count(*), round(sum(amount),2) from "NEW_fin_item_fees" group by 1 order by 2 desc')
print("== fee_type ==")
for r in cur.fetchall():
    print(f"  {r[0]:<35} n={r[1]:<5} sum={r[2]}")

# 2) Phân phối rate per-row cho Commission
cur.execute('''
  select percentile_cont(array[0.05,0.25,0.5,0.75,0.95]) within group (order by abs(amount)/principal)
  from "NEW_fin_item_fees"
  where fee_type ilike '%commission%' and principal > 0
''')
print("\n== rate=|commission|/principal quantiles [p5,p25,p50,p75,p95] ==")
print(" ", [round(float(x), 4) for x in cur.fetchone()[0]])

# 3) Đếm theo bucket rate
cur.execute('''
  select case
           when abs(amount)/principal < 0.145 then '<14.5%'
           when abs(amount)/principal < 0.155 then '~15%'
           when abs(amount)/principal < 0.18  then '15.5-18%'
           else '>=18%' end as bucket,
         count(*), round(avg(principal)::numeric,2) as avg_principal,
         round(avg(abs(amount))::numeric,2) as avg_comm
  from "NEW_fin_item_fees"
  where fee_type ilike '%commission%' and principal > 0
  group by 1 order by 1
''')
print("\n== bucket rate ==")
for r in cur.fetchall():
    print(f"  {r[0]:<10} n={r[1]:<5} avg_principal={r[2]:<8} avg_comm={r[3]}")

# 4) Ví dụ 15 dòng rate cao nhất
cur.execute('''
  select order_id, sku, quantity, principal, amount,
         round((abs(amount)/principal)::numeric, 4) as rate
  from "NEW_fin_item_fees"
  where fee_type ilike '%commission%' and principal > 0
  order by abs(amount)/principal desc limit 15
''')
print("\n== top 15 rate cao nhất ==")
for r in cur.fetchall():
    print(f"  {r[0]} {r[1]:<28} qty={r[2]} principal={r[3]:<8} comm={r[4]:<7} rate={r[5]}")

# 5) Ví dụ 10 dòng rate ~ thấp nhất
cur.execute('''
  select order_id, sku, quantity, principal, amount,
         round((abs(amount)/principal)::numeric, 4) as rate
  from "NEW_fin_item_fees"
  where fee_type ilike '%commission%' and principal > 0
  order by abs(amount)/principal asc limit 10
''')
print("\n== top 10 rate thấp nhất ==")
for r in cur.fetchall():
    print(f"  {r[0]} {r[1]:<28} qty={r[2]} principal={r[3]:<8} comm={r[4]:<7} rate={r[5]}")

# 6) Tổng thể: sum(comm)/sum(principal) — weighted rate
cur.execute('''
  select round((sum(abs(amount))/sum(principal))::numeric, 4)
  from "NEW_fin_item_fees" where fee_type ilike '%commission%' and principal > 0
''')
print("\nWeighted rate sum(|comm|)/sum(principal):", cur.fetchone()[0])
conn.close()
