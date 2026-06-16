# Session Handoff — Thiết lập CLAUDE.md & Global Skills cho Claude Code

## 🎯 Mục tiêu tổng thể

Xây dựng hệ thống "quy tắc làm việc" cho Claude Code khi code trong repo
`VPS\` (SellerVision), gồm 2 tầng:
1. **Project-level**: file `CLAUDE.md` tự nạp mỗi session, chứa guardrails/quy
   ước riêng của SellerVision (đã rút ra từ memory các session trước).
2. **Global-level**: các skill hành vi tổng quát (không đặc thù project) cài ở
   `~/.claude/skills/`, áp dụng cho MỌI project trên máy.

## ✅ Đã hoàn thành

- **Tạo [`VPS/CLAUDE.md`](CLAUDE.md)** (gốc project, tự nạp mỗi session mở
  trong `VPS\`). Nội dung tổng hợp từ memory `sellervision-3phase-pipeline` +
  `sellervision-fee-model` + `SESSION_HANDOFF.md`/`PIPELINE_3PHASE_README.md`
  của `sellerboard_clone`:
  - Kiến trúc pipeline 3 giai đoạn + vị trí code
  - 5 guardrail cứng (không sửa tay backend/frontend production, không xóa
    bảng sống Supabase, quy ước `--fresh`, user kiểm soát ingest, Bash thiếu
    cat/grep/sed)
  - Quy ước dấu/công thức tài chính (Gross/Net Profit, Margin, amazon_fees)
  - Fee model đã kiểm chứng (referral 16.5% = 15% + 10% VAT VN — KHÔNG sửa về
    15%)
  - Timezone protocol (Pacific, AT TIME ZONE conversion)
  - Memory-safety rules (chunk ≤100, del+gc.collect, savepoint per order)
  - Quy ước đối chiếu file Sellerboard (so số tolerance 0.01, không so chuỗi)
  - Thông tin VPS/DB admin (SSH password, `_dbadmin.py`...)
  - Trỏ tới `docs/SESSION_HANDOFF.md` và `PIPELINE_3PHASE_README.md` để tra
    chi tiết sâu (không duplicate nội dung)

- **Phân tích folder `C:\Users\nnh16\github repo\`** (6 repo skill/tool đã
  clone: andrej-karpathy-skills, goose, harness, skills_google_AI_AGent,
  superpowers, understand-anything) — đánh giá repo nào hữu ích cho
  SellerVision, repo nào không (xem bảng quyết định ở mục "Quyết định đã
  xác nhận").

- **Cài 3 global skill** tại `~/.claude/skills/` (= `C:\Users\TGS\.claude\skills\`):
  - `karpathy-guidelines/SKILL.md` — copy nguyên bản từ
    `andrej-karpathy-skills/skills/karpathy-guidelines/SKILL.md`. 4 nguyên
    tắc: Think Before Coding, Simplicity First, Surgical Changes,
    Goal-Driven Execution.
  - `systematic-debugging/SKILL.md` (+ `root-cause-tracing.md`,
    `defense-in-depth.md`, `condition-based-waiting.md`) — copy từ
    `superpowers/skills/systematic-debugging/`, ĐÃ SỬA: bỏ 2 cross-reference
    tới skill chưa cài (`superpowers:test-driven-development`,
    `superpowers:verification-before-completion`), thay bằng hướng dẫn
    tổng quát "tạo reproduction trước khi fix". Iron Law: "NO FIXES WITHOUT
    ROOT CAUSE INVESTIGATION FIRST", 4 phases, ≥3 fix thất bại → đặt lại câu
    hỏi kiến trúc.
  - `using-git-worktrees/SKILL.md` — copy nguyên bản từ
    `superpowers/skills/using-git-worktrees/SKILL.md`. Ưu tiên native
    `EnterWorktree` trước khi fallback `git worktree add`.
  - Đã verify: cả 3 skill hiện xuất hiện trong danh sách skill khả dụng của
    Claude Code (system-reminder xác nhận).

- **Lưu memory** (`C:\Users\TGS\.claude\projects\C--Users-nnh16-ads-trading-system-VPS\memory\`):
  - File mới `global-skills-installed.md` (type: reference) — ghi lại 3 skill
    đã cài, lý do, link tới `sellervision-fee-model`.
  - Cập nhật `MEMORY.md` index thêm 1 dòng trỏ tới file trên.

## 🔄 Đang dở / Chưa hoàn thiện

- Không có việc dở dang trong phạm vi "thiết lập skills" — đã xong toàn bộ.
- Việc dở dang của PROJECT SellerVision (calibrate fees, refund hybrid,
  Phase 2 refactor...) KHÔNG thuộc phạm vi session này — xem
  `VPS_AMZ/sellerboard_clone/docs/SESSION_HANDOFF.md` riêng cho phần đó.

## 📋 Việc cần làm tiếp theo (theo thứ tự ưu tiên)

1. (Tuỳ chọn, không gấp) Nếu sau này cần build multi-agent team cho
   SellerVision (vd refactor lớn Phase 2), xem lại `harness` repo trong
   `C:\Users\nnh16\github repo\harness\` — đã đánh giá là overkill hiện tại
   nhưng có thể hữu ích về sau.
2. (Tuỳ chọn) `understand-anything` (visualize codebase) có thể hữu ích khi
   codebase 3-phase phình to, nhưng cần cài Node/pnpm riêng — chưa làm.
3. Quay lại công việc chính của SellerVision: đọc
   `VPS_AMZ/sellerboard_clone/docs/SESSION_HANDOFF.md` mục 5/5b/6 (calibrate
   fees, Phase 2 refactor "Enterprise ETL", refund hybrid).

## 🏗️ Kiến trúc / Cấu trúc hệ thống

Không thay đổi kiến trúc SellerVision trong session này. Tham khảo
`CLAUDE.md` (mới tạo) hoặc `PIPELINE_3PHASE_README.md` cho kiến trúc pipeline
3 giai đoạn:
```
Amazon API ──(Phase1: Direct-Stream)──► Supabase NEW_* (bảng đệm)
Supabase   ──(Phase2: Transform)──────► NEW_summary_order_items / NEW_summary_products / NEW_summary_campaigns
Summary    ──(Phase3: Bridge/Patch)───► Web App app.tap2soul.com
```

## 📁 Cấu trúc thư mục quan trọng

```
C:\Users\nnh16\ads-trading-system\VPS\
├── CLAUDE.md                          # MỚI — tự nạp mỗi session, guardrails SellerVision
├── CLAUDE_SKILLS_SETUP_HANDOFF.md      # file này
└── VPS_AMZ/sellerboard_clone/
    ├── docs/SESSION_HANDOFF.md         # bàn giao công việc pipeline (riêng, không đổi)
    └── PIPELINE_3PHASE_README.md       # kiến trúc pipeline (riêng, không đổi)

