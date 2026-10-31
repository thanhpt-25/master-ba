# MasterBA — Roadmap theo Phase (Spec-Driven Development)

Status: DRAFT v0.1 (2026-10-31). Đi cùng [concept-design.md](concept-design.md) (v0.3 — kiến trúc/what); tài liệu này trả lời **implement theo thứ tự nào, mỗi phase làm gì, khi nào coi là xong**.

## 0. Quy trình SDD áp dụng cho MỌI phase (không lặp lại ở từng phase)

Mỗi phase bên dưới đi qua đúng 5 bước, theo thứ tự, không bỏ bước:

1. **Spec** (`specs/NN-<ten-phase>.md`) — viết TRƯỚC khi code 1 dòng nào. Nội dung bắt buộc:
   - *Mục tiêu* (1 câu) + *Phi-mục-tiêu* (non-goals, để tránh lan phạm vi)
   - *Input/Output contract* (schema, API, file format cụ thể)
   - *Acceptance Criteria* — danh sách kiểm được (test được), không mơ hồ
   - *Rủi ro & điểm cần rollback nếu sai hướng*
   - *Phụ thuộc vào phase nào, phase nào phụ thuộc vào mình*
2. **Plan** — chọn công cụ/thư viện cụ thể, thiết kế module/function signature, KHÔNG viết logic chi tiết.
3. **Tasks** — checklist nhỏ, mỗi task làm xong trong ≤ 1 buổi, có thể giao riêng cho 1 agent/dev.
4. **Implement** — code theo tasks, không thêm gì ngoài spec (đúng nguyên tắc YAGNI).
5. **Validate** — chạy Acceptance Criteria của bước 1; nếu fail → quay lại Spec (không patch lụi cho qua). Phase chỉ "đóng" khi Acceptance Criteria pass.

Mọi spec lưu trong `specs/`, đánh số theo thứ tự phase (`00-`, `01-`, ...), là nguồn sự thật để đối chiếu — nếu code lệch spec, sửa 1 trong 2 cho khớp lại, không để lệch âm thầm.

## 1. Chiến lược trình tự: Walking Skeleton trước, mở rộng bề ngang sau

Không build đủ 6 content agent cùng lúc rồi mới test. Build **1 đường dẫn mỏng chạy end-to-end** (intake → BRD JSON → BRD Excel → trace store) sớm nhất có thể (Phase 3), để xác nhận kiến trúc (tách content/render, ID ổn định, git-store) đúng — rồi mới lặp lại pattern đó để mở rộng ra các tầng còn lại. Lý do: rẻ hơn nhiều nếu phát hiện sai kiến trúc ở Phase 3 (1 agent) so với phát hiện sau khi đã xây cả 6 agent.

## 2. Sơ đồ phụ thuộc giữa các phase

```
Phase 0 (Foundations)
   │
   ▼
Phase 1 (Data Contracts: schema + trace/DR store)
   │
   ▼
Phase 2 (Excel Rendering Engine, deterministic)
   │
   ▼
Phase 3 (Walking skeleton: requirements-analyst-agent, BRD only) ◀── mốc xác nhận kiến trúc
   │
   ▼
Phase 4 (SRS + QA-reviewer-agent dùng chung cho các phase sau)
   │
   ▼
Phase 5 (Basic Design + Test IT/ST)
   │
   ▼
Phase 6 (Detail Design + Test UT)              ◀── mốc: sinh đủ tài liệu V-model (yêu cầu gốc #1-3)
   │
   ▼
Phase 7 (Decision Record + Impact Analysis + Propagation)   ◀── mốc: quản trị thay đổi (yêu cầu gốc #5)
   │
   ▼
Phase 8 (Dashboard/UI)                          ◀── mốc: dùng được qua browser, không cần CLI

Phase 9 (Template calibration từ file mẫu thật) — chạy PARALLEL, bắt đầu bất cứ lúc nào có file mẫu (không chờ thứ tự trên)
Phase 10 (Dev/Unit-test codegen extension) — chỉ viết SPEC để xác nhận kiến trúc mở rộng được (yêu cầu gốc #6), KHÔNG code — backlog
```

## 3. Chi tiết từng phase

### Phase 0 — Foundations & Constitution
- **Spec**: `specs/00-constitution.md` — quy ước coding (Python version, style), cấu trúc thư mục (đã có ở concept-design.md mục 11, copy làm chuẩn), quy ước ID (`REQ-####`, `DOC-<TYPE>-####`, `DR-####`), luật "ID phải ổn định qua version" (concept-design.md mục 6), quy ước commit message cho trace store.
- **Plan**: scaffold repo theo mục 11 concept-design.md; chọn toolchain: `pydantic` (schema), `pytest`, `networkx` (trace graph), `deepdiff` (structural diff), `openpyxl` (render), `FastAPI` + `React/Next.js` (phase 8).
- **Tasks**: tạo thư mục rỗng theo cấu trúc; `pyproject.toml`/`requirements.txt`; CI tối thiểu (lint + pytest, dù chưa có test).
- **Acceptance Criteria**: `pytest` chạy được (0 test, không lỗi); cấu trúc thư mục khớp concept-design.md mục 11; `specs/00-constitution.md` được review/merge.

