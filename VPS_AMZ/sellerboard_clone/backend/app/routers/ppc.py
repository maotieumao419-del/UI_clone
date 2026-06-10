"""Router PPC đa-store: stores -> listing -> campaign theo SKU -> metrics + export + upload."""
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from ..deps import get_current_user
from ..models import User
from ..services import ppc as ppc_service

router = APIRouter(prefix="/api/ppc", tags=["ppc"])

MAX_UPLOAD_MB = 25


@router.get("/stores")
def stores(current: User = Depends(get_current_user)):
    """Danh sách store (mỗi store = 1 file Excel PPC)."""
    return ppc_service.list_stores()


@router.post("/upload")
async def upload(file: UploadFile = File(...), current: User = Depends(get_current_user)):
    """Upload file Excel PPC lên server (thay cho đường dẫn local khi chạy trên domain)."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        return {"error": f"File quá lớn (>{MAX_UPLOAD_MB}MB)"}
    return ppc_service.save_upload(file.filename, content)


@router.get("/listing")
def listing(store: str | None = Query(None), current: User = Depends(get_current_user)):
    """Danh sách Listing (SKU) của 1 store."""
    return ppc_service.get_listing(store)


@router.get("/sku")
def sku_detail(sku: str = Query(..., description="Mã SKU lấy từ danh sách Listing"),
              store: str | None = Query(None),
              current: User = Depends(get_current_user)):
    """Chi tiết 1 SKU: campaign + target + Impression/Click/Order + CTR/CVR theo kỳ."""
    return ppc_service.get_sku_detail(sku, store)


@router.get("/export")
def export(store: str | None = Query(None),
           sku: str | None = Query(None, description="Bỏ trống = xuất cả store"),
           format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
           current: User = Depends(get_current_user)):
    """Xuất kết quả (1 SKU hoặc cả store) ra CSV/Excel, đã gồm CTR/CVR."""
    name = (sku or store or "ppc").replace(" ", "_").replace(",", "")
    if format == "csv":
        data = ppc_service.export_csv(store, sku)
        media = "text/csv"
        fname = f"PPC_{name}.csv"
    else:
        data = ppc_service.export_xlsx(store, sku)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        fname = f"PPC_{name}.xlsx"
    import io
    return StreamingResponse(io.BytesIO(data), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})
