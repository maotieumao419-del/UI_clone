"""Phase1_Fetch — Nguồn chân lý DUY NHẤT cho đường dẫn file raw.

Cấu trúc lưu trữ theo NGÀY (dữ liệu Amazon vốn chia theo report_date):

    data/<YYYY>/<MM>/<DD>/
        orders.jsonl.gz                 # SP-API Orders + items (theo CreatedDate ngày đó)
        finances.jsonl.gz               # SP-API FinancialEvents (theo PostedDate ngày đó)
        ads_sp_campaigns.json.gz        # mỗi report type 1 file
        ads_sp_keywords.json.gz
        ...
        mgmt_campaigns_raw.json.gz      # snapshot mgmt (gắn vào ngày chạy)
        mgmt_bid_recommendations.json.gz

CẢ fetch lẫn upload đều gọi helper ở đây — KHÔNG hardcode đường dẫn nơi khác.
Khi nào muốn đổi cách lưu (vd nén tháng, chuyển sang S3) chỉ sửa 1 file này.

    from Phase1_Fetch.paths import (day_dir, orders_file, finances_file,
                                    ads_report_file, ads_mgmt_file,
                                    read_jsonl_gz, read_json_gz, iter_days)
"""
import gzip
import json
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def day_dir(date_str: str) -> Path:
    """data/YYYY/MM/DD cho 1 ngày (YYYY-MM-DD). Tự tạo khi ghi."""
    y, m, d = date_str.split("-")
    return DATA_DIR / y / m / d


# ── Đường dẫn từng loại file (đều nằm trong day_dir) ──────────────────────────

def orders_file(date_str: str) -> Path:
    return day_dir(date_str) / "orders.jsonl.gz"


def finances_file(date_str: str) -> Path:
    return day_dir(date_str) / "finances.jsonl.gz"


def ads_report_file(date_str: str, file_key: str) -> Path:
    """vd file_key='sp_campaigns' → .../ads_sp_campaigns.json.gz"""
    return day_dir(date_str) / f"ads_{file_key}.json.gz"


def ads_mgmt_file(snapshot_date: str, file_key: str) -> Path:
    """vd file_key='campaigns_raw' → .../mgmt_campaigns_raw.json.gz"""
    return day_dir(snapshot_date) / f"mgmt_{file_key}.json.gz"


def summary_file(date_str: str, table: str) -> Path:
    """Archive summary Phase2 ra local theo ngày (để hydrate khoảng cũ không cần
    transform lại). vd table='PPC_Phase2_summary_keywords'
    → .../summary_PPC_Phase2_summary_keywords.json.gz"""
    return day_dir(date_str) / f"summary_{table}.json.gz"


# ── Persistent (slowly-changing, KHÔNG theo ngày) ─────────────────────────────
PERSISTENT_DIR = DATA_DIR / "_persistent"


def product_images_file() -> Path:
    """Map ảnh sản phẩm tích luỹ {asin: {image_url, updated_at}} — ảnh đổi rất
    chậm nên lưu 1 file chung, không chia theo ngày."""
    return PERSISTENT_DIR / "product_images.json.gz"


# ── Đọc (memory-safe) ──────────────────────────────────────────────────────────

def read_jsonl_gz(path: Path):
    """Generator: yield từng dòng JSON trong file JSONL.gz. Không tồn tại → rỗng."""
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def read_json_gz(path: Path):
    """Đọc file JSON.gz (1 list/dict). Không tồn tại → []."""
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# ── Ghi ──────────────────────────────────────────────────────────────────────

def write_json_gz(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def open_jsonl_writer(path: Path):
    """Trả file handle JSONL.gz (mode wt) — caller tự ghi từng dòng + đóng."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return gzip.open(path, "wt", encoding="utf-8")


# ── Tiện ích ngày ──────────────────────────────────────────────────────────────

def iter_days(start: str, end: str):
    """Yield từng 'YYYY-MM-DD' trong [start, end] (cả 2 đầu)."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    if e < s:
        s, e = e, s
    cur = s
    while cur <= e:
        yield cur.isoformat()
        cur += timedelta(days=1)
