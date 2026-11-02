# Spec 01 — Core Data Contracts (schema + trace/DR store)

Status: v0.3 (2026-10-31) — đã implement, Acceptance Criteria pass; v0.2 thêm mục "Quyết định bổ sung khi implement". Nguồn: [concept-design.md](../docs/concept-design.md) mục 6/13.3/14, [roadmap-phases.md](../docs/roadmap-phases.md) Phase 1, [00-constitution.md](00-constitution.md) mục 3/4/5.

## Mục tiêu
Định nghĩa hợp đồng dữ liệu (Pydantic model → JSON Schema) và package `trace_store` (lưu file trong git, truy vấn impact bằng graph) để mọi phase sau chỉ đọc/ghi dữ liệu qua một lớp duy nhất.

## Phi-mục-tiêu
- Không có logic LLM/agent. Không render Excel (Phase 2). Không CLI/orchestrator (Phase 3+).
- Không implement vòng đời DR đầy đủ (approve/propagate — Phase 7); Phase này chỉ lưu/đọc DR và truy vấn impact.
- Không định nghĩa nội dung nghiệp vụ chi tiết từng ô Excel; payload ở mức đủ để trace và diff (chi tiết trường mở rộng ở spec phase tương ứng).

## 1. Nguyên tắc thiết kế
1. **Pydantic v2 là nguồn sự thật**; `schemas/*.schema.json` được **sinh** từ model (`model_json_schema()`), không sửa tay. Test kiểm tra schema đã commit khớp model.
2. **Model bất biến** (`frozen=True`): cập nhật = tạo bản sao mới (`model_copy(update=...)`), không mutate.
3. **Mọi id tuân regex** ở spec 00 mục 3 (validator trong model). ID sai format bị từ chối khi nạp/ghi.
4. **Ngày dùng ISO 8601** (`YYYY-MM-DD`; timestamp `YYYY-MM-DDTHH:MM:SSZ`). `extra="forbid"` cho mọi model (field lạ = lỗi).
5. **Store là file thuần** (JSON) trong `projects/<project_id>/`; mọi ghi qua `trace_store`, mỗi hành động nghiệp vụ = 1 git commit theo format spec 00 mục 5.

## 2. Entity (module `src/masterba/models/`)

Kiểu dùng chung: `ProjectId` (`PRJ-###`), `ReqId` (`REQ-####`), `DocId` (`DOC-<TYPE>-####`), `ItemRef` (`<DocId>#item.<n>`), `DrId` (`DR-####`), `TcId` (`TC-<LEVEL>-####`), `RunId` (`RUN-####`), `DocType` (enum 8 giá trị spec 00), `Level` (enum UT/IT/ST/UAT).

| Entity | Field chính (bắt buộc trừ khi ghi `?`) | Ràng buộc |
|---|---|---|
| `RequirementItem` | `id: ReqId`, `source_ref: str` (trích dẫn/đường dẫn intake), `text: str`, `category: business\|functional\|non_functional`, `parent_id?: ReqId`, `status: active\|removed` | `parent_id` không được trỏ vòng; `removed` không tái dùng ID |
| `Document` | `id: DocId`, `type: DocType`, `version: int ≥1`, `status: draft\|in_review\|approved\|superseded`, `template_id: str`, `content_ref: str`, `render_ref?: str`, `project_id: ProjectId` | `type` khớp phần `<TYPE>` trong `id`; `content_ref` theo spec 00 mục 4 (`<DOC_ID>.v<n>.json`) |
| `TraceLink` | `from_id: ReqId\|DocId\|ItemRef\|TcId`, `to_id: (cùng tập)`, `link_type: realizes\|verifies\|derives_from\|tests\|implements` | `from_id != to_id`; hai đầu phải tồn tại khi `add_trace_link` |
| `DecisionRecord` | `id: DrId`, `date`, `trigger: requirement_change\|design_change\|defect\|clarification`, `description`, `decision?`, `rationale?`, `impacted_items: list[ReqId\|ItemRef]`, `affected_documents: list[DocId]`, `status: proposed\|approved\|propagated\|closed`, `approver?` | `approved` trở đi bắt buộc có `approver` và `decision` |
| `TemplateDefinition` | `company_id`, `doc_type`, `source: baseline\|calibrated_from_sample`, `sheet_map`, `cell_bindings`, `validation_rules` | Cấu trúc chi tiết chốt ở spec 02; Phase 1 chỉ định nghĩa vỏ (field khai báo, nội dung `dict`) |
| `ProjectConfig` | `project_id`, `company_id`, `propagation_mode: manual_gate\|auto_low_risk` (mặc định `manual_gate`), `team_max_rounds: int ≥1` (3), `team_token_budget?: int`, `document_language: ja\|en` (mặc định `ja`, thêm ở v0.3), `dashboard_roles` | Lưu tại `projects/<id>/project.json` |
| `TeamRun` | `run_id: RunId`, `stage: DocType`, `trigger: "initial"\|DrId`, `status: running\|done\|escalated`, `rounds`, `issues_raised`, `issues_resolved`, `escalations: list[str]`, `tokens_used?` | Chỉ định nghĩa model; chạy team ở Phase 4 |

