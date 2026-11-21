# Spec 19 — Deliverable fit: SIer-quality templates and content

Status: v0.3 (2026-11-21), parts 1, 2 and 3 implemented. Sources: [docs/next-steps.md](../docs/next-steps.md) Phase 19 (gaps A3, A4, A6, A7), [02-excel-rendering.md](02-excel-rendering.md), [15-phase-review-gates.md](15-phase-review-gates.md), [07-change-management.md](07-change-management.md).

## Goal

A workbook rendered from the default templates should look like a document a Japanese SIer hands to a customer, not like a data dump. Every deliverable gets a cover sheet (表紙) and a revision history (改訂履歴) filled by code from data the store already holds, Japanese labels for every value it prints, a traceability sheet in the requirement and design documents, an exclusions sheet (除外項目) in the test specifications, and print settings a reviewer can print from.

Part 1 changes only rendering. No model call is added, the payload models do not change, and the content of a document stays exactly what the stage wrote.

## Non-goals (later parts of Phase 19)

- Document-level prose sections (背景・目的, 制約事項, システム概要, 結合テスト観点): part 2 below.
- CRUD matrix and screen transitions. The payload has no relation between a function and the tables it touches, or between screens, so they cannot be derived honestly yet.
- Merged data cells, multi-row headers or several tables per sheet in company templates (gap A2), direct edits (B5), intake formats (E1), the Japanese dashboard (E3).

## 1. Revision context

`render_document(doc, content, template, context=None)` takes an optional `RenderContext` (new module `rendering/context.py`). Without one (the calibration preview, unit tests) every context-bound cell stays empty, so existing callers are unchanged.

```python
@dataclass(frozen=True)
class Revision:  # one row of 改訂履歴
    version: int
    date: str | None  # YYYY/MM/DD
    summary: str  # 改訂内容
    reason: str  # 改訂理由
    author: str  # 作成者
    approver: str | None  # 承認者
    approved_on: str | None  # 承認日


@dataclass(frozen=True)
class TraceRow:  # one row of トレーサビリティ
    item: str  # REQ id or item ref of this document
    name: str  # title, statement or name of the item
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]


@dataclass(frozen=True)
class RenderContext:
    company: str | None
    author: str
    revisions: tuple[Revision, ...]
    trace: tuple[TraceRow, ...]
```

`build_context(store, doc, content, revised_by=None)` derives it, with no model:

- **Revisions**: one row per stored version `<= doc.version`.
  - date: the commit date of the version's JSON file (`git log --diff-filter=A`); empty when git has none.
  - summary: v1 is `初版作成`; a later version counts the item changes against the previous version with `masterba.diff` (`追加 n件、変更 n件、削除 n件`).
  - reason: the Decision Record that produced the version, found in the DR's `propagation` progress (or passed as `revised_by` while propagation is still writing it): `DR-0003（要件変更）: <description>`. v1 has `新規作成`.
  - approver: `Review.by` of an approval review that lists this version; its date is the cover's 承認日.
  - author: `MasterBA`, because the system wrote the version; the reviewer is the approver.
- **Trace**: one row per active item; upstream and downstream are the ends of stored trace links whose other end is the item id, its requirement id or its test case id, sorted.
- company: `ProjectConfig.company_id`, empty for `default`.

`render_to_project(..., revised_by=None)` builds the context; `change/propagate.py` passes the DR id when it renders a revised version, so the first render already shows the reason. A later render (review approval, supersede) finds the same DR in the progress file, so the output is the same bytes and makes no commit.

Rendering stays byte-deterministic: the context is derived only from committed data.

## 2. Bindings

`Bindings` gains, all optional so existing and calibrated templates stay valid:

- `HeaderBinding.value_map`: maps the header value, e.g. document status `approved` to `承認済`.
- New header sources: `$document.title` (Japanese document name), `$document.created_on`, `$document.updated_on`, `$document.approver`, `$document.approved_on`, `$document.author`, `$project.company`.
- `lists`: tables filled from the context or from the payload rather than from `content.items`: `{"sheet", "start_row", "source", "numbering", "columns"}` with `source` one of `$revisions`, `$trace`, `$exclusions`. A column `field` must be a field of the row type, checked at load time like item fields.

## 3. Default templates

Every document type starts with:

