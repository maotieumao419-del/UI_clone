========================================================
HƯỚNG DẪN: GỌI AMAZON SP-API VÀ PHÂN TÍCH DỮ LIỆU THÔ
========================================================
Mục đích: Lấy dữ liệu orders 24h từ Amazon SP-API, lưu ra file JSON
để phân tích cấu trúc trước khi thiết kế database.

Phương thức xác thực: LWA OAuth (LWA-only) HOẶC LWA OAuth + AWS SigV4 + STS AssumeRole.
(Script sẽ tự động chạy ở chế độ LWA-only nếu không điền AWS credentials trong file .env, giúp đơn giản hóa việc thiết lập trên máy mới).
Không phụ thuộc vào bất kỳ hệ thống nào khác (chạy độc lập).

*LƯU Ý*: Script đã được tích hợp cơ chế tự động thử lại (retry backoff) khi gặp lỗi rate limit (HTTP 429) từ Amazon, đồng thời tăng khoảng nghỉ giữa các request lên 1.0 giây để đảm bảo chạy mượt mà và lấy đầy đủ thông tin order items.

--------------------------------------------------------
YÊU CẦU
--------------------------------------------------------
- Python 3.8 trở lên
- Kết nối internet
- Credentials Amazon SP-API (xem Bước 2)

--------------------------------------------------------
BƯỚC 1: CÀI ĐẶT
--------------------------------------------------------
Mở terminal (Command Prompt hoặc PowerShell) trong thư mục này:

    pip install -r requirements.txt

Hoặc chạy file setup tự động (Windows):

    setup.bat

--------------------------------------------------------
BƯỚC 2: ĐIỀN CREDENTIALS VÀO .env
--------------------------------------------------------
1. Copy file mẫu:
       copy .env.example .env        (Windows)
       cp .env.example .env          (Linux/Mac)

2. Mở file .env và điền đúng giá trị:

   AMAZON_SPI_CLIENT_ID      → Lấy tại: developer.amazon.com
                                Apps & Services > Develop Apps > App của bạn
                                Tab "LWA credentials" > Client ID

   AMAZON_SPI_CLIENT_SECRET  → Cùng chỗ trên > Client Secret

   AMAZON_SPI_REFRESH_TOKEN  → Seller Central > Apps & Services
                                > Authorize app > copy Refresh Token
                                Hoặc dùng tool: sp-api-auth-tool

   AMAZON_SPI_MARKETPLACE_ID → Mặc định US: ATVPDKIKX0DER
                                Các marketplace khác xem bảng cuối file

   AWS_ACCESS_KEY_ID         → AWS Console > IAM > Users
                                > User của bạn > Security credentials
                                > Create access key

   AWS_SECRET_ACCESS_KEY     → Lấy cùng lúc với Access Key (chỉ hiện 1 lần)

   AWS_ROLE_ARN              → AWS Console > IAM > Roles
                                > Role tên "SellingPartnerAPIRole" (hoặc tương tự)
                                > Copy ARN: arn:aws:iam::123456789:role/TenRole

   AWS_REGION                → Để mặc định: us-east-1

--------------------------------------------------------
BƯỚC 3: CHẠY SCRIPT
--------------------------------------------------------
    python fetch_24h_orders.py

Script sẽ:
  1. Lấy LWA access token từ Amazon
  2. Assume STS Role để lấy temporary credentials
  3. Gọi SP-API getOrders cho 24 giờ gần nhất
  4. Gọi getOrderItems cho từng order
  5. Lưu kết quả ra thư mục raw_data/

--------------------------------------------------------
KẾT QUẢ
--------------------------------------------------------
Sau khi chạy xong, thư mục raw_data/ sẽ có:

  orders_24h_raw.json   → Toàn bộ JSON thô Amazon trả về
                           Mở bằng VSCode hoặc Notepad++ để xem cấu trúc

  fields_map.txt        → Danh sách TẤT CẢ fields xuất hiện trong response
                           Format: TênField | KiểuDữLiệu | VíDụGiáTrị
                           Dùng để thiết kế schema database

--------------------------------------------------------
CẤU TRÚC FILE
--------------------------------------------------------
test_lwa_spapi/
  README.txt              ← File này
  requirements.txt        ← Thư viện Python cần cài
  .env.example            ← Mẫu credentials (KHÔNG điền thật)
  .env                    ← Credentials thật (TỰ TẠO, không commit git)
  fetch_24h_orders.py     ← Script chính
  raw_data/               ← Output (tự tạo khi chạy)
    orders_24h_raw.json
    fields_map.txt