### 2.1 Content payload (mỗi loại tài liệu)

Mọi payload có `items: list[<Item>]`; mỗi item có `item_id: ItemRef` (ổn định, spec 00 mục 3), `status: active|removed`, và field riêng:

| Payload | Item chính |
|---|---|
| `BrdContent` | `requirement_id: ReqId`, `title`, `description`, `scope: in\|out`, `source_ref` |
| `SrsContent` | `requirement_id`, `kind: functional\|non_functional`, `statement`, `acceptance_hint?`, `derives_from: list[ReqId]` |
| `BasicDesignContent` | `kind: function\|screen\|interface\|data_entity`, `name`, `description`, `realizes: list[ItemRef\|ReqId]` |
| `DetailDesignContent` | `kind: module\|processing_step\|db_table\|api`, `name`, `spec`, `refines: list[ItemRef]` |
| `TestSpecContent` | `test_id: TcId`, `level: Level`, `precondition`, `input`, `steps`, `expected`, `verifies: list[ItemRef\|ReqId]` |

Field chi tiết bổ sung theo từng spec phase (03/04/05/06); Phase 1 chốt **khung chung + khoá ổn định**. Thêm field mới = thay đổi spec (bump version), không thêm ngầm trong code.

## 3. Layout lưu trữ trong `projects/<project_id>/`

```
project.json                          # ProjectConfig
requirements/REQ-0001.json            # RequirementItem
json/<doc_type>/<DOC_ID>.v<n>.json    # {document: Document, content: <Payload>}
decision-records/DR-0007.json         # DecisionRecord
traceability/links.json               # list[TraceLink] (sắp theo from_id,to_id,link_type)
runs/RUN-0012/team-summary.json       # TeamRun (Phase 4 ghi)
```

Quy tắc: file ghi **sắp key + indent 2 + newline cuối** (diff git ổn định). `json/` là nguồn sự thật nội dung; `xlsx/` do Phase 2 sinh. Version cũ không bao giờ bị ghi đè hay xoá (spec 00 mục 4).

## 4. API `trace_store` (module `src/masterba/trace_store/`)

Tất cả hàm nhận `ProjectStore` (gốc `projects/` + `project_id`), **không có state toàn cục**.

| Hàm | Hành vi | Commit message (spec 00 mục 5) |
|---|---|---|
| `create_project(config)` | Tạo cây thư mục + `project.json`; lỗi nếu đã tồn tại | `project(PRJ-001): create` |
| `add_requirement(req)` | Ghi `REQ-####.json`; từ chối trùng ID/ID đã `removed` | `req(PRJ-001): add REQ-0001` |
| `add_document(doc, content)` | Validate payload khớp `doc.type`; kiểm item_id duy nhất & đúng tiền tố `doc.id`; ghi file version mới (`version = latest+1` hoặc 1) | `doc(PRJ-001): create DOC-BRD-0001 v1` |
| `get_document(doc_id, version=None)` | Đọc; mặc định version mới nhất | — |
| `add_trace_link(link)` | Kiểm hai đầu tồn tại, không trùng lặp, thêm vào `links.json` | `trace(PRJ-001): link A -> B` |
| `add_decision_record(dr)` / `get_decision_record(id)` | Lưu/đọc DR (chỉ CRUD) | `dr(PRJ-001): create DR-0007` |
| `build_graph()` | `networkx.DiGraph` từ trace links (+ cạnh `Document→Item`) | — |
| `query_impact(node_id, direction="downstream"\|"upstream"\|"both")` | Danh sách node bị ảnh hưởng, kèm `link_type` và độ sâu | — |
| `rtm(req_id)` | Chuỗi trace REQ → Doc item → test case | — |

