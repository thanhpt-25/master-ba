# Spec 09 — Template calibration from a real Excel sample

Status: v0.1 (2026-10-31), draft. Sources: [concept-design.md](../docs/concept-design.md) sections 8 and 13.1 (Vietnamese), [roadmap-phases.md](../docs/roadmap-phases.md) Phase 9, [02-excel-rendering.md](02-excel-rendering.md) (bindings, template files, "the renderer never uses an unconfirmed template"), [08-dashboard.md](08-dashboard.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

When a customer or company supplies its own Excel format for a document (a BRD list, a test specification ...), turn that sample into a working template without hand-writing JSON: read the sample's structure, propose which cell holds which field, let a human fix and confirm the proposal, and from then on render documents in that company's layout. Content is never regenerated; only the rendering changes (concept-design section 0, decision 1).

## Non-goals

- No automatic use of an unconfirmed template: the renderer's rule from spec 02 section 6 stands.
- No support in this phase for what the renderer cannot yet do: merged data cells, several tables on one sheet, multi-row headers, formulas, charts, images, named ranges. The profile **reports** these as warnings so a human knows the template will be an approximation.
- No change to JSON content or to the agents.
- No machine learning beyond one optional model call that proposes the mapping; the deterministic mapper is the baseline and the validation gate is code.
- No sample from a real company exists yet in this repository; the tests use synthetic samples that imitate the usual Japanese SIer shape (title rows, a header row below them, different column order and labels). The first real sample is the live review of this phase (section 8).

## 1. Flow

```
sample.xlsx --profile--> WorkbookProfile --heuristic--> MappingDraft --(optional LLM refine)--> MappingDraft
   --validate--> build: TemplateDefinition + cleaned shell --write--> templates/companies/<company>/
   --human: view, fix columns, preview, check--> confirm  (writes <TYPE>.confirmed)
```

Everything up to `confirm` leaves the company folder in the *draft* state: the files exist, but `resolve_template` ignores them until `<TYPE>.confirmed` exists, so a draft can never change a rendered document.

## 2. Profile (`masterba.calibration.profile`, no LLM)

`profile_workbook(path) -> WorkbookProfile` reads the sample with `openpyxl` (never executes macros; `.xlsm`, `.xls` and files over 5 MB are refused) and returns, per sheet: name, used range, merged ranges, column widths, the first 40 rows of cell texts, the **header-row candidate** and the **warnings**.

- Header-row detection: among the first 15 rows, the row with the most recognised field labels (section 3), ties broken by the number of non-empty text cells; at least 3 non-empty cells are required.
- Data rows start on the row after the header row; `sample_rows` shows up to 5 of them (text only) so a human and the model can see the value formats.
- Sheets with fewer than 2 recognised labels are *not* tables; they are kept in the shell as they are (cover page, notes, revision history).
- Document-info cells (above the header row): a cell whose normalised text is a known label (`文書ID`, `文書番号`, `版`, `Ver`, `プロジェクト`, `案件`, `状態` ...) and whose right neighbour exists becomes a **header binding** (`$document.id`, `$document.version`, `$project.id`, `$document.status`).
- Warnings: merged cells inside the data region, a formula in a data row, more than one table-looking block, a header spanning two rows, hidden sheets or columns, protected sheets, images or charts (which are dropped from the shell).

## 3. Heuristic mapper (`masterba.calibration.heuristic`, no LLM)

Labels are normalised (Unicode NFKC, lower case, spaces and punctuation removed) and compared with a synonym table per item field of the document type, Japanese and English:

| Field | Examples of recognised labels |
|---|---|
| `item_id` | 項目ID, アイテムID, item id |
| `requirement_id` | 要件ID, 要件番号, requirement id, req id |
| `title` | タイトル, 要件名, 件名 |
| `description` | 内容, 説明, 要件内容, 概要, description |
| `scope` | 対象範囲, 範囲, スコープ, scope |
| `source_ref` | 出典, 根拠, 原文, source |
| `kind` | 種別, 区分, 種類, kind, type |
| `statement` | 要求記述, 要求内容, 記述, statement |
| `acceptance_hint` | 受入観点, 受入条件, 確認方法, acceptance |
| `derives_from`, `realizes`, `refines`, `verifies` | 派生元・関連要件, 実現対象・対応要件, 詳細化対象, 確認対象・紐付け対象 |
| `name`, `spec` | 名称・機能名・画面名, 仕様・詳細 |
| `test_id`, `level` | テストケースID・テストID, レベル・テストレベル |
| `precondition`, `input`, `steps`, `expected` | 前提条件, 入力値, 操作手順・手順, 期待結果・期待値 |
| numbering column | No, No., 番号, 連番, # |

The longest matching synonym wins; a field is used at most once per sheet; only fields that exist on the item class of the document type are candidates (the same item classes the renderer validates against). Unrecognised columns stay *unmapped* and are reported. For `scope`, `kind` and `level` columns the Japanese display labels of the baseline templates (`対象` / `対象外`) are used as the value map when the sample's data values match them or the sample has no data.

The result is a `MappingDraft`:

```python
class ColumnMap(FrozenModel):  col: str; header: str; field: str | None; value_map: str | None
class TableMap(FrozenModel):   sheet: str; key: str; header_row: int; first_row: int; numbering: str | None
                               columns: list[ColumnMap]; where: dict[str, str] = {}
class HeaderCell(FrozenModel): sheet: str; cell: str; source: str       # a spec 02 header source
class MappingDraft(FrozenModel): doc_type: DocType; tables: list[TableMap]; headers: list[HeaderCell]
                                 unmapped: list[str]; warnings: list[str]
```

## 3.1 Optional model refinement (`masterba.calibration.suggest`)

`--llm` sends the profile (no cell data beyond the first sample rows), the item fields of the document type with their meaning, and the heuristic draft to the **template-calibrator** agent (`agents/template-calibrator.md`, tool `submit_mapping`), which returns a corrected `MappingDraft`: it may map columns the heuristic could not, add `where` filters (for example one sheet per scope), or mark a column as intentionally empty. One retry on a rejected draft (as in earlier agents); the sample's text is data, not instructions. If the model fails or is rejected twice, the heuristic draft is used and the failure is reported. No model is needed for a normal sample.

## 4. Validation gate (`validate_mapping`, deterministic)

A draft is accepted only if: every sheet and cell exists in the sample; header rows are before first data rows; each field exists on the item class of the document type and is used once per table; column letters are unique and inside the used range; `where` keys are item fields; value maps exist; header sources are in the allowed set of spec 02; at least one table with at least one mapped column exists; and the required fields of the item class for a *rendered* document (`item_id` or an equivalent identifier column, plus at least one text field) are present, otherwise it is reported as a warning (a template may legitimately omit columns, but it must keep the stable id visible).

## 5. Build (`masterba.calibration.build`)

From a validated draft and the sample:

1. **Shell workbook**: the sample with every data row cleared (values removed, styles kept), one styled sample row left at each table's first data row, frozen panes and widths kept, macros and external links dropped, workbook properties normalised. Written with the deterministic `workbook_bytes`.
2. **`TemplateDefinition`** (`source: calibrated_from_sample`, `company_id` the target company) whose `sheet_map`, `cell_bindings` (typed through the spec 02 `Bindings` model, so the same loader checks it) and `validation_rules` reproduce the draft; every table has the filter `status = active` as in the baseline.
3. Files in `templates/companies/<company>/`: `<TYPE>.template.json`, `<TYPE>.xlsx` (the shell), `<TYPE>.sample.xlsx` (the untouched sample, kept for comparison) and `<TYPE>.calibration.json` (the draft with its unmapped list and warnings, for the editor).

Writing the draft is one commit `template(<company>): calibrate <TYPE>` in the repository root. Calibrating again replaces a **draft** only; replacing a *confirmed* template needs `--replace`, which also removes the marker (the new draft must be confirmed again).

## 6. Review, preview and confirmation

- `template show`: prints the mapping per table (column letter, sample header, mapped field), the unmapped columns and the warnings.
- **Editing** changes only column-to-field assignments (`template set` / the dashboard editor): assign a field to a column, clear a column, change `where`; the result is re-validated, rewritten and committed (`template(<company>): edit <TYPE>`). Any edit removes an existing `.confirmed` marker.
- `template preview`: renders a document into the draft template and saves `<TYPE>.preview.xlsx` next to it (not committed). Content comes from a stored project document of that type when `--project` is given, otherwise from a small built-in demo document. It also runs the **layout comparison** against the sample: same sheet names, same header texts in the same cells, same column widths; every difference is listed.
- `template check`: loads the draft with the same loader the renderer uses (`load_template`); reports problems.
- `template confirm --by NAME`: requires `check` to pass; writes `<TYPE>.confirmed` as `{"by": NAME, "at": "<UTC ISO 8601>"}` and commits (`template(<company>): confirm <TYPE>`). `template unconfirm` removes it.
- From the confirmation on, projects whose `company_id` matches render this document type in the company's layout; documents already rendered are not touched (re-render with `render_to_project`).

## 7. CLI, API and dashboard

```
masterba template calibrate --company ACME --doc-type BRD --sample sample.xlsx [--llm --model M] [--replace]
masterba template show|check|preview|confirm|unconfirm  --company ACME --doc-type BRD [--project PRJ-001] [--by NAME]
masterba template set --company ACME --doc-type BRD --sheet S --col C --field FIELD|none
masterba template list [--company ACME]
```

Dashboard (admin only, spec 08 roles): `GET /api/templates`, `POST /api/templates/{company}/{doc_type}/calibrate` (multipart sample, option `use_llm`), `GET .../{company}/{doc_type}` (draft, mapping, warnings, confirmed?), `PUT .../mapping` (column assignments), `GET .../preview` (the preview file), `POST .../confirm`, `POST .../unconfirm`. A **Templates** view lists company templates with their state (none, draft, confirmed), has the upload form, shows the mapping as a table with a field select per column, the warnings, the layout comparison and the Preview and Confirm buttons. The company id and document type are validated against patterns before any file is touched; uploads are `.xlsx` only, at most 5 MB.

## 8. Layout

```
agents/template-calibrator.md  skills/template-calibration/SKILL.md
src/masterba/calibration/  __init__.py  profile.py  heuristic.py  models.py  validate.py  build.py
                           suggest.py  demo.py  store.py  compare.py
src/masterba/api/routes_templates.py   frontend/views/templates.js
schemas/MappingDraft.schema.json
tests/calibration/  (samples built in code)
```

## 9. Acceptance Criteria

- [x] A synthetic SIer-style BRD sample (title rows, header on row 3, columns in a different order with Japanese labels, a document-info block, a cover sheet) yields a draft whose mapped fields, header row, first data row, numbering column and header bindings are exactly the expected ones, with no model call.
- [x] Samples for the other document types (SRS, Basic Design, tests with execution columns, two tables on separate sheets) are profiled and mapped as expected; unrecognised columns are listed as unmapped; merged cells, formulas, hidden sheets and several blocks produce warnings.
- [x] Building a draft writes the four files in `templates/companies/<company>/`, one commit, and the draft is **ignored** by `resolve_template` (falls back to the default) until confirmed.
- [x] After `confirm`, rendering a document for a project of that company produces a workbook whose sheet names, header texts, header row position, column order and column widths equal the sample's, with the document's items written from the first data row, styles copied from the sample's data row; the layout comparison reports no difference.
- [x] Editing a column assignment re-validates, rewrites the draft and removes the confirmation; invalid edits (unknown field, duplicate field, column outside the range) are rejected and change nothing.
- [x] `template check` reports the same problems `load_template` would; `confirm` is refused while check fails; `--replace` is required to overwrite a confirmed template.
- [x] The optional model refinement: a valid answer replaces the heuristic draft; an invalid answer is retried once and then ignored with a visible message; the prompt contains the profile and heuristic draft and no more than the first sample rows.
- [x] Hostile input: `.xlsm`, `.xls`, oversized and non-workbook files are refused before parsing; company ids and document types are validated; a sample with macros produces a shell without them.
- [x] API: only an admin may use any template route (the whole Templates area is admin-only, reads included); all routes enforce the CSRF header; the Templates view works in the browser against a seeded company and a recorded browser pass is added to section 10.
- [ ] (OPEN) A live attempt with a real sample, when one is available, is recorded in section 10; until then the criterion is open and says so.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass; the `MappingDraft` schema is generated and drift-tested.

## 10. Manual review record

- No real customer sample was available. Every check ran on synthetic SIer-style workbooks built by `tests/calibration_samples.py` (title rows, Japanese labels in another order, a document-info block, a cover sheet). The live-sample criterion in section 9 stays open.
- Browser pass (built-in browser, local server, admin user, synthetic BRD sample uploaded through the real form): the draft appeared with the mapping table (B requirement_id, C title, D description, E scope, F unmapped), `Render preview` reported no layout difference, `Confirm template` switched the state to Approved and offered `Remove confirmation`. No console errors. Narrow-width and dark-mode checks were not repeated for this view; it reuses the shared table and panel styles already checked in spec 08.

## 10.1 Decisions taken while implementing

1. `heuristic_draft` lives in `calibration/profile.py` (it needs the workbook), `profile_workbook(path, doc_type)` takes the document type, and `demo_document` and `compare_layout` live in `calibration/preview.py`.
2. The whole Templates API is admin only, including reads and the preview download, because a draft may reflect a customer's confidential layout. This replaces the looser reading in the acceptance wording.
3. The CLI uses `--type` (not `--doc-type`) and takes the sample as a positional argument; `--model` turns on the model refinement and a replace is `--replace`.
4. API upload is `multipart` with `?replace=true`; the sample is copied to a temporary folder and parsed from there; the model refinement is CLI only.
5. A requirement label such as `要求ID` was added to the synonym table after the SRS sample showed it matched `statement` instead.

## 11. Open points (do not block implementation)

1. **Renderer features.** Merged data cells, several tables per sheet and multi-row headers are the usual reasons a real sample will only be approximated; each needs a renderer extension (spec 02) decided on evidence from real samples.
2. **Value labels.** Real samples may use their own labels for `scope`, `kind` and `level`; the draft can carry a value map built from the sample's data values once such a sample is available.
3. **Exclusion sheets** of test documents (spec 05 open point 1) can be mapped once the renderer reads `$content.exclusions`.
