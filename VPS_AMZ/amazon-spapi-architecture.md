# Kiến Trúc Hệ Thống: Amazon Operations + Ads Automation Platform

> **Mục tiêu:** Web app (1) hỗ trợ vận hành Amazon Seller và (2) chạy quảng cáo tự động.
> Bắt đầu phục vụ chính mình, sau phát triển thành dịch vụ (SaaS).
>
> **Phiên bản:** 3.0 · **Ngày:** 2026-06-09
>
> **Cách đọc tài liệu này:** Tài liệu mô tả *khung xương sống* của hệ thống — phần kiến trúc cứng mà mọi giai đoạn phát triển đều tuân theo. Với mỗi thành phần, tài liệu nêu **các hướng triển khai có thể chọn**, **lợi thế / điểm yếu** của từng hướng, và **đề xuất** hướng tối ưu cho dự án này. Toàn bộ code/SQL được đưa xuống [Phụ lục — Ví dụ minh họa](#phụ-lục--ví-dụ-minh-họa); phần thân chỉ nói về kiến trúc.

---

## Mục lục

- [Phần I — Tư tưởng thiết kế](#phần-i--tư-tưởng-thiết-kế)
- [Phần II — Kiến trúc tổng quan (sơ đồ khối)](#phần-ii--kiến-trúc-tổng-quan-sơ-đồ-khối)
- [Phần III — Đi sâu từng khối](#phần-iii--đi-sâu-từng-khối)
  - [Khối A — Giao diện người dùng](#khối-a--giao-diện-người-dùng-frontend)
  - [Khối B — Tầng ứng dụng](#khối-b--tầng-ứng-dụng-api-server)
  - [Khối C — Tích hợp Amazon](#khối-c--tích-hợp-amazon-integration-layer)
  - [Khối D — Tầng dữ liệu](#khối-d--tầng-dữ-liệu-data-layer)
  - [Khối E — Bộ máy tự động hóa](#khối-e--bộ-máy-tự-động-hóa-automation-engine)
  - [Khối F — Tầng AI](#khối-f--tầng-ai-ai-layer)
  - [Khối G — Hạ tầng & Bảo mật](#khối-g--hạ-tầng--bảo-mật-cross-cutting)
- [Phần IV — Mô hình dữ liệu (khái niệm)](#phần-iv--mô-hình-dữ-liệu-khái-niệm)
- [Phần V — Roadmap theo giai đoạn](#phần-v--roadmap-theo-giai-đoạn)
- [Phần VI — Nhật ký quyết định](#phần-vi--nhật-ký-quyết-định)
- [Phụ lục — Ví dụ minh họa](#phụ-lục--ví-dụ-minh-họa)

---

## Phần I — Tư tưởng thiết kế

Trước khi vẽ khối nào, có hai tư tưởng chi phối toàn bộ kiến trúc. Hiểu hai điều này thì các quyết định phía sau sẽ tự nhiên.

### 1. Khung xương sống cố định, xây dựng theo giai đoạn

Kiến trúc trong tài liệu là **khung xương sống (backbone)** — các khối, ranh giới, luồng dữ liệu sẽ không đổi. Nhưng ta **không xây tất cả cùng lúc**. Ta dựng dần theo giai đoạn, mỗi giai đoạn tạo ra một sản phẩm dùng được và là nền cho giai đoạn sau:

```
Giai đoạn nền      →  Call API + dựng cơ sở dữ liệu + trích ra giao diện PnL
(làm trước tiên)      Mục tiêu: NHÌN THẤY tiền vào / tiền ra một cách chính xác.

Giai đoạn phân tích →  Dashboard quảng cáo, phát hiện điểm "đốt tiền", báo cáo.
                      Mục tiêu: HIỂU dữ liệu đủ để ra quyết định thủ công.

Giai đoạn tự động   →  Đề xuất hành động → người duyệt → máy tự chạy có guardrail.
                      Mục tiêu: GIAO việc cho máy sau khi đã tin logic.
```

Điểm mấu chốt của giai đoạn nền: **dữ liệu phải đổ vào DB của mình rồi trích ngược ra giao diện**, chứ không gọi API trực tiếp để hiển thị. Vì sao? Vì API Amazon có rate limit, có độ trễ, và ta cần đối chiếu lịch sử theo thời gian. DB là "nguồn chân lý" của riêng ta; giao diện PnL chỉ là một khung nhìn đọc từ DB ra.

> **PnL (Profit & Loss) là ngôi sao Bắc Đẩu của giai đoạn nền.** Một màn hình trả lời được câu: *"Hôm nay / tuần này tôi lãi hay lỗ thật sự bao nhiêu?"* — gộp doanh thu, phí Amazon, chi phí quảng cáo, giá vốn. Mọi automation sau này chỉ đáng tin khi con số PnL nền này đã chính xác.

### 2. Crawl → Walk → Run (không để máy tự tiêu tiền sớm)

Hệ thống có hai nửa với **profile rủi ro khác hẳn nhau**: nửa *vận hành* chỉ đọc dữ liệu (bug thì dashboard sai — khó chịu), nửa *quảng cáo tự động* ghi dữ liệu và tiêu tiền thật (bug thì cháy ngân sách trong đêm — mất tiền). Vì vậy nguyên tắc xuyên suốt:

```
CRAWL │ ĐỌC      │ Chỉ hiển thị. Người tự quyết định trên Seller Central.
      │          │ → đạt được: dữ liệu chính xác, dashboard đáng tin.
WALK  │ ĐỀ XUẤT  │ Máy tính toán & đề xuất. Người bấm duyệt từng cái.
      │          │ → đạt được: chứng minh logic đúng trên thực tế.
RUN   │ TỰ ĐỘNG  │ Máy tự áp dụng trong giới hạn guardrail. Có cầu dao ngắt.
      │          │ → đạt được: scale, giải phóng thời gian con người.
```

**Cổng then chốt:** chỉ chuyển từ WALK sang RUN khi giai đoạn đề xuất đã chạy thực tế ≥ 4 tuần và tỉ lệ đề xuất bị người từ chối < 5%. Nếu người vẫn thường xuyên sửa đề xuất của máy → logic chưa đủ tin để giao quyền tự động.

---

## Phần II — Kiến trúc tổng quan (sơ đồ khối)

Hệ thống chia thành **7 khối**. Khối A→B→C→D là trục xương sống chính (người dùng → ứng dụng → tích hợp → dữ liệu). Khối E là bộ máy tự động hóa được **cố ý tách riêng** để cô lập rủi ro tiêu tiền. Khối F (AI) và Khối G (hạ tầng & bảo mật) là các lớp cắt ngang phục vụ toàn hệ thống.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  KHỐI A — GIAO DIỆN NGƯỜI DÙNG                                            │
│  Vận hành: Orders · Inventory · Finance/PnL                              │
│  Quảng cáo: Campaigns · Performance · Rules · Approval Queue · Audit Log  │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │  REST + Realtime (HTTPS)
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  KHỐI B — TẦNG ỨNG DỤNG (API Server, stateless)                          │
│  Auth · REST API · Job Enqueue · Realtime push · Approve/Reject           │
└───┬─────────────────────────┬───────────────────────────┬────────────────┘
    │ đọc/ghi                 │ enqueue job               │ enqueue job
    ▼                         ▼                           ▼
┌──────────────┐   ┌────────────────────────────┐   ┌──────────────────────┐
│  KHỐI D      │   │  KHỐI C — TÍCH HỢP AMAZON   │   │  KHỐI E              │
│  TẦNG DỮ LIỆU│◄─►│  ┌──────────┐ ┌──────────┐  │   │  AUTOMATION ENGINE   │
│              │   │  │  SP-API  │ │ Ads API  │  │   │  (tách blast radius) │
│  Postgres    │   │  │  worker  │ │  worker  │  │   │                      │
│  Redis       │   │  └────┬─────┘ └────┬─────┘  │   │  Rules Engine        │
│  (KMS vault) │   │   Notif│      Stream│        │   │   → Proposed Actions │
│              │   │   → SQS│   → Kinesis│        │   │   → Guardrails       │
│              │   └────────┴────────────┴────────┘   │   → Gate (duyệt/auto)│
│              │◄──────────────────────────────────── │   → Executor (WRITE) │
│              │                                       │   → Reconcile        │
│              │                                       │   → Audit Log        │
│              │                                       │   ▲ Circuit Breaker  │
└──────┬───────┘                                       └───┬──────────────────┘
       │                                                   │
       ▼                                                   ▼
┌──────────────────────────┐              ┌────────────────────────────────────┐
│  KHỐI F — TẦNG AI        │              │  KHỐI G — HẠ TẦNG & BẢO MẬT (cắt   │
│  Claude API: tóm tắt,    │              │  ngang mọi khối)                   │
│  anomaly, gợi ý rule,    │              │  Token vault (KMS) · Multi-tenant ·│
│  NL Q&A, forecast        │              │  Queue (Celery/Redis) · Pooling ·  │
│  (chỉ đề xuất, qua       │              │  Monitoring                        │
│   guardrail Khối E)      │              │                                    │
└──────────────────────────┘              └────────────────────────────────────┘
```

**Đọc sơ đồ:**

| Khối | Vai trò một câu | Tính chất rủi ro |
|---|---|---|
| **A** Giao diện | Nơi người dùng nhìn và bấm | Không |
| **B** Tầng ứng dụng | Bộ não điều phối, nguồn chân lý logic | Không |
| **C** Tích hợp Amazon | Hai cánh tay nối SP-API & Ads API | Đọc (C) + Ghi (qua E) |
| **D** Tầng dữ liệu | Bộ nhớ dài hạn của hệ thống | Không |
| **E** Automation Engine | Nơi máy ra quyết định tiêu tiền | **Cao — tách riêng** |
| **F** Tầng AI | Cố vấn thông minh, chỉ đề xuất | Trung bình (qua guardrail) |
| **G** Hạ tầng & Bảo mật | Nền móng đỡ mọi khối | Bảo mật token + cô lập tenant |

> **Quyết định kiến trúc nền tảng:** Khối E (Automation) là **service tách biệt** với worker đồng bộ của Khối C. Một bug trong đồng bộ đơn hàng tuyệt đối không được chạm tới luồng tiêu tiền quảng cáo. Đây là ranh giới blast-radius quan trọng nhất của cả hệ thống.

---

## Phần III — Đi sâu từng khối

Mỗi khối trình bày theo cùng một khuôn: **gồm những phần gì → các hướng triển khai (lợi thế/điểm yếu) → đề xuất**.

---

### Khối A — Giao diện người dùng (Frontend)

**Gồm những phần gì**

- *Nhóm Vận hành:* màn hình Orders, Inventory, và **Finance/PnL** (ngôi sao của giai đoạn nền).
- *Nhóm Quảng cáo:* màn hình Campaigns, Performance, Rules (định nghĩa luật), Approval Queue (duyệt đề xuất), Audit Log (truy vết).
- *Realtime:* trạng thái job đồng bộ và cảnh báo đẩy về theo thời gian thực.

**Các hướng triển khai**

| Hướng | Lợi thế | Điểm yếu |
|---|---|---|
| **React SPA client thuần** (Vite) | Tách bạch rõ FE/BE; backend là nguồn chân lý duy nhất; client gọi REST sinh từ OpenAPI nên không viết type 2 lần | Không tận dụng server-side rendering; phải duy trì API contract |
| **Next.js có server components** (đọc DB trực tiếp ở tầng server) | SEO tốt, render nhanh trang đầu, fetch dữ liệu ngay tại server | **Xé business logic ra 2 ngôn ngữ + 2 nơi cùng chạm DB** → khó giữ một nguồn chân lý; rủi ro lệch logic Python/JS |
| **Server-rendered thuần** (template-based) | Đơn giản, ít JS | Trải nghiệm dashboard realtime/tương tác cao bị hạn chế |

**➜ Đề xuất:** **React SPA client thuần**, gọi FastAPI qua REST với client sinh tự động từ OpenAPI; realtime job-status qua SSE/WebSocket. Lý do quyết định: hệ thống này có nhiều logic tài chính nhạy cảm (PnL, guardrail) — phải giữ **một nguồn chân lý duy nhất ở backend Python**, không để Next.js đọc thẳng DB và làm logic phân mảnh sang JS. *Phản biện đã cân nhắc:* ta đánh đổi mất server components, nhưng OpenAPI auto-gen bù lại phần lớn công sức contract.

---

### Khối B — Tầng ứng dụng (API Server)

**Gồm những phần gì**

- *Auth & session:* xác thực người dùng, quản lý phiên.
- *REST API:* CRUD rules, endpoint approve/reject hành động, truy vấn dữ liệu cho FE.
- *Job Enqueue:* nhận yêu cầu nặng (sync, report) → đẩy vào hàng đợi cho worker.
- *Realtime push:* SSE/WebSocket đẩy trạng thái về FE.

Đây là **bộ não điều phối** — stateless, có thể scale ngang. Nó là tầng business-logic + data-access *duy nhất*.

**Các hướng triển khai**

| Hướng | Lợi thế | Điểm yếu |
|---|---|---|
| **Python — FastAPI** | Hệ sinh thái data/AI mạnh nhất (pandas, anthropic SDK, sp-api lib); async + Pydantic v2; tự sinh OpenAPI | Async Python + worker sync cùng chạm Postgres cần chú ý connection pooling |
| **Node/TypeScript** (NestJS) | Cùng ngôn ngữ với FE; type end-to-end tự nhiên | Hệ thư viện Amazon/AI/phân tích dữ liệu yếu hơn Python; tự viết nhiều |
| **Lai (Python cho data, Node cho API)** | Mỗi ngôn ngữ làm việc nó giỏi | Hai runtime, hai pipeline deploy → phức tạp vận hành sớm |

**➜ Đề xuất:** **Python + FastAPI** (đồng bộ với SQLAlchemy 2.0 async + Alembic, Celery + Beat trên broker Redis). Lý do: giai đoạn sau cần nặng về phân tích dữ liệu và AI — chọn Python để cả hệ thống nằm trong một hệ sinh thái, một ngôn ngữ. *Phản biện đã cân nhắc & cách xử lý:* FastAPI async và Celery worker sync cùng truy cập Postgres dễ cạn connection → bắt buộc đặt **PgBouncer/Supavisor** ở giữa (xem Khối G).

---

### Khối C — Tích hợp Amazon (Integration Layer)

Đây là phần đặc thù nhất của dự án. Điểm cốt lõi: **SP-API và Amazon Ads API là HAI hệ thống riêng biệt** — khác URL, khác scope, khác data model, khác cách nhận dữ liệu push. Cùng dùng đăng nhập LWA (Login with Amazon) nhưng **khác scope nên phải authorize riêng và lưu token riêng**.

```
            SP-API                          AMAZON ADS API
  ─────────────────────────────   ─────────────────────────────────
  sellingpartnerapi-na.amazon.com   advertising-api.amazon.com
  Dữ liệu: orders, inventory,       Dữ liệu: campaigns, ad groups,
           finance, catalog                  keywords, targets, spend
  Push: Notifications API → SQS     Push: Marketing Stream → Kinesis
  Reports: createReport → poll      Reports v3: createReport → poll
  Rủi ro: chủ yếu ĐỌC               Rủi ro: ĐỌC + GHI (tiêu tiền)
```

**Gồm những phần gì**

- *SP-API client:* đọc orders, inventory, finance, catalog.
- *Ads API client:* đọc campaigns/performance và (giai đoạn sau) ghi bid/budget/state.
- *Rate limiter riêng cho mỗi API:* hai API có hạn mức khác nhau, không dùng chung.
- *Token management:* refresh token tự động, cache access token (xem vault ở Khối G).

**Các hướng triển khai — cách lấy dữ liệu (ingestion)**

| Hướng | Lợi thế | Điểm yếu |
|---|---|---|
| **Polling** (cron kéo report định kỳ) | Đơn giản, dễ hiểu, dễ debug | Dữ liệu trễ; tốn rate limit; bỏ lỡ thay đổi giữa hai lần kéo |
| **Push** (Notifications→SQS, Marketing Stream→Kinesis) | Dữ liệu tươi theo giờ; `budget-usage` real-time — sống còn cho circuit breaker | Hạ tầng phức tạp hơn (SQS/Kinesis); cần xử lý trùng/thiếu message |
| **Lai: Push là chính + Poll dự phòng** | Vừa tươi vừa không sót (poll vá lỗ hổng khi push trễ/mất) | Phải viết logic chống trùng giữa hai nguồn |

**➜ Đề xuất:** **Hướng lai** — Push làm nguồn chính, Poll làm lưới dự phòng. Lý do: automation cần quyết định trên **dữ liệu tươi theo giờ**, và `budget-usage` real-time từ Amazon Marketing Stream là input bắt buộc cho cầu dao ngắt (Khối E). Poll dự phòng đảm bảo không sót dữ liệu khi stream gặp sự cố. *Phản biện đã cân nhắc:* thư viện cộng đồng cho Ads API còn yếu → **tự viết thin client bằng httpx** cho Ads API (ghi nhận đây là một điểm rủi ro kỹ thuật cần kiểm thử kỹ); SP-API thì dùng `python-amazon-sp-api` (cộng đồng, ổn định).

---

### Khối D — Tầng dữ liệu (Data Layer)

**Gồm những phần gì**

- *Postgres:* lưu toàn bộ — dữ liệu vận hành, dữ liệu quảng cáo, rule, hành động, audit.
- *Ba tầng dữ liệu:* `raw` (nguyên gốc từ API) → `normalized` (đã chuẩn hóa) → `aggregated` (tổng hợp sẵn để dashboard đọc nhanh, ví dụ bảng PnL theo ngày).
- *Time-series:* bảng hiệu suất quảng cáo có volume lớn → **partition theo tháng**.
- *Redis:* hàng đợi cho Celery + cache access token.

**Các hướng triển khai — nhà cung cấp Postgres managed**

> Lưu ý: hệ thống *luôn cần Postgres thật*. Câu hỏi chỉ là chọn nhà cung cấp. Vì truy cập qua SQLAlchemy + Alembic (Postgres chuẩn, tránh feature độc quyền), nên đổi nhà cung cấp về sau = đổi connection string + migrate data, rủi ro thấp.

| Hướng | Lợi thế | Điểm yếu |
|---|---|---|
| **Supabase** | Postgres + Realtime + Storage (lưu file report) + Studio UI; free tier rộng → khởi động nhanh nhất | RLS/Auth ít giá trị khi Python đứng trước (dùng như "Postgres + Realtime + Storage") |
| **Neon** | Postgres thuần, có branching (dev/staging), scale-to-zero rẻ; ít lock-in nhất | Không có Realtime/Storage/Auth — phải tự làm qua FastAPI |
| **AWS Aurora Serverless v2** | Cùng VPC với KMS/SQS/Kinesis → một ranh giới bảo mật cho PII, IAM auth, hợp compliance | Vận hành nặng hơn, đắt hơn, không scale-to-zero |

**➜ Đề xuất theo giai đoạn:**
- *Giai đoạn nền & phân tích (cho mình):* **Supabase** (nhanh, sẵn Realtime + Storage) hoặc **Neon** (nếu thích Postgres thuần + branching).
- *Khi thành dịch vụ + siết PII:* cân nhắc migrate sang **Aurora Serverless v2**.

*Phản biện đã cân nhắc:* nếu dùng sâu Supabase Realtime/Storage/Auth thì sẽ có lock-in nhẹ ở các phần đó. Nếu muốn portable tuyệt đối, tự làm Realtime/Storage qua FastAPI — đổi lại tốn công hơn lúc đầu.

---

### Khối E — Bộ máy tự động hóa (Automation Engine)

Đây là **trái tim và cũng là phần nguy hiểm nhất** của hệ thống — nơi máy ra quyết định tiêu tiền. Vì vậy nó được tách thành service riêng, và mọi hành động phải đi qua một vòng đời chặt chẽ.

**Gồm những phần gì** (theo đúng vòng đời một quyết định)

```
1. Rules Engine     Đọc dữ liệu hiệu suất mới nhất, so với điều kiện rule.
2. Proposed Action  Sinh đề xuất {target, giá trị cũ → mới, lý do}. Chưa gọi API.
3. Guardrails       Kiểm tra qua TẤT CẢ lớp an toàn. Vi phạm → BLOCK + ghi lý do.
4. Gate             WALK: vào Approval Queue (chờ người).
                    RUN:  pass guardrail → tự đi tiếp.
5. Executor         Gọi Ads API (WRITE) — đây là điểm duy nhất ghi ra Amazon.
6. Reconcile        Đọc lại sau X phút để xác nhận thay đổi đã "ăn"
                    (Ads API là eventual consistency). Lệch → alert.
7. Audit Log        Mọi bước ghi vào log append-only (không sửa/xóa).
        ▲
   Circuit Breaker ◄── budget-usage real-time (từ Marketing Stream)
```

**Hướng triển khai — biểu diễn rule**

| Hướng | Lợi thế | Điểm yếu |
|---|---|---|
| **Hardcode** (rule viết thẳng trong code) | Nhanh nhất lúc đầu | Mỗi rule mới phải deploy lại; không cho người dùng tự định nghĩa |
| **Data-driven** (rule là dữ liệu JSON: điều kiện + hành động) | Thêm/sửa rule không cần deploy; mở đường cho UI tạo rule; dễ audit | Phải xây "trình thông dịch" điều kiện; cần validate kỹ |
| **DSL/scripting** (ngôn ngữ luật riêng) | Linh hoạt tối đa | Phức tạp, dễ thành "ngôn ngữ lập trình mini" khó kiểm soát |

**➜ Đề xuất:** **Data-driven** — rule lưu dạng dữ liệu có cấu trúc (điều kiện + hành động + chế độ), engine đọc và đánh giá. Lý do: đây là nền để sau này người dùng (và AI) tự đề xuất rule mà không cần lập trình, và để audit "rule nào đã kích hoạt". Ví dụ cấu trúc rule xem [Phụ lục](#phụ-lục--ví-dụ-minh-họa).

**Hướng triển khai — chế độ thực thi (gate)**

Đây không phải lựa chọn loại trừ mà là **một thang tiến hóa** gắn với Crawl→Walk→Run: cùng một rule chạy lần lượt qua 3 chế độ `dry_run` → `recommend` → `auto`. Một rule mới **bắt buộc** bắt đầu ở `dry_run`.

**An toàn — 7 lớp guardrail (mỗi lớp là một tuyến phòng thủ độc lập)**

> Triết lý: không tin vào một điểm phòng thủ duy nhất — *defense in depth* cho tiền thật.

1. **Budget Cap** — tổng spend/ngày không vượt trần; automation không được tự tăng budget vượt mức người đặt.
2. **Max Change per Action** — một lần đổi bid/budget tối đa ±X% (chặn lỗi tính toán gây thay đổi cực đoan).
3. **Min/Max Bid** — bid không bao giờ về 0 (tắt hiển thị) hoặc vọt lên mức cháy tiền.
4. **Frequency Cap** — mỗi target chỉ bị đổi tối đa 1 lần / cooldown (chặn rule "đánh nhau" làm bid dao động liên tục).
5. **Circuit Breaker** — `budget-usage` real-time vượt ngưỡng bất thường → **ngắt toàn bộ automation**. Đây là cầu dao tổng.
6. **Dry-run / Shadow** — rule mới bắt buộc chạy thử, log "nếu chạy sẽ đổi gì" mà không gọi API.
7. **Rollback** — snapshot trước mỗi batch, cho phép hoàn tác 1-click. Lưới an toàn cuối cùng.

**➜ Đề xuất:** Triển khai **đủ cả 7 lớp** trước khi mở chế độ `auto`. Mỗi lớp độc lập, một lớp hỏng vẫn còn lớp khác. *Phản biện đã cân nhắc:* nhiều lớp guardrail khiến hệ thống "chậm và cẩn thận" hơn — đây là đánh đổi **chủ động chấp nhận**, vì cái giá của một đêm cháy ngân sách lớn hơn nhiều cái giá của vài đề xuất bị chặn oan.

---

### Khối F — Tầng AI (AI Layer)

**Gồm những phần gì**

- Tóm tắt hiệu suất hàng ngày.
- Phát hiện bất thường (spike ACOS, sụt doanh thu).
- Gợi ý rule mới từ pattern dữ liệu.
- Khai thác negative keyword (search term nên loại).
- Hỏi-đáp ngôn ngữ tự nhiên ("Tại sao ACOS tháng này tăng?").
- Dự báo tồn kho / spend.

**Hướng triển khai — quyền hạn của AI**

| Hướng | Lợi thế | Điểm yếu |
|---|---|---|
| **AI gọi API và tự áp dụng** | Tối ưu nhanh, ít người can thiệp | **Cực kỳ rủi ro** — AI có thể sai và tiêu tiền ngay; không kiểm soát được |
| **AI chỉ đề xuất, đi qua đúng pipeline guardrail/approval** | An toàn; AI được đối xử như một "nguồn đề xuất" bình thường | Chậm hơn; AI không có "đặc quyền" |

**➜ Đề xuất:** **AI chỉ đề xuất, không bao giờ bypass guardrail.** Đề xuất của AI đi qua đúng đường `proposed_action → guardrail → (duyệt/auto)` như rule thường. Nguyên tắc bất biến:

- ❌ AI **không** bypass guardrail.
- ❌ **Không** gửi PII vào LLM.
- ✅ Gọi LLM async qua hàng đợi; cache output + dùng Prompt Caching để giảm chi phí.
- ✅ AI đề xuất *rule*, người phải duyệt trước khi rule lên chế độ `auto`.

*Lựa chọn model theo việc:* tóm tắt/anomaly dùng `claude-haiku-4-5` (rẻ, nhanh); gợi ý rule / NL Q&A / tối ưu bid dùng `claude-sonnet-4-6`; phân tích chiến lược sâu (on-demand) dùng `claude-opus-4-8`.

---

### Khối G — Hạ tầng & Bảo mật (cross-cutting)

Khối này không nằm trên một tầng cụ thể mà **đỡ toàn bộ hệ thống**.

**Gồm những phần gì**

- *Token Vault (AWS KMS):* refresh token của SP-API và Ads API được mã hóa, lưu **riêng từng tenant, riêng từng API**.
- *Multi-tenancy seam:* `tenant_id` trên mọi bảng từ ngày đầu.
- *Connection pooling (PgBouncer/Supavisor):* chống cạn connection khi FastAPI async + Celery sync cùng chạm DB.
- *Queue & worker (Celery + Redis):* chạy job nặng; Flower để monitoring.
- *SQS / Kinesis:* nhận push từ hai API (đã mô tả ở Khối C).

**Hướng triển khai — chiến lược multi-tenancy**

| Hướng | Lợi thế | Điểm yếu |
|---|---|---|
| **Single-tenant trước, migrate sau** | Đơn giản lúc đầu | Migrate single→multi về sau **rất đắt** (đụng mọi query, mọi bảng) |
| **Full SaaS ngay** (billing, onboarding, team) | Sẵn sàng bán dịch vụ ngay | Lãng phí lớn khi chưa có khách; làm chậm sản phẩm cho chính mình |
| **Làm "seam" rẻ ngay, hoãn phần đắt** | Tránh migrate đau mà không tốn công xây SaaS sớm | Cần kỷ luật code (mọi query phải có tenant_id) |

**➜ Đề xuất:** **Làm seam ngay, hoãn phần đắt.**
- *Làm ngay (~5% công):* `tenant_id` mọi bảng; data-access layer luôn lọc theo `tenant_id` (không có "seller hiện tại" toàn cục); token vault tách theo tenant; không singleton giả định một seller.
- *Hoãn (khi thành dịch vụ thật):* billing, self-serve onboarding, team/role management, rate-limit công bằng giữa tenant.

*Phản biện đã cân nhắc — hệ quả của backend Python:* Python dùng service-role connection nên **RLS của Supabase bị bypass**. Vì vậy **tenant isolation phải enforce ở tầng Python**: dùng **Base Repository bắt buộc truyền `tenant_id`** (không cho query "trần"), để chống quên lọc tenant. Đây là đánh đổi: mất lớp bảo vệ tự động của DB, đổi lấy kiểm soát hoàn toàn ở tầng app — chấp nhận được nếu giữ kỷ luật code.

---

## Phần IV — Mô hình dữ liệu (khái niệm)

Phần này mô tả **các thực thể và quan hệ** ở mức khái niệm. Schema cụ thể (DDL/JSON) nằm trong [Phụ lục](#phụ-lục--ví-dụ-minh-họa).

**Nhóm Vận hành (SP-API):**
- `sellers` — tài khoản seller (gắn `tenant_id`).
- `orders`, `order_items` — đơn hàng và dòng hàng.
- `inventory`, `products` — tồn kho và danh mục sản phẩm.
- `settlement_*` — báo cáo quyết toán tài chính (nguồn của phí Amazon).
- `aggregated_daily` — bảng tổng hợp sẵn để dashboard/PnL đọc nhanh.

**Nhóm Quảng cáo (Ads API):** quan hệ phân cấp
```
ad_profiles (theo marketplace/account)
  └── ad_campaigns (SP / SB / SD; có budget, state)
        └── ad_groups (default bid, state)
              └── ad_targets (keyword/product; bid, match type, state)

ad_performance — time-series theo ngày/giờ
  (impressions, clicks, cost, sales, orders → tính ACOS/ROAS/CTR/CVR khi query)
```

**Nhóm Automation:**
- `automation_rules` — rule dạng dữ liệu (điều kiện + hành động + chế độ).
- `proposed_actions` — đề xuất chờ duyệt/đã xử lý (vòng đời pending→approved/rejected→executed/blocked).
- `action_log` — **audit log bất biến, append-only**: ghi mọi đề xuất, quyết định của người, kết quả API. Không cho UPDATE/DELETE để truy vết "tại sao bid này bị đổi".
- `guardrail_configs` — cấu hình các trần an toàn theo tenant.

**Cách dữ liệu chảy để ra PnL (giai đoạn nền):**
```
SP-API (doanh thu, phí)  ─┐
Ads API (chi phí QC)     ─┼─► raw ─► normalized ─► aggregated_daily ─► Giao diện PnL
COGS (nhập tay)          ─┘                          (đọc ra, không gọi API trực tiếp)
```

---

## Phần V — Roadmap theo giai đoạn

Khung xương sống (Phần II–IV) là cố định. Phần này là **thứ tự xây dựng** — mỗi giai đoạn ra một sản phẩm dùng được và là nền cho giai đoạn sau.

| Phase | Thời gian | Khối chính | Bản chất | Ghi? | Rủi ro tiền |
|---|---|---|---|---|---|
| **0** | Tuần 1-2 | C, D, G | Foundation (auth + infra) | Không | Không |
| **1** | Tháng 1 | A, B, C(SP), D | Vận hành + **PnL** (read) | Không | Không |
| **2** | Tháng 2 | A, C(Ads), D | Ads visibility (read) | Không | Không |
| **3** | Tháng 3 | E | Đề xuất + người duyệt (WALK) | Có (qua duyệt) | Thấp |
| **4** | Tháng 4+ | E | Tự động + guardrail (RUN) | Có (tự động) | Cao |
| **5** | Tháng 5+ | F | AI tối ưu | Có (qua guardrail) | Trung bình |

### Phase 0 — Foundation *(nền móng, chưa có nghiệp vụ)*

- Đăng ký SP-API app + Ads API app (2 app riêng trong developer console).
- LWA OAuth cho **cả hai scope** (authorize riêng từng cái).
- Token Vault: lưu refresh token mã hóa qua KMS cho cả 2 API.
- Infra cơ bản: Postgres + Redis + 1 container API + skeleton worker.
- Single seller (chính mình) — nhưng `tenant_id` đã có sẵn trong schema.
- **Exit:** gọi được 1 endpoint mỗi API (getMarketplaceParticipations + listProfiles); token tự refresh, lưu mã hóa.

### Phase 1 — Vận hành + PnL *(giai đoạn nền — quan trọng nhất để khởi động)*

> Đây chính là **"call API + dựng cơ sở dữ liệu + trích ra giao diện PnL"**. Mọi thứ đọc từ DB ra, không gọi API trực tiếp để hiển thị.

- Sync orders (Notifications→SQS + fallback poll), inventory, settlement report (cron ngày).
- Dựng 3 tầng dữ liệu: raw → normalized → `aggregated_daily`.
- **Giao diện PnL:** doanh thu − phí Amazon − giá vốn = lợi nhuận (chưa có chi phí QC, sẽ hoàn thiện ở Phase 2).
- Dashboard KPI: doanh thu, đơn hàng, tồn kho; cảnh báo tồn kho thấp.
- **Exit:** dữ liệu khớp Seller Central khi đối chiếu thủ công; dashboard đáng tin.

### Phase 2 — Ads Visibility *(hoàn thiện PnL + giai đoạn phân tích)*

- Sync Ads: profiles → campaigns → ad groups → keywords/targets.
- Performance: Reports v3 (cron) + Marketing Stream (real-time) qua Kinesis.
- **PnL hoàn chỉnh:** cộng nốt chi phí quảng cáo vào → lợi nhuận *thật*.
- Dashboard quảng cáo: ACOS, ROAS, spend, CTR, CVR; phát hiện keyword "đốt tiền" (chỉ hiển thị).
- **Exit:** dữ liệu ads khớp Ads Console; đã hiểu rõ pattern dữ liệu trước khi cho máy tự động.

### Phase 3 — Recommendation Engine *(WALK — máy đề xuất, người duyệt)*

- Rules Engine: định nghĩa rule dạng dữ liệu (ví dụ "ACOS > 40% trong 14 ngày → giảm bid 10%").
- Sinh proposed actions; chạy **dry-run** trước.
- Approval Queue UI: người xem từng đề xuất, Approve/Reject.
- Khi Approve → Action Executor gọi Ads API (lần đầu có WRITE) → Reconciliation xác nhận.
- Audit Log ghi đầy đủ.
- **Exit (= cổng lên Phase 4):** chạy ≥ 4 tuần; reject rate < 5%; reconcile xác nhận 100%; không có sự cố tiêu tiền.

### Phase 4 — Full Automation *(RUN — máy tự chạy có guardrail)*

- Auto-apply: rule pass guardrail → thực thi không cần người duyệt.
- Đủ 7 guardrail + Circuit Breaker (từ `budget-usage` AMS) + Rollback 1-click.
- Daily spend digest: báo cáo automation đã làm gì hôm nay.
- Vẫn giữ approval cho rule "rủi ro cao" (đổi budget lớn).
- **Exit:** spend ổn định; circuit breaker test fire đúng; rollback test thành công.

### Phase 5 — AI Optimization

- AI gợi ý rule mới, anomaly detection, forecast, bid optimization, NL Q&A, negative keyword mining.
- AI luôn đi qua pipeline guardrail/approval như rule thường; không PII vào LLM.

---

## Phần VI — Nhật ký quyết định

Ghi lại các quyết định kiến trúc cốt lõi và đánh đổi của chúng (để sau này nhớ *vì sao* đã chọn).

| # | Quyết định | Lý do | Đánh đổi chấp nhận |
|---|---|---|---|
| 1 | SP-API và Ads API là **2 integration độc lập** | Khác URL, scope, data model, rate limit | Hai client, hai luồng token để quản |
| 2 | **Automation Engine tách service riêng** | Cô lập blast-radius — bug sync không chạm luồng tiêu tiền | Thêm một service để vận hành |
| 3 | Bắt buộc **Crawl→Walk→Run** (qua Phase 3 trước Phase 4) | Cần dữ liệu thực chứng minh logic đúng (reject <5%) trước khi tự động | Chậm hơn, đổi lấy tránh thảm họa cháy ngân sách |
| 4 | **7 lớp guardrail** độc lập + circuit breaker + rollback | Không tin một điểm phòng thủ duy nhất | Hệ thống "chậm và cẩn thận" hơn |
| 5 | **Audit log append-only** | Compliance + truy vết quyết định tài chính | Không sửa/xóa được log (đúng ý đồ) |
| 6 | **Backend Python + Frontend client thuần** | Một nguồn chân lý logic, không xé sang JS | Mất server components; phải giữ API contract (OpenAPI bù lại) |
| 7 | **Tenant isolation ở tầng app** (không dựa RLS) | Python service-role bypass RLS | Cần kỷ luật: Base Repository bắt buộc `tenant_id` |
| 8 | **Multi-tenant seam ngay, SaaS hoãn sau** | Migrate single→multi rất đắt; build SaaS sớm thì lãng phí | Thêm ~5% công ngay từ đầu |
| 9 | **Managed Postgres, chọn theo giai đoạn** | Không lock-in nhờ SQLAlchemy/Alembic | Lock-in nhẹ nếu dùng sâu Supabase Realtime/Storage |

---

## Phụ lục — Ví dụ minh họa

> Phần này chứa toàn bộ schema/JSON cụ thể. Đây **chỉ là minh họa** cho phần kiến trúc ở trên, không phải bản cài đặt cuối.

### A. Rule dạng dữ liệu (Khối E)

```json
{
  "name": "Giảm bid khi ACOS cao",
  "scope": { "level": "keyword", "campaign_id": "..." },
  "conditions": [
    { "metric": "acos", "op": ">", "value": 0.4, "window_days": 14 }
  ],
  "action": { "type": "adjust_bid", "mode": "percent", "value": -10 },
  "mode": "dry_run",
  "cooldown_hours": 24,
  "is_active": true
}
```

### B. Proposed action & Audit log (Khối E)

```json
// proposed_action
{
  "rule_id": "...",
  "target_type": "keyword",
  "target_id": "...",
  "action_type": "adjust_bid",
  "old_value": { "bid": 1.20 },
  "new_value": { "bid": 1.08 },
  "reason": "acos=46% > 40% trong 14 ngày",
  "status": "pending",
  "guardrail_result": { "max_change": "pass", "min_max_bid": "pass" }
}
```

```json
// action_log (append-only — không UPDATE/DELETE)
{
  "seller_id": "...",
  "rule_id": "...",
  "target_type": "keyword",
  "action_type": "adjust_bid",
  "old_value": { "bid": 1.20 },
  "new_value": { "bid": 1.08 },
  "reason": "acos=46% > 40% trong 14 ngày",
  "triggered_by": "automation",
  "guardrail_check": { "all": "pass" },
  "api_request": { "...": "..." },
  "api_response": { "...": "..." },
  "reconciled": true,
  "created_at": "2026-06-09T10:00:00Z"
}
```

### C. Guardrail config theo tenant (Khối E/G)

```json
{
  "seller_id": "...",
  "max_daily_spend": 200.00,
  "max_bid_change_pct": 15,
  "max_budget_change_pct": 20,
  "min_bid": 0.02,
  "max_bid": 5.00,
  "circuit_breaker_spend_per_hour": 50.00
}
```

### D. Schema DDL tham khảo (Khối D)

> DDL đầy đủ (bảng ads, performance partition theo tháng, action_log…) được giữ làm tham khảo khi cài đặt. Ý chính về mặt kiến trúc:
> - `ad_performance` **partition theo tháng** vì là time-series volume cao (cân nhắc TimescaleDB nếu bùng nổ).
> - `action_log` dùng `bigserial`, **không có UPDATE/DELETE**.
> - Token Ads API lưu **riêng** (`refresh_token_enc bytea`, mã hóa KMS), không dùng chung token SP-API.

```json
// ad_performance (minh họa cấu trúc một dòng)
{
  "target_id": "...",
  "date": "2026-06-09",
  "hour": 14,                 // null nếu từ report ngày; có giá trị nếu từ AMS
  "impressions": 1200,
  "clicks": 35,
  "cost": 28.40,
  "sales": 95.00,
  "orders": 4
  // ACOS/ROAS/CTR/CVR tính khi query hoặc qua materialized view
}
```

---

*v3.0 — Kiến trúc theo khối (A–G), backbone cố định + triển khai theo giai đoạn. Giai đoạn nền: call API → dựng DB → trích ra giao diện PnL. Triết lý: dữ liệu chính xác trước (Phase 1-2), logic được người tin tưởng (Phase 3), rồi mới giao quyền tự động (Phase 4-5). Không bao giờ để máy tiêu tiền trước khi chứng minh được nó đáng tin.*