**Ràng buộc ID Stability (spec 00 mục 3) được enforce trong store:** `add_document` version n+1 phải **giữ nguyên mọi `item_id` đã có ở version n**; item bị bỏ khỏi payload mới → lỗi (phải ghi tường minh `status: removed`). Vi phạm = `IdStabilityError`.

## 5. Structural diff & phân loại (module `src/masterba/diff/`)

- `diff_documents(old, new) -> list[ItemChange]` — so theo `item_id`: `added | removed | field_changed` (dùng `deepdiff`, không gọi LLM).
- `classify_change(old_text, new_text, threshold=0.85) -> reworded_only | structural_change` — dùng `difflib.SequenceMatcher` ratio (thuần thuật toán, quyết định 13.3). Field không phải text dài luôn là `structural_change` nếu đổi.
- `ItemChange`: `item_id`, `field`, `old`, `new`, `change_type`, `classification`.

## Acceptance Criteria
- [x] Mỗi model có test validate: ID sai format bị từ chối; `extra` field bị từ chối; `Document.type` lệch `id` bị từ chối. *(tests/models/)*
- [x] `schemas/*.schema.json` được sinh bằng script; test fail nếu file đã commit lệch model. *(tests/test_schema_export.py)*
- [x] `create_project` + `add_requirement` + `add_document`(2 version) + `add_trace_link` hoạt động trên thư mục tạm; mỗi hành động tạo đúng **1 commit** với message đúng format. *(tests/trace_store/test_store.py)*
- [x] `add_document` version 2 làm rơi một `item_id` của version 1 → `IdStabilityError`; đánh dấu `removed` tường minh thì được chấp nhận.
- [x] `query_impact` trên project giả (REQ → SRS item → Basic item → test case): downstream từ REQ trả đủ 3 node đúng thứ tự; upstream từ test case trả về REQ gốc. *(tests/trace_store/test_graph.py)*
- [x] `rtm(req_id)` trả đúng chuỗi cho ví dụ trên.
- [x] `diff_documents` + `classify_change`: diễn đạt lại (ratio ≥ ngưỡng) → `reworded_only`; đổi giá trị/ý nghĩa → `structural_change`; item thêm/xoá được nhận diện. *(tests/diff/)*
- [x] Ghi file hai lần cùng nội dung → không tạo diff git (key sắp xếp, định dạng cố định). *(`commit_paths` trả `False`, không tạo commit)*
- [x] Coverage ≥ 80% cho `models`, `trace_store`, `diff`; `mypy --strict` và `ruff` sạch. *(2026-10-31: 76 test pass, coverage 98.8%)*

