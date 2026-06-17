"""Phase 3 — manage_user.py
Công cụ quản trị tài khoản đăng nhập app.tap2soul.com (chạy TRÊN VPS).

Backend không có endpoint đổi mật khẩu, và toàn bộ dữ liệu store (orders,
products...) gắn với owner_id = id của user — nên muốn "thống nhất tài khoản"
cho store MUSEMORY thì phải SỬA user hiện có (giữ nguyên id), KHÔNG tạo user
mới (user mới sẽ là dashboard trống không có dữ liệu).

Script này import trực tiếp models + hash_password của chính backend nên
mật khẩu băm đúng chuẩn PBKDF2 hiện hành và ghi vào đúng DB trong
backend/.env (DATABASE_URL).

Cách dùng (từ thư mục gốc ~/VPS_AMZ/sellerboard_clone trên VPS):

  # 1. Xem danh sách tài khoản hiện có (id, email, số sản phẩm...)
  python3 Phase3/manage_user.py --list

  # 2. Đổi email + mật khẩu của user hiện có (giữ nguyên dữ liệu)
  python3 Phase3/manage_user.py --set --id 1 \
      --new-email musemory@sellervision.io --password 'MUSEMORY1234'

  #    (hoặc chọn theo email cũ thay vì id)
  python3 Phase3/manage_user.py --set --email cu@example.com \
      --new-email musemory@sellervision.io --password 'MUSEMORY1234'

  # 3. Chỉ đổi mật khẩu, giữ email
  python3 Phase3/manage_user.py --set --email musemory@sellervision.io \
      --password 'MatKhauMoi123'

  # 4. Tạo tài khoản MỚI (cảnh báo: không có dữ liệu store sẵn)
  python3 Phase3/manage_user.py --create \
      --email them@example.com --password 'MatKhau123' --full-name 'Ten'

Sau khi đổi KHÔNG cần restart backend (DB đọc mỗi lần login).
"""
import argparse
import sys
from pathlib import Path

# Console Windows mặc định cp1252 — ép UTF-8 để in được tiếng Việt
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

# Cho phép import code backend (app.*) dù chạy từ thư mục gốc dự án
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from sqlalchemy import func, select
    from sqlalchemy.exc import OperationalError

    from app.core.security import hash_password, verify_password
    from app.database import SessionLocal
    from app.models import Order, Product, User
except Exception as exc:  # noqa: BLE001
    raise SystemExit(
        f"[LỖI] Không import được backend ({exc}).\n"
        "Hãy chạy từ thư mục gốc dự án: cd ~/VPS_AMZ/sellerboard_clone && "
        "python3 Phase3/manage_user.py --list\n"
        "(cần cùng môi trường Python/venv mà backend đang dùng)"
    )


def cmd_list(db) -> None:
    """Liệt kê tài khoản + số liệu gắn kèm để biết user nào giữ dữ liệu store."""
    users = db.scalars(select(User).order_by(User.id)).all()
    if not users:
        print("(chưa có tài khoản nào trong DB)")
        return
    print(f"{'id':>3}  {'email':<40} {'active':<7} {'sản phẩm':>9} {'đơn hàng':>9}  full_name")
    for u in users:
        n_products = db.scalar(select(func.count(Product.id)).where(Product.owner_id == u.id)) or 0
        n_orders = db.scalar(select(func.count(Order.id)).where(Order.owner_id == u.id)) or 0
        print(f"{u.id:>3}  {u.email:<40} {str(u.is_active):<7} {n_products:>9} {n_orders:>9}  {u.full_name or ''}")
    print("\n=> User có 'sản phẩm/đơn hàng' > 0 chính là tài khoản đang giữ dữ liệu store.")


def _find_user(db, args) -> "User":
    if args.id is not None:
        u = db.get(User, args.id)
        if not u:
            raise SystemExit(f"[LỖI] Không có user id={args.id}. Chạy --list để xem.")
        return u
    if args.email:
        u = db.scalar(select(User).where(User.email == args.email))
        if not u:
            # Gợi ý các email gần giống (case-insensitive) vì login phân biệt hoa thường
            similar = db.scalars(select(User).where(
                func.lower(User.email) == args.email.lower())).all()
            hint = f" (Có email gần giống: {[s.email for s in similar]})" if similar else ""
            raise SystemExit(f"[LỖI] Không có user email='{args.email}'.{hint} Chạy --list để xem.")
        return u
    raise SystemExit("[LỖI] --set cần --id hoặc --email để chọn user.")


