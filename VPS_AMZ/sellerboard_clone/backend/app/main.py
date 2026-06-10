"""Điểm vào FastAPI - kiến trúc Headless: REST API + phục vụ SPA dashboard.

Dev:   uvicorn app.main:app --reload
Prod:  gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --workers 2
Docs:  /docs   ·   UI: /
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import alerts, auth, dashboard, ethics, inventory, ppc, products, ads, spapi, amazon_sync

# Schema do Alembic quản lý — chạy "alembic upgrade head" trước khi khởi động app.
# Đảm bảo thư mục upload PPC tồn tại
os.makedirs(settings.PPC_DIR, exist_ok=True)

# Ẩn /docs khi chạy production cho an toàn (bật lại bằng ENV=dev)
_is_prod = settings.ENV.lower() == "prod"
app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description="Nền tảng phân tích lợi nhuận & vận hành cho người bán Amazon "
                "(clone Sellerboard + Lớp Đạo đức Dữ liệu).",
    version="0.1.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
)

# Chống Host header giả mạo (chỉ bật khi đã giới hạn domain cụ thể)
if settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routers
for r in (auth, products, dashboard, inventory, alerts, ethics, ppc, ads, spapi, amazon_sync):
    app.include_router(r.router)


@app.on_event("startup")
def _start_amazon_auto_sync():
    """Tu dong dong bo Amazon dinh ky o nen, de mo dashboard luc nao cung co so lieu moi
    ma khong can bam nut Sync (xem app/routers/amazon_sync.py: start_auto_sync_thread)."""
    if settings.AMAZON_SPI_CLIENT_ID and settings.AMAZON_AUTO_SYNC_ENABLED:
        amazon_sync.start_auto_sync_thread()


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENV}


# ----- Phục vụ frontend SPA (web). App mobile gọi cùng REST API ở trên. -----
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))


# Cho phép chạy trực tiếp: `python -m app.main` (một số PaaS cần) — đọc PORT từ ENV.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", settings.PORT)),
        proxy_headers=True,            # tin cậy X-Forwarded-* sau reverse proxy/HTTPS
        forwarded_allow_ips="*",
    )
