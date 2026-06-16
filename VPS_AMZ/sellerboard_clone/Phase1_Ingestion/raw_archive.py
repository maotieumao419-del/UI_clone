"""Phase 1 — Raw archive (tầng bronze bất biến) lên Cloudflare R2.

SellerVision gốc stream thẳng API → Supabase NEW_* (mutable, --fresh xóa được),
KHÔNG giữ raw. Module này đẩy BẢN SAO BẤT BIẾN của payload thô lên object storage
R2 (S3-compatible) TRƯỚC khi NEW_* bị ghi đè — để:
  - re-transform / sửa công thức KHỎI phải pull lại Amazon (tốn quota),
  - audit + backfill khi cần.

Bật bằng RAW_ARCHIVE_ENABLED=1 + nhóm R2_* trong .env (xem .env.example).
Triết lý: archive là PHỤ TRỢ — mọi lỗi R2/log chỉ in cảnh báo, KHÔNG raise,
KHÔNG chặn luồng ingest chính.

Self-test:  python raw_archive.py --selftest
"""
import gzip
import io
import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

ENABLED     = os.getenv("RAW_ARCHIVE_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")
R2_KEY      = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET   = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET   = os.getenv("R2_BUCKET", "")
SELLER_TAG  = os.getenv("R2_SELLER_TAG", "default")

_client = None


def _configured() -> bool:
    return bool(R2_ENDPOINT and R2_KEY and R2_SECRET and R2_BUCKET)


def _get_client():
    global _client
    if _client is None:
        import boto3  # import trễ — chỉ cần khi archive thật sự bật
        _client = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_KEY,
            aws_secret_access_key=R2_SECRET,
            region_name="auto",   # R2 bỏ qua region nhưng boto3 cần 1 giá trị
        )
    return _client


def _supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")
    if not (url and key):
        return None
    return create_client(url, key)


def archive(source: str, payload, date: str = None, seller: str = None, log_db: bool = True):
    """Đẩy `payload` (list/dict) lên R2 dạng gzip JSON, key:
        raw/{seller}/{source}/{YYYY-MM-DD}/{timestamp}.json.gz
    rồi ghi 1 dòng NEW_raw_archive_log. Trả về object_key (None nếu tắt/lỗi).
    KHÔNG raise — archive hỏng không được làm sập ingest.
    """
    if not ENABLED:
        return None
    if not _configured():
        print("  ⚠️ [raw_archive] thiếu cấu hình R2_* trong .env → bỏ qua archive")
        return None
    try:
        day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sel = seller or SELLER_TAG
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        key = f"raw/{sel}/{source}/{day}/{ts}.json.gz"

        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        body = buf.getvalue()

        _get_client().put_object(Bucket=R2_BUCKET, Key=key, Body=body,
                                 ContentType="application/gzip")

        rows = len(payload) if isinstance(payload, list) else 1
        if log_db:
            try:
                sb = _supabase()
                if sb is not None:
                    sb.table("NEW_raw_archive_log").insert({
                        "source": source, "archive_date": day, "object_key": key,
                        "rows": rows, "bytes": len(body),
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
            except Exception as exc:                       # noqa: BLE001
                print(f"  ⚠️ [raw_archive] ghi NEW_raw_archive_log lỗi: {exc}")
        print(f"  📦 [raw_archive] {key}  ({rows} rows, {len(body) / 1024:.0f} KB)")
        return key
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⚠️ [raw_archive] lỗi đẩy R2 ({source}): {exc} — bỏ qua, ingest tiếp tục")
        return None


def _selftest():
    print(f"RAW_ARCHIVE_ENABLED={ENABLED}  bucket={R2_BUCKET!r}  endpoint={R2_ENDPOINT!r}")
    if not ENABLED:
        print("→ Đặt RAW_ARCHIVE_ENABLED=1 + nhóm R2_* trong .env rồi chạy lại để test thật.")
        return
    if not _configured():
        print("✗ Thiếu cấu hình R2_* — điền .env trước.")
        return
    key = archive("_selftest",
                  [{"hello": "world", "ts": datetime.now(timezone.utc).isoformat()}])
    if not key:
        print("✗ archive() trả None — kiểm tra cấu hình/credential R2.")
        return
    try:
        resp = _get_client().list_objects_v2(Bucket=R2_BUCKET, Prefix=key)
        found = any(o.get("Key") == key for o in resp.get("Contents", []))
        print(f"{'✓' if found else '✗'} list_objects_v2 thấy object vừa đẩy: {found}")
    except Exception as exc:                               # noqa: BLE001
        print(f"✗ list_objects_v2 lỗi: {exc}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("Dùng: python raw_archive.py --selftest")