| Sheet | Content |
|---|---|
| 表紙 | Document name (e.g. 業務要件定義書), project, company, then a label table: 文書ID, 版数, 状態, 作成日, 最終更新日, 作成者, 承認者, 承認日; an empty 承認 / 確認 / 作成 stamp box |
| 改訂履歴 | 版, 改訂日, 改訂内容, 改訂理由, 作成者, 承認者 |

then the existing content sheets, unchanged in position (header block rows 2 to 5, header row 7, data from row 8), so existing bindings and tests keep their cells. Added sheets:

| DocType | Added sheet |
|---|---|
| BRD, SRS, BASIC_DESIGN, DETAIL_DESIGN | トレーサビリティ: 項目ID, 名称, 上流, 下流 |
| TEST_IT, TEST_ST, TEST_UT, TEST_UAT | 除外項目: 対象項目, 除外理由 |

Japanese value maps: document status (作成中, レビュー中, 承認済, 旧版), test level (単体テスト, 結合テスト, 総合テスト, 受入テスト), plus the existing scope map. The header block's 状態 uses the status map.

Print and entry settings in every shell: A4 landscape, fit to one page wide, the table header row repeated on each printed page, a footer with the file name and `ページ n / m`. The 判定 column of test specifications offers a list `OK, NG, 保留, 対象外`.

## 4. Acceptance criteria

- [x] Every default workbook starts with 表紙 and 改訂履歴; content sheets keep their cells.
- [x] A rendered v2 produced by a DR shows two revision rows, the v2 row naming the DR and counting added, changed and removed items; an approval review fills 承認者 and 承認日 on the cover.
- [x] Re-rendering after the propagation progress is written gives the same bytes as the first render.
- [x] The 状態 cell prints Japanese; no default sheet prints an English enum value.
- [x] SRS, Basic Design and Detail Design workbooks carry a traceability row per active item with upstream and downstream ids; test workbooks list their exclusions.
- [x] Without a context the renderer still works and leaves context cells empty (calibration preview).
- [x] An unknown `lists` source or row field fails at template load.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass; the committed shells match the generator.

## 5. Decisions

1. The author of every version is `MasterBA`, not the person who started the run: runs do not record who started them, and the person who takes responsibility is the approver.
2. Dates come from git, which the store already requires, instead of a new field on `Document` (spec 01 stays unchanged).
3. The stamp box is left empty for a hand or electronic seal; an approval in MasterBA fills 承認者, not the seal.

# Part 2 — Stronger document content

## 6. Goal

Fill the prose sheets a reviewer expects with text that rests on the input, hold the wording to the rules a Japanese SIer reviewer checks first, and measure the result so that a prompt or model change can be judged. No new model call is added: sections come from the same writer call, style checks and the report are deterministic.

## 7. Document sections

Spec 01 amendment (`specs/01-data-contracts.md`, 2026-11-21): `BrdContent`, `SrsContent`, `BasicDesignContent` and `DetailDesignContent` gain `sections: list[DocumentSection]` (default empty, so stored documents stay valid). `DocumentSection` is `{key: SectionKey, body: str, sources: list[str]}`; a section is not an item, has no id and no trace link, and the ID Stability Rule does not apply to it.

| Document | Sections (key, sheet) | Written by | `sources` |
|---|---|---|---|
| BRD | `background` 背景・目的, `constraints` 制約事項 | requirements analyst | intake line ranges, stored as `intake/<file>#L<a>-L<b>` |
| SRS | `background`, `constraints` | SRS writer | BRD REQ ids and BRD section refs (`DOC-BRD-0001#background`) |
| Basic Design | `it_viewpoints` 結合テスト観点 | designer | SRS item refs and SRS section refs |
| Detail Design | `system_overview` システム概要 | detail designer | Basic Design item refs and section refs |

