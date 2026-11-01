# Spec 00 — Constitution

Status: v0.3 (2026-10-31) — v0.2: thêm `projects/<project_id>/runs/` cho Phase Team (concept-design.md mục 14.5). v0.3: thêm `project.json`, `requirements/` và ID `PRJ-###` theo spec 01. Nguồn: [concept-design.md](../docs/concept-design.md) mục 0/6/11, [roadmap-phases.md](../docs/roadmap-phases.md) Phase 0.

## Mục tiêu
Thiết lập quy ước nền tảng (toolchain, cấu trúc repo, ID scheme, git convention) dùng chung cho toàn bộ phase tiếp theo, để không phase nào tự chế lại chuẩn riêng.

## Phi-mục-tiêu
- Không định nghĩa logic nghiệp vụ của bất kỳ agent nào (spec riêng ở Phase 3+).
- Không chọn hạ tầng hosting/deploy — ngoài phạm vi hiện tại.
- Không viết code nghiệp vụ ở phase này — chỉ scaffold + convention.

## 1. Ngôn ngữ & toolchain

| Mục đích | Chọn | Lý do ngắn |
|---|---|---|
| Ngôn ngữ chính | Python ≥ 3.11 | Nhất quán với quyết định concept-design.md mục 0; ecosystem openpyxl/pydantic mạnh |
| Dependency mgmt | `pyproject.toml` (PEP 621) | Chuẩn hiện đại, 1 file duy nhất |
| Format + Lint | `ruff` | Gộp format+lint trong 1 tool, nhanh |
| Type check | `mypy` | Bắt buộc tối thiểu cho `trace_store`, `schemas`, `excel_renderer` (phần lõi) |
| Test | `pytest` + `pytest-cov` | Coverage ≥80% theo rule testing chung đã áp dụng cho user |
| Data model / schema | `pydantic` v2 | Nguồn sự thật duy nhất; export JSON Schema qua `model_json_schema()` — KHÔNG viết JSON Schema tay song song (tránh lệch 2 nguồn) |
| Trace graph | `networkx` | Query impact (ancestors/descendants) có sẵn, không tự viết graph traversal |
| Structural diff | `deepdiff` | Diff theo key/path, phục vụ mục 13.3 concept-design.md |
| Excel I/O | `openpyxl` | Đọc/viết `.xlsx` theo template, không phụ thuộc Excel cài sẵn |
| Backend API (Phase 8) | `FastAPI` | Nhất quán Python, async-ready |
| Frontend (Phase 8) | React + Next.js (TypeScript) | Phổ biến, dễ maintain/tuyển dụng |

## 2. Cấu trúc repo (chuẩn — không tự thêm thư mục ngoài danh sách nếu chưa có trong spec)

```
MasterBA/
  CLAUDE.md
  docs/
  specs/
  agents/
  skills/
  schemas/
  mcp-configs/
  templates/default/
  templates/companies/<company_id>/
  backend/
  frontend/
  projects/<project_id>/
    project.json
    intake/
    requirements/
    json/<doc_type>/
    xlsx/
    decision-records/
    traceability/
    runs/<run_id>/          # team-summary.json, team-tasks.json, mailbox.json, .gitignore commit; transcripts/ gitignore
  src/
  tests/
```

Thư mục mới ngoài danh sách trên phải được thêm vào spec này (hoặc spec của phase liên quan) trước khi tạo trong code — không tự phát sinh khi implement.

## 3. Quy ước ID — áp dụng xuyên suốt, KHÔNG đổi về sau (toàn bộ trace graph phụ thuộc vào đây)

| Entity | Format | Ví dụ | Phạm vi duy nhất |
|---|---|---|---|
| Project | `PRJ-###` | `PRJ-001` | toàn repo |
| RequirementItem | `REQ-####` | `REQ-0001` | trong 1 project |
| Document | `DOC-<TYPE>-####` | `DOC-BRD-0001` | trong 1 project |
| Item trong Document | `<DOC_ID>#item.<n>` | `DOC-SRS-0001#item.12` | trong 1 document |
| DecisionRecord | `DR-####` | `DR-0007` | trong 1 project |
| TestCase | `TC-<LEVEL>-####` | `TC-UT-0045` | trong 1 project |
| TeamRun | `RUN-####` | `RUN-0012` | trong 1 project |
| Team task | `T-##` | `T-03` | trong 1 run |

`<TYPE>` ∈ `{BRD, SRS, BASIC_DESIGN, DETAIL_DESIGN, TEST_IT, TEST_ST, TEST_UT, TEST_UAT}`. `<LEVEL>` ∈ `{UT, IT, ST, UAT}`.