C:\Users\TGS\.claude\skills\            # GLOBAL — áp dụng mọi project
├── karpathy-guidelines/SKILL.md        # MỚI
├── systematic-debugging/SKILL.md       # MỚI (đã sửa cross-ref)
│   ├── root-cause-tracing.md           # MỚI
│   ├── defense-in-depth.md             # MỚI
│   └── condition-based-waiting.md      # MỚI
└── using-git-worktrees/SKILL.md        # MỚI

C:\Users\TGS\.claude\projects\C--Users-nnh16-ads-trading-system-VPS\memory\
├── MEMORY.md                           # cập nhật thêm 1 dòng
└── global-skills-installed.md          # MỚI

C:\Users\nnh16\github repo\             # nguồn skill, KHÔNG thay đổi
├── andrej-karpathy-skills/             # → đã lấy karpathy-guidelines
├── superpowers/                        # → đã lấy systematic-debugging + using-git-worktrees
├── harness/                            # không dùng (overkill hiện tại)
├── skills_google_AI_AGent/             # không dùng (GCP, không liên quan Supabase/VPS)
├── goose/                               # không dùng (agent app khác, không phải skill)
└── understand-anything/                # không dùng (chưa cần, cần Node/pnpm)
```

## ⚙️ Biến môi trường & Cấu hình (.env)

Không có thay đổi `.env` trong session này.

## 🔑 Thông số kỹ thuật quan trọng

- 3 skill global mới: `karpathy-guidelines`, `systematic-debugging`,
  `using-git-worktrees` — tự trigger theo description, không cần gọi tay.
- `CLAUDE.md` ở gốc `VPS\` — Claude Code tự nạp khi mở session trong thư mục
  này (không cần "nhét" file mỗi lần).
- Memory project path:
  `C:\Users\TGS\.claude\projects\C--Users-nnh16-ads-trading-system-VPS\memory\`

## 🐛 Vấn đề đã gặp & Cách giải quyết

- Lệnh `Bash` dạng `find . -iname "*claude*" -o -iname "SESSION_HANDOFF*"`
  với path có dấu cách (`"C:/Users/nnh16/github repo"`) ban đầu lỗi exit code
  2 (`ls: cannot access`) khi check `~/.claude/skills` chưa tồn tại — không
  phải lỗi nghiêm trọng, chỉ là thư mục chưa được tạo trước khi `mkdir -p`.
- `systematic-debugging/SKILL.md` gốc (từ `superpowers`) tham chiếu 2 skill
  khác (`superpowers:test-driven-development`,
  `superpowers:verification-before-completion`) KHÔNG được cài → đã sửa
  thành hướng dẫn tổng quát để tránh Claude tìm skill không tồn tại.

## 🚫 Quyết định đã được xác nhận (không thay đổi)

- **Dùng `CLAUDE.md` (tự nạp) thay vì `SKILLS.md` rời** — vì CLAUDE.md được
  Claude Code tự động đưa vào context mỗi session mở trong `VPS\`, không cần
  user thao tác thêm. SKILLS.md rời sẽ không tự nạp.
- **Đặt nội dung guardrail SellerVision ở project-level (`VPS/CLAUDE.md`)**,
  không phải global — vì đặc thù riêng project này (fee model, pipeline...),
  để global sẽ "rác" context cho project khác.
- **Chỉ cài 3/nhiều skill từ `github repo`**: `karpathy-guidelines`,
  `systematic-debugging`, `using-git-worktrees`. Lý do loại các repo khác:
  - `harness` — meta-skill build multi-agent team, overkill cho 1 dev + Claude
  - `skills_google_AI_AGent` — skill cho Google Cloud, SellerVision dùng
    Supabase + VPS thuần, không liên quan
  - `goose` — là 1 AI agent app khác (Rust), không phải skill cắm vào Claude
    Code được
  - `understand-anything` — visualize codebase, cần cài Node/pnpm riêng, chưa
    cần thiết
  - Từ `superpowers`, bỏ qua `code-review`, `simplify`, `brainstorming`,
    `test-driven-development`, v.v. vì trùng skill có sẵn
    (`code-review`, `simplify` đã có trong hệ thống).

## 💡 Context bổ sung

- Đây là việc THIẾT LẬP TOOLING, không phải code nghiệp vụ SellerVision.
  Khi mở session mới trong `VPS\`, `CLAUDE.md` sẽ tự nạp — không cần paste
  lại nội dung guardrail.
- File handoff công việc nghiệp vụ chính (pipeline/fees/calibrate) vẫn là
  `VPS_AMZ/sellerboard_clone/docs/SESSION_HANDOFF.md` — đọc file đó khi tiếp
  tục công việc pipeline, đọc file này (`CLAUDE_SKILLS_SETUP_HANDOFF.md`) chỉ
  khi cần biết bối cảnh thiết lập skill/tooling.
- Memory đã được cập nhật, session mới có thể tự "nhớ" qua memory system
  (`sellervision-3phase-pipeline`, `sellervision-fee-model`,
  `global-skills-installed`).

---
*Session kết thúc lúc: 2026-06-16*
*File này được tạo tự động để kế thừa sang session tiếp theo.*
