# Sensitive-data guardrails

MasterBA reads customer RFPs, writes documents from them, and sends text to a model that is often reached through a third-party gateway. Spec 30 ([../../specs/30-sensitive-data-guardrails.md](../../specs/30-sensitive-data-guardrails.md)) puts one deterministic guard on each road the data can leave by. No guard calls a model. The code is in `src/masterba/guard/`.

## Where data can leave, and the guard on each road

```
upload ──► scan_upload ──► secret? refuse : store (personal data reported)
                                   │
intake / knowledge / answers ──► prompt ──► RecordingLLM ──mask──► model (tokens only)
                                                 ▲                    │
                                                 └──── unmask ◄───────┘
                                                 │
                                     gates, documents (real values; secrets stay tokens)
                                                 │
                         Team.log ──redact──► transcripts (deleted after 30 days)
errors ──scrub──► team-summary.json, .masterba/jobs/*.json, dashboard
template set ──clean_workbook──► shell; findings? stays private
```

| Road | Guard | Code |
|---|---|---|
| Model request | `Masker.mask` replaces secrets, personal data and the project's terms by tokens like `⟦EMAIL-1⟧`; the answer is restored before any gate | `guard/mask.py`, `team/workspace.py` `RecordingLLM`, `calibration/suggest.py` |
| Prompt injection | `number_lines` turns a tag start `<x` into `‹x`, so the intake cannot close `<intake>` | `agents/requirements_analyst.py` |
| Upload | A secret refuses an intake, a knowledge file, a question answer and a BRD run; personal data is reported on intake upload | `guard/upload.py`, `api/routes_projects.py`, `knowledge/store.py`, `questions/answer.py`, `pipeline/brd.py` |
| Transcripts | `Team.log` writes `redact`ed text; files older than `MASTERBA_TRANSCRIPT_DAYS` (30) are deleted at server start and by `masterba guard prune` | `guard/retention.py` |
| Errors | `scrub` removes findings, URL credentials and auth headers from escalation reasons and job errors and logs | `guard/scrub.py`, `team/loop.py`, `api/jobs.py` |
| Template sets | The shell loses comments, descriptive properties and every cell with a finding; the customer sample is never committed or cloned; a set with findings cannot be shared and is made private at server start | `guard/templates.py`, `calibration/build.py`, `library/access.py` |
| Stored files | `masterba guard scan` (and the `guard` check of `doctor`) lists findings in a project's files and, with `--history`, its git history | `guard/scan.py`, `cli_guard.py` |

## Detection

`guard.find(text, terms)` returns non-overlapping findings. Secrets (API keys of common providers, private keys, JWTs, `password=` style values) are always blocked. Personal data covers e-mail addresses, Japanese and Vietnamese phone numbers, My Number and card numbers (with their check digits) and IPv4 addresses. Number rules need clean boundaries, so MasterBA ids (`REQ-0001`, `L3-L5`), dates and amounts never match. Names of people and companies are not recognised; a project lists the words to mask in `ProjectConfig.masking_terms`.

## Settings

`ProjectConfig.pii_masking` (default true, also for older projects) and `masking_terms` are changed in Project settings, `POST /api/projects/{pid}/settings/guard` or `masterba guard settings`. A project admin edits the terms; only a global admin may switch masking off. Every change writes the audit row `project.guard`. With masking off, personal data reaches the model as written, but secrets are still masked and transcripts are still redacted.

## What it does not do

- Documents keep the real personal data, because they are delivered to the customer. A secret is never restored into a document.
- Checkpoints keep real values, because a stopped run resumes from them; they are gitignored.
- A secret already in git history stays there; `guard scan --history` finds it and removing it is an operator task.
