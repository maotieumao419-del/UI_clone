# SellerVision - image production (backend FastAPI + phục vụ luôn SPA frontend)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Cài thư viện trước để tận dụng cache layer
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --upgrade pip && pip install -r backend/requirements.txt

# Copy mã nguồn
COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend
RUN mkdir -p data/ppc

EXPOSE 8000

# PORT & WEB_CONCURRENCY lấy từ ENV (nền tảng deploy thường tự set PORT).
# --forwarded-allow-ips=* để tin cậy header HTTPS từ reverse proxy phía trước.
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 120 --forwarded-allow-ips=*"]
