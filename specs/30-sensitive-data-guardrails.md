# Spec 30 — Sensitive-data guardrails

Status: v0.1 (2026-11-28), from the owner's proposal "Guardrails chống lộ thông tin nhạy cảm" (approved 2026-11-28 with every recommended option: personal data is masked before a model call and restored in the output; documents keep the real personal data and secrets are always blocked; transcripts are kept 30 days; only a global admin may switch masking off; public template sets that show findings become private; no model-based name recognition in this phase). Sources: [11-hardening.md](11-hardening.md), [12-local-rag.md](12-local-rag.md), [23-multi-user-and-usage-limits.md](23-multi-user-and-usage-limits.md), [24-admin-console.md](24-admin-console.md), [29-template-library.md](29-template-library.md).

## Goal

Customer data leaves MasterBA on five roads: model requests (often to a third-party gateway), run transcripts and checkpoints on disk, job and escalation messages, template sets shared with other users, and the documents and git history themselves. This spec puts one deterministic guard on each road. No rule calls a model.

## Non-goals

- Recognising person or company names without a list (named-entity recognition). A project lists such words itself (section 2.3).
- Rewriting git history that already holds a secret. `masterba guard scan --history` finds it; removing it is an operator task.
- Encrypting files at rest.

## 1. Detector (`guard/detect.py`)

`find(text, terms=()) -> list[Finding]` returns non-overlapping findings in text order. A `Finding` has `kind`, `category` (`secret`, `pii` or `term`), `start`, `end`, `value` and the 1-based `line`.

| kind | category | rule |
| --- | --- | --- |
| `private_key` | secret | a PEM block `-----BEGIN … PRIVATE KEY-----` to its `END` line |
| `anthropic_key` | secret | `sk-ant-` and 20 or more key characters |
| `openai_key` | secret | `sk-` (also `sk-proj-`) and 32 or more key characters |
| `aws_key` | secret | `AKIA` or `ASIA` and 16 capitals or digits |
| `github_token` | secret | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` and 36 or more characters, or `github_pat_` |
| `slack_token` | secret | `xoxb-`, `xoxp-`, `xoxa-`, `xoxr-`, `xoxs-` and 10 or more characters |
| `google_key` | secret | `AIza` and 35 key characters |
| `jwt` | secret | three base64url parts, the first two starting `eyJ` |
| `credential` | secret | the value after `password`, `passwd`, `pwd`, `secret`, `token`, `api_key`, `apikey`, `access_key`, `パスワード` and `:`, `=` or `：`, when it has 8 or more ASCII characters with a letter and a digit |
| `email` | pii | an e-mail address |
| `phone` | pii | a Japanese number (`0` and 9 or 10 digits, hyphens allowed, or `+81`), or a Vietnamese mobile (`0` or `+84`, then 3, 5, 7, 8 or 9 and 8 digits) |
| `my_number` | pii | 12 digits (in one run or 4-4-4) whose check digit is right |
| `card` | pii | 13 to 19 digits (groups of 4 separated by a space or hyphen allowed) passing the Luhn check |
| `ipv4` | pii | four dotted numbers 0 to 255, not part of a longer dotted number or version |
| `term` | term | a word from the project's `masking_terms`, case-insensitive |

Digits that are part of a MasterBA id (`REQ-0001`, `DOC-BRD-0001`, `KB-0001#chunk.2`, `L3-L5`), a date or a plain amount never match: number rules need a non-digit, non-letter boundary on both sides and a leading `0` (phones) or a check digit (My Number, cards). A secret wins over an overlapping personal-data finding; a longer finding wins over a shorter one.

`preview(finding)` shows a finding without its value: a secret as its kind only, an e-mail as `t***@e***.com`, other values as their first and last character around `***`.

## 2. Masking model calls

### 2.1 `Masker` (`guard/mask.py`)

A `Masker(pii=True, terms=())` keeps one table per run: each distinct value gets a stable token `⟦KIND-n⟧` (`⟦EMAIL-1⟧`, `⟦SECRET-2⟧`, `⟦TERM-1⟧`).

- `mask(text)` replaces every secret, and every personal-data and term finding when `pii` is true. Newlines inside a finding (a PEM block) are kept after the token, so line numbers and line citations do not move.
- `redact(text)` replaces every finding whatever `pii` says; it is used for anything written to disk.
- `unmask(text)` puts personal-data and term values back. A secret token is never put back: a document can print `⟦SECRET-1⟧`, never the secret.
- `unmask_model(value)` applies `unmask` to every string of a Pydantic value and validates it again.

### 2.2 Where it runs

- `RecordingLLM` (every team call of every stage and of DR propagation): the confirmed facts are added, the user prompt is masked, the masked prompt is logged, the inner model gets the masked prompt, and the answer is unmasked before any gate sees it. The gates (quote checks, citations) therefore compare real text with real text.
- `Team.log` (every transcript file, including artifacts written with `Team.write`) passes its text through `redact`.
- Calibration (`calibration/suggest.py`): the sample profile sent to the model is masked with a `GuardedLLM(inner, Masker())`.
- The system prompt is MasterBA's own text and is not masked.