- Drafts carry `sections: list[DraftSection]`. A later writer receives the upstream sections in an `<upstream_sections>` block; QA sees them in the draft view and in the upstream text.
- Gate (`agents/sections.py`, `validate_sections`): the key belongs to the document, each key once, at least one source, every source is an intake line range inside the intake (BRD) or an id the writer was given (later stages), body within 4,000 characters and in the document language. Errors go back to the writer like any gate error.
- A section is optional. When the input does not support it the writer leaves it out, and the sheet prints 「（入力資料に記載がないため、本版では記載していません。）」 instead of the old "pending" note.
- Checklists: BRD-07 and SRS-08 (blocking) require a section to add nothing its sources do not support; BD-07 and DD-07 (advisory) check the viewpoints and the overview.
- Rendering: `SectionBinding {sheet, key, body_cell, sources_cell, empty_text}`; the default section sheets show 記載内容 (A8) and 出典 (A11).
- A Decision Record revises items only; `apply_patch` keeps the sections of the previous version unchanged.

## 8. SIer writing rules

Every writer prompt gains a short section with the rules a reviewer checks first: one point per sentence (一文一義), a named subject, no vague words, the plain である style in Japanese, one term per concept. Test writers also get the rule that an expected result names what a tester observes (TS-07, UT-06, advisory).

Deterministic style findings (`quality/lint.py`):

| Rule | Finding | Applies to |
|---|---|---|
| STY-01 | vague word (適宜, 速やかに, 柔軟に, 十分な, 必要に応じて, ... / as needed, appropriate, ...) | BRD descriptions, SRS statements, design descriptions and specs |
| STY-02 | requirement statement without an obligation ending (〜こと / 〜ならない; 'shall') | SRS statements |
| STY-03 | sentence over 150 characters (Japanese) or 50 words (English) | all prose |
| STY-04 | expected result such as 正常に動作すること, 問題がないこと, 'works correctly' | test cases |
| STY-05 | non-functional statement with no figure | SRS non-functional statements |
| STY-06 | です/ます in a Japanese document | all prose |

A vague word or a missing figure is not reported for a draft item whose source the writer already raised an open question about (intake lines overlap, or a shared REQ id).

In the BRD and SRS stages `StyleFeedback` returns the findings to the writer as gate feedback **at most once per run, and only while at least two rounds remain**, so wording never costs the round QA needs; afterwards they appear only in the quality report. The design stages do not gate on style (their convergence is the open problem of Phase 18); their findings are reported.

## 9. Quality report

`masterba quality --project PRJ-001 [--out report.md]` writes a Markdown report of the latest version of every document (`quality/report.py`, no model):

- per document: version, status, active items, items traced upstream and downstream, missing sections, style findings by rule, open customer questions of that stage;
- SRS: functional items with an acceptance hint, non-functional items with a figure; tests: exclusions;
- a rubric table per document for the SIer reviewer, scored 1 to 5: 網羅性, 正確性, 検証可能性, 表現・用語, 構成.

Phase 17 (benchmark) reuses these figures per run and stores the reviewer's scores; this part only produces the report.

## 10. Acceptance criteria (part 2)

- [x] Stored documents without `sections` still load; the generated schemas include `sections`.
- [x] A BRD draft section with a source outside the intake, a duplicate key or a key of another document is sent back; a valid one is stored with intake citations and rendered on its sheet with its sources.
- [x] An SRS, Basic Design and Detail Design draft section may cite only the ids and upstream section refs the writer was given.
- [x] A section sheet with no section prints the "not stated" text, not "pending".
- [x] Style findings reach the writer once, only with two rounds left, and never block a run on their own afterwards.
- [x] `masterba quality` lists the figures, findings and the rubric for every latest document.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass.

# Part 3 — Dashboard flows for a pilot team

Sources: [docs/next-steps.md](../docs/next-steps.md) Phase 19 item 8 (gap E3), [08-dashboard.md](08-dashboard.md), [15-phase-review-gates.md](15-phase-review-gates.md), [13-customer-questions.md](13-customer-questions.md).

## 11. Goal

A Japanese SIer reviewer who opens a project should see, without reading a manual, what the project waits for and do it in one click: upload the intake, run a phase, answer the questions that block it, read the document in the browser, approve or reject it, and move to the next phase. The dashboard speaks Japanese by default.

No model call, store format or library function changes. The dashboard keeps calling the same library functions as the CLI, so git history stays identical.

## 12. Non-goals

- Direct edits of a document in the browser (B5), intake formats other than `.txt` / `.md` (E1, part 4 of the pilot plan), SSO (C6).
- Translating content: documents print in the project's `document_language`; only the dashboard's own words change with the UI language.
- A preview of a calibrated company layout. The preview shows the default layout (section 14); the downloaded workbook still follows the project's template.

