"""Lớp kết nối CSDL bằng SQLAlchemy 2.0 (ORM cho dữ liệu giao dịch).

Production: DATABASE_URL trỏ tới Supabase PostgreSQL (psycopg driver).
Dev local : DATABASE_URL để mặc định SQLite để khởi động nhanh không cần cloud.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# check_same_thread chỉ cần cho SQLite (multi-thread Gunicorn worker).
# prepare_threshold=None: tắt prepared statements cho Supabase Transaction Pooler
# (PgBouncer transaction mode không hỗ trợ prepared statements).
connect_args = {"check_same_thread": False} if _is_sqlite else {"prepare_threshold": None}

# Supabase free tier giới hạn ~50 kết nối trực tiếp (Pooler mode: ~100).
# pool_size + max_overflow không áp dụng cho SQLite (StaticPool).
pool_kwargs = (
    {"pool_size": 5, "max_overflow": 10, "pool_timeout": 30}
    if not _is_sqlite else {}
)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    **pool_kwargs,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency của FastAPI: mở session cho mỗi request rồi đóng lại."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
