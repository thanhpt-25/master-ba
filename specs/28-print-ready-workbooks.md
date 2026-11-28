# Spec 28 — Print-ready workbooks

Status: v0.1 (2026-11-28), implemented. Sources: [02-excel-rendering.md](02-excel-rendering.md), [09-template-calibration.md](09-template-calibration.md), [27-sier-default-templates.md](27-sier-default-templates.md).

## Goal

A downloaded workbook prints like a finished SIer deliverable whatever template produced it: white sheets without gridlines, every table drawn with borders on every row, A4 page setup on every sheet, and no field left blank when the store holds a value for it. The owner found the opposite in `DOC-BRD-0001.v1.xlsx` of a project on the `sample-sier` company template: gridlines on every sheet, an empty cover, an empty revision history, empty 作成日 / 作成者 / 承認者, and a traceability sheet frozen at the moment the document was first rendered.

## Non-goals

- No change to the default layout of spec 27 (sheets, columns, bindings).
- No new payload data (spec 27 part B).
- No PDF export from the server.

## 1. Finishing pass (`rendering/finish.py`, no LLM)

`finish_workbook(wb)` runs on every workbook the system writes: rendered documents (`render_document`), registers (`registers.py`), default shells (`shells.py`) and calibrated shells (`calibration/build.py`). For each worksheet:

- `showGridLines = False` (the sheet prints and shows on white).
- Page setup, only where the template set none (`orientation` empty): A4, landscape, one page wide (`fitToWidth = 1`, `fitToHeight = 0`, `fitToPage`), centred horizontally, footer with file name and `ページ &P / &N`. A template that set its own page setup keeps it.

It is deterministic, so re-rendering unchanged content stays a no-op in git.

## 2. Borders the template did not draw (`engine.py`)

- **Table and list rows.** Each written row copies the style of the template's first data row (unchanged). Where that cell has no border, the engine adds a thin border and top-aligned wrapping, so a table whose sample styled only the header row still prints as a grid.
- **Header cells.** A header-bound cell with no border at all gets a thin border, and so does its label cell to the left when that cell holds text and has no border. A cell with any border (an underline on a cover) is left as designed.

## 3. Calibration fills what the sample shows (`calibration/`)

- **More document-info labels** (`heuristic.DOC_INFO`): 文書名 / ドキュメント名 → `$document.title`; システム名 → `$project.name`; 顧客名 / 会社名 / 顧客 → `$project.company`; 作成日 → `$document.created_on`; 更新日 / 最終更新日 / 改訂日 → `$document.updated_on`; 作成者 / 担当者 → `$document.author`; 承認者 → `$document.approver`; 承認日 → `$document.approved_on`; 機密区分 → `$document.classification`; 発行元 → `$document.publisher`.
- **Info cells on every sheet.** Labels are searched above the table header on a table sheet (unchanged) and in the first 40 rows of a sheet without a table (a cover), skipping a sheet that holds a revision-history list. The value cell is the next cell right of the label (after a merge); it is used only when it is empty or is not itself a label.
- **Revision-history list.** A sheet whose header row (first 15 rows) names at least three revision columns, one of them 版数, is mapped as a list bound to `$revisions` (`MappingDraft.lists`, `ListMap`). Labels: 版数 / 版 / 改版番号 / 改訂番号 → `version_label`; 改版日 / 改訂日 / 日付 / 変更日 → `date`; 改版内容 / 改訂内容 / 変更内容 / 内容 → `summary`; 改版理由 / 改訂理由 / 理由 → `reason`; 改版者 / 改訂者 / 作成者 / 変更者 → `author`; 承認者 → `approver`; 承認日 → `approved_on`; 改版箇所 / 改訂箇所 / 変更箇所 → `changed_sheets`; No. as numbering. The validation gate checks list columns like table columns (fields from `REVISION_FIELDS`). A model refinement that returns no lists keeps the heuristic lists.
- `templates/companies/sample-sier/` is calibrated again from `scripts/make_sier_samples.py`, so its cover, 改版履歴 and info block are filled.

## 4. Download renders the current state (`api/routes_docs.py`)

`GET .../documents/{id}/xlsx` renders the requested stored version on request (same `render_document`, template and `build_context` as `render_to_project`) and returns the bytes without writing or committing anything. Traceability, approvals and the formatting of this spec are therefore current even for a version rendered long ago. The committed file is still written at stage end (git history unchanged) and is served as a fallback only when rendering fails.

## 5. Acceptance criteria

1. Every sheet of every rendered default workbook, register and calibrated workbook has gridlines off and a page setup.
2. A list bound to a start row without borders prints every row with borders.
3. Calibrating the `sample-sier` BRD sample binds the cover values (案件名, 文書番号, 版数, 作成日, 作成者, 承認者), the info block (incl. 作成日, 作成者, 承認者) and the 改版履歴 list; a render fills them.
4. Downloading a document after a downstream stage ran prints the downstream links in トレーサビリティ.
5. Re-rendering unchanged content is byte-identical.
