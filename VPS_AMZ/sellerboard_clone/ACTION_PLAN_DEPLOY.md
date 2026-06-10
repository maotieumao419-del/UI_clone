# Kế hoạch đưa SellerVision lên online (StableHost + VPS Megahost)

> Mục tiêu: từ localhost → 2 bản chạy online (cPanel/StableHost và VPS Ubuntu/Megahost),
> dữ liệu bán hàng lấy qua **API VST** (SPI đấu sau), vẫn giữ được upload file Excel.
>
> **Nguyên tắc nền:** KHÔNG duy trì 2 source code khác nhau. Chỉ có **1 codebase**,
> đóng gói thành **2 bản triển khai** khác nhau ở 2 thứ duy nhất: (a) điểm vào (entrypoint)
> và (b) file `.env`. Giữ 1 source giúp sửa lỗi 1 lần, không lệch phiên bản.

---

## PHẦN 0 — Hiện trạng (đã làm sẵn, KHÔNG cần refactor lại)

App `sellerboard_clone` đã chuẩn 12-factor. Đừng tốn công làm lại các phần sau:

| Hạng mục | Đã có ở đâu |
|---|---|
| Port động qua ENV | `backend/app/config.py:31`, `backend/app/main.py:75` |
| Path tương đối (không còn `E:\`) | `config.py:56` (`PPC_DIR="data/ppc"`), `main.py:59` |
| Base URL UI động | `frontend/app.js:4` (`window.SV_API_BASE || location.origin`) |
| CORS + chống Host giả mạo | `main.py:40-46`, `config.py:46-48` |
| Quản lý bí mật qua `.env` | `backend/.env.example` |
| Entrypoint cPanel (Passenger/WSGI) | `backend/passenger_wsgi.py` |
| Entrypoint VPS (Docker/systemd) | `Dockerfile`, `docker-compose.yml`, `deploy/` |

→ Việc còn lại: **(A)** thêm lớp gọi API VST/SPI song song với file; **(B)** thêm loading UI;
**(C)** hạ tầng DNS + đẩy code lên 2 host.

---

## PHẦN 1 — HẠ TẦNG: Lấy IP VPS & cấu hình DNS

### 1.1 Lấy IP công khai (public IPv4) của VPS Megahost
- Đăng nhập panel Megahost → thường IP hiển thị ngay ở trang quản lý VPS.
- Hoặc SSH vào VPS rồi chạy:
  ```bash
  curl -4 ifconfig.me
  ```
  → ra dạng `103.x.x.x`. Đây là IP để trỏ DNS.

### 1.2 Tạo subdomain + bản ghi A
Vào trang quản lý DNS của **domain** (nơi mua domain hoặc Cloudflare). Thêm:

| Type | Name (Host) | Value (Points to) | TTL |
|---|---|---|---|
| A | `app` | `103.x.x.x` (IP VPS) | Auto / 300 |
| A | `test` | `103.x.x.x` (IP VPS) | Auto / 300 |

- `Name=app` → tạo `app.tencuaban.com`. `Name=test` → `test.tencuaban.com`.
- Nếu bản cPanel chạy trên StableHost: trỏ subdomain đó về **IP StableHost** (xem trong cPanel → mục *Shared IP Address* hoặc *General Information*), KHÔNG phải IP VPS.
  - Ví dụ kịch bản "2 bản": `app.tencuaban.com` → IP VPS; `test.tencuaban.com` → IP StableHost (hoặc ngược lại tuỳ bạn).
- Kiểm tra đã trỏ đúng (sau 5–30 phút):
  ```bash
  nslookup app.tencuaban.com
  # hoặc
  ping app.tencuaban.com
  ```

### 1.3 (Nếu dùng Cloudflare) lưu ý
- Bật proxy (mây cam) để có HTTPS/CDN, nhưng khi cài Certbot trên VPS thì tạm để **DNS only** (mây xám) cho Let's Encrypt xác thực, xong bật lại.

---

## PHẦN 2 — REFACTOR CODE: đấu nối API VST/SPI (song song với file)

### Chiến lược: "Hydrate" — ít rủi ro nhất
Parser Excel hiện tại (`services/ppc.py`) rất tốt và đã chịu lỗi. Thay vì viết lại toàn bộ
parser cho JSON, ta thêm **lớp nguồn (source layer)**:

```
DATA_SOURCE=file  → đọc Excel trong data/ppc  (như cũ)
DATA_SOURCE=vst   → gọi API VST:
                     • JSON  → trả thẳng cho UI
                     • link Excel → tải về data/ppc rồi cho parser cũ chạy (tái dùng 100%)
```

### 2.1 Sửa `backend/app/config.py` — thêm cấu hình nguồn + API
Thêm vào trong class `Settings` (sau khối PPC, khoảng dòng 59):

```python
    # --- Nguồn dữ liệu PPC ---
    # "file" = đọc Excel upload (mặc định) · "vst" = gọi API VST · "spi" = SP-API (sau)
    DATA_SOURCE: str = "file"

    # --- API VST (đấu nối trước) ---
    VST_API_BASE: str = ""          # vd: https://api.vst-provider.com
    VST_API_KEY: str = ""           # BÍ MẬT — chỉ đặt trong .env, KHÔNG commit
    VST_TIMEOUT: int = 30           # giây
    VST_VERIFY_SSL: bool = True     # đặt False nếu API dùng cert nội bộ (tránh ở prod)

    # --- API SPI / Amazon SP-API (đấu nối sau) ---
    SPI_API_BASE: str = ""
    SPI_API_KEY: str = ""
```

### 2.2 Thêm thư viện HTTP — sửa `backend/requirements.txt`
Thêm 1 dòng:
```
requests==2.32.3
```

### 2.3 Tạo file mới `backend/app/services/vst_client.py`
```python
"""Client gọi API VST (và SPI sau) lấy dữ liệu bán hàng/PPC.

Bật bằng ENV DATA_SOURCE=vst. Mọi key/token đọc từ ENV — không hardcode.
Hỗ trợ 2 kiểu trả về: JSON (cho UI) và link file Excel (tái dùng parser cũ).
"""
import requests

from ..config import settings


class VSTError(RuntimeError):
    """Lỗi khi gọi API VST — router sẽ bắt và trả thông báo thân thiện."""


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if settings.VST_API_KEY:
        h["Authorization"] = f"Bearer {settings.VST_API_KEY}"   # đổi scheme nếu VST khác
    return h


def _get(path: str, params: dict | None = None) -> requests.Response:
    if not settings.VST_API_BASE:
        raise VSTError("Chưa cấu hình VST_API_BASE trong .env")
    url = path if path.startswith("http") else settings.VST_API_BASE.rstrip("/") + path
    try:
        r = requests.get(url, headers=_headers(), params=params,
                         timeout=settings.VST_TIMEOUT, verify=settings.VST_VERIFY_SSL)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        raise VSTError(f"Lỗi gọi VST {url}: {e}") from e


# ---- JSON cho UI ----
def fetch_listing_json(store: str | None = None) -> list[dict]:
    """Danh sách SKU dạng JSON. TODO: map field VST -> schema {sku,store,link,status...}."""
    data = _get("/v1/listing", params={"store": store} if store else None).json()
    # Ví dụ map (đổi theo field thật của VST):
    return [
        {
            "stt": i + 1,
            "sku": row.get("sku") or row.get("SKU"),
            "store": row.get("store", store or ""),
            "link": row.get("link", ""),
            "status": row.get("status", ""),
            "has_detail": True,
        }
        for i, row in enumerate(data.get("items", data) if isinstance(data, dict) else data)
    ]


# ---- Link Excel -> bytes (tái dùng parser openpyxl cũ) ----
def fetch_ppc_workbook_bytes(store: str | None = None) -> bytes:
    """API trả link tải Excel -> tải về bytes."""
    meta = _get("/v1/ppc/export", params={"store": store} if store else None).json()
    file_url = meta.get("download_url")
    if not file_url:
        raise VSTError("API VST không trả download_url")
    return _get(file_url).content
```
> Các endpoint `/v1/listing`, `/v1/ppc/export` và cách map field là **placeholder** —
> khi có tài liệu API VST thật, chỉ sửa trong file này, không đụng phần khác.

### 2.4 Sửa `backend/app/services/ppc.py` — thêm nhánh nguồn
Thêm hàm "hydrate" (kéo file từ API về `PPC_DIR` rồi để code cũ chạy). Thêm gần `_registry()`:

```python
from . import vst_client   # thêm ở đầu file

def _hydrate_from_vst(store: str | None) -> None:
    """Khi DATA_SOURCE=vst: tải Excel từ API về PPC_DIR (1 file/store) để parser cũ dùng."""
    blob = vst_client.fetch_ppc_workbook_bytes(store)
    fname = f"{store or 'vst_store'}.xlsx"
    with open(os.path.join(_ppc_dir(), fname), "wb") as f:
        f.write(blob)
```

Sửa đầu hàm `_load()` (dòng ~295) để gọi hydrate khi cần:
```python
def _load(store: str | None) -> dict:
    if settings.DATA_SOURCE == "vst":
        try:
            _hydrate_from_vst(store)        # kéo file mới nhất từ API
        except vst_client.VSTError as e:
            return {"error": str(e), "listing": [], "sheet_index": {}, "store": store or ""}
    reg = _registry()
    ...  # phần còn lại GIỮ NGUYÊN
```

> Cách này giữ **toàn bộ logic CTR/CVR/export** không đổi, rủi ro thấp nhất.
> Nếu sau này muốn JSON thuần (không qua Excel), thêm nhánh dùng `vst_client.fetch_listing_json`.

### 2.5 Sửa `backend/.env.example` — khai báo biến mới (giá trị placeholder)
Thêm cuối file:
```bash
# --- Nguồn dữ liệu ---
DATA_SOURCE=file            # đổi thành "vst" khi đấu nối API
VST_API_BASE=https://api.vst-provider.com
VST_API_KEY=DAN_KEY_THAT_VAO_DAY
VST_TIMEOUT=30
VST_VERIFY_SSL=true
# SPI (đấu sau)
SPI_API_BASE=
SPI_API_KEY=
```

### 2.6 CORS — chỉ cần điền domain, không sửa code
Trong `.env` của từng host:
```bash
CORS_ORIGINS=https://app.tencuaban.com,https://test.tencuaban.com
ALLOWED_HOSTS=app.tencuaban.com,test.tencuaban.com
```
Code CORS đã đọc các biến này ở `main.py:40-46`. Nếu frontend & backend **cùng domain**
(app này phục vụ luôn UI) thì gần như không gặp lỗi CORS. CORS chỉ phát sinh khi UI ở
domain A gọi API domain B — khi đó thêm domain A vào `CORS_ORIGINS`.

### 2.7 Path tĩnh → tương đối (Windows → Linux)
App web **đã dùng path tương đối**, không cần sửa. CHỈ các script trong `AMZ-ADS/amzads`
còn `E:\...`. Nếu định chạy các pipeline đó trên VPS, sửa theo nguyên tắc:
```python
# THAY:  pd.read_excel(r"E:\Anti+Claude AI\amzads\input.xlsx")
# BẰNG:
from pathlib import Path
BASE = Path(__file__).resolve().parent          # thư mục chứa script
pd.read_excel(BASE / "input.xlsx")              # dùng "/", chạy được cả Linux/Windows
```
> Pipeline AMZ-ADS là job offline, KHÔNG cần thiết cho lần lên domain đầu tiên. Để giai đoạn 2.

---

## PHẦN 3 — GIAO DIỆN: base URL + trạng thái chờ (loading)

### 3.1 Base URL
- **Cùng domain** (mặc định): không cần làm gì — `app.js:4` tự lấy `location.origin`.
- **Tách domain** (UI và API khác nhau): thêm vào `frontend/index.html` TRƯỚC thẻ load `app.js`:
  ```html
  <script>window.SV_API_BASE = "https://app.tencuaban.com";</script>
  <script src="/static/app.js"></script>
  ```

### 3.2 Thêm spinner loading khi gọi API
**`frontend/index.html`** — thêm 1 lần, ngay trước `</body>`:
```html
<div id="sv-loading" class="hidden" style="position:fixed;inset:0;z-index:9999;
     background:rgba(255,255,255,.6);display:flex;align-items:center;justify-content:center">
  <div style="width:42px;height:42px;border:4px solid #ddd;border-top-color:#2563eb;
       border-radius:50%;animation:svspin .8s linear infinite"></div>
</div>
<style>@keyframes svspin{to{transform:rotate(360deg)}}
  #sv-loading.hidden{display:none}</style>
```

**`frontend/app.js`** — bọc hàm `api()` (dòng 13) để tự bật/tắt spinner:
```javascript
let _pending = 0;
function _loading(on) {
  _pending += on ? 1 : -1;
  const el = document.getElementById('sv-loading');
  if (el) el.classList.toggle('hidden', _pending <= 0);
}

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (TOKEN) headers['Authorization'] = 'Bearer ' + TOKEN;
  if (opts.json) { headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.json); delete opts.json; }
  _loading(true);                                    // BẬT
  try {
    const res = await fetch(API + path, { ...opts, headers });
    if (res.status === 401) { App.logout(); throw new Error('401'); }
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    return res.status === 204 ? null : res.json();
  } finally {
    _loading(false);                                 // TẮT (kể cả khi lỗi)
  }
}
```
> Vì mọi request đều qua `api()`, chỉ sửa 1 chỗ là toàn bộ app có loading. Gọi API online
> chậm hơn localhost nên bước này quan trọng để UX không bị "đơ im lặng".

---

## PHẦN 4 — TRIỂN KHAI: 2 bản từ 1 source

### Khác biệt duy nhất giữa 2 bản
| | StableHost (cPanel) | VPS Megahost (Ubuntu) |
|---|---|---|
| Entrypoint | `passenger_wsgi.py` (WSGI) | `gunicorn`/Docker (ASGI) |
| Chạy nền (Celery sau này) | ❌ không | ✅ có |
| DB khuyến nghị | SQLite | SQLite → PostgreSQL khi tải nặng |
| File `.env` | của StableHost | của VPS |
> Cùng source. Đừng fork code. Quản lý bằng 1 repo Git, mỗi host `git pull` rồi dùng `.env` riêng.

### 4.A — Bản StableHost (cPanel / Passenger)
Theo `DEPLOY.md` mục "cPanel / StableHost". Tóm tắt:
1. Nén dự án → cPanel → File Manager → upload `~/sellervision` → Extract. (Hoặc cPanel → Git Version Control → clone.)
2. cPanel → **Setup Python App → Create**:
   - Python 3.12 · App root `sellervision/backend` · App URL = `test.tencuaban.com`
   - Startup file `passenger_wsgi.py` · Entry point `application`
3. Mục *Configuration files* → `requirements.txt` → **Run Pip Install**.
4. Mục *Environment variables* → thêm `SECRET_KEY`, `ENV=prod`, `CORS_ORIGINS`, `ALLOWED_HOSTS`,
   (và `DATA_SOURCE`, `VST_*` khi đấu API) → **Restart**.
5. cPanel → **SSL/TLS Status → Run AutoSSL** → mở `https://test.tencuaban.com`.
- Đổi code sau này: upload/`git pull` → **Restart** (hoặc `touch tmp/restart.txt`).

