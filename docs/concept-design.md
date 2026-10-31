# MasterBA — Concept Design: Hệ thống Agent Sinh & Quản trị Tài liệu V-Waterfall (IPA)

Status: DRAFT v0.3 — các quyết định nền tảng (v0.2) + 4 điểm mở (mục 13) đã được chốt (2026-10-31); vẫn chưa có code, vẫn là concept để chi tiết hoá trước khi implement.

## 0. Thay đổi so với v0.1 (quyết định đã chốt)

| # | Quyết định | Chốt |
|---|---|---|
| 1 | Ngôn ngữ orchestrator/MCP | **Python**. Agent chỉ sinh **JSON artifact** (structured content) — KHÔNG trực tiếp ghi Excel. Một tool deterministic (openpyxl) đọc JSON + template để fill ra Excel ở bước riêng. |
| 2 | Lưu trace graph & Decision Record | **File-based trong git** (YAML/JSON), review qua PR/commit. |
| 3 | Mô hình project | **1 project active tại 1 thời điểm** (không chạy đa project đồng thời), nhưng **framework đa năng, tái sử dụng**: mỗi input/khách hàng khác nhau → 1 project riêng, cấu trúc folder cách ly hoàn toàn; chuyển project chỉ là đổi context, không đổi code/deploy. |
| 4 | Giao diện phê duyệt | **Cần Dashboard/UI thật** (không chỉ CLI): upload tài liệu, tạo/xem/approve Decision Record, theo dõi toàn bộ pipeline agent một cách comprehensive. |
| 5 | Template Excel mẫu | **Chưa có file thật.** Dùng baseline tổng hợp từ thực tiễn ngành SI Nhật (xem mục 8) làm điểm khởi đầu; sẽ hiệu chỉnh lại khi có 1 file mẫu thật từ công ty/khách hàng. |

Lý do kiến trúc của quyết định #1 (rất quan trọng, nên giữ xuyên suốt): **tách "nội dung" (content, do LLM sinh, dạng JSON có schema) ra khỏi "hình thức" (Excel rendering, code thuần, deterministic)**. Lợi ích:
- JSON diff được sạch (git diff đọc được), Excel diff thì không — nên mọi so sánh version/impact-analysis chạy trên JSON, Excel chỉ là "view" xuất ra cuối cùng.
- Đổi template công ty = đổi cách render, KHÔNG cần sinh lại nội dung bằng LLM → rẻ, nhanh, không rủi ro agent "bịa" lại nội dung khi chỉ đổi hình thức.
- QA/review có thể review JSON (ngắn, có cấu trúc) trước khi tốn effort render/layout.

## 1. Mục tiêu & phạm vi (không đổi so với v0.1)

1. Phân tích requirements thô của khách hàng → sinh **BRD** (業務要件定義書) và **SRS** (システム要件定義書).
2. BRD/SRS → **Basic Design** (基本設計書) + test tương ứng (結合テスト/システムテスト仕様書).
3. Basic Design → **Detail Design** (詳細設計書) + **Unit Test Design** (単体テスト仕様書).
4. Theo mô hình **V-Waterfall IPA**, output **Excel**, template SIer Nhật chuẩn (default) hoặc theo công ty (override).
5. Quản trị thay đổi theo **Decision Record**, có traceability, biết tài liệu nào bị ảnh hưởng và cập nhật.
6. Mở rộng được sang development/unit test thực thi.

## 2. Ánh xạ mô hình chữ V (không đổi)

```
業務要件定義 (BRD)          ───────────────▶ 受入テスト (UAT)
システム要件定義 (SRS)      ───────────────▶ システムテスト (ST)
基本設計 (Basic Design)     ───────────────▶ 結合テスト (IT)
詳細設計 (Detail Design)    ───────────────▶ 単体テスト (UT)
            ╲____________ 開発 (Development) ______╱
```

## 3. Kiến trúc tổng quan (cập nhật: thêm layer Content/Render tách biệt + Dashboard)

