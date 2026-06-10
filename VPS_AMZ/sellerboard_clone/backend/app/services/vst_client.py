"""Client gọi API VST (và SPI sau này) để lấy dữ liệu bán hàng/PPC.

Thay cho việc đọc file Excel vật lý. Bật bằng ENV DATA_SOURCE=vst.
Mọi key/token đọc từ ENV (config.settings) — KHÔNG hardcode, KHÔNG commit.

Hỗ trợ 2 kiểu API trả về (theo yêu cầu: vừa JSON cho UI, vừa cho tải Excel):
  - JSON              -> fetch_listing_json()        : danh sách SKU hiển thị ngay
  - link tải Excel    -> fetch_ppc_workbook_bytes()  : tải file -> tái dùng parser openpyxl

LƯU Ý: tên endpoint ("/v1/listing", "/v1/ppc/export") và cách map field bên dưới là
PLACEHOLDER. Khi có tài liệu API VST thật, chỉ sửa trong file này — phần còn lại của app
(router, parser ppc.py) không phải đụng tới.
"""
from __future__ import annotations    # annotation thành lazy: 'requests' có thể chưa cài

from ..config import settings

# Import 'requests' kiểu lazy: chế độ DATA_SOURCE=file vẫn chạy được dù host chưa cài lib.
try:
    import requests
except ImportError:                                  # pragma: no cover
    requests = None


class VSTError(RuntimeError):
    """Lỗi khi gọi API VST — router/service bắt và trả thông báo thân thiện cho UI."""


# ---------------------------------------------------------------- HTTP nền
def _headers() -> dict:
    """Header xác thực. Đổi scheme nếu VST không dùng Bearer (vd 'X-Api-Key')."""
    h = {"Accept": "application/json"}
    if settings.VST_API_KEY:
        h["Authorization"] = f"Bearer {settings.VST_API_KEY}"
    return h


def _request(method: str, path: str, *, params: dict | None = None):
    if requests is None:
        raise VSTError("Thiếu thư viện 'requests' — chạy: pip install -r requirements.txt")
    if not settings.VST_API_BASE:
        raise VSTError("Chưa cấu hình VST_API_BASE trong .env (cần khi DATA_SOURCE=vst).")
    # Cho phép path là URL tuyệt đối (vd link tải file API trả về) hoặc đường dẫn tương đối.
    url = path if path.startswith("http") else settings.VST_API_BASE.rstrip("/") + path
    try:
        r = requests.request(
            method, url,
            headers=_headers(), params=params,
            timeout=settings.VST_TIMEOUT, verify=settings.VST_VERIFY_SSL,
        )
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        raise VSTError(f"Lỗi gọi VST {method} {url}: {e}") from e


def _get(path: str, params: dict | None = None) -> requests.Response:
    return _request("GET", path, params=params)


# ---------------------------------------------------------------- JSON cho UI
def fetch_listing_json(store: str | None = None) -> list[dict]:
    """Danh sách SKU dạng JSON (hiển thị thẳng lên UI, không qua Excel).

    TODO khi có API thật: chỉnh tên endpoint + map field cho khớp schema VST.
    Schema UI cần: {stt, sku, store, link, portfolio_id, portfolio_name, status, has_detail}
    """
    data = _get("/v1/listing", params={"store": store} if store else None).json()
    items = data.get("items", data) if isinstance(data, dict) else data
    out = []
    for i, row in enumerate(items or []):
        out.append({
            "stt": i + 1,
            "sku": row.get("sku") or row.get("SKU") or "",
            "store": row.get("store", store or ""),
            "link": row.get("link", ""),
            "portfolio_id": row.get("portfolio_id", ""),
            "portfolio_name": row.get("portfolio_name", ""),
            "status": row.get("status", ""),
            "has_detail": bool(row.get("has_detail", True)),
        })
    return out


# ---------------------------------------------------------------- Excel -> bytes
def fetch_ppc_workbook_bytes(store: str | None = None) -> bytes:
    """Lấy file Excel PPC của store dưới dạng bytes (để tái dùng parser openpyxl cũ).

    Hỗ trợ 2 kịch bản API:
      (a) API trả thẳng nhị phân Excel  -> dùng luôn r.content
      (b) API trả JSON có 'download_url' -> tải link đó về
    TODO khi có API thật: chỉnh endpoint/field cho khớp.
    """
    r = _get("/v1/ppc/export", params={"store": store} if store else None)
    ctype = r.headers.get("Content-Type", "")
    # (a) Trả thẳng file Excel
    if "spreadsheet" in ctype or "octet-stream" in ctype or "excel" in ctype:
        return r.content
    # (b) Trả JSON chứa link tải
    try:
        meta = r.json()
    except ValueError as e:
        raise VSTError(f"VST trả dữ liệu không hiểu (Content-Type={ctype}).") from e
    file_url = meta.get("download_url") or meta.get("url")
    if not file_url:
        raise VSTError("API VST không trả 'download_url' để tải Excel.")
    return _get(file_url).content


def list_stores_json() -> list[dict]:
    """(Tuỳ chọn) Danh sách store từ API. Trả [] nếu API chưa hỗ trợ — service tự fallback."""
    try:
        data = _get("/v1/stores").json()
    except VSTError:
        return []
    items = data.get("items", data) if isinstance(data, dict) else data
    return [{"store": x.get("store") or x.get("name"), "file": x.get("file", "")}
            for x in (items or []) if x.get("store") or x.get("name")]
