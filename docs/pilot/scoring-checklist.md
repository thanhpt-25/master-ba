# Scoring checklist for a pilot run

Fill in one copy per phase (業務要件定義, システム要件定義, 基本設計, 詳細設計) of the pilot
project, so every run is scored the same way and runs can be compared. Japanese labels are kept
where the reviewer sees them in the workbook. Guide: [pilot-guide.md](pilot-guide.md) /
[pilot-guide.ja.md](pilot-guide.ja.md). Spec: [19-deliverable-fit.md](../../specs/19-deliverable-fit.md) section 20.

## 0. Agree the pass level before the first run

Agree these with the pilot lead **before** the first run and do not change them afterwards.

| Threshold | Suggested | Agreed |
|---|---|---|
| Lowest rubric score for any criterion | 3 | |
| Average rubric score | 3.5 | |
| Reviewer time compared with writing by hand | at most 50% | |
| Hand edits before the document can go to the customer | at most 1 per 10 items | |
| Missing sections (`masterba quality`) | none | |

A phase **passes** when every threshold is met. A phase that fails is still scored in full,
because the comments are what the next round of improvements is built from.

## 1. Run record

| Field | Value |
|---|---|
| Project / phase | |
| Document id and version (e.g. `DOC-SRS-0001` v1) | |
| Intake (name, pages or lines, original format) | |
| Run id (`RUN-####`), result (`done` / escalated), rounds | |
| Writer model / QA model | |
| Tokens used (run summary) | |
| Reviewer, date | |

## 2. Measured figures

Run on the server (the report is not in the dashboard yet):

```bash
docker compose run --rm masterba quality --project PRJ-001 --out quality-PRJ-001.md
```

Copy the line for this document:

| Figure | Value |
|---|---|
| Items | |
| Upstream traced (share of items with a link to the previous phase) | |
| Downstream traced (share of items with a link to the next phase, once it ran) | |
| Missing sections | |
| Style findings (STY-01 to STY-06), total and the most frequent rule | |
| Open customer questions | |

## 3. Reviewer rubric

1 = unusable, 3 = usable after normal review edits, 5 = hand to the customer as is. Give a note
for every score below 4, with an item id where possible.

| Criterion | What to check | Score (1-5) | Notes |
|---|---|---|---|
| 網羅性 (completeness) | Every upstream need is covered; nothing is missing or invented. | | |
| 正確性 (correctness) | Statements match the source; no contradiction, no wrong figure. | | |
| 検証可能性 (testability) | A tester can judge each item or case OK or NG. | | |
| 表現・用語 (wording) | One point per sentence, consistent terms, である style. | | |
| 構成 (structure) | Sheets and items sit where an IPA-style document puts them. | | |
| **Average** | | | |

## 4. Effort and edits

| Measure | Value |
|---|---|
| Reviewer time for this document (minutes) | |
| Estimated time to write it by hand (minutes, from the team's own past documents) | |
| Review comments given on reject (count; attach the text) | |
| Reject rounds until approval | |
| Hand edits made after approval before it could go to the customer (count) | |
| Of those: wrong content / missing content / wording / layout | / / / |
| Customer questions raised by MasterBA / of those, ones the customer really had to answer | / |
| Questions the customer had to answer that MasterBA did not raise | |

## 5. Verdict

| | |
|---|---|
| Pass level met? (yes / no, which threshold failed) | |
| The three most important problems | 1. <br> 2. <br> 3. |
| Would you send this document to the customer after your edits? (yes / no, why) | |
