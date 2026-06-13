"""Helper tạm: upload các Phase lên VPS qua SFTP. python _vps_upload.py (env VPS_PASSWORD)."""
import os
import sys
from pathlib import Path

import paramiko

HOST, USER = "REDACTED_VPS_IP", "sellervision"
REMOTE_ROOT = "/home/sellervision/VPS_AMZ/sellerboard_clone"
LOCAL_ROOT = Path(__file__).resolve().parent
UPLOADS = ["Phase1_Ingestion", "Phase2_Transformation", "Phase3_Application", "Phase3",
           "docs", "PIPELINE_3PHASE_README.md"]
EXCLUDE = {".env", "__pycache__", "backups", "_probe_fees.py"}


def skip(p: Path) -> bool:
    return any(part in EXCLUDE for part in p.parts) or p.suffix == ".pyc"


def mkdirs(sftp, remote_dir: str):
    cur = ""
    for part in remote_dir.strip("/").split("/"):
        cur += "/" + part
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=os.environ.get("VPS_PASSWORD", ""),
                   timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    sent = 0
    try:
        for item in UPLOADS:
            local = LOCAL_ROOT / item
            if local.is_file():
                sftp.put(str(local), f"{REMOTE_ROOT}/{item}")
                sent += 1
                continue
            for f in sorted(local.rglob("*")):
                rel = f.relative_to(LOCAL_ROOT)
                if skip(rel) or f.is_dir():
                    continue
                remote = f"{REMOTE_ROOT}/{rel.as_posix()}"
                mkdirs(sftp, os.path.dirname(remote))
                sftp.put(str(f), remote)
                sent += 1
        print(f"UPLOAD_OK: {sent} files")
        return 0
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