```
┌─────────────────────────────────────────────────────────────────┐
│ A. Intake Layer            — chuẩn hoá input khách hàng →       │
│                               RequirementItem có ID              │
├─────────────────────────────────────────────────────────────────┤
│ B. Content Agents (LLM)   — mỗi tầng chữ V = 1 cặp agent        │
│    (doc-writer + test-writer) → sinh JSON artifact có schema    │
├─────────────────────────────────────────────────────────────────┤
│ C. Excel Rendering Engine (deterministic, KHÔNG phải LLM)       │
│    — JSON artifact + TemplateDefinition → file .xlsx            │
│    — tool thuần Python/openpyxl, không gọi model                │
├─────────────────────────────────────────────────────────────────┤
│ D. Traceability & Decision Record Store (git-based YAML/JSON)   │
│    — graph nối Requirement ↔ BRD ↔ SRS ↔ BD ↔ DD ↔ TestCase     │
├─────────────────────────────────────────────────────────────────┤
│ E. Impact Analysis & Change Propagation Agent                    │
├─────────────────────────────────────────────────────────────────┤
│ F. Orchestrator Agent — điều phối pipeline, version, gate        │
├─────────────────────────────────────────────────────────────────┤
│ G. QA/Review Agent — review JSON nội dung trước khi render       │
├─────────────────────────────────────────────────────────────────┤
│ H. Dashboard / Control-Plane UI (web)                           │
│    — upload intake, tạo/duyệt Decision Record, theo dõi         │
│      toàn bộ trạng thái pipeline, xem/download Excel, xem RTM   │
└─────────────────────────────────────────────────────────────────┘
```

Thứ tự dữ liệu chảy trong 1 lượt sinh tài liệu:
`Intake → Content Agent (LLM) → JSON artifact (git commit) → QA review JSON → Excel Rendering Engine → .xlsx (git commit, hoặc object storage) → Dashboard hiển thị cho user`

## 4. Danh sách Agent (cập nhật output = JSON, không phải Excel trực tiếp)

| Agent | Input | Output |
|---|---|---|
| `orchestrator-agent` | Trigger (intake mới / DR mới) | Lệnh dispatch cho phase agent, cập nhật trạng thái pipeline cho Dashboard |
| `requirements-analyst-agent` | Raw intake | `brd.json` + RequirementItem IDs |
| `srs-writer-agent` | `brd.json` | `srs.json` |
| `basic-design-agent` | `srs.json` | `basic_design.json` |
| `basic-test-design-agent` | `srs.json`, `basic_design.json` | `test_it.json`, `test_st.json` |
| `detail-design-agent` | `basic_design.json` | `detail_design.json` |
| `unit-test-design-agent` | `detail_design.json` | `test_ut.json` |
| `traceability-agent` | Mọi JSON artifact | RTM (yaml/json), trace graph |
| `decision-record-agent` | Change request/defect/clarification | `dr.json` (status: proposed) |
| `impact-analysis-agent` | DR đã approve + trace graph | Impact list + regen tasks |
| `template-manager-agent` | doc_type, company_id | Resolved `TemplateDefinition` cho Rendering Engine |
| `qa-reviewer-agent` | JSON artifact vừa sinh | Pass/fail + ghi chú (review nội dung, KHÔNG review layout Excel) |
| *(tool, không phải LLM agent)* `excel-renderer` | JSON artifact + TemplateDefinition | `.xlsx` |
| *(tương lai)* `dev-agent`, `unit-test-codegen-agent` | `detail_design.json`, `test_ut.json` | Source code, test code, kết quả chạy test |

`excel-renderer` cố tình KHÔNG phải là LLM agent — nó là 1 MCP tool/service thuần Python (openpyxl), để việc render luôn deterministic, test được bằng unit test thông thường, và không tốn token mỗi lần đổi hình thức.

## 5. Skills đề xuất (không đổi nhiều, thêm 1 skill cho JSON schema)