def cmd_set(db, args) -> None:
    """Đổi email/mật khẩu user hiện có — giữ nguyên id nên dữ liệu store còn nguyên."""
    u = _find_user(db, args)
    changed = []
    if args.new_email and args.new_email != u.email:
        dup = db.scalar(select(User).where(User.email == args.new_email, User.id != u.id))
        if dup:
            raise SystemExit(f"[LỖI] Email '{args.new_email}' đã thuộc user id={dup.id}.")
        print(f"  email: {u.email}  ->  {args.new_email}")
        u.email = args.new_email
        changed.append("email")
    if args.password:
        u.hashed_password = hash_password(args.password)
        changed.append("mật khẩu")
    if args.activate:
        u.is_active = True
        changed.append("kích hoạt")
    if not changed:
        raise SystemExit("[LỖI] --set cần ít nhất --new-email / --password / --activate.")

    db.commit()
    db.refresh(u)
    # Tự kiểm chứng: verify lại mật khẩu vừa ghi
    if args.password and not verify_password(args.password, u.hashed_password):
        raise SystemExit("[LỖI] Verify mật khẩu sau khi ghi THẤT BẠI — kiểm tra lại DB!")
    print(f"[OK] Đã cập nhật user id={u.id} ({', '.join(changed)}).")
    print(f"     Đăng nhập app.tap2soul.com bằng: {u.email} / <mật khẩu vừa đặt>")
    print("     (email phân biệt HOA/thường — gõ đúng y hệt chuỗi trên)")


def cmd_create(db, args) -> None:
    """Tạo tài khoản mới (dashboard trống — dữ liệu store thuộc user khác)."""
    if not args.email or not args.password:
        raise SystemExit("[LỖI] --create cần --email và --password.")
    if db.scalar(select(User).where(User.email == args.email)):
        raise SystemExit(f"[LỖI] Email '{args.email}' đã tồn tại — dùng --set để đổi mật khẩu.")
    u = User(email=args.email, full_name=args.full_name or "",
             hashed_password=hash_password(args.password),
             consent={"analytics": True, "marketing": False, "data_sharing": False})
    db.add(u)
    db.commit()
    db.refresh(u)
    print(f"[OK] Đã tạo user id={u.id}: {u.email}")
    print("[CHÚ Ý] User mới KHÔNG có dữ liệu store (owner_id khác) — muốn thống nhất "
          "tài khoản cho store hiện có thì dùng --set trên user cũ thay vì tạo mới.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Quản trị tài khoản SellerVision (chạy trên VPS)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="Liệt kê tài khoản")
    g.add_argument("--set", action="store_true", help="Đổi email/mật khẩu user hiện có")
    g.add_argument("--create", action="store_true", help="Tạo tài khoản mới")
    ap.add_argument("--id", type=int, help="Chọn user theo id (cho --set)")
    ap.add_argument("--email", help="Email hiện tại (chọn user cho --set) hoặc email mới (cho --create)")
    ap.add_argument("--new-email", help="Email mới (cho --set)")
    ap.add_argument("--password", help="Mật khẩu mới")
    ap.add_argument("--full-name", help="Tên hiển thị (cho --create)")
    ap.add_argument("--activate", action="store_true", help="Bật lại is_active (cho --set)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            cmd_list(db)
        elif args.set:
            cmd_set(db, args)
        else:
            cmd_create(db, args)
    except OperationalError as exc:
        raise SystemExit(
            f"[LỖI] Không truy vấn được DB ({exc.orig}).\n"
            "DB này chưa có bảng 'users' — gần như chắc chắn bạn đang chạy trên máy "
            "khác (mirror local) thay vì VPS. Hãy SSH vào VPS rồi chạy:\n"
            "  cd ~/VPS_AMZ/sellerboard_clone && python3 Phase3/manage_user.py --list"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
