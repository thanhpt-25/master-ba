# Spec 26 — Japanese SIer default templates

Status: draft v0.1 (2026-11-28), part A proposed, waiting for the owner's approval. Sources: [02-excel-rendering.md](02-excel-rendering.md), [19-deliverable-fit.md](19-deliverable-fit.md) part 1, [07-change-management.md](07-change-management.md), [13-customer-questions.md](13-customer-questions.md).

## Goal

The default workbooks follow the way large Japanese SIers and public-sector buyers lay out deliverables: one header band on every sheet, a table of contents, a list sheet (一覧) per kind of design object before any definition sheet, display codes per kind (SCR-, IF-, TBL-...), test specifications as テスト項目表 with a progress count, and two management workbooks every SIer project keeps: 変更管理台帳 (change log with one 変更管理票 per change) and QA管理表 (customer Q&A log).

Fujitsu (SDEM) and NTT Data (TERASOLUNA 標準手順) do not publish their forms. The layout rests on public sources that follow the same practice: the 出力成果物 list in the 特許庁 system procurement (別紙3: 機能一覧, 画面一覧, 帳票一覧, メッセージ一覧, 外部インタフェース一覧, エンティティ定義書, CRUD マトリックス, 処理一覧, テーブル設計書, テスト項目表 with テスト項番 / テスト項目の内容 / テストデータ), IPA 非機能要求グレード, and common 基本設計書 samples (表紙・改訂履歴 → 概要 → 一覧 → 定義).

## Parts

- **Part A (this spec, sections 1 to 6): layout only.** No payload model change, no model call, no prompt change. Everything printed comes from data the store already holds.
- **Part B (section 7, later spec amendment): new data.** Fields and kinds the writers must produce. Not implemented by part A.

## 1. Common frame

Every sheet except the cover:

| Rows | Content |
|---|---|
| 1 | Sheet title (e.g. `3. 機能一覧`) |
| 2 to 3 | Header band, a bordered grid of label/value pairs: システム名, 文書名, 文書番号, 版数 / シート名, 作成日, 更新日, 作成者 |
| 5 | Note row (unchanged role) |
| 7 | Table header row |
| 8 | First data row |

The header band replaces the label block of rows 2 to 5 (spec 19 section 3). Header and first data rows keep their row numbers, so `HEADER_ROW`, `FIRST_ROW` and the section cells stay where they are.

