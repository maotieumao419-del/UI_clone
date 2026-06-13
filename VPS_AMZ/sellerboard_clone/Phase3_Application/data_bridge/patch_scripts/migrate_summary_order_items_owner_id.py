"""Phase 3 — migrate_summary_order_items_owner_id.py
Thêm cột `owner_id` vào bảng "NEW_summary_order_items" (đã tồn tại trên Postgres
production qua Supabase pooler) và đưa nó vào PRIMARY KEY, để khớp với model
SummaryOrderItem mới và với bảng "NEW_summary_products" (đã có owner_id từ trước).

Idempotent: nếu cột owner_id đã tồn tại -> không làm gì thêm.

Các bước:
  1. ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE (nullable).
  2. UPDATE ... SET owner_id = 1 WHERE owner_id IS NULL  (DB hiện chỉ có 1 user, id=1).
  3. ALTER COLUMN owner_id SET NOT NULL.
  4. DROP CONSTRAINT PK cũ (order_number, asin, sku, row_type) -> ADD PK mới
     (owner_id, order_number, sku, asin, row_type).

Chạy:
    cd ~/VPS_AMZ/sellerboard_clone
    python Phase3_Application/data_bridge/patch_scripts/migrate_summary_order_items_owner_id.py
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402
from app.database import engine  # noqa: E402

TABLE = "NEW_summary_order_items"


def main() -> None:
    with engine.begin() as conn:
        cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t"
            ), {"t": TABLE}).fetchall()
        }
        if "owner_id" in cols:
            print(f'[OK] "{TABLE}" đã có cột owner_id — không làm gì thêm.')
            return

        print(f'[1/4] ADD COLUMN owner_id vào "{TABLE}"...')
        conn.execute(text(
            f'ALTER TABLE "{TABLE}" ADD COLUMN owner_id INTEGER '
            f'REFERENCES "users"("id") ON DELETE CASCADE'
        ))

        print('[2/4] Backfill owner_id = 1 cho các dòng hiện có...')
        result = conn.execute(text(
            f'UPDATE "{TABLE}" SET owner_id = 1 WHERE owner_id IS NULL'
        ))
        print(f'      -> {result.rowcount} dòng đã được gán owner_id = 1')

        print('[3/4] SET owner_id NOT NULL...')
        conn.execute(text(f'ALTER TABLE "{TABLE}" ALTER COLUMN owner_id SET NOT NULL'))

        print('[4/4] Cập nhật PRIMARY KEY -> (owner_id, order_number, sku, asin, row_type)...')
        pk_name = conn.execute(text(
            "SELECT tc.constraint_name FROM information_schema.table_constraints tc "
            "WHERE tc.table_name = :t AND tc.constraint_type = 'PRIMARY KEY'"
        ), {"t": TABLE}).scalar()
        conn.execute(text(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{pk_name}"'))
        conn.execute(text(
            f'ALTER TABLE "{TABLE}" ADD PRIMARY KEY (owner_id, order_number, sku, asin, row_type)'
        ))

    print(f'[OK] Đã thêm owner_id và cập nhật PRIMARY KEY cho "{TABLE}".')


if __name__ == "__main__":
    main()
