import os
from dotenv import dotenv_values
import psycopg

script_dir = os.path.dirname(os.path.abspath(__file__))
env = dotenv_values(os.path.join(script_dir, "backend", ".env"))
URL = env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
conn = psycopg.connect(URL, connect_timeout=20)
cur = conn.cursor()
cur.execute(
    "select column_name, data_type from information_schema.columns "
    "where table_name='NEW_fin_item_fees' order by ordinal_position"
)
for c in cur.fetchall():
    print(c)
cur.execute(
    'select count(*), count(*) filter (where principal is not null and principal <> 0) '
    'from "NEW_fin_item_fees"'
)
print("rows total / with principal:", cur.fetchone())
cur.execute(
    'select min(posted_date), max(posted_date) from "NEW_fin_item_fees"'
)
print("posted_date range:", cur.fetchone())
conn.close()