- 版数 prints `n.0` (`$document.version_label`); the stored version stays an integer.
- システム名 prints the project id (`$project.name`); `ProjectConfig` has no display name yet, and adding an optional `name` is a spec 01 amendment left to part B.
- New header sources: `$project.name`, `$document.version_label`, `$sheet.title` (the sheet's own name, resolved per binding), `$document.classification`.

Cover (表紙): adds システム名, 顧客名 (`$project.company`), 発行元 (fixed `MasterBA`, overridable by a company template), 機密区分 (default 社外秘). The stamp box 承認 / 確認 / 作成 stays.

改訂履歴: columns No., 版数, 改訂日, 改訂箇所, 改訂内容, 改訂理由, 作成者, 承認者. 改訂箇所 lists the sheets whose items changed (from `masterba.diff` and the table `where` filters), e.g. `3. 機能一覧、4. 画面一覧`; v1 prints `全体`.

目次 (new, third sheet): No., シート名, 記載内容. Rows are fixed text generated from the catalog (`SheetSpec.summary`), written into the shell, so no binding is needed.

Tables: column A stays No. (連番); 備考 is the last column and is left empty for hand notes; the item ref column moves next to 備考 as 管理ID.

## 2. Display codes

A table column may bind the virtual field `$code`. It prints a code derived only from the item ref and the item's kind, so it never changes for an item and needs no storage:

| Kind | Code |
|---|---|
| BRD item, SRS item | the REQ id (unchanged) |
| Basic design `function` / `screen` / `interface` / `data_entity` | `FN-` / `SCR-` / `IF-` / `TBL-` + item number, 4 digits |
| Detail design `module` / `processing_step` / `db_table` / `api` | `MOD-` / `PRC-` / `DBT-` / `API-` + item number |
| Test case | the TC id (unchanged) |

`DOC-BASIC_DESIGN-0001#item.12` with kind `screen` prints `SCR-0012`. Codes can skip numbers, because item numbers are shared by all kinds of a document; this is accepted (a reviewer reads gaps as removed or other-kind items). Trace, 改訂箇所 and the other sheets keep printing item refs where they print upstream and downstream ends, plus the code in brackets when the end is in a design document.

## 3. Sheets per document

`=` unchanged content; `new` added in part A.

**業務要件定義書 (BRD):** 表紙, 改訂履歴, 目次, 1. 背景・目的, 2. 業務要件一覧, 3. システム化の範囲 (one table, column 対象区分 対象 / 対象外, replacing the two sheets), 4. 前提条件・制約事項, 5. 未決事項 (new), トレーサビリティ.

**システム要件定義書 (SRS):** 表紙, 改訂履歴, 目次, 1. 背景・目的, 2. 機能要件一覧, 3. 非機能要件一覧, 4. 前提条件・制約事項, 5. 未決事項 (new), トレーサビリティ.

**基本設計書:** 表紙, 改訂履歴, 目次, 1. 機能一覧, 2. 画面一覧, 3. 画面遷移図 (picture placeholder, new), 4. 外部インタフェース一覧, 5. エンティティ一覧, 6. システム構成図・業務フロー (picture placeholder), 7. 結合テスト観点, トレーサビリティ.

**詳細設計書:** 表紙, 改訂履歴, 目次, 1. 概要, 2. モジュール一覧, 3. 処理一覧・処理フロー, 4. テーブル定義書, 5. API・インタフェース定義書, トレーサビリティ.

**テスト仕様書 (単体 / 結合 / 総合 / 受入):** 表紙, 改訂履歴, 目次, 1. テスト項目表, 2. 消化状況 (new), 除外項目.

Column sets (between No. and 備考):

| Sheet | Columns |
|---|---|
| 業務要件一覧 | 要件ID, 要件名, 要件内容, 対象区分, 出典, 管理ID |
| 機能要件一覧 / 非機能要件一覧 | 要件ID, 要求内容, 受入基準, 派生元業務要件, 管理ID |
| 基本設計 一覧 | 機能ID / 画面ID / IF ID / エンティティID (`$code`), 名称, 概要, 実現要件, 管理ID |
| 詳細設計 一覧 | モジュールID / 処理ID / テーブルID / API ID (`$code`), 名称, 仕様, 詳細化元, 管理ID |
| テスト項目表 | テスト項番, 大項目 (`$verifies_name`: the name or title of the first verified item), 確認内容 (steps), 前提条件, テストデータ (input), 期待結果, 確認対象 (verifies), 実施予定日, 実施日, 実施者, 判定, 不具合No., 管理ID |
| 未決事項 | QA番号, 内容, 参照箇所, 起票日, 状態 |

`$verifies_name` resolves against the upstream documents in the render context (no model). 未決事項 is a new list source `$questions`: the open questions of the document's stage from the question ledger, sorted by id.

消化状況: a fixed table in the shell with one row per judgement (OK, NG, 保留, 対象外, 未実施) and 件数 / 比率, computed by `COUNTIF` formulas over the 判定 column of テスト項目表 (rows 8 to 2000). These are the only formulas in a default workbook; they are template text, never built from content, so the rule that every content string is written as text (spec 02) still holds.

## 4. Management workbooks

Rendered by new functions in `rendering/registers.py` from the DR and question stores; no `Document`, no ID Stability Rule. Written to `projects/<id>/deliverables/変更管理台帳.xlsx` and `QA管理表.xlsx` in the commit of the business action that changed them (DR create, approve, reject, propagate, close; question record, answer, withdraw), byte-deterministic like the other workbooks.

**変更管理台帳.xlsx**
- 表紙, 改訂履歴 are not used; the workbook starts with sheet 変更管理台帳: No., 変更管理番号 (DR id), 起票日, 変更区分 (trigger in Japanese), 件名 (description, first line), 状態 (起票 / 承認 / 反映済 / 完了; a closed DR without impact analysis prints 却下), 承認者, 反映先文書 (affected documents with the version propagation wrote).
- One sheet per DR, named by its id: 変更管理票 laid out as a form: 変更管理番号, 起票日, 変更区分, 状態, 変更内容 (description), 判断 (decision), 理由 (rationale), 影響範囲 (impacted items with their codes, grouped by document), 反映結果 (document and version per affected document), 工数・納期への影響 (empty, hand entry), stamp box 承認 / 確認 / 起票.

**QA管理表.xlsx**
- One sheet QA管理表: No., QA番号, 工程 (stage in Japanese), 起票日, 起票元 (agent / QA指摘), 質問内容, 参照箇所, 回答, 回答者, 回答日, 状態 (未回答 / 回答済 / 取下げ), 関連変更管理番号 (DR id).

CLI `masterba export changes|questions --project P [--out f.xlsx]` writes the same bytes to a chosen path; API `GET /api/projects/{pid}/registers/{changes|questions}.xlsx` (viewer role). The dashboard links are not part of this spec (the 成果物 view is being reworked separately).

## 5. Compatibility

- Default shells and `.template.json` files are regenerated; cells of content sheets move (columns), so existing projects get one new commit per workbook at their next render.
- Calibrated company templates keep their own bindings and are not affected. The new header sources and `$code` / `$verifies_name` / `$questions` are available to them.
- The browser preview reads the default layout and follows it.
- `rendering/preview.py` shows 消化状況 as its labels only (no formula evaluation).

## 6. Acceptance criteria (part A)

- [ ] Every default workbook has 表紙, 改訂履歴, 目次 as its first three sheets, and every other sheet has the header band with システム名, 文書名, 文書番号, 版数, シート名, 作成日, 更新日, 作成者.
- [ ] A basic design item of kind `screen` and number 12 prints `SCR-0012` on 画面一覧; the code is the same after a DR revision.
- [ ] 改訂履歴 of a v2 lists the sheets whose items changed in 改訂箇所.
- [ ] BRD and SRS print the stage's open questions on 未決事項; an answered question leaves it at the next render.
- [ ] Filling 判定 by hand updates 消化状況 when the file is opened in Excel (formula check in a test with openpyxl reading the formula text).
- [ ] A DR approval writes 変更管理台帳.xlsx in the same commit; rendering it again without a change makes no commit.
- [ ] Answering a question updates QA管理表.xlsx and its 関連変更管理番号.
- [ ] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass; the committed shells match the generator.

## 7. Part B (proposed, needs data)

Each needs a spec 01 amendment (optional field, old documents still load), writer prompt and QA checklist changes, and a live run to check quality:

1. `SrsItem.nfr_category`: IPA 非機能要求グレード 大項目 (可用性, 性能・拡張性, 運用・保守性, 移行性, セキュリティ, システム環境・エコロジー); 非機能要件一覧 sorts and groups by it.
2. `TestCaseItem.viewpoint`: 正常系 / 異常系 / 境界値, printed as 観点区分; 消化状況 adds a count per viewpoint.
3. Basic design kinds `report` (帳票一覧, RPT-), `batch` (バッチ一覧, BAT-), `message` (メッセージ一覧, MSG-: 区分, 文言, 表示先).
4. CRUD relation: basic design function, screen or batch to data entity with C/R/U/D, printed as CRUDマトリクス.
5. Sections `current_issues` (現状業務と課題, BRD), `glossary` (用語集, BRD), `system_overview` in 基本設計書, `test_overview` (テスト概要: 目的, 範囲, 環境, 合否判定基準) in test specifications.