### 4.B — Bản VPS Megahost (Ubuntu) — khuyến nghị Docker
SSH vào VPS:
```bash
ssh root@103.x.x.x

# 1) Cài Docker (nếu chưa)
curl -fsSL https://get.docker.com | sh

# 2) Lấy code — cách Git (khuyến nghị) hoặc SCP
git clone <repo-url> sellervision && cd sellervision
#   (không có Git? Từ máy bạn: scp -r "E:\Anti+Claude AI\sellerboard_clone" root@103.x.x.x:~/sellervision)

# 3) Tạo .env thật cho VPS
cp backend/.env.example backend/.env
nano backend/.env      # đổi SECRET_KEY, ENV=prod, CORS_ORIGINS=https://app.tencuaban.com ...

# 4) Chạy
docker compose up -d --build      # app lắng nghe cổng 8000

# 5) Nginx + HTTPS đặt trước
sudo apt install -y nginx
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/sellervision
sudo nano /etc/nginx/sites-available/sellervision   # sửa server_name = app.tencuaban.com
sudo ln -s /etc/nginx/sites-available/sellervision /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d app.tencuaban.com           # cấp SSL Let's Encrypt miễn phí
```
- Cập nhật code: `git pull && docker compose up -d --build`.
- Xem log: `docker compose logs -f`.
- **Không Docker?** dùng `deploy/sellervision.service.example` (systemd) + venv — xem `DEPLOY.md` "Cách 2".

