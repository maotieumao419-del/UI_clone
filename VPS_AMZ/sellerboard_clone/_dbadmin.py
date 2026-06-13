"""Admin DB tạm: liệt kê / đếm / drop. python _dbadmin.py <list|count|drop> [name...]"""
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

NEW_TABLES = {
    # Phase 1 raw
    "NEW_sp_orders", "NEW_sp_order_items", "NEW_fin_item_fees", "NEW_fin_refunds",
    "NEW_fin_adjustments", "NEW_ads_campaigns_daily", "NEW_ads_sp_asin_daily",
    # input tay
    "NEW_product_cogs", "NEW_indirect_expenses", "NEW_product_price", "NEW_fee_cache",
    # Phase 2 master + views
    "NEW_summary_order_items", "NEW_summary_products", "NEW_summary_campaigns",
    "NEW_v_daily_sales_localized", "NEW_v_daily_refunds_localized",
    "NEW_v_daily_fees_localized",
    # view tiện ích từ schema gốc
    "NEW_v_order_items_csv",
}
APP_TABLES = {
    # bảng sống web app (alembic 0001 + 0002)
    "users", "products", "inventory_batches", "orders", "order_items",
    "listing_snapshots", "bsr_snapshots", "alerts", "reimbursement_cases",
    "settlement_entries", "aggregated_daily", "alembic_version",
}
CURRENT = NEW_TABLES | APP_TABLES
COUNT_TABLES = [
    "NEW_sp_orders", "NEW_sp_order_items", "NEW_fin_item_fees", "NEW_fin_refunds",
    "NEW_fin_adjustments", "NEW_ads_campaigns_daily", "NEW_ads_sp_asin_daily",
    "NEW_product_cogs", "NEW_indirect_expenses", "NEW_product_price", "NEW_fee_cache",
    "NEW_summary_order_items", "NEW_summary_products", "NEW_summary_campaigns",
]


def conn():
    return psycopg.connect(URL, autocommit=True, connect_timeout=20)


def cmd_list():
    with conn() as c, c.cursor() as cur:
        cur.execute("""select table_name, table_type from information_schema.tables
            where table_schema='public' order by table_type, table_name""")
        rows = cur.fetchall()
    print(f"{'TÊN':<40} {'LOẠI':<12} TRẠNG THÁI")
    print("-" * 70)
    for name, ttype in rows:
        status = "✅ đang dùng" if name in CURRENT else "❓ KHÔNG thuộc hệ thống hiện tại"
        print(f"{name:<40} {ttype:<12} {status}")
    orphans = [n for n, t in rows if n not in CURRENT]
    print("\nỨng viên XÓA (không thuộc hệ thống hiện tại):")
    for o in orphans:
        print("  -", o)


def cmd_count():
    with conn() as c, c.cursor() as cur:
        print(f"{'BẢNG':<28} SỐ DÒNG")
        print("-" * 40)
        for t in COUNT_TABLES:
            try:
                cur.execute(f'select count(*) from "{t}"')
                print(f"{t:<28} {cur.fetchone()[0]}")
            except Exception as e:
                print(f"{t:<28} (lỗi: {e})")


def cmd_all():
    with conn() as c, c.cursor() as cur:
        cur.execute("""select table_name from information_schema.tables
            where table_schema='public' and table_type='BASE TABLE' order by table_name""")
        names = [r[0] for r in cur.fetchall()]
        print(f"{'BẢNG':<28} SỐ DÒNG   PHÂN LOẠI")
        print("-" * 60)
        for t in names:
            cur.execute(f'select count(*) from "{t}"')
            n = cur.fetchone()[0]
            if t in NEW_TABLES:
                cat = "NEW_ pipeline"
            elif t in APP_TABLES:
                cat = "🔵 BẢNG SỐNG web app (GIỮ)"
            elif t == "raw_amazon_orders":
                cat = "⚠️ LEGACY staging (ứng viên xóa)"
            else:
                cat = "❓ KHÔNG thuộc hệ thống hiện tại"
            print(f"{t:<28} {n:<9} {cat}")


def cmd_status():
    with conn() as c, c.cursor() as cur:
        cur.execute('select order_status, count(*) from "NEW_sp_orders" '
                    'group by 1 order by 2 desc')
        print(f"{'order_status':<20} count")
        print("-" * 30)
        for s, n in cur.fetchall():
            print(f"{str(s):<20} {n}")


def cmd_feematch():
    with conn() as c, c.cursor() as cur:
        cur.execute('select count(distinct order_id) from "NEW_sp_orders"')
        n_orders = cur.fetchone()[0]
        cur.execute('select count(distinct order_id) from "NEW_fin_item_fees"')
        n_fee_ord = cur.fetchone()[0]
        cur.execute('''select count(distinct f.order_id) from "NEW_fin_item_fees" f
                       join "NEW_sp_orders" o on o.order_id=f.order_id''')
        overlap = cur.fetchone()[0]
        print(f"Đơn trong NEW_sp_orders:            {n_orders}")
        print(f"Đơn có fee trong NEW_fin_item_fees: {n_fee_ord}")
        print(f"=> Đơn KHỚP được fee (overlap):     {overlap}")
        cur.execute('''select min((posted_date at time zone 'UTC' at time zone
                       'America/Los_Angeles')::date),
                       max((posted_date at time zone 'UTC' at time zone
                       'America/Los_Angeles')::date) from "NEW_fin_item_fees"''')
        print("Khoảng posted_date của fees (Pacific):", cur.fetchone())
        cur.execute('''select min((purchase_date at time zone 'UTC' at time zone
                       'America/Los_Angeles')::date),
                       max((purchase_date at time zone 'UTC' at time zone
                       'America/Los_Angeles')::date) from "NEW_sp_orders"''')
        print("Khoảng order_date (Pacific):          ", cur.fetchone())


def cmd_sql(path):
    with open(path, encoding="utf-8") as fh:
        sql = fh.read()
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
    print(f"ĐÃ CHẠY SQL: {path}")


def cmd_drop(names):
    with conn() as c, c.cursor() as cur:
        for n in names:
            # tự nhận view hay table
            cur.execute("select table_type from information_schema.tables "
                        "where table_schema='public' and table_name=%s", (n,))
            r = cur.fetchone()
            if not r:
                print(f"  (bỏ qua) {n}: không tồn tại")
                continue
            kind = "VIEW" if r[0] == "VIEW" else "TABLE"
            cur.execute(f'DROP {kind} IF EXISTS "{n}" CASCADE')
            print(f"  ĐÃ XÓA {kind}: {n}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "list"
    if action == "list":
        cmd_list()
    elif action == "all":
        cmd_all()
    elif action == "count":
        cmd_count()
    elif action == "status":
        cmd_status()
    elif action == "feematch":
        cmd_feematch()
    elif action == "sql":
        cmd_sql(sys.argv[2])
    elif action == "drop":
        cmd_drop(sys.argv[2:])
    else:
        print("Dùng: list | count | drop <name...>")