--------------------------------------------------------
MARKETPLACE IDs
--------------------------------------------------------
Hoa Kỳ (US)         ATVPDKIKX0DER
Canada (CA)         A2EUQ1WTGCTBG2
Mexico (MX)         A1AM78C64UM0Y8
Anh (UK)            A1F83G8C2ARO7P
Đức (DE)            A1PA6795UKMFR9
Pháp (FR)           A13V1IB3VIYZZH
Nhật Bản (JP)       A1VC38T7YXB528
Ấn Độ (IN)          A21TJRUUN4KGV
Úc (AU)             A39IBJ37TRP1C6

--------------------------------------------------------
LƯU Ý BẢO MẬT
--------------------------------------------------------
- KHÔNG commit file .env lên GitHub
- KHÔNG chia sẻ AWS_SECRET_ACCESS_KEY
- AWS_ROLE_ARN chỉ nên có quyền tối thiểu (Least Privilege)
- Access Key nên rotate định kỳ 90 ngày

--------------------------------------------------------
XỬ LÝ LỖI THƯỜNG GẶP
--------------------------------------------------------
Lỗi 403 Forbidden
  → Kiểm tra lại AWS_ROLE_ARN và quyền IAM Role
  → Đảm bảo SP-API app đã được authorize bởi seller account

Lỗi 401 Unauthorized
  → REFRESH_TOKEN đã hết hạn hoặc sai
  → Cần re-authorize SP-API app

Lỗi 429 Too Many Requests
  → Amazon rate limit. Chờ 60 giây rồi chạy lại

Lỗi InvalidClientTokenId (STS)
  → AWS_ACCESS_KEY_ID hoặc AWS_SECRET_ACCESS_KEY sai
  → Kiểm tra lại AWS Console > IAM > Users

Lỗi AccessDenied (STS AssumeRole)
  → IAM User chưa có quyền sts:AssumeRole cho Role này
  → Vào AWS Console > IAM > User > Add permission: sts:AssumeRole

