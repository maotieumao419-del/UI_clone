"""Trang thai sync Amazon chay nen.

Gunicorn chay nhieu worker process (memory rieng), nen trang thai phai luu
xuong dia (file) de moi worker doc/ghi deu thay nhau:
- LOCK_PATH: file khoa, tao bang O_CREAT|O_EXCL (atomic) -> chi 1 job sync
  chay cung luc, du request den tu worker nao hay tu vong lap auto-sync.
- PROGRESS_PATH: JSON tien do, ghi kieu atomic (tmp + replace) de endpoint
  /sync/progress doc duoc tu worker khac trong luc job dang chay.
"""
import json, os, time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2]
LOCK_PATH = _BACKEND_DIR / "amazon_sync.lock"
PROGRESS_PATH = _BACKEND_DIR / "amazon_sync_progress.json"

# Neu lock ton tai qua lau (vd: process bi kill giua chung) -> coi la lock "chet", tu don
_STALE_LOCK_SECONDS = 2 * 3600


def acquire_lock() -> bool:
    try:
        if LOCK_PATH.exists() and time.time() - LOCK_PATH.stat().st_mtime > _STALE_LOCK_SECONDS:
            LOCK_PATH.unlink(missing_ok=True)
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock():
    LOCK_PATH.unlink(missing_ok=True)


def write_progress(data: dict):
    tmp = PROGRESS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PROGRESS_PATH)


def read_progress() -> dict:
    try:
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "idle"}
