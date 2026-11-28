# Spec 26 — Workspace: a modern look for the dashboard

Status: approved (2026-11-28). The owner compared three directions (Workspace, Studio, Control room) and chose Workspace.

## Goal

The design ledger of spec 25 fixed colour roles and flows, but the dashboard still read as old-fashioned: every block was a bordered box inside another box, document ids in a typewriter face everywhere, the V drawn as a staircase of cards longer than one screen, flat grey ground and one text weight, and no quick way to jump between projects and pages. This spec gives the dashboard the look of a current SaaS work tool while keeping the spec 25 identity (藍 indigo for everything you can act on, 朱 vermilion only for the seal and approval) and every flow. It changes `frontend/` only: no API, model or storage change, the no-build CSP-safe vanilla JS stack stays, and no new runtime dependency.

## Decisions

### 1. Tokens and type

- Interface face: Inter (variable, Latin subset, self-hosted as `frontend/fonts/inter-latin-wght-normal.woff2`, OFL licence beside it) followed by the Japanese system faces (Hiragino Sans, Noto Sans JP, Yu Gothic UI, Meiryo UI). The CSP stays `default-src 'self'`. Mincho stays only on the printed cover sheet.
- Indigo moves slightly towards blue-violet and gains chroma so a primary button reads as the one action on a screen; dark theme follows. Neutrals keep a slight indigo bias. Ground is lighter so surfaces stand out by a soft shadow, not only a border.
- Radius: 6 / 8 / 10 / 12 px by size. Panels get a 1 px hairline plus a very soft shadow (`--shadow-card`); floating things keep `--shadow-float`.
- Document ids keep the mono face but at the small size in secondary ink, so they read as references, not as the content.

### 2. Shell

- **Project rail** (52 px, left edge): the seal 要 (to Projects), one square per project the user can open (its number, e.g. `001`, with the id as tooltip and accessible name; the current one ringed in indigo) and a `+` to Projects. It is filled after the first paint from `GET /api/projects` and kept for the session; switching projects is one click from any page.
- **Sidebar** (216 px): inside a project it starts with the project switcher (id and company), then the project's sections. 顧客確認事項 shows the open question count. Workspace and 管理 follow as in spec 25.
- **Top bar**: breadcrumb, a search field that opens the command palette, the account menu.
- **Command palette** (`frontend/palette.js`, ⌘K / Ctrl+K, or the search field): one input over a list of projects, the current project's sections, workspace and admin pages (by role), and actions (theme, language, sign out). Matching is by substring on the label and its keywords, case and width insensitive (`filterCommands`, pure, unit tested). Arrow keys move, Enter runs, Escape closes, focus returns to where it was. It is a `modal()` dialog, so the focus trap and `aria-modal` are the existing ones.
- Below 760 px the rail and sidebar give way to the existing top bar and tab strip; the palette stays available.

### 3. Status

`badge()` keeps icon and word (colour is never the only signal). Calm states (done, draft, running, not started) are drawn as coloured icon plus word without a fill; states that ask for attention (in review, waiting, escalated, failed) keep a soft fill; approval keeps the seal ring.

### 4. Overview

Order: header (id, status, project facts as one dotted line), the next step (tinted, one action), the figures as an unboxed strip, a running job, the V, the phases, then project settings (admins, folded). On wide screens recent activity and open customer questions sit in a right column beside all of this; on narrower screens they follow below.

- **The V** (`vDiagram(overview, pid)`) is a compact drawing that fits one screen: eight nodes, three columns wide on a twelve-column grid, design phases stepping down the left arm, test levels stepping up the right arm level with them, each pair joined by a dashed line labelled with the trace it carries (BRD ↔ UAT …), 実装 at the vertex. A node shows its title, a status mark and word, and its document id; a node with a document links to it. The current phase is ringed. Below 760 px it becomes a two-column list of pairs.
- **The phases** list (`phaseList`) holds what the V cards held in spec 25: per design phase its documents with version and status, open questions, the last run, the review gate state, and its one action (review box, waiting hint, run). The run or upload control of the current phase stays only in the next-step panel.

### 5. Other screens

They change through tokens and shared components only (panels, tables, badges, page header, toolbar): lighter table headers, row hover, softer panels. No flow changes.

### 6. Documents as a folder tree (approved 2026-11-28)

The Documents page reads like a file manager: a tree on the left, the selected thing on the right.