**ID Stability Rule (bắt buộc):** một khi ID đã gán cho 1 requirement/item/test-case, ID đó **không bao giờ đổi** qua các version sau, dù nội dung/vị trí dòng thay đổi. Item bị xoá → đánh dấu `status: removed` trong JSON, KHÔNG tái sử dụng số ID đó cho entity khác. Đây là điều kiện tiên quyết để Phase 7 (impact analysis) đúng — vi phạm luật này ở agent bất kỳ là bug **CRITICAL**, không phải style issue.

## 4. Versioning tài liệu
- Mỗi `Document` có `version` là số nguyên tăng dần (`v1, v2, v3...`), không dùng semver.
- Nội dung JSON đổi (agent sinh mới hoặc propagate từ Decision Record) → version +1; giữ JSON + Excel của version cũ trong git history, không overwrite/xoá.
- Tên file: `<DOC_ID>.v<version>.json` và `<DOC_ID>.v<version>.xlsx`.

## 5. Quy ước Git / commit cho trace & decision-record store
- 1 project = 1 thư mục `projects/<project_id>/` trong git repo chính (không submodule — theo concept-design.md mục 0 quyết định #2).
- Commit message: `<scope>(<project_id>): <action> <entity_id>`. Ví dụ:
  - `doc(PRJ-001): create DOC-BRD-0001 v1`
  - `dr(PRJ-001): approve DR-0007`
  - `doc(PRJ-001): regenerate DOC-SRS-0001 v2 via DR-0007`
- Mỗi hành động nghiệp vụ = đúng 1 commit, không gộp nhiều hành động khác nhau vào 1 commit — để `git log` dùng trực tiếp làm audit log (concept-design.md mục 10).

## 6. Ràng buộc quy trình spec (nhắc lại, chi tiết ở roadmap-phases.md mục 0)
- Từ Phase 1 trở đi: phải có `specs/NN-*.md` được tạo/review trước khi có bất kỳ file code nào của phase đó xuất hiện trong git.
- Phát hiện spec sai/thiếu lúc code → sửa spec trước (commit riêng), rồi mới tiếp tục code — không sửa code để lách qua spec cũ.

## Acceptance Criteria (của chính spec này)
- [x] Repo có đủ các thư mục ở mục 2 (rỗng là được, chỉ cần tồn tại). *(2026-10-31: tạo kèm `.gitkeep`; `projects/<project_id>/*` do `trace_store` tạo lúc runtime ở Phase 1, không scaffold sẵn.)*
- [x] `pyproject.toml` khai báo đúng toolchain mục 1 (ruff, mypy, pytest, pydantic, networkx, deepdiff, openpyxl).
- [x] `pytest` chạy được, kết quả "no tests collected", không lỗi — xác nhận wiring toolchain đúng. *(2026-10-31: `uv run pytest` → "collected 0 items / no tests ran", exit 5 = không có test; `ruff check` pass.)*
- [ ] File này tồn tại và không có code nào ở phase sau mâu thuẫn với nó. *(tiêu chí liên tục — kiểm lại ở mỗi phase.)*

## Sửa đổi

- **2026-10-31 (spec 11 mục 4, 5, 7):**
  - Frontend Phase 8 dùng ES module thuần, không có bước build (quyết định của spec 08), thay cho React + Next.js ghi ở bảng mục 1. Bảng mục 1 giữ nguyên để lưu lịch sử.
  - Bỏ hai thư mục `backend/` và `mcp-configs/` khỏi mục 2. Backend nằm trong `src/masterba/api/`; hiện chưa có cấu hình MCP nào.
  - Thêm ở thư mục gốc: `.github/workflows/` (CI), cùng các file `Dockerfile`, `.dockerignore`, `compose.yaml`, `.env.example`. `work/` (work tree mặc định của Docker Compose) và `.env` được gitignore.

- **2026-11-01 (spec 13):**
  - Thêm ID `Q-####` (Question, sổ câu hỏi cho khách hàng), duy nhất trong 1 project, ví dụ `Q-0007`. Bảng mục 3 giữ nguyên để lưu lịch sử.
  - Thêm thư mục `questions/` vào `projects/<project_id>/` (mục 2), mỗi câu hỏi một file `Q-####.json`.
  - Thêm scope commit `question` (mục 5): `question(PRJ-001): add Q-0007`, `question(PRJ-001): answer Q-0007`, `question(PRJ-001): withdraw Q-0007`.

## Rủi ro & rollback
- ID scheme (mục 3) thiếu trường hợp (vd. cần ID cho "field" chứ không chỉ "item") → sửa spec này trước, bump version (`v0.1`→`v0.2`), rà soát lại `trace_store` ở Phase 1 — không patch ngầm ở Phase 7.
- Đổi toolchain (vd. bỏ `ruff`) → phải sửa spec này trước, không đổi lặt vặt trong CI config mà không cập nhật spec.

## Phụ thuộc
- Không phụ thuộc phase nào (Phase 0 là phase đầu tiên).
- Toàn bộ Phase 1-10 phụ thuộc vào mục 2 (cấu trúc repo) và mục 3 (ID scheme) của spec này.