## 13. Guided journey (Overview)

`nextStep(overview)` (pure, in `frontend/views/journey.js`) returns the one action the project waits for, in this order:

| Situation | Next step | Action |
|---|---|---|
| A job is running | 「<phase> を実行中です」 | none, the job panel shows progress |
| An approved DR with affected documents waits for propagation | Propagate `DR-####` | link to the DR |
| The current phase's run waits for input | Answer the `n` blocker questions | link to Questions |
| The current phase escalated | Resume the run (one round) | button: resume `last_run` |
| The current phase is `in_review` | Review `<document>` | link to the document preview, where approve and reject are |
| The current phase is ready (BRD) | Upload the intake and run BRD | file picker and button |
| The current phase is ready (later phase) | Run `<phase>` | button |
| Every phase is finished | Changes go through a Decision Record | link to DRs |

The step shows as one panel at the top of the Overview with a single primary button; a viewer sees the same text with no button ("an approver does this"). The V-model cards stay below it.

Blockers are shown where they block: a stage card names its open customer questions (`n` 件の未回答の質問) with a link, and the overview response gains, per stage, `open_questions` (open questions whose stage is one of the stage's document types) and, per project, `pending_drs` (approved DRs with affected documents whose propagation has not finished, `{id, description}`; a clarification that affects no stored document is only a fact for later runs).

## 14. Document preview

`GET /api/projects/{pid}/documents/{doc_id}/preview?version=n` (viewer) returns the document as the default workbook would print it, built from `rendering/catalog.py` and `build_context` with no model and no write (`rendering/preview.py`):

```json
{"document": {...}, "versions": [1, 2],
 "sheets": [
   {"key": "cover", "name": "表紙", "kind": "cover", "title": "業務要件定義書", "rows": [["文書ID", "DOC-BRD-0001"], ...]},
   {"key": "history", "name": "改訂履歴", "kind": "table", "columns": ["版", ...], "rows": [["1", ...]]},
   {"key": "background", "name": "背景・目的", "kind": "section", "body": "...", "sources": ["intake/x.md#L3-L5"], "empty_text": "（入力資料に…）"},
   {"key": "diagrams", "name": "構成図・フロー図・ER図", "kind": "note", "note": "（図は別途添付）"}
 ]}
```

- Table rows hold the same text the workbook cells hold (value maps applied, lists joined by new lines, numbered steps); columns without a field (判定, 実施日, ...) are left out of the preview.
- The Documents view shows the sheets as tabs in workbook order, with the version selector, the Excel download and the version comparison kept.
- When the document's phase is `in_review` and the user is an approver, a note at the top says so and the review box sits below the sheets, so the reviewer reads first: approve, or reject with one comment per line (an item ref at the start of a line ties the comment to that item, as on the Overview). After either the dashboard returns to the Overview, where the next step shows.

## 15. Japanese UI

- `frontend/i18n.js` holds `t(text, vars)`; the English text is the key and `frontend/i18n-ja.js` maps it to Japanese, so English needs no second catalog. Every view takes its words from `t()` (or marks a static label with `N_()`). A missing entry falls back to English, and a test fails when a string passed to `t()` has no Japanese entry or an entry is unused.
- The language is chosen in the header (日本語 / English) and kept per user in the browser (`masterba-lang:<user>`); the default is Japanese. `<html lang>` follows the choice.
- Status words (badges) and phase names come from the catalog; ids, enum values in code and API error texts are not translated.
- Dates use `Intl` with the chosen language.

## 16. Acceptance criteria (part 3)

- [x] For each situation in section 13 `nextStep` returns the listed step (unit tests in `frontend/test`).
- [x] A stage card with open questions links to them; an approved, unpropagated DR with affected documents shows as the next step.
- [x] The preview endpoint returns every sheet of the default layout in order with the workbook's cell text, including revision history, sections and traceability; it writes nothing.
- [x] A reviewer can approve or reject an `in_review` phase from the document preview.
- [x] With the default language every view shows Japanese labels; switching to English and back needs no page reload; every string passed to `t()` has a Japanese entry and the catalog has no unused entry.
- [x] `uv run pytest`, `ruff`, `mypy --strict` and `npm test` in `frontend/` pass.
