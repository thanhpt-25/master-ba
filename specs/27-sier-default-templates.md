# Spec 27 — Japanese SIer default templates

Status: v0.2 (2026-11-28), part A implemented (approved by the owner 2026-11-28); part B proposed for a later PR. Sources: [02-excel-rendering.md](02-excel-rendering.md), [19-deliverable-fit.md](19-deliverable-fit.md) part 1, [07-change-management.md](07-change-management.md), [13-customer-questions.md](13-customer-questions.md).

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
| 1 | Sheet title (the sheet name) |
| 2 to 3 | Header band, a bordered grid of label/value pairs in columns A to H: システム名, 文書名, 文書番号, 版数 / シート名, 作成日, 更新日, 状態 |
| 5 | Note row (unchanged role) |
| 7 | Table header row |
| 8 | First data row |

The header band replaces the label block of rows 2 to 5 (spec 19 section 3). Header and first data rows keep their row numbers, so `HEADER_ROW`, `FIRST_ROW` and the section cells stay where they are. 状態 takes the place of 作成者 in the band because the review state matters on every page and the author is always MasterBA (on the cover). Columns A to H are at least 14 wide and band values shrink to fit. On a section sheet the headers, body and sources cells are merged over A to H; the engine sets the body row height from the text (about 120 half-width characters per line), because Excel does not grow a merged row.

- 版数 prints `n.0` (`$document.version_label`); the stored version stays an integer.
- システム名 prints the project id (`$project.name`); `ProjectConfig` has no display name yet, and adding an optional `name` is a spec 01 amendment left to part B.
- New header sources: `$project.name`, `$document.version_label`, `$document.classification` (社外秘), `$document.publisher` (MasterBA). The シート名 value is fixed text in the shell.

Cover (表紙): adds システム名, 顧客名 (`$project.company`), 発行元 (fixed `MasterBA`, overridable by a company template), 機密区分 (default 社外秘). The stamp box 承認 / 確認 / 作成 stays.

改訂履歴: columns No., 版数, 改訂日, 改訂箇所, 改訂内容, 改訂理由, 作成者, 承認者. 改訂箇所 lists the default content sheets that hold a changed item (from `masterba.diff` and the table `where` filters without the status filter, so a removed item counts), e.g. `業務要件一覧、システム化の範囲`; v1 prints `全体`. It names the default layout's sheets also when a company template is used.

目次 (new, third sheet): No., シート名, 記載内容. Rows are fixed text generated from the catalog (`SheetSpec.summary`), written into the shell, so no binding is needed.

Tables: column A stays No. (連番, centred); 備考 is the last column and is left empty for hand notes; the item ref column moves next to 備考 as 管理ID. Sheet names carry no chapter numbers (目次 numbers them), so they stay short and stable.

## 2. Display codes

A table column may bind the virtual field `$code`. It prints a code derived only from the item ref and the item's kind, so it never changes for an item and needs no storage:

| Kind | Code |
|---|---|
| BRD item, SRS item | the REQ id (unchanged) |
| Basic design `function` / `screen` / `interface` / `data_entity` | `FN-` / `SCR-` / `IF-` / `TBL-` + item number, 4 digits |
| Detail design `module` / `processing_step` / `db_table` / `api` | `MOD-` / `PRC-` / `DBT-` / `API-` + item number, 4 digits |
| Test case | the TC id (unchanged) |

`DOC-BASIC_DESIGN-0001#item.12` with kind `screen` prints `SCR-0012`. Codes can skip numbers, because item numbers are shared by all kinds of a document; this is accepted (a reviewer reads gaps as removed or other-kind items). トレーサビリティ prints the code as 項目ID and the item ref as 管理ID; its 上流 and 下流 cells keep printing ids and item refs.

## 3. Sheets per document

**業務要件定義書 (BRD):** 表紙, 改訂履歴, 目次, 背景・目的, 業務要件一覧, システム化の範囲 (対象), 対象外業務, 前提条件・制約事項, 未決事項, トレーサビリティ. The two scope sheets stay separate: a single sheet would only repeat 業務要件一覧, which already has 対象区分.

**システム要件定義書 (SRS):** 表紙, 改訂履歴, 目次, 背景・目的, 機能要件一覧, 非機能要件一覧, 前提条件・制約事項, 未決事項, トレーサビリティ.

**基本設計書:** 表紙, 改訂履歴, 目次, 機能一覧, 画面一覧, 画面遷移図 (picture placeholder), インタフェース一覧, エンティティ一覧, システム構成図・業務フロー (picture placeholder), 結合テスト観点, トレーサビリティ.

**詳細設計書:** 表紙, 改訂履歴, 目次, 概要, モジュール一覧, 処理一覧, テーブル定義, API定義, トレーサビリティ.

**テスト仕様書 (単体 / 結合 / 総合 / 受入):** 表紙, 改訂履歴, 目次, テスト項目表, 消化状況, 除外項目. The level column is dropped: a workbook holds one level, named in its title.

Sheet keys (`SheetSpec.key`) are unchanged where a sheet existed, so stored sheet references keep working; new keys are `toc`, `open_questions`, `screen_flow`, `progress`.

Column sets (between No. and 備考):

| Sheet | Columns |
|---|---|
| 業務要件一覧 / システム化の範囲 / 対象外業務 | 要件ID, 要件名, 要件内容, 対象区分, 出典, 管理ID |
| 機能要件一覧 / 非機能要件一覧 | 要件ID, 要求内容, 受入基準, 派生元業務要件, 管理ID |
| 基本設計 一覧 | 機能ID / 画面ID / IF ID / エンティティID (`$code`), 名称, 概要, 実現要件, 管理ID |
| 詳細設計 一覧 | モジュールID / 処理ID / テーブルID / API ID (`$code`), 名称, 仕様, 詳細化元, 管理ID |
| テスト項目表 | テスト項番, 大項目 (`$verifies_name`), 前提条件, テストデータ, 確認手順, 期待結果, 確認対象, 実施予定日, 実施日, 実施者, 判定, 不具合No., 管理ID |
| 未決事項 | QA番号, 内容, 参照箇所, 起票日, 状態 |
| トレーサビリティ | 項目ID (code), 名称, 上流, 下流, 管理ID |