- `skill: brd-from-intake`, `srs-from-brd`, `basic-design-from-srs`, `detail-design-from-basic`, `test-design-v-mapping` — như v0.1, nhưng output format bắt buộc là JSON đúng schema (xem mục 6).
- `skill: json-schema-contracts` *(mới)* — định nghĩa & validate schema cho từng loại artifact (brd/srs/basic_design/detail_design/test_*), dùng chung bởi content agent (lúc sinh) và QA agent (lúc review) và excel-renderer (lúc render).
- `skill: excel-template-binding` — map field JSON → cell/sheet theo template (default hoặc company), dùng bởi `excel-renderer`.
- `skill: decision-record-management`, `impact-analysis-traceability`, `qa-checklist-ipa` — như v0.1.
- `skill: template-calibration-from-sample` *(mới, mục 13.1)* — khi có 1 file Excel mẫu thật, đọc cấu trúc (sheet, header, vùng ô) bằng openpyxl, gợi ý mapping field JSON ↔ cell bằng LLM, xuất `TemplateDefinition` nháp để human xác nhận trên Dashboard trước khi dùng thật.
- `skill: json-diff-classification` *(mới, mục 13.3)* — phân loại mỗi thay đổi field JSON thành `added|removed|structural_change|reworded_only`, dùng similarity ratio thuần thuật toán (không gọi LLM) cho field text dài.

## 6. Mô hình dữ liệu cốt lõi (cập nhật: Document tách content/json và render/xlsx)

```yaml
RequirementItem:
  id: REQ-0001
  source: intake-ref
  text: ...
  category: business|functional|non-functional
  parent_id: null|REQ-xxxx

Document:
  id: DOC-BRD-0001
  type: BRD|SRS|BASIC_DESIGN|DETAIL_DESIGN|TEST_IT|TEST_ST|TEST_UT|TEST_UAT
  version: v3
  status: draft|in_review|approved|superseded
  content_ref: json/brd/DOC-BRD-0001.v3.json   # nguồn sự thật
  render_ref: xlsx/brd/DOC-BRD-0001.v3.xlsx     # sinh ra từ content_ref, có thể tái tạo lại bất cứ lúc nào
  template_id: default/BRD_v1 | company/acme/BRD_v2
  project_id: PRJ-001

TraceLink:
  from_id: REQ-0001
  to_id: DOC-SRS-0001#item.3
  link_type: realizes|verifies|derives_from|tests

DecisionRecord:
  id: DR-0007
  date: 2026-10-31
  trigger: requirement_change|design_change|defect|clarification
  description: ...
  decision: ...
  rationale: ...
  impacted_items: [REQ-0001, DOC-SRS-0001#item.3]
  affected_documents: [DOC-SRS-0001, DOC-BASIC-0003]
  status: proposed|approved|propagated|closed
  approver: ...

TemplateDefinition:
  company_id: default|acme|...
  doc_type: BRD
  source: baseline|calibrated_from_sample    # mục 13.1
  sheet_map: {...}
  cell_bindings: {...}      # field JSON → cell/range
  validation_rules: [...]

ProjectConfig:                               # mục 13.4
  project_id: PRJ-001
  propagation_mode: manual_gate              # manual_gate (default) | auto_low_risk
  dashboard_roles: [approver, viewer, admin] # mục 13.2
```

Nguyên tắc bắt buộc giữ từ v0.1: **mọi "item" trong JSON (mỗi dòng requirement, mỗi hàng test case...) phải có ID ổn định** (`#item.N` hoặc key riêng) không đổi qua version — đây là mấu chốt để trace graph hoạt động đúng khi content thay đổi.

## 7. Luồng quản trị thay đổi (Decision Record) — không đổi logic, cập nhật bước render

```
1. Trigger thay đổi (KH bổ sung yêu cầu / defect / clarify)
2. decision-record-agent soạn DR (status=proposed), gắn impacted_items
3. Human sign-off qua DASHBOARD (approve/reject/request-more-info)  ← GATE BẮT BUỘC
4. impact-analysis-agent truy trace graph → downstream/upstream docs bị ảnh hưởng
5. orchestrator-agent dispatch lại content agent liên quan
   → chỉ regenerate JSON section bị ảnh hưởng (không rebuild toàn JSON)
6. JSON mới → version bump, git diff JSON (đọc được trực tiếp) → excel-renderer render lại .xlsx
7. qa-reviewer-agent review JSON vừa cập nhật
8. DR.status = propagated → closed; RTM & trace graph cập nhật; Dashboard hiển thị trạng thái mới
```

