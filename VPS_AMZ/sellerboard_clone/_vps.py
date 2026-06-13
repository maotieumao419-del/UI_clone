"""Helper tạm: chạy lệnh trên VPS qua paramiko. python _vps.py "<cmd>"  (env VPS_PASSWORD)."""
import os
import sys

import paramiko

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

HOST, USER = "REDACTED_VPS_IP", "sellervision"


def run(cmd: str, timeout: int = 600) -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=os.environ.get("VPS_PASSWORD", ""),
                   timeout=20, allow_agent=False, look_for_keys=False)
    try:
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if out:
            print(out)
        if err:
            print(err, file=sys.stderr)
        return code
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "echo SSH_OK"))