`$verifies_name` is the name (title, statement or design name) of the first item a test case verifies, looked up in `RenderContext.names`, built from the latest stored documents (no model). `$code` and `$verifies_name` are accepted only in item tables, and `$verifies_name` only in test specifications; anything else fails at template load. 未決事項 is a new list source `$questions`: the open questions of the document's stage from the question ledger, sorted by id.

消化状況: a fixed table in the shell with one row per judgement (OK, NG, 保留, 対象外, 未実施) and 合計, with 件数 / 比率: `COUNTIF` over the 判定 column of テスト項目表 (rows 8 to 2000), 合計 is `COUNTA` of テスト項番, 未実施 is 合計 minus the counted judgements. The browser preview shows every case as 未実施, since judgements exist only in Excel. These are the only formulas in a default workbook; they are template text, never built from content, so the rule that every content string is written as text (spec 02) still holds.

## 4. Management workbooks

Printed by `rendering/registers.py` from the DR and question stores; no `Document`, no ID Stability Rule, no model. They are exported on demand and **not committed**: the DRs and questions they print are already committed, so a stored copy would only duplicate them and add a commit to every DR or question action. Output is byte-deterministic.

**変更管理台帳.xlsx**
- No 表紙 or 改訂履歴 (a register is a living list, not a versioned deliverable); the workbook starts with sheet 変更管理台帳: No., 変更管理番号 (DR id), 起票日, 変更区分 (trigger label of 改訂理由), 件名 (description, first line), 状態 (起票 / 承認 / 反映済 / 完了; a closed DR without impact analysis prints 却下), 承認者, 反映先文書 (affected documents, with `vN` once propagation revised them).
- One sheet per DR, named by its id: 変更管理票 laid out as a form: 変更管理番号, 起票日, 変更区分, 状態, 変更内容 (description), 判断 (decision), 理由 (rationale), 影響範囲 (impacted items, with their display code when it differs), 反映結果 (document and version per affected document), 工数・納期への影響 (（手入力）), 承認者, stamp box 承認 / 確認 / 起票.

**QA管理表.xlsx**
- One sheet QA管理表: No., QA番号, 工程 (the stage's document name), 起票日, 起票元 (作成担当 / QAレビュー指摘), 質問内容, 参照箇所, 回答, 回答者, 回答日, 状態 (未回答 / 回答済 / 取下げ), 関連変更管理番号 (DR id).

CLI `masterba export changes|questions --project P [--out f.xlsx]` (default file `<project>_<name>.xlsx`); API `GET /api/projects/{pid}/registers/{changes|questions}.xlsx` (viewer role, file name in `filename*`). The dashboard links are not part of this spec (the 成果物 view is being reworked separately).

## 5. Compatibility

- Default shells and `.template.json` files are regenerated; cells of content sheets move (columns), so existing projects get one new commit per workbook at their next render.
- Calibrated company templates keep their own bindings and are not affected. The new header sources and `$code` / `$verifies_name` / `$questions` are available to them.
- The browser preview reads the default layout and follows it.
- `rendering/preview.py` shows 目次 and 消化状況 as plain tables, so the dashboard needs no change.

## 6. Acceptance criteria (part A)

- [x] Every default workbook has 表紙, 改訂履歴, 目次 as its first three sheets, and every other sheet has the header band with システム名, 文書名, 文書番号, 版数, シート名, 作成日, 更新日, 状態.
- [x] A basic design item of kind `screen` and number 12 prints `SCR-0012` on 画面一覧; the code depends only on the item ref and kind, so a DR revision keeps it.
- [x] 改訂履歴 of a v2 lists the sheets whose items changed in 改訂箇所.
- [x] BRD and SRS print the stage's open questions on 未決事項; other stages' questions and answered questions are not listed.
- [x] 消化状況 holds `COUNTIF` / `COUNTA` formulas over テスト項目表 (checked as formula text; LibreOffice evaluates them).
- [x] `masterba export changes|questions` and the API write 変更管理台帳 (list and one 変更管理票 per DR) and QA管理表 (with the answer and its DR); exporting twice gives the same bytes.
- [x] A derived field outside its document type fails at template load.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass; the committed shells match the generator.

## 7. Part B (proposed, needs data)

Each needs a spec 01 amendment (optional field, old documents still load), writer prompt and QA checklist changes, and a live run to check quality:

1. `SrsItem.nfr_category`: IPA 非機能要求グレード 大項目 (可用性, 性能・拡張性, 運用・保守性, 移行性, セキュリティ, システム環境・エコロジー); 非機能要件一覧 sorts and groups by it.
2. `TestCaseItem.viewpoint`: 正常系 / 異常系 / 境界値, printed as 観点区分; 消化状況 adds a count per viewpoint.
3. Basic design kinds `report` (帳票一覧, RPT-), `batch` (バッチ一覧, BAT-), `message` (メッセージ一覧, MSG-: 区分, 文言, 表示先).
4. CRUD relation: basic design function, screen or batch to data entity with C/R/U/D, printed as CRUDマトリクス.
5. Sections `current_issues` (現状業務と課題, BRD), `glossary` (用語集, BRD), `system_overview` in 基本設計書, `test_overview` (テスト概要: 目的, 範囲, 環境, 合否判定基準) in test specifications.