## 8. Template Excel: baseline mặc định (tổng hợp từ thực tiễn ngành SI Nhật, chưa có file mẫu thật)

⚠️ IPA "共通フレーム" (Common Framework 2013) là khung **quy trình/vai trò** cho toàn bộ lifecycle, **không phải file Excel mẫu** — không có 1 template Excel chính thức duy nhất do IPA phát hành cho từng loại tài liệu. Baseline dưới đây tổng hợp từ cấu trúc phổ biến trong ngành SI Nhật (sẽ hiệu chỉnh khi có file mẫu thật của công ty/khách hàng — xem mục 0, quyết định #5):

**要件定義書 (BRD/SRS)** — 5 khối phổ biến:
`背景・目的` → `業務要件`(業務フロー, 規模, 管理指標, **システム化の範囲**) → `機能要件` → `非機能要件`(性能, 信頼性, セキュリティ, 移行, 運用保守) → `制約事項`

**基本設計書 (Basic Design)**:
`システム構成図`(ハード/ソフト/ネットワーク) → `業務フロー図` → `機能一覧表` → `画面一覧表・画面遷移図` → `CRUD図` → `ER図` → `テーブル定義書` → `I/F設計` → `結合テスト観点（概要）`

**詳細設計書 (Detail Design)**:
`システム概要` → `機能仕様`(モジュール/クラス単位) → `処理フロー`(入力→バリデーション→重複チェック→登録→通知→出力→エラー処理 kiểu tuần tự có số thứ tự) → `画面設計（詳細）` → `データベース設計（詳細）` → `インターフェース設計（詳細）`

**テスト仕様書 (IT/ST/UT/UAT)** — cột chuẩn tối thiểu:
`テストケースID` (nối trace về requirement/design item) → `前提条件` → `入力値` → `操作手順` → `期待結果` → `判定(OK/NG)` → `実施日/実施者` → `不具合ID(nếu NG, nối sang DecisionRecord)`

Cấu trúc trên là **baseline khởi điểm cho `templates/default/`**, map trực tiếp vào JSON schema ở mục 6. Khi có file Excel thật từ khách hàng/công ty, chỉ cần cập nhật `TemplateDefinition.sheet_map`/`cell_bindings` — không cần đổi JSON schema hay agent, đúng tinh thần tách content/render ở mục 0.

Nguồn tham khảo: [IPA 共通フレーム2013](https://www.ipa.go.jp/publish/secbooks20130304.html) (khung quy trình), [IPA PDF tổng quan](https://www.ipa.go.jp/archive/files/000004771.pdf), các bài tổng hợp cấu trúc thực tiễn: [基本設計書テンプレート](https://crexgroup.com/ja/development/project/basic-design-document-template/), [imitsu.jp blueprint template](https://imitsu.jp/matome/web-system/blueprint-template), [要件定義書 構成](https://www.issoh.co.jp/tech/details/12849/), [詳細設計書サンプル](https://ones.com/ja/blog/detailed-design-document-samples/).

## 9. Mô hình Project: 1-active, framework đa năng (chốt theo quyết định #3)

- **1 project = 1 bộ requirement/khách hàng** (hoặc 1 engagement), cách ly hoàn toàn: `projects/<project_id>/` chứa toàn bộ intake/JSON/Excel/DR/trace riêng.
- Tại 1 thời điểm, orchestrator chỉ **active trên 1 project context** (không chạy song song nhiều project để tránh phức tạp về state/approval-gate) — nhưng đổi project chỉ là đổi `project_id` context, không redeploy, không đổi code → đúng nghĩa "framework đa năng" tái sử dụng cho nhiều khách hàng.
- `company_id` (chọn template) và `project_id` (cách ly dữ liệu) là 2 khái niệm khác nhau nhưng liên kết: 1 project thuộc 1 company/client, dùng template của company đó (hoặc default).
- Dashboard cho phép chọn/chuyển project đang active (xem mục 10).

## 10. Dashboard / Control-Plane UI (mới — chốt theo quyết định #4)

Không dùng CLI-only cho MVP. Cần 1 web app tối thiểu gồm:

**Backend API** (Python, FastAPI — nhất quán ngôn ngữ với orchestrator):
- Project management: tạo/chọn/chuyển project active
- Intake: upload file (docx/pdf/email...) → trigger `requirements-analyst-agent`
- Pipeline control: xem trạng thái từng agent/stage (queued/running/done/failed), trigger lại 1 stage, xem log
- Decision Record: tạo/xem danh sách/approve/reject (ghi quyết định vào git), xem impact list trước khi approve
- Document: xem version history, download `.xlsx`, xem diff JSON giữa 2 version (hiển thị dạng bảng thay vì raw diff)
- Traceability: xem RTM dạng bảng/matrix, click 1 requirement → xem toàn bộ chain xuyên các tầng

**Frontend**: 1 SPA (đề xuất React/Next.js — phổ biến, dễ tuyển dụng/maintain) với các view chính:
1. Project overview (trạng thái tổng theo mô hình chữ V, dạng pipeline/kanban theo tầng)
2. Intake & Upload
3. Document viewer (list theo loại, version, status, nút download Excel)
4. Decision Record inbox (list cần approve, detail view có impact preview trước khi approve)
5. Traceability Matrix viewer
6. Activity/audit log (ai làm gì, agent nào chạy khi nào — map trực tiếp từ git commit history của trace/DR store)

Backend đọc/viết trực tiếp vào git-backed store (mục 0, quyết định #2) — mọi hành động qua Dashboard (approve DR, trigger stage...) đều tạo ra 1 commit, nên audit log = `git log`, không cần xây hệ thống logging riêng ở giai đoạn đầu.

## 11. Đề xuất cấu trúc thư mục (cập nhật)

```
MasterBA/
  CLAUDE.md
  docs/
    concept-design.md
  agents/                          # định nghĩa subagent (.md), bao gồm cả excel-renderer là MCP tool riêng
  skills/                          # quy trình + json-schema-contracts
  schemas/                         # JSON Schema cho từng loại artifact (brd, srs, basic_design, ...)
  mcp-configs/
    excel-renderer.json            # tool deterministic, không phải LLM agent
    traceability-store.json
  templates/
    default/                       # baseline mục 8
    companies/<company_id>/
  backend/                         # FastAPI control-plane (mục 10)
  frontend/                        # React/Next.js dashboard (mục 10)
  projects/<project_id>/
    intake/
    json/
      brd/ srs/ basic_design/ detail_design/ test_it/ test_st/ test_ut/ test_uat/
    xlsx/                          # sinh ra từ json/, có thể xoá và render lại bất cứ lúc nào
    decision-records/
    traceability/                 # RTM export + trace graph (yaml/json)
  src/                             # orchestrator, trace engine, impact analysis
```

## 12. Mở rộng sang Development / Unit Test (không đổi so với v0.1)

- `dev-agent`: `detail_design.json` → source code (gắn `implements` link vào trace graph).
- `unit-test-codegen-agent`: `test_ut.json` → test code thực thi (pytest/JUnit...), chạy test → ghi kết quả pass/fail ngược lại vào `test_ut.json` → re-render Excel để người không kỹ thuật vẫn đọc được kết quả.
- Không đổi kiến trúc nền — chỉ thêm agent/skill mới theo đúng pattern content-agent → JSON → (render nếu cần) đã có.

## 13. Giải quyết 4 điểm mở (chốt 2026-10-31)

### 13.1 Template thật chưa có → biến "thiếu file" thành 1 bước onboarding có quy trình, không phải blocker

Không chờ có file mẫu mới code tiếp. Thay vào đó định nghĩa **quy trình calibration** như 1 phần chính thức của hệ thống (không phải việc làm tay 1 lần):

1. Mặc định mọi project mới dùng `templates/default/` (baseline mục 8).
2. Khi công ty/khách hàng cung cấp 1 file Excel mẫu thật: upload qua Dashboard → `skill: template-calibration-from-sample` đọc cấu trúc bằng openpyxl (sheet, header, vùng ô) + dùng LLM gợi ý mapping field JSON ↔ cell → xuất `TemplateDefinition` **nháp** (`source: calibrated_from_sample`).
3. Human (BA/PM) xác nhận/sửa mapping trên Dashboard trước khi set làm template chính thức cho company đó — `excel-renderer` không bao giờ dùng template chưa được xác nhận.
4. Vì content (JSON) và render (Excel) đã tách nhau (mục 0, quyết định #1), việc có file mẫu thật sau này **không yêu cầu sinh lại nội dung** — chỉ re-render.

→ Hệ quả: không cần chặn code JSON schema/agent để "chờ có file mẫu" — 2 việc độc lập.

### 13.2 Auth cho Dashboard → 3 role tối giản, không SSO ngay từ đầu

MVP dùng auth đơn giản (local user list, YAML/DB nhỏ), 3 role:

- `admin` — tạo/xoá project, quản lý template, quản lý user.
- `approver` (BA/PM) — **duy nhất** được approve/reject Decision Record và bấm "Propagate" sau impact analysis.
- `viewer` (dev, stakeholder khác) — chỉ đọc: xem tài liệu, RTM, trạng thái pipeline, download Excel.

Lý do: approve DR là hành động có tính pháp lý/audit (ai quyết định thay đổi gì, khi nào) — phải có phân quyền rõ ngay từ MVP, nhưng chưa cần SSO/OAuth phức tạp (có thể nâng cấp sau, interface auth tách riêng để không phải sửa logic nghiệp vụ khi đổi provider).

### 13.3 Diff JSON hiển thị → 2 tầng diff, tránh noisy diff mà không cần LLM chấm điểm diff

- **Tầng 1 — structural diff (luôn hiển thị, có giá trị pháp lý cho impact analysis):** so sánh theo ID ổn định của từng item → `added | removed | field_changed`. Dùng diff thuần (vd. `deepdiff`), không qua LLM.
- **Tầng 2 — phân loại thay đổi trên field text dài** (vd. mô tả requirement): dùng `skill: json-diff-classification` — tính similarity ratio thuần thuật toán (`difflib.SequenceMatcher` hoặc tương đương, **không gọi LLM**) để gắn nhãn `reworded_only` (similarity cao, nội dung gần như giữ nguyên) vs `structural_change` (similarity thấp, cần review kỹ).
- Dashboard hiển thị bảng: `ID | field | old | new | loại thay đổi`, cho phép filter ẩn `reworded_only` để BA chỉ tập trung review `structural_change` — giảm nhiễu mà vẫn giữ toàn bộ diff gốc truy xuất được (không mất thông tin, chỉ ẩn theo UI).
- Không dùng LLM để phân loại diff: giữ bước này rẻ, deterministic, test được bằng unit test.

### 13.4 Auto vs manual trigger sau DR approved → mặc định **manual_gate** (an toàn, đúng tinh thần V-model), có thể nâng cấp sau

Quyết định mặc định (`ProjectConfig.propagation_mode = manual_gate`):

1. DR được approve → `impact-analysis-agent` chạy **ngay, tự động** (rẻ: chỉ truy graph, không gọi LLM, không sinh nội dung mới) → impact list hiển thị trên Dashboard.
2. Regeneration thực sự (gọi lại content agent, tốn LLM, thay đổi nội dung tài liệu) **chờ `approver` bấm nút "Propagate"** sau khi xem impact list — không tự động chạy ngay để tránh cascade ngoài ý muốn và tốn chi phí LLM không cần thiết.
3. Để lại chỗ mở rộng: `propagation_mode: auto_low_risk` (tự động propagate nếu impact chỉ chạm các item được đánh dấu rủi ro thấp) — **không implement ở MVP**, chỉ giữ field trong `ProjectConfig` để không phải đổi schema khi cần.

---
*Tài liệu này là concept v0.3. Mục 0 + mục 13 ghi toàn bộ quyết định nền tảng đã chốt. Thứ tự implement cụ thể theo phase, áp dụng spec-driven development, nằm ở [roadmap-phases.md](roadmap-phases.md).*