--------------------------------------------------------
THÔNG TIN CHI TIẾT CÁCH CALL API (HTTP SPECIFICATION)
--------------------------------------------------------
Quy trình gọi Amazon SP-API được thực hiện qua các bước HTTP thô (Raw HTTP Request) dưới đây. Bạn có thể dùng thông tin này để tự viết code gọi bằng bất kỳ ngôn ngữ nào (Node.js, PHP, Go, C#...) mà không bị phụ thuộc vào SDK hay Python.

1. LẤY LWA OAUTH ACCESS TOKEN (Dùng chung cho cả 2 chế độ)
--------------------------------------------------------
Để gọi bất kỳ API nào của Amazon, trước hết bạn cần đổi Refresh Token lấy một Access Token ngắn hạn (hết hạn sau 1 tiếng).

- HTTP Method: POST
- URL: https://api.amazon.com/auth/o2/token
- Content-Type: application/x-www-form-urlencoded
- Body (Form fields):
  + grant_type: "refresh_token"
  + refresh_token: <AMAZON_SPI_REFRESH_TOKEN>
  + client_id: <AMAZON_SPI_CLIENT_ID>
  + client_secret: <AMAZON_SPI_CLIENT_SECRET>

- Response trả về (JSON):
  {
    "access_token": "Atzr|IQEBLjIQAtw...",
    "refresh_token": "Atzr|IQEBLjIQAtw...",
    "token_type": "bearer",
    "expires_in": 3600
  }

- Lưu ý: Dùng giá trị "access_token" để truyền vào header "x-amz-access-token" ở các API tiếp theo.


2. CÁC ENDPOINT CALL API CHÍNH
--------------------------------------------------------

A. LẤY DANH SÁCH ORDERS (Get Orders)
- HTTP Method: GET
- URL (Bắc Mỹ): https://sellingpartnerapi-na.amazon.com/orders/v0/orders
- Headers:
  + x-amz-access-token: <LWA_ACCESS_TOKEN>
  + Content-Type: application/json
  + (Nếu dùng AWS SigV4: Cần thêm header Authorization, x-amz-date, x-amz-security-token)
- Query Parameters quan trọng:
  + MarketplaceIds: ATVPDKIKX0DER (ID của thị trường muốn query, có thể truyền nhiều ID cách nhau bằng dấu phẩy)
  + CreatedAfter: 2026-06-08T17:26:00Z (Định dạng ISO 8601 UTC)
  + MaxResultsPerPage: 100 (Số lượng order trên một trang, tối đa 100)
  + NextToken: <TOKEN_PAGINATION> (Token lấy từ trang trước để lấy trang tiếp theo)

- Response trả về (JSON):
  {
    "payload": {
      "Orders": [
        {
          "AmazonOrderId": "113-1234567-1234567",
          "PurchaseDate": "2026-06-09T10:00:00Z",
          "LastUpdateDate": "2026-06-09T10:30:00Z",
          "OrderStatus": "Unshipped",
          "OrderTotal": { "CurrencyCode": "USD", "Amount": "25.00" },
          "NumberOfItemsShipped": 0,
          "NumberOfItemsUnshipped": 1,
          "MarketplaceId": "ATVPDKIKX0DER",
          ...
        }
      ],
      "NextToken": "..."
    }
  }


B. LẤY CHI TIẾT SẢN PHẨM TRONG ORDER (Get Order Items)
- HTTP Method: GET
- URL (Bắc Mỹ): https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{AmazonOrderId}/orderItems
- Path Parameter:
  + {AmazonOrderId}: Mã order ID (ví dụ: 113-1234567-1234567)
- Headers:
  + x-amz-access-token: <LWA_ACCESS_TOKEN>
  + Content-Type: application/json
  + (Nếu dùng AWS SigV4: Cần các header Authorization, x-amz-date, x-amz-security-token)
- Query Parameters:
  + NextToken: (Tùy chọn) Nếu order có quá nhiều items cần phân trang.

- Response trả về (JSON):
  {
    "payload": {
      "AmazonOrderId": "113-1234567-1234567",
      "OrderItems": [
        {
          "ASIN": "B0XXXXXXXX",
          "SellerSKU": "MY-PRODUCT-SKU",
          "OrderItemId": "98765432101234",
          "Title": "Tên sản phẩm hiển thị trên Amazon",
          "QuantityOrdered": 1,
          "ItemPrice": { "CurrencyCode": "USD", "Amount": "25.00" },
          "ItemTax": { "CurrencyCode": "USD", "Amount": "2.00" },
          ...
        }
      ]
    }
  }


3. CƠ CHẾ BẢO VỆ RATE LIMIT (HTTP 429) VÀ THỬ LẠI
--------------------------------------------------------
Amazon SP-API áp dụng thuật toán Token Bucket để giới hạn số lượng request (rate limit):
- /orders/v0/orders: Có rate limit thoải mái hơn.
- /orders/v0/orders/{AmazonOrderId}/orderItems: Rate limit cực kỳ ngặt nghèo (khoảng 1 request mỗi giây).

Nếu gọi quá nhanh, Amazon sẽ trả về HTTP Status Code: 429 (Too Many Requests).
Cách xử lý chuẩn:
- Khi nhận HTTP 429, đọc header "Retry-After" trong response (nếu có) hoặc chờ tối thiểu 2 giây.
- Sử dụng thuật toán Exponential Backoff: tăng thời gian chờ sau mỗi lần thử lại thất bại (ví dụ: chờ 2s, 4s, 6s, 8s...).
- Đặt khoảng nghỉ cố định giữa các request lấy Order Items từ 1.0 giây trở lên để chủ động tránh bị chặn.

--------------------------------------------------------
PHÂN BIỆT SP-API VÀ ADS API — DÙNG CREDENTIALS NÀO?
--------------------------------------------------------
Amazon có 2 hệ thống API hoàn toàn riêng biệt:

┌─────────────────────┬──────────────────────────────┬──────────────────────────────────┐
│                     │ SP-API (Selling Partner API) │ Ads API (Advertising API)        │
├─────────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ Dùng để lấy         │ Orders, Inventory,           │ PPC Campaigns, Ad Groups,        │
│                     │ Settlements, Products        │ Keywords, Spend, Impressions     │
├─────────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ Endpoint            │ sellingpartnerapi-na.        │ advertising-api.amazon.com       │
│                     │ amazon.com                   │                                  │
├─────────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ Đăng ký app tại     │ developer.amazon.com         │ advertising.amazon.com           │
│                     │ > Selling Partner Apps       │ > Developer Portal               │
├─────────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ Client ID / Secret  │ Từ SP-API app               │ Từ Ads API app (khác app)        │
├─────────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ Refresh Token       │ Seller ủy quyền SP-API app   │ Seller ủy quyền Ads API app      │
│                     │ (Scope: sellingpartnerapi::) │ (Scope: advertising::)           │
├─────────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ Cần AWS SigV4?      │ Có (kèm STS AssumeRole)      │ KHÔNG — LWA-only là đủ           │
├─────────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ Cần AWS Role ARN?   │ Có                           │ KHÔNG                            │
└─────────────────────┴──────────────────────────────┴──────────────────────────────────┘

Các file trong thư mục này (.env, fetch_24h_orders.py) chỉ dành cho SP-API.
Ads API là hệ thống riêng, cần đăng ký app riêng và lấy Refresh Token riêng.

Lệnh LWA OAuth dùng cùng 1 URL https://api.amazon.com/auth/o2/token cho cả 2 API,
NHƯNG Client ID, Client Secret và Refresh Token phải đúng với từng loại app.

--------------------------------------------------------
GỌI SP-API TRỰC TIẾP TỪ TERMINAL (KHÔNG CẦN CODE)
--------------------------------------------------------
Phần này hướng dẫn gọi Amazon SP-API thủ công bằng lệnh curl trong terminal —
hữu ích để kiểm tra nhanh credentials hoặc xem response thô mà không cần chạy script Python.

Tất cả credentials dưới đây là SP-API credentials (lấy từ file .env trong thư mục này).

Yêu cầu: curl (có sẵn trên Windows 10+, Linux, Mac)

=== TRÊN WINDOWS (Command Prompt hoặc PowerShell) ===

Bước 0 — Mở terminal và vào đúng thư mục:
    cd C:\Users\nnh16\ads-trading-system\test_lwa_spapi

Bước 1 — Lấy LWA Access Token:

    [Command Prompt]
    curl -X POST "https://api.amazon.com/auth/o2/token" ^
         -H "Content-Type: application/x-www-form-urlencoded" ^
         -d "grant_type=refresh_token&refresh_token=YOUR_REFRESH_TOKEN&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET"

    [PowerShell]
    curl.exe -X POST "https://api.amazon.com/auth/o2/token" `
         -H "Content-Type: application/x-www-form-urlencoded" `
         -d "grant_type=refresh_token&refresh_token=YOUR_REFRESH_TOKEN&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET"

    → Response trả về JSON có trường "access_token". Copy giá trị đó (bắt đầu bằng Atzr|...).
      Gán vào biến để dùng tiếp:

    [Command Prompt]
    set ACCESS_TOKEN=Atzr|IQEBLjIQAtw...   (dán access_token vào đây)

    [PowerShell]
    $ACCESS_TOKEN = "Atzr|IQEBLjIQAtw..."  (dán access_token vào đây)

Bước 2 — Lấy danh sách Orders 24h gần nhất:

    [Command Prompt]
    curl -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders?MarketplaceIds=ATVPDKIKX0DER&CreatedAfter=2026-06-08T00:00:00Z&MaxResultsPerPage=5" ^
         -H "x-amz-access-token: %ACCESS_TOKEN%" ^
         -H "Content-Type: application/json"

    [PowerShell]
    curl.exe -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders?MarketplaceIds=ATVPDKIKX0DER&CreatedAfter=2026-06-08T00:00:00Z&MaxResultsPerPage=5" `
         -H "x-amz-access-token: $ACCESS_TOKEN" `
         -H "Content-Type: application/json"

    → Thay 2026-06-08T00:00:00Z bằng ngày hôm qua theo định dạng ISO 8601 UTC.
    → MaxResultsPerPage=5 để lấy ít order trước, tránh response quá dài.

Bước 3 — Lấy Order Items của 1 order cụ thể:

    [Command Prompt]
    curl -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/113-1234567-1234567/orderItems" ^
         -H "x-amz-access-token: %ACCESS_TOKEN%" ^
         -H "Content-Type: application/json"

    [PowerShell]
    curl.exe -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/113-1234567-1234567/orderItems" `
         -H "x-amz-access-token: $ACCESS_TOKEN" `
         -H "Content-Type: application/json"

    → Thay 113-1234567-1234567 bằng AmazonOrderId thật lấy từ Bước 2.

Bước 4 — Lưu response ra file để đọc dễ hơn:

    [Command Prompt]
    curl -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders?MarketplaceIds=ATVPDKIKX0DER&CreatedAfter=2026-06-08T00:00:00Z&MaxResultsPerPage=10" ^
         -H "x-amz-access-token: %ACCESS_TOKEN%" ^
         -H "Content-Type: application/json" ^
         -o raw_data\orders_manual.json

    → File raw_data\orders_manual.json sẽ chứa JSON thô — mở bằng VSCode để xem.

=== TRÊN VPS (Linux / SSH) ===

Bước 0 — SSH vào VPS và vào đúng thư mục:
    ssh sellervision@<IP_VPS>
    cd /home/sellervision/VPS_AMZ/sellerboard_clone/backend

    Hoặc vào thư mục chứa .env của VPS:
    cd /home/sellervision/VPS_AMZ/sellerboard_clone/backend

    Đọc credentials từ .env:
    grep -E "AMAZON_SPI|AWS_" .env

Bước 1 — Lấy giá trị credentials từ file .env của VPS:
    grep -E "AMAZON_SPI_CLIENT_ID|AMAZON_SPI_CLIENT_SECRET|AMAZON_SPI_REFRESH_TOKEN" .env

    Kết quả sẽ hiện ra 3 dòng. Gán từng giá trị vào biến shell:
    CLIENT_ID="amzn1.application-oa2-client.xxxx"     ← AMAZON_SPI_CLIENT_ID
    CLIENT_SECRET="amzn1.oa2-cs.v1.xxxx"              ← AMAZON_SPI_CLIENT_SECRET
    REFRESH_TOKEN="Atzr|IQEBLjIQ..."                  ← AMAZON_SPI_REFRESH_TOKEN

    Đây là SP-API credentials — KHÔNG phải Ads API credentials.

Bước 2 — Lấy LWA Access Token (SP-API):
    ACCESS_TOKEN=$(curl -s -X POST "https://api.amazon.com/auth/o2/token" \
         -H "Content-Type: application/x-www-form-urlencoded" \
         -d "grant_type=refresh_token&refresh_token=$REFRESH_TOKEN&client_id=$CLIENT_ID&client_secret=$CLIENT_SECRET" \
         | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    echo "Token: ${ACCESS_TOKEN:0:30}..."

    → Lệnh trên tự động trích xuất access_token và gán vào biến $ACCESS_TOKEN.
    → Token này chỉ dùng được với sellingpartnerapi-na.amazon.com, KHÔNG dùng được với Ads API.

Bước 3 — Lấy Orders 24h gần nhất trên VPS:
    curl -s -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders?MarketplaceIds=ATVPDKIKX0DER&CreatedAfter=$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')&MaxResultsPerPage=5" \
         -H "x-amz-access-token: $ACCESS_TOKEN" \
         -H "Content-Type: application/json" | python3 -m json.tool | head -80

    → python3 -m json.tool để format JSON đẹp, head -80 để giới hạn 80 dòng đầu.
    → Đây là SP-API endpoint — chỉ trả về Orders, không có PPC/Ads data.

Bước 4 — Lưu toàn bộ response ra file trên VPS:
    curl -s -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders?MarketplaceIds=ATVPDKIKX0DER&CreatedAfter=$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')&MaxResultsPerPage=20" \
         -H "x-amz-access-token: $ACCESS_TOKEN" \
         -H "Content-Type: application/json" \
         -o ~/orders_raw.json && cat ~/orders_raw.json | python3 -m json.tool | less

    → Lưu ý: KHÔNG dùng /tmp — Snap curl (Ubuntu) bị sandbox chặn ghi vào /tmp.
      Dùng ~/orders_raw.json (thư mục home) thay thế.
    → Dùng phím q để thoát less, mũi tên lên/xuống để cuộn.

Bước 5 — Lấy Order Items của 1 order trên VPS:
    curl -s -X GET "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/113-1234567-1234567/orderItems" \
         -H "x-amz-access-token: $ACCESS_TOKEN" \
         -H "Content-Type: application/json" | python3 -m json.tool

    → Thay 113-1234567-1234567 bằng AmazonOrderId thật lấy từ Bước 3.

=== LƯU Ý QUAN TRỌNG KHI DÙNG TERMINAL ===
- Access Token chỉ có hiệu lực trong 1 tiếng (3600 giây). Nếu gặp lỗi 401, chạy lại Bước 1.
- Mỗi lần mở terminal mới, biến $ACCESS_TOKEN hoặc %ACCESS_TOKEN% bị mất — phải lấy lại.
- Nếu dùng LWA-only (không có AWS credentials), cách curl trên đây là đủ — không cần SigV4.
- Nếu Amazon yêu cầu SigV4 (trả về lỗi 403 với message "Access denied"), dùng script Python
  fetch_24h_orders.py thay vì curl vì SigV4 quá phức tạp để làm thủ công bằng tay.