### 2.3 Project settings (`ProjectConfig`)

- `pii_masking: bool = True` — also true for `project.json` files written before this spec. False masks only secrets.
- `masking_terms: list[str] = []` — at most 200 words of 2 to 80 characters (customer names, product names, internal codes). Terms are masked and restored like personal data.

API `POST /api/projects/{pid}/settings/guard` with `{pii_masking, masking_terms}` (project admin). Switching `pii_masking` from true to false needs a global admin (403 otherwise). Each change writes the audit row `project.guard` with the new value and the number of terms (not the terms). CLI: `masterba guard settings --project P [--pii on|off] [--term WORD ...] [--clear-terms]` (actor `cli`).

## 3. Inputs

### 3.1 Prompt injection through the intake

`number_lines` (the only way intake text reaches a prompt) replaces `<` with `‹` where it starts a tag (`<` followed by an optional `/` and a letter), so an intake cannot close `<intake>` or open a block of its own. `validate_draft` accepts an evidence quote that matches either the stored lines or the neutralised lines. Confirmed facts and open questions were already neutralised (spec 13), the knowledge block already escaped (spec 12).

### 3.2 Uploads

`guard.upload.scan_upload(name, data) -> UploadScan` extracts text the way the intake and the knowledge base do (UTF-8 for `.txt`/`.md`, the extractors for `.docx`, `.pdf`, `.xlsx`; a file that cannot be read is left to the existing checks).

- Intake upload (`POST /projects/{pid}/intake`): any secret refuses the file (400, `the file contains a secret (<kind>, line <n>); remove it and upload again`). Personal data is accepted; the response carries `findings` (kind, line, preview, at most 50) and the dashboard shows them as a warning.
- Knowledge base (`add_sources`, `replace_source`): a secret refuses the file with the same message (a refusal of kind `secret`).
- `run_brd` refuses an intake that contains a secret before any model call (`InvalidDocumentError`), so the CLI is covered too.
- Answering a customer question refuses an answer that contains a secret.

## 4. Logs, transcripts and errors

- `guard.scrub(text)` = `redact` plus URLs with a user name or password (`https://user:pass@host` → `https://***@host`) and `Authorization`, `x-api-key` and `api-key` header values.
- `request_failed` and `unusable_answer` (escalation reasons that are committed in `team-summary.json`), job errors and job log lines (`.masterba/jobs/`) and the calibration message about an unusable model are scrubbed.
- Retention: `guard.prune_transcripts(root, days)` deletes transcript files older than `days` under `projects/*/runs/*/transcripts/`. `days` comes from `MASTERBA_TRANSCRIPT_DAYS` (default 30; 0 keeps everything). It runs when the API app starts and with `masterba guard prune`. Checkpoints stay, because a stopped run resumes from them.

## 5. Template sets

- `build_shell` also removes cell comments, clears the workbook's descriptive properties (title, subject, keywords, description, category, company, manager) and empties every cell left in the shell whose text has a finding. The cells it emptied are listed as calibration warnings.
- The customer sample (`<TYPE>.sample.xlsx`) is no longer committed and is not copied by a clone; it stays on the server disk so the mapping can be edited again. It is gitignored. Samples already committed (the synthetic `sample-sier` set) stay.
- `guard.templates.set_findings(root, set_id)` scans the shells (every sheet, hidden ones included, and comments), the definitions and the calibration records of a set.
- A set with findings cannot be made `shared` or `public` (`TemplateAccessError`, 400 with the first findings). Making it private is always allowed.
- When the API app starts, every shared or public set with findings becomes private, with the audit row `template.private_by_guard` (actor `system`).

## 6. Scan (`masterba guard scan`)

`masterba guard scan --project P [--history] [--json]` scans the project's stored intakes, documents, decision records, questions, knowledge sources and transcripts (and with `--history` every version of the project's files in git). It prints one line per finding (path, line, kind, preview), never a value, exits 1 when a secret is found, and writes the audit row `guard.scan` with the counts. `masterba doctor` adds the check `guard`: a warning when any project holds a secret in its stored files.

## 7. Dashboard

- Intake upload: a warning lists the personal data found (kind, line, preview) and says it is masked before each model call when masking is on.
- Project settings: a row "Data protection" shows the masking state and the term list; an admin edits the terms; only a global admin sees the switch-off action.
- Japanese text for every new string (`i18n-ja.js`).

## 8. Tests

- Detector: positives for every kind, negatives for MasterBA ids, dates, amounts, versions, line refs and normal Japanese text.
- Masker: stable tokens, line counts kept, secrets never restored, `unmask_model` on nested models.
- A BRD run with the fake model over an intake that holds an e-mail, a phone number and a term: the model never receives the values, the stored document holds them, the transcripts do not.
- Intake with `</intake>`: the prompt holds `‹/intake`, and a quote of that line is accepted.
- Uploads with a secret are refused (intake and knowledge base); PII findings are returned.
- Scrubbing of escalation reasons and job errors; transcript pruning.
- Template shell cleaning; sharing refused for a set with findings; the start-up downgrade.
- Settings API: admin-only switch-off and the audit row; scan CLI exit code.