### Phase 1 — Core Data Contracts (JSON Schema + Trace/DR store)
- **Spec**: `specs/01-data-contracts.md` — định nghĩa đầy đủ `RequirementItem`, `Document`, `TraceLink`, `DecisionRecord`, `TemplateDefinition`, `ProjectConfig` (concept-design.md mục 6) + payload riêng từng loại tài liệu (BrdContent, SrsContent, BasicDesignContent, DetailDesignContent, TestSpecContent) với item-ID ổn định.
- **Plan**: dùng Pydantic models làm nguồn sự thật, export ra `schemas/*.schema.json`; viết package `trace_store` (CRUD + git commit wrapper + query impact qua networkx).
- **Tasks**: Pydantic models cho 6 entity + 5 content payload; `trace_store.create_project()/add_document()/add_trace_link()/query_impact()`; tool diff structural (`deepdiff`) + `skill: json-diff-classification` (difflib ratio, không LLM).
- **Acceptance Criteria**: unit test cho `trace_store` (tạo project giả, 2 document giả, 1 trace link, query impact ra đúng); diff tool có test case phân biệt được `reworded_only` vs `structural_change`.

### Phase 2 — Deterministic Excel Rendering Engine
- **Spec**: `specs/02-excel-rendering.md` — hợp đồng JSON content + `TemplateDefinition` → file `.xlsx`; chốt cấu trúc 8 template default (BRD/SRS/BasicDesign/DetailDesign/Test IT/ST/UT/UAT) dựa trên baseline concept-design.md mục 8.
- **Plan**: `excel-renderer` tool thuần Python/openpyxl, cell-binding điều khiển bằng config (không hardcode); `template-manager` là function thuần (resolve company override → default), chưa phải LLM agent ở bước này.
- **Tasks**: tạo 8 file `.xlsx` mẫu trong `templates/default/`; viết `cell_bindings` cho từng loại; viết renderer + golden-file test (JSON fixture → so sánh giá trị cell sau khi render).
- **Acceptance Criteria**: với 1 JSON fixture viết tay cho mỗi loại tài liệu, renderer xuất `.xlsx` đúng giá trị từng cell đã khai báo trong `cell_bindings`.

### Phase 3 — Walking Skeleton: `requirements-analyst-agent` (mốc kiến trúc)
- **Spec**: `specs/03-requirements-analyst-agent.md` — input (intake text/file) → output `brd.json` (đúng schema Phase 1), ràng buộc: mỗi requirement phải trích dẫn được về câu gốc trong intake, phải gán `REQ-####` ổn định.
- **Plan**: implement agent (Claude Agent SDK hoặc Claude Code subagent), tool truy cập hẹp (đọc intake, viết JSON, validate schema); viết orchestrator CLI tối giản (`masterba run brd --project X`, chưa cần Dashboard) nối: intake → agent → validate → `trace_store.add_document` → `excel-renderer`.
- **Tasks**: implement agent; implement CLI orchestrator; chuẩn bị 2-3 intake mẫu thực tế (viết tay, không cần KH thật) làm fixture; review thủ công chất lượng BRD sinh ra.
- **Acceptance Criteria**: `masterba run brd --project demo --input sample_intake.txt` ra `brd.json` hợp lệ schema + `BRD.xlsx` mở được, giá trị cell khớp JSON + trace store có commit git tương ứng. **Đây là mốc xác nhận toàn bộ kiến trúc (content/render tách biệt, ID ổn định, git-store) hoạt động đúng trước khi mở rộng.**

### Phase 4 — SRS + QA-reviewer-agent (dùng chung từ đây về sau)
- **Spec**: `specs/04-srs-and-qa.md` — `srs-writer-agent` (BRD→SRS); `qa-reviewer-agent` **generic, điều khiển bằng schema + checklist config** (không hardcode riêng cho SRS) — vì sẽ tái dùng y nguyên cho Basic/Detail Design ở phase 5-6.
- **Plan/Tasks**: implement 2 agent; mở rộng CLI (`masterba run srs`); checklist QA baseline lấy từ concept-design.md mục 8 (đầy đủ trường, ID hợp lệ, nhất quán thuật ngữ).
- **Acceptance Criteria**: pipeline `brd → srs` chạy xong có QA pass/fail; `qa-reviewer-agent` chứng minh tái dùng được (chạy thử trên cả BRD lẫn SRS mà không sửa code, chỉ đổi config checklist).

### Phase 5 — Basic Design + Test IT/ST
- **Spec**: `specs/05-basic-design.md` — `basic-design-agent`, `basic-test-design-agent`; đặc biệt mô tả cách sinh test-case ID khớp ngược về SRS/requirement ID (đúng nguyên tắc chữ V ở concept-design.md mục 2/7).
- **Tasks**: implement 2 agent, mở rộng CLI, xác nhận `traceability-agent`/`trace_store` tự ghi link `realizes`/`tests` đúng khi mỗi agent chạy xong.
- **Acceptance Criteria**: pipeline đầy đủ `brd→srs→basic_design(+test_it/st)` cho project demo; query RTM từ 1 `REQ-####` ra đúng chain tới test case tương ứng.