## Rủi ro & rollback
- **ID Stability sai/thiếu ca biên** (item bị tách/gộp) → impact analysis Phase 7 sai. Giảm thiểu: spec 00 mục 3 là luật cứng; ca tách/gộp phải biểu diễn bằng `removed` + item mới có ID mới + `derives_from`, test ca này.
- **Khoá payload quá chặt** làm vướng spec 03-06 → khung chung ổn định, field riêng mở rộng bằng bump spec (không đổi khung); nếu khung sai, sửa spec này trước rồi sinh lại schema.
- **Store file-based chậm khi nhiều tài liệu** → chấp nhận ở MVP (quyết định concept 0 #2); `trace_store` che giấu lớp lưu trữ nên thay bằng DB sau không đổi API.

## Phụ thuộc
- Phụ thuộc: Phase 0 (spec 00: ID scheme, layout, commit format, toolchain).
- Phase phụ thuộc vào đây: 2 (đọc content payload + `TemplateDefinition`), 3-6 (ghi artifact qua `trace_store`), 7 (DR + impact), 8 (API bọc `trace_store`).

## Quyết định bổ sung khi implement (2026-10-31)

1. **Hướng của `TraceLink`**: `from_id` luôn là artifact **upstream**, `to_id` là **downstream**, bất kể `link_type` (REQ → SRS item → Basic item → test case). `downstream` = hậu duệ, `upstream` = tổ tiên. `link_type` chỉ mô tả bản chất quan hệ.
2. **`TcId` được chuẩn hoá về item ref**: `TC-IT-0001` là alias của item test tương ứng; trong graph chỉ tồn tại node `DOC-TEST_*#item.n`. `query_impact` và `rtm` nhận cả hai dạng, kết quả luôn trả item ref.
3. **`query_impact` chỉ đi theo cạnh `trace`**, bỏ qua cạnh chứa `Document → Item` (cạnh này chỉ có trong `build_graph` để tra tài liệu của một item; suy ra từ `doc_id_of(item_ref)`).
4. **`classify_change` có thêm hai chốt chặn ngoài similarity**: text ngắn hơn 20 ký tự luôn là `structural_change`; nếu tập số trong hai chuỗi khác nhau (vd. `100` → `1000`) cũng là `structural_change`, vì sửa một con số gần như không đổi tỉ lệ similarity nhưng đổi hẳn ý nghĩa.
5. **Ràng buộc bổ sung ở `add_document`**: `content_ref` phải đúng `json/<type>/<DOC_ID>.v<n>.json`; `version` phải bằng latest+1; item ref phải bắt đầu bằng `<DOC_ID>#item.`; test case phải đúng `level` của loại tài liệu và `test_id` không trùng trong payload; item đã `removed` không được kích hoạt lại.
6. **API thêm ngoài bảng mục 4**: `open_project`, `get_config`, `get_requirement`, `list_requirements`, `get_trace_links`, `known_nodes`, `latest_documents` (đọc, cần cho Phase 3+).
7. **Chạy script sinh schema**: ban đầu cần `PYTHONPATH=src` vì dự án dùng `package = false`; từ Phase 3 package được cài (xem spec 03 mục 1.6) nên chỉ cần `uv run python -m masterba.schema_export`.
8. **Intake (thêm ở Phase 3)**: `add_intake(store, name, text)` ghi `projects/<id>/intake/<name>` (chỉ `.txt`/`.md`, tên không chứa dấu phân cách đường dẫn, bất biến, xuống dòng chuẩn hoá về `\n`) trong đúng 1 commit `intake(<project_id>): add <name>`; `get_intake` đọc lại. Chi tiết ở spec 03 mục 2. Ngoài ra `trace_store.git.ensure_ready(cwd)` kiểm tra có git work tree và `user.name`/`user.email` trước khi CLI ghi bất cứ thứ gì.
9. **`ProjectConfig.document_language` (thêm sau lần review live của Phase 3)**: `ja` (mặc định, khớp quy trình SIer Nhật) hoặc `en`; quyết định ngôn ngữ của nội dung do agent sinh ra (tiêu đề, mô tả, câu hỏi mở), độc lập với ngôn ngữ của intake. Project cũ thiếu trường này vẫn nạp được nhờ giá trị mặc định. `init-project` nhận `--language`. Xem spec 03 mục 12.
10. **Mô hình của team run (Phase 4)**: thêm `TeamTask` (`id` dạng `T-01`, `title`, `owner`, `status: todo|in_progress|blocked|done`, `depends_on`) và `TeamMessage` (`sender`, `to`, `type: question|feedback|answer|done`, `ref?: ItemRef`, `round ≥ 1`, `body`) trong `masterba.team.models`; `team-summary.json` vẫn là `TeamRun` không đổi. Ngoài ra `runs/<RUN>/mailbox.json` và `.gitignore` của từng run cũng được commit (xem spec 04 mục 2 và 11).
11. **`TestSpecContent.exclusions` (Phase 5)**: `exclusions: list[TestExclusion]` (mặc định rỗng; `TestExclusion = {item_ref: ItemRef, reason: str}`) ghi lại những mục cố ý không có test case kèm lý do. Tài liệu cũ không có trường này vẫn nạp được. Trong tài liệu IT, `item_ref` là mục Basic Design; trong tài liệu ST là mục SRS. Chi tiết ở spec 05 mục 2.2.
12. **Hàm store cho Decision Record (Phase 7)**: `list_decision_records`, `save_decision_record(store, dr, action, extras)` (ghi lại DR đã có + file dẫn xuất, 1 commit `dr(P): <action> <id>`), `get_dr_extra` / `write_dr_extra` (file `DR-####.impact.json`, `DR-####.propagation.json`), `update_requirement` (giữ nguyên id, sửa text/status, 1 commit `req(P): update <id>`). Chi tiết ở spec 07.

## Bổ sung 2026-11-01 (spec 13: sổ câu hỏi cho khách hàng)

13. **Entity `Question`** (module `models/`, đóng băng như các entity khác): `id: QuestionId` (`Q-####`), `origin: agent|qa_blocker`, `stage: DocType`, `run_id: RunId`, `refs: list[str]` (tham chiếu ổn định: `ReqId`, `ItemRef` của tài liệu đã lưu, hoặc dòng intake), `text: str`, `status: open|answered|withdrawn`, `asked_on: date`, và khi `answered`: `answer`, `answered_by`, `answered_on`, `dr_id`, `source?`. Ràng buộc: các field `answer`, `answered_by`, `answered_on`, `dr_id` được đặt cùng nhau khi và chỉ khi `status = answered`; `source` chỉ có khi `answered`.
14. **Layout**: `questions/Q-0007.json` (một `Question`), bên cạnh `decision-records/`.
15. **Hàm store**: `add_question`, `get_question`, `list_questions`, `save_question(store, question, action)` (ghi lại câu hỏi đã có, 1 commit `question(P): <action> <id>`). Quy tắc nghiệp vụ (gộp trùng, trả lời thành DR, dữ kiện xác nhận) nằm ngoài `trace_store`, trong gói `questions/` (spec 13).

## Bổ sung 2026-11-02 (spec 12: kho tri thức cục bộ)

16. **Kiểu id mới** (`models/ids.py`): `SourceId` (`^KB-\d{4}$`, ví dụ `KB-0003`) và `ChunkRef` (`^KB-\d{4}#chunk\.[1-9]\d*$`, tức Source_Id theo sau là `#chunk.<n>`, ví dụ `KB-0001#chunk.3`). Số `KB-####` do code gán (lớn nhất từng ghi trong manifest, kể cả nguồn đã `removed`, cộng 1) và không bao giờ tái sử dụng (spec 00 mục "Sửa đổi" 2026-11-02). `NODE_ID_PATTERN` nhận thêm `KB-####` (Knowledge_Node).
17. **Entity mới** (module `models/knowledge.py`, đóng băng, thêm vào `schema_export.SCHEMA_MODELS` và có test lệch schema):
    - `KbSource`: `id: SourceId`, `file_name: str` (1 đến 255 ký tự, tên lúc tải lên, chỉ để hiển thị), `suffix: .md|.txt|.xlsx|.docx|.pdf`, `sha256` (64 ký tự hex thường), `added_by: str`, `added_at: datetime` (UTC, dạng `2026-11-02T09:14:05Z`), `removed: bool = False`, `removed_at?: datetime`.
    - `KbManifest`: `format: 1`, `sources: list[KbSource]` (sắp tăng theo id, id không trùng).
    - `KbCitation`: `chunk_ref: str`, `quote?: str`. `chunk_ref` là chuỗi thường trong model; dạng `ChunkRef` do citation gate kiểm (spec 12 mục 9).
    - `Passage`, `SourceIndexState`, `ReindexRecord`: dữ liệu của chỉ mục, nằm trong `knowledge/index/` (gitignore), không commit.
    - Trạng thái `indexed`/`failed`/`missing`/`stale` của một nguồn **không** nằm trong manifest; manifest chỉ giữ các field của `KbSource`.
18. **Field thêm vào model có sẵn** (đều rỗng hoặc `false` theo mặc định, nên JSON đã lưu vẫn nạp được): `PayloadItem.kb_citations: list[KbCitation]` và `kb_citations` trên sáu model draft item, `QaIssue.chunk_refs`, `Check.requires_reference`, `RunCheckpoint.kb_seen_refs`, giá trị mới `DrTrigger.KNOWLEDGE_CHANGE = "knowledge_change"`.
19. **Layout** trong `projects/<project_id>/` (spec 00 mục "Sửa đổi" 2026-11-02):
    ```
    knowledge/manifest.json               # KbManifest; commit
    knowledge/sources/KB-0001.md          # bản sao file nguồn, tên theo Source_Id; gitignore
    knowledge/index/                      # chỉ mục (CURRENT + gen-####/); gitignore, dựng lại được
    knowledge/.lock                       # gitignore
    traceability/knowledge-nodes.json     # list[SourceId] của các Knowledge_Node, sắp tăng; commit
    ```
20. **Knowledge_Node và trace link**: `known_nodes()` trả thêm `{source_id: "knowledge"}` cho mỗi Knowledge_Node đã ghi, tức node có kind `knowledge`. Liên kết từ nguồn tới item trích dẫn nó là `TraceLink(from_id=KB-####, to_id=<ItemRef>, link_type=derives_from)`, đúng hướng upstream → downstream của quyết định 1. Hàm `trace_store` mới hoặc đổi:

    | Hàm | Hành vi |
    |---|---|
    | `add_document(store, doc, content, *, links: Sequence[TraceLink] = (), knowledge_nodes: Sequence[str] = ())` | Như cũ; khi có `links`/`knowledge_nodes` thì ghi thêm `knowledge-nodes.json` (hợp với danh sách cũ) và `links.json` (bỏ link đã có) trong **cùng commit** `doc(P): create DOC-... v<n>`. Caller cũ không truyền gì và không đổi hành vi. |
    | `knowledge_nodes(store) -> list[str]` | Đọc `traceability/knowledge-nodes.json`. |

    `query_impact(store, "KB-0003")` đi theo các cạnh `derives_from`; Source_Id chưa có Knowledge_Node → `NotFoundError`.
21. **Hàm public của KB_Store** (gói `src/masterba/knowledge/`, không thuộc `trace_store`; mọi hàm nhận `ProjectStore`, không có state toàn cục; mỗi thao tác ghi giữ khoá `knowledge/.lock` và chỉ commit `knowledge/manifest.json`):

    | Hàm (module) | Hành vi | Commit message |
    |---|---|---|
    | `read_manifest(store: ProjectStore) -> KbManifest` (`store.py`) | Đọc manifest; file chưa có → manifest rỗng | — |
    | `add_sources(store: ProjectStore, files: Sequence[IncomingFile], added_by: str, *, now: Clock = utc_now) -> AddReport` (`store.py`) | Kiểm file, bỏ qua file trùng sha256 với nguồn đang active, gán `KB-####` mới, chép vào `sources/`, cập nhật chỉ mục | `kb(P): add KB-0003, KB-0004` |
    | `replace_source(store: ProjectStore, source_id: str, file: IncomingFile, added_by: str, *, now: Clock = utc_now) -> ReplaceReport` (`store.py`) | Thay nội dung, giữ nguyên Source_Id | `kb(P): replace KB-0003` |
    | `remove_source(store: ProjectStore, source_id: str) -> KbSource` (`store.py`) | Đánh dấu `removed=true`, `removed_at`; xoá file nguồn sau khi commit; số id không tái sử dụng | `kb(P): remove KB-0003` |
    | `list_sources(store: ProjectStore) -> list[SourceView]` (`store.py`) | Các nguồn active, sắp tăng theo id, kèm trạng thái | — |
    | `reindex(store: ProjectStore, *, embedder_factory: EmbedderFactory = default_factory) -> BuildOutcome` (`indexer.py`) | Dựng lại toàn bộ chỉ mục từ `sources/`; không đổi manifest | — (không commit) |
    | `replace_with_proposal(store, source_id, file, added_by) -> tuple[ReplaceReport, DecisionRecord \| None]` (`proposal.py`) | Như `replace_source`; nếu nguồn đang được trích dẫn thì trước đó tạo một DR `proposed` (trigger `knowledge_change`) qua `new_dr` | `dr(P): create DR-####` (khi có trích dẫn), rồi `kb(P): replace KB-0003` |
    | `remove_with_proposal(store, source_id) -> tuple[KbSource, DecisionRecord \| None]` (`proposal.py`) | Như `remove_source`, cùng quy tắc DR; Knowledge_Node và link của nguồn vẫn giữ lại | `dr(P): create DR-####` (khi có trích dẫn), rồi `kb(P): remove KB-0003` |

    Id không có trong manifest hoặc đã `removed` → `UnknownSourceError` (lớp con của `KbError`) trước mọi thay đổi. `proposal.py` chỉ được `cli.py` và API import, không được `pipeline/` import (giống `questions/answer.py`). Chi tiết hành vi ở spec 12.
