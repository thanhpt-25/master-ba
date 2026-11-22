# Pilot guide

For the team trying MasterBA on one real project. Japanese version: [pilot-guide.ja.md](pilot-guide.ja.md).
Server setup: [deployment-runbook.md](deployment-runbook.md). Scoring: [scoring-checklist.md](scoring-checklist.md).

## What MasterBA does

You give it the customer's requirements (text, Word, PDF or Excel). It writes the V-model
documents one phase at a time as Excel workbooks in a standard Japanese SIer layout:

| Phase | Documents |
|---|---|
| 業務要件定義 (BRD) | 業務要件定義書 |
| システム要件定義 (SRS) | システム要件定義書 |
| 基本設計 | 基本設計書, 結合テスト仕様書, 総合テスト仕様書 |
| 詳細設計 | 詳細設計書, 単体テスト仕様書 |

In each phase a writer agent drafts, deterministic checks reject unsupported content (every
requirement must quote the intake line it comes from), and a QA agent reviews the draft. Then a
person on your team reviews the phase and approves it or sends it back with comments. Nothing
moves to the next phase without that approval.

## Roles

| Who | Role in MasterBA | Does |
|---|---|---|
| Pilot lead | admin | creates the project, manages accounts, watches cost |
| Reviewers (PM, lead engineer) | approver | uploads the intake, runs phases, answers customer questions, approves or rejects, decides Decision Records |
| Others | viewer | read documents and traceability |

## Week one

| Day | Step | Who |
|---|---|---|
| 1 | Pick one real, small requirement set (5 to 30 pages). Remove names and data the customer does not allow to leave the company. | lead |
| 1 | Create the project (Projects, New project; document language 日本語). | admin |
| 1 | On the Overview, follow 次の作業: upload the intake and run 業務要件定義. | approver |
| 1-2 | Answer the customer questions the agents raise (顧客確認事項). Ask the customer where you cannot answer. | approver |
| 2 | Open the 業務要件定義書 from 次の作業, read every sheet, then approve or reject with comments. Fill in the scoring sheet. | approver |
| 3 | Run システム要件定義, review, score. | approver |
| 4-5 | Run 基本設計 (with the IT and ST test specifications), review, score. | approver |
| 5 | Send the scoring sheets and the five most important review comments to the MasterBA team. | lead |

Detail Design can follow in week two once Basic Design is approved.

## Working in the dashboard

- **次の作業 (Next step)** at the top of the Overview always shows the one thing the project
  waits for, with its button. If you are unsure what to do, start there.
- **Reviewing**: open the document, go through the sheet tabs (表紙, 改訂履歴, the content sheets,
  トレーサビリティ), and download the Excel file if you want to read it there. At the end of the page:
  - 承認 (approve) when the document can go to the customer as is or with small edits you make
    yourself.
  - コメントを付けて差し戻す (reject with comments): one comment per line. Start a line with an item
    id, such as `DOC-SRS-0001#item.3: split this into two requirements`, to tie it to that item. The
    agents revise only what the comments touch and write a new version for review.
- **Customer questions**: an agent never guesses an answer only the customer can give; it raises a
  question instead. Record the answer with who gave it and where (for example "田中様, 11/25 定例").
  The answer becomes a confirmed fact for every later phase.
- **Changes after approval**: raise a Decision Record (変更管理). It shows the impact across the
  documents before you approve it; approving and propagating writes new versions of every affected
  document, with the reason in each 改訂履歴.

## Good to know

- An intake converted from Word, PDF or Excel is stored as text; requirements cite its lines. Check
  the converted text in the BRD's 出典 column if a citation looks wrong.
- The cover's stamp boxes (承認・確認・作成) are left empty for your seals.
- 判定, 実施日, 実施者 and 不具合ID in the test specifications are for your testers; they are
  cleared when the workbook is rendered again, so keep test results in a copy.
- A run that cannot agree stops (エスカレーション) instead of producing a weak document. Resume it
  once from 次の作業, or tell the MasterBA team.

## What to send back

1. The filled [scoring checklist](scoring-checklist.md) for each phase.
2. The review comments you gave when rejecting.
3. Anything a customer would not accept in the workbook layout (missing sheet, wrong column, wording).
4. How long each review took compared with writing the document by hand.