### Phase 6 — Detail Design + Test UT (mốc: đủ tài liệu V-model)
- **Spec/Tasks**: lặp đúng pattern Phase 5 cho tầng Detail Design (`detail-design-agent`, `unit-test-design-agent`).
- **Acceptance Criteria**: pipeline đầy đủ `brd→srs→basic→detail(+test ut)` chạy headless cho project demo. **Mốc: thoả yêu cầu gốc #1-3 (sinh đủ BRD/SRS/Basic/Detail Design + test tương ứng).**

### Phase 7 — Decision Record + Impact Analysis + Propagation (mốc: quản trị thay đổi)
- **Spec**: `specs/07-change-management.md` — `decision-record-agent`, `impact-analysis-agent`; luồng `manual_gate` (concept-design.md mục 7/13.4) dưới dạng CLI trước (`masterba dr new/approve/propagate`).
- **Tasks**: implement DR lifecycle; impact-analysis chỉ truy graph (không LLM, nhanh); orchestrator chỉ dispatch lại agent/section bị ảnh hưởng; hiển thị diff (CLI table, dùng tool Phase 1) phân loại structural/reworded.
- **Acceptance Criteria**: giả lập 1 thay đổi requirement trên project demo → tạo DR → approve → impact list đúng → propagate → đúng tài liệu bị regenerate, version bump, lịch sử cũ giữ trong git, diff hiển thị đúng phân loại. **Mốc: thoả yêu cầu gốc #5.**

### Phase 8 — Dashboard / Control-Plane UI
- **Spec**: `specs/08-dashboard.md` — API contract (bọc lại các hàm Python đã xây ở phase 3-7, KHÔNG viết lại logic), các view theo concept-design.md mục 10, 3 role (13.2).
- **Tasks**: FastAPI backend gọi lại `trace_store`/orchestrator functions; frontend React/Next cho 6 view chính; auth local 3 role.
- **Acceptance Criteria**: 1 BA (không cần biết CLI) qua browser: upload intake → xem pipeline chạy qua từng tầng → xem/approve/propagate 1 DR → download Excel → xem RTM — toàn bộ không cần CLI.

### Phase 9 — Template Calibration từ file mẫu thật (chạy song song, không chờ thứ tự)
- **Spec**: `specs/09-template-calibration.md` (theo concept-design.md mục 13.1). Bắt đầu **ngay khi có 1 file Excel mẫu thật**, không phụ thuộc các phase 4-8 đã xong hay chưa (chỉ cần Phase 2 đã có renderer).
- **Acceptance Criteria**: từ 1 file mẫu thật, hệ thống ra `TemplateDefinition` nháp, BA chỉnh/xác nhận được, `excel-renderer` xuất bản ra giống layout file mẫu.

### Phase 10 — Backlog: Dev/Unit-test codegen (chỉ viết spec, không code)
- **Spec**: `specs/10-dev-extension.md` — mô tả `dev-agent`, `unit-test-codegen-agent` (concept-design.md mục 12) đủ chi tiết để chứng minh **không cần đổi kiến trúc nền** (trace graph đã có sẵn link type `implements`/`verifies`). Không có Plan/Tasks/Implement ở giai đoạn này — giữ backlog cho đến khi có nhu cầu thật.

## 4. Độ lớn tương đối & rủi ro chính (không ước lượng thời gian tuyệt đối — chưa có dữ liệu team size/velocity)

| Phase | Độ lớn tương đối | Rủi ro chính nếu làm sai |
|---|---|---|
| 0 | S | Bỏ qua → cấu trúc lệch dần, khó review spec sau |
| 1 | M | Sai ID-stability rule → impact analysis sai ở Phase 7, phải làm lại nhiều |
| 2 | M | Template baseline sai nhiều so với thực tế → tốn công sửa lại khi có file mẫu thật (Phase 9), nhưng KHÔNG ảnh hưởng content agent (đã tách lớp) |
| 3 | M | **Phase rủi ro kiến trúc cao nhất** — nếu sai ở đây, phát hiện sớm còn rẻ để sửa |
| 4 | S (lặp lại pattern Phase 3) | `qa-reviewer-agent` thiết kế không generic → phải viết lại ở mỗi phase sau |
| 5, 6 | M mỗi phase (lặp pattern) | Test-case ID không khớp ngược requirement ID → RTM sai |
| 7 | L | Logic impact analysis sai → propagate nhầm tài liệu, mất lòng tin vào hệ thống |
| 8 | L | Không ảnh hưởng data layer (chỉ là lớp UI bọc ngoài) nếu Phase 1-7 làm đúng |
| 9 | M, song song | — |
| 10 | S (chỉ spec) | — |

## 5. Bước tiếp theo ngay bây giờ

Theo đúng quy trình SDD ở mục 0: bước đầu tiên là viết `specs/00-constitution.md` (Phase 0) — **chưa code gì** cho đến khi spec này được xác nhận.

---
*Tài liệu này là roadmap v0.1, đi cùng concept-design.md v0.3. Cập nhật khi phase nào đổi scope/thứ tự.*
