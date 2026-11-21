# Spec 19 — Deliverable fit, part 1: SIer-quality default templates

Status: v0.1 (2026-11-21), part 1 implemented. Sources: [docs/next-steps.md](../docs/next-steps.md) Phase 19 (gaps A3, A4, A6, A7), [02-excel-rendering.md](02-excel-rendering.md), [15-phase-review-gates.md](15-phase-review-gates.md), [07-change-management.md](07-change-management.md).

## Goal

A workbook rendered from the default templates should look like a document a Japanese SIer hands to a customer, not like a data dump. Every deliverable gets a cover sheet (表紙) and a revision history (改訂履歴) filled by code from data the store already holds, Japanese labels for every value it prints, a traceability sheet in the requirement and design documents, an exclusions sheet (除外項目) in the test specifications, and print settings a reviewer can print from.

Part 1 changes only rendering. No model call is added, the payload models do not change, and the content of a document stays exactly what the stage wrote.

## Non-goals (later parts of Phase 19)

- Document-level prose sections (背景・目的, 制約事項, システム概要, 結合テスト観点). They need a payload change (spec 01 amendment) and writer work, and are part 2. Their sheets stay placeholders.
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
