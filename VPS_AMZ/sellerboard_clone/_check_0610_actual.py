"""Phí THẬT (settled) của các đơn đặt ngày 10/06 Pacific — so với Sellerboard -323.41."""
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

DAY = "2026-06-10"

# Đơn ngày 10/06 (Pacific)
cur.execute('''
  with d as (
    select order_id, order_status from "NEW_sp_orders"
    where (purchase_date at time zone 'UTC' at time zone 'America/Los_Angeles')::date = %s
  )
  select count(*), count(*) filter (where order_status='Canceled') from d
''', (DAY,))
n_orders, n_cancel = cur.fetchone()
print(f"Đơn 10/06: {n_orders} (canceled: {n_cancel})")

# Coverage: bao nhiêu đơn 10/06 đã có phí thật
cur.execute('''
  with d as (
    select order_id from "NEW_sp_orders"
    where (purchase_date at time zone 'UTC' at time zone 'America/Los_Angeles')::date = %s
      and order_status <> 'Canceled'
  )
  select count(distinct d.order_id),
         count(distinct f.order_id)
  from d left join "NEW_fin_item_fees" f on f.order_id = d.order_id
''', (DAY,))
total, with_fees = cur.fetchone()
print(f"Coverage phí thật: {with_fees}/{total} đơn")

# Tổng phí thật theo bucket cho đơn 10/06
cur.execute('''
  with d as (
    select order_id from "NEW_sp_orders"
    where (purchase_date at time zone 'UTC' at time zone 'America/Los_Angeles')::date = %s
      and order_status <> 'Canceled'
  )
  select f.fee_type, count(*), round(sum(f.amount),2), sum(f.quantity)
  from "NEW_fin_item_fees" f join d on d.order_id = f.order_id
  group by 1 order by 3
''', (DAY,))
print("\n== Phí thật đơn 10/06 theo fee_type ==")
tot_comm = tot_fba = 0.0
for ft, n, s, q in cur.fetchall():
    print(f"  {ft:<30} n={n:<4} qty={q:<4} sum={s}")
    if "commission" in ft.lower():
        tot_comm = float(s)
    if "fbaperunit" in ft.lower():
        tot_fba = float(s)
print(f"\n  => amazon_fees THẬT (Commission+FBA) phần đã settle: {round(tot_comm+tot_fba,2)}")

# Units & principal đã settle vs tổng đơn hàng
cur.execute('''
  with d as (
    select order_id from "NEW_sp_orders"
    where (purchase_date at time zone 'UTC' at time zone 'America/Los_Angeles')::date = %s
      and order_status <> 'Canceled'
  )
  select coalesce(sum(f.quantity),0), round(coalesce(sum(f.principal),0),2)
  from "NEW_fin_item_fees" f join d on d.order_id = f.order_id
  where f.fee_type='Commission'
''', (DAY,))
q_settled, p_settled = cur.fetchone()
print(f"  Units đã settle (Commission rows): {q_settled}, principal settle: ${p_settled}")

cur.execute('''
  select coalesce(sum(i.quantity_ordered),0), round(coalesce(sum(i.item_price),0),2)
  from "NEW_sp_order_items" i join "NEW_sp_orders" o on o.order_id = i.order_id
  where (o.purchase_date at time zone 'UTC' at time zone 'America/Los_Angeles')::date = %s
    and o.order_status <> 'Canceled'
''', (DAY,))
q_all, sales_all = cur.fetchone()
print(f"  Tổng units đơn 10/06: {q_all}, sales (item_price, chưa impute): ${sales_all}")

# FBA per-unit thật theo SKU (đơn 10/06)
cur.execute('''
  with d as (
    select order_id from "NEW_sp_orders"
    where (purchase_date at time zone 'UTC' at time zone 'America/Los_Angeles')::date = %s
      and order_status <> 'Canceled'
  )
  select f.sku, sum(f.quantity), round(sum(abs(f.amount))::numeric,2),
         round((sum(abs(f.amount))/sum(f.quantity))::numeric, 2)
  from "NEW_fin_item_fees" f join d on d.order_id = f.order_id
  where f.fee_type = 'FBAPerUnitFulfillmentFee'
  group by 1 order by 2 desc
''', (DAY,))
print("\n== FBA thật per-unit theo SKU (đơn 10/06) ==")
for r in cur.fetchall():
    print(f"  {r[0]:<32} qty={r[1]:<4} sum={r[2]:<8} per_unit={r[3]}")
conn.close()