### 4.C — Mở tường lửa VPS
```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'    # mở 80 + 443
sudo ufw enable
```

---

## PHẦN 5 — BẢNG TÓM TẮT FILE CẦN SỬA

| File | Sửa gì | Bắt buộc? |
|---|---|---|
| `backend/app/config.py` | + `DATA_SOURCE`, `VST_*`, `SPI_*` | Khi đấu API |
| `backend/app/services/vst_client.py` | **TẠO MỚI** — client gọi VST | Khi đấu API |
| `backend/app/services/ppc.py` | + `_hydrate_from_vst()`, sửa đầu `_load()` | Khi đấu API |
| `backend/requirements.txt` | + `requests==2.32.3` | Khi đấu API |
| `backend/.env.example` | + biến `DATA_SOURCE`, `VST_*` | Khi đấu API |
| `backend/.env` (mỗi host) | điền giá trị THẬT (key, domain) | ✅ Luôn |
| `frontend/index.html` | + div spinner (+ `SV_API_BASE` nếu tách domain) | Nên có |
| `frontend/app.js` | bọc `api()` bật/tắt loading | Nên có |
| DNS (ngoài code) | A record `app`/`test` → IP | ✅ Luôn |
| `AMZ-ADS/amzads/*.py` | `E:\...` → `Path(__file__)` | Giai đoạn 2 |

---

## Thứ tự thực hành đề xuất
1. **Hạ tầng trước**: DNS A record → trỏ subdomain (Phần 1).
2. **Deploy "as-is"** (chưa đụng API, `DATA_SOURCE=file`): đưa app lên cả 2 host, test upload Excel chạy được online (Phần 4). → Xác nhận hạ tầng OK.
3. **Thêm loading UI** (Phần 3) — nhanh, cải thiện UX ngay.
4. **Đấu API VST** (Phần 2) khi có URL/key: sửa 4 file backend, đặt `DATA_SOURCE=vst`, restart.
5. **SPI sau**: nhân bản `vst_client.py` thành `spi_client.py`, thêm nhánh `DATA_SOURCE=spi`.
