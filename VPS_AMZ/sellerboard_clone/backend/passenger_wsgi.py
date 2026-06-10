"""Điểm vào cho cPanel "Setup Python App" (Phusion Passenger - giao thức WSGI).

FastAPI là ASGI nên được bọc bằng a2wsgi.ASGIMiddleware để chạy dưới Passenger.
Trong cPanel:
  - Application root      = thư mục chứa file này (backend/)
  - Application startup    = passenger_wsgi.py
  - Application Entry point = application
"""
import os
import sys

# Passenger chạy từ Application Root; đảm bảo import được package app/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from a2wsgi import ASGIMiddleware  # noqa: E402
from app.main import app as _asgi_app  # noqa: E402

# Passenger tìm biến tên "application"
application = ASGIMiddleware(_asgi_app)