- **Tree** (`views/explorer.js`, pure `buildTree(docs, intakes, mode)`): by default one folder per design phase, numbered in V order (01 業務要件定義, 02 システム要件定義, 03 基本設計 with 基本設計書 and the IT and ST specifications, 04 詳細設計 with 詳細設計書 and the UT specification), then 入力資料 with the project's intake files. A segmented switch regroups the documents by kind (設計書 / テスト仕様書); the choice is kept per browser. A document is a file whose children are its versions, newest first. Folders show the number of documents and a warning count for documents in review; files show a status mark and word. A filter field narrows the tree by name or document id.
- **Keyboard and assistive tech**: WAI-ARIA tree pattern (`role="tree"`, `treeitem`, `aria-expanded`, `aria-level`, `aria-selected`, roving tabindex). Up and Down move, Right opens a folder or moves into it, Left closes or moves to the parent, Home and End jump, Enter opens, typing a letter jumps to the next name that starts with it. Open folders and the tree width are kept per browser (`localStorage`, wrapped in try/catch); the width changes by dragging the divider or with the arrow keys on it.
- **Preview pane**: a file shows a Finder-style path, the document name and status, the version picker, 差分 (compare with the previous version, shown in a dialog) and Excel download, then the workbook preview with the sheet tabs along the bottom edge like Excel. When the document's phase is in review, a band above the preview carries the review: 承認 and コメントを付けて差し戻す open in place (decided by the owner: no longer at the end of the page). A version opens that version. A folder shows a details list (name, document id, latest version, status, items); a double click or Enter opens a file. An intake file shows its text with line numbers, because the BRD cites intake lines.
- **URLs**: `#/p/<pid>/documents/<DOC-ID>[/v<n>]`, `#/p/<pid>/documents/folder/<key>` and `#/p/<pid>/documents/intake/<name>`, so a link opens the same file and version.
- Below 760 px the tree takes the screen and a file opens the preview full width with a back control.

API, read only, viewer role: `GET /api/projects/{pid}/intake` lists the intake files (name, size in bytes, line count) and `GET /api/projects/{pid}/intake/{name}` returns one file's text (404 for an unknown or invalid name). `trace_store.list_intakes(store)` returns the stored names in order.

Decision Records are not in the tree (decided by the owner): they keep their own page, section 7, and a document links to the records that touch it.

### 7. Change management page (approved 2026-11-28)

The 変更管理 page uses the same two panes as Documents: a list on the left, the selected record on the right.

- **List**: one row per Decision Record (id, kind, date, status), newest first. Status chips above it filter the list: すべて, 起票 (proposed), 承認済 (approved), 反映済 (propagated), 完了 (closed), 却下 (rejected: closed without an impact analysis, the same rule as 変更管理台帳; the API marks such a record `rejected: true` in the list and in `GET .../drs/{dr_id}`), each with its count; the choice is kept per browser. A filter field narrows by id, kind or description.
- **Preview**: the record's id, kind and status, then the action band of its state above the sheets (decide while proposed, propagate once approved, close once propagated, the live job while propagating). The record prints as four sheets with tabs along the bottom, like a workbook:
  - 変更管理票: the form (管理番号, 変更区分, 起票日, 状態, 変更内容, 対象項目, 影響文書, 判断, 理由, 承認者) with the seal boxes.
  - 影響分析: the documents to revise in V order and the affected items (depth, link), or the preview of named documents while the record is proposed.
  - 反映結果: propagation per document (outcome, version, run) in V order (the order of the impact analysis) and, once propagated, what changed per document.
  - 履歴: the commits that touched the record, oldest first, in plain words.
- **Register**: the page header links 変更管理台帳 (`GET .../registers/changes.xlsx`, spec 27); the Questions page header links QA管理表 (`GET .../registers/questions.xlsx`).
- **Links from documents**: a document's preview names the records whose affected documents include it ("変更管理票 N件"), each linking to `#/p/<pid>/drs/<DR-ID>`.
- URLs: `#/p/<pid>/drs/<DR-ID>`; the list filter is not in the URL. Below 760 px the list takes the screen and a record opens full width with a back control.

API, read only, viewer role: `GET /api/projects/{pid}/drs/{dr_id}/history` returns the commits that touched the record's files (`commit`, `author`, `time`, `subject`), oldest first.

## Acceptance

- `node --test` in `frontend/` and `uv run pytest tests/test_frontend.py` pass; every new string has a Japanese entry.
- Checked in Chromium at 1440 × 900 and 390 × 844, Japanese, light and dark: no console error, no horizontal page scroll; Projects, Overview (all stages done, and a phase in review), Documents.
- Documents: the tree groups by phase and by kind, keyboard navigation follows the tree pattern, a file, a version, a folder and an intake file each open on the right, the review band approves and rejects; `buildTree` is unit tested; the intake endpoints have API tests.
- 変更管理: the status chips filter the list, the four sheets show for a proposed and a propagated record, a document links to its records; the history endpoint has an API test.
- The palette opens with ⌘K and Ctrl+K, filters, runs with Enter, closes with Escape and returns focus.
- The CSP is unchanged: no inline style attribute (CSSOM only), no external resource; the font is served from the app's own origin.
