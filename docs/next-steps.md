# Next steps: from a working system to production

Status: proposal v0.3 (2026-11-10). Nothing here is implemented. Each phase below follows the repo's spec-driven process: a `specs/NN-*.md` is written and approved before any code. The previous plan (Phases 11 and 12) is implemented and kept in [archive/next-steps-phases-11-12.md](archive/next-steps-phases-11-12.md).

Spec numbers continue at 16. The number 14 is taken by work on the unmerged branch `claude/bd-architecture-team-process-7690de` (patch revisions for the design-test loop, a DR that starts a stage that has not run yet); decision O4 below settles what happens to it.

## 1. Where the project stands

The idea in [concept-design.md](concept-design.md) is built end to end: intake to BRD, SRS, Basic Design with IT and ST tests, and Detail Design with UT tests, each written by a writer, a tester where needed and a QA reviewer; deterministic gates; Excel rendering from JSON; a trace graph; Decision Records with impact analysis and propagation; customer questions; phase review gates; a local knowledge base; template calibration; a dashboard with three roles; containers and CI. The suite has about 680 tests at over 95% coverage.

The evidence that the documents are good enough to hand to a customer is thin:

| Evidence | What it shows | Where recorded |
|---|---|---|
| One full live run, `timesheet_ja.md` (77 lines), `kr/claude-opus-5.5`, 2026-11-03 | every stage can reach `done` with a strong model; 421,345 tokens; 20 customer questions | spec 11 section 10.3 |
| That run predates the review gates | the gated flow (approve, reject, revision run) has not run live | spec 15 |
| Basic Design on weaker gateway models | never reached `done` in 10+ runs; the tester oscillates between gate errors; the spec 14 branch scored 0 of 3 | spec 05 section 9, spec 11 section 11 item 7 |
| Template calibration | verified on synthetic samples only | spec 09 section 10 |
| Nobody outside the project has used it | no real intake, no real company template, no SIer reviewer has scored a document | |

In short, the machinery is proven and the product is not. Production readiness here means proving and fixing the product, then making it safe to run for a team.

## 2. What "production ready" means for MasterBA

A SIer delivery team uses MasterBA on a real engagement (the customer's own intake, the company's own templates, the model the company has a contract for) from intake to approved Detail Design and test specifications. The workbooks go to the customer after the usual human review and edits. Concretely, all of these hold:

1. **Quality is measured.** On a fixed benchmark (Phase 16), an SIer reviewer scores each document with a written rubric, and the scores meet a threshold the owner sets. A prompt or model change is judged against the same benchmark.
2. **Runs are reliable.** With the production model, each stage reaches `done` within its round limit in at least 4 of 5 runs per benchmark intake, including a large intake (300+ requirements). No run loses work: an escalated or interrupted run resumes.
3. **The workbooks fit.** They match the company template, show Japanese labels, carry a filled cover sheet (表紙) and revision history (改訂履歴), and no sheet says "pending".
4. **It operates like a service.** It installs from a runbook on the company's server behind TLS, has backups with a tested restore, upgrades without losing project data, and shows logs, job metrics and cost.
5. **Data handling is stated and controllable.** Which provider receives which text is configurable and documented, transcripts have a retention rule, and every decision has an audit trail.

## 3. Gaps found in this review

### A. Document quality and fit (the product)

| # | Gap | Source |
|---|---|---|
| A1 | No quality benchmark. One full live run exists; there is no way to tell whether a prompt or model change makes documents better or worse. `scripts/qa_issue_stats.py` counts QA rules but does not score documents. | spec 11 section 10.3 |
| A2 | No real company template has been calibrated. Real samples usually need merged data cells, multi-row headers or several tables per sheet, which the renderer lacks. | spec 02 open point 3, spec 09 open point 1 |
| A3 | Workbooks show English enum values (`functional`, `draft`) in Japanese documents; only the `scope` value map exists. | spec 11 open point 6 |
| A4 | The default templates have no 表紙 (cover, with author, approver, version, date) and no 改訂履歴 (revision history), which every Japanese SIer document carries. The data exists: document versions, reviews (`REV-####`) and DRs. | `rendering/catalog.py` |
| A5 | Sheets with no payload source say "pending": 背景・目的, 制約事項, システム概要, 結合テスト観点; diagrams say 別途添付. The payload has no document-level sections. | spec 02 open point 1, spec 03 open point 4 |
| A6 | Matrices a reviewer expects are not derived: CRUD (function by table), screen transition, the RTM as a workbook. They can be computed from items and links without a model. | concept-design section 8 |
| A7 | Exclusions of test documents live in the JSON only; no 除外項目 sheet. | spec 05 open point 1, spec 09 open point 3 |
| A8 | No UAT stage: the template exists, nothing generates it, so the top of the V's right side is empty. | archived plan 11.2 item 8 |

### B. Agent runs: reliability and scale

| # | Gap | Source |
|---|---|---|
| B1 | Convergence of the design-test loop depends on a strong model. The tester rewrites its whole list each round and swaps one gate error for another; TS-01 (a test asserting an outcome the upstream leaves open) was the main reason for escalation on the spec 14 branch. | spec 11 open point 7, spec 14 branch |
| B2 | Scale. 67 SRS items made a 61 KB tester prompt that timed out at 180 s and needed 900 to 1800 s. Real systems have hundreds of requirements; the writers, the tester and the DR reviser all receive whole documents. | spec 11 section 10.3, spec 07 open point 2 |
| B3 | Attempts whose answer does not fit the schema are recorded as 0 tokens, so cost is under-reported. | spec 12 section 21 |
| B4 | The supported models are not stated. Prompts were tuned on one strong model through a gateway. | spec 11 section 10.3 |
| B5 | A person can change a document only through a DR, and propagation always calls the model reviser. A typo fix costs a model call and may change more than intended. | `change/propagate.py` |

### C. Operations

| # | Gap | Source |
|---|---|---|
| C1 | The dashboard binds to 127.0.0.1 with no TLS; there is no documented reverse proxy setup, so it cannot be shared with a team safely. | architecture 6.7 |
| C2 | All state is one git work tree on one disk. Nothing pushes it to a remote, there is no restore drill, and checkpoints stay on one machine. | spec 08 open point 3, spec 11 open point 1 |
| C3 | Stage runs execute in a thread of the web process; a restart interrupts them (they can resume, but a person has to notice). | architecture 6.3 |
| C4 | No structured logs, no metrics, no alerting. A job keeps its last 200 log lines. | `api/jobs.py` |
| C5 | No release process: no version policy or changelog, the image is not published, and there is no migration path when `project.json` or a payload model changes beyond adding a defaulted field. | spec 11 open point 3 |
| C6 | Accounts are local and managed only from the CLI; no SSO, no password reset in the dashboard. The concept deferred SSO on purpose. | concept-design 13.2 |
| C7 | No dependency audit or SBOM in CI. | `.github/workflows/ci.yml` |

### D. Cost and data governance

| # | Gap | Source |
|---|---|---|
| D1 | Cost is tokens per run only. There is no price table, no total per project and no budget across runs (one full chain cost 421k tokens before review revisions). | spec 11 section 10.3 |
| D2 | Intake text, design content and knowledge passages go to whatever endpoint `ANTHROPIC_BASE_URL` names. Japanese enterprise customers often require a contracted provider or data residency; the options and what is sent are not documented. | architecture 6.2 |
| D3 | `transcripts/` keep full prompts and answers on disk with no retention rule. | spec 04 decision 6 |

### E. Use by a BA team

| # | Gap | Source |
|---|---|---|
| E1 | The intake upload accepts `.txt` and `.md` only, while customers send `.docx`, `.pdf`, `.xlsx` and mail. The knowledge base already has extractors for these. | spec 03 open point 2, spec 08 open point 4 |
| E2 | A real engagement often starts mid-way, with a BRD or SRS already written in Excel. There is no import into the JSON store. | |
| E3 | The dashboard is in English (`lang="en"`); the users are Japanese SIer staff. | `frontend/index.html` |
| E4 | Customer questions cannot be added by hand or exported for the customer meeting, and nobody is notified when a run raises them. | spec 13 open points 2 and 3 |

## 4. Phases

Each phase has its own spec. Phase 16 comes first because every later change is judged by it.

### Phase 16: quality benchmark (`specs/16-quality-benchmark.md`)

Answers A1, B3, B4.

1. A benchmark set under `benchmarks/`: four intakes of different size and language (the existing `timesheet_ja.md` and `hrm_employee_ja.txt`, one English intake, and one large Japanese intake of 300+ requirements), plus one real anonymised intake as soon as the pilot partner provides one. Each comes with the review decisions a person would take at each gate, so the gated flow runs unattended.
2. `scripts/benchmark.py` runs the chain N times per intake on a named model and writes one record per run: result per stage, rounds, resumes, gate errors and QA rules by count, tokens (fixing B3), duration and cost.
3. A scoring rubric per document type (completeness against upstream, correctness, testability, Japanese business style, fit to IPA structure), scored 1 to 5 by an SIer reviewer through a small form, stored next to the run records. A model may pre-score, but the threshold applies to human scores.
4. A supported-models table in the README, filled from benchmark results: which models are supported for which role.

Acceptance: a baseline report for the current `main` on the production model, with done-rate, tokens and human scores, committed under `benchmarks/results/`.

### Phase 17: convergence and scale (`specs/17-convergence-and-scale.md`)

Answers B1, B2, and decision O4 on the spec 14 branch. Every change is measured on the Phase 16 benchmark against the baseline.

1. Chunked generation. Writers, the tester and the reviser work on one slice at a time (by item kind or by feature group from the BRD), with the slice's upstream items and the titles of the other slices' items for context. Gates run per slice and once over the whole document (coverage, unique titles, links). Ids stay stable because only code assigns them.
2. Incremental test revision. The tester returns changes to its case list (add, update, remove, the `RevisionPatch` shape spec 07 already has) instead of a whole new list, so fixing one gate error cannot break another item. Take what the spec 14 branch proved useful; drop the rest.
3. TS-01. The tester receives the open questions of its upstream items explicitly and must write either a case for the stated part or an exclusion naming the open fact; the gate checks that an expected result does not assert the subject of an open question.
4. Request limits per stage from the measured prompt sizes instead of one global timeout.

Acceptance: on the production model, every benchmark intake, the large one included, reaches `done` in at least 4 of 5 runs per stage, and no stage needs a timeout above 600 s.

### Phase 18: deliverable fit (`specs/18-deliverable-fit.md`)

Answers A2 to A7, B5, E1, E3. Can run in parallel with Phase 17; it does not touch the loops.

1. Japanese value maps for every enum in the default templates (A3).
2. 表紙 and 改訂履歴 sheets in every default template, filled by code from the document, its versions, reviews and DRs (A4). The calibration heuristic learns to map these sheets in company samples.
3. Document-level sections in the payloads (背景・目的, 制約事項, システム概要, 結合テスト観点), written by the stage writer from upstream material and checked by the citation gate like items (A5). A spec 01 amendment, in its own commit.
4. Derived sheets with no model: CRUD matrix, screen list with transitions where design items name them, RTM workbook, 除外項目 (A6, A7). Diagrams: decision O8.
5. Renderer support for merged data cells, multi-row headers and several tables per sheet, built against the first real company sample; then that sample calibrated, previewed and confirmed (A2).
6. Direct edits: a DR whose patch a person writes in the dashboard (one item, one field), checked by the same gate, versioned and reviewed like a model revision, with no model call (B5).
7. Intake upload of `.docx`, `.pdf`, `.xlsx` and `.eml`, reusing `knowledge/extract/` to produce numbered text; the stored intake is that text, so citations keep working (E1).
8. Dashboard in Japanese with English as an option: strings moved to one catalog per language, chosen per user (E3).

Acceptance: an SIer reviewer compares the workbooks of one benchmark intake, rendered into the pilot company's confirmed templates, with that company's own documents and records which differences remain; no default sheet shows a pending note.

### Phase 19: operations (`specs/19-operations.md`)

Answers C1 to C5 and C7.

1. Deployment recipe: Compose with a reverse proxy (Caddy) terminating TLS, the app published only to the proxy, secure cookies, and the security headers kept (C1).
2. Backups: after each business commit, or on a schedule, the work tree is pushed to a configured git remote; `masterba backup check` verifies the remote is current. A restore drill (clone, `doctor`, resume an interrupted run) is part of the runbook and of CI on a sample project (C2).
3. A worker process: stage runs and propagations move out of the web process into a `masterba worker` service that takes jobs from `.masterba/jobs/`; the web process only submits and reads. Still one job per project and one writer per work tree (C3, decision O6).
4. Structured JSON logs with the job id and run id on every line, and a `/api/metrics` endpoint (jobs by status, run durations, tokens and cost per project) (C4).
5. Releases: semantic versions, a changelog, the image published to a registry by digest, and a `schema_version` in `project.json` with `masterba migrate` for changes that are not additive (C5).
6. CI: `pip-audit`, an SBOM of the image, and image scanning (C7).
7. A runbook: install, first admin, upgrade, restore, rotate the session secret and the model key, read logs, resume interrupted runs.

Acceptance: a person who has not worked on the project installs it on a fresh server from the runbook, serves it over TLS, runs the benchmark chain, restores the project from the remote onto a second machine, and resumes an interrupted run there.

### Phase 20: cost and data governance (`specs/20-governance.md`)

Answers D1 to D3, C6, E4.

1. A price table per model in the server configuration; cost per call, run, stage and project in the run records and the dashboard; a project budget with a warning level and a hard stop that escalates the run like any other limit (D1).
2. Provider profiles: the Anthropic API, Claude on AWS Bedrock and on Google Vertex AI (both have Japanese regions), and an Anthropic-compatible gateway. The `LLM` protocol stays; each profile is one class. A data-handling section in the README states what text leaves the server at each stage (D2, decision O1).
3. Optional masking of personal data in the intake (names, mail addresses, phone numbers) before it reaches a prompt, with the mapping kept locally so the stored documents show the real values (decision O9).
4. Transcript retention: a configured age after which `transcripts/` of finished runs are deleted; checkpoints of escalated runs are kept until the run is resumed or closed (D3).
5. Sign-in through OIDC (Entra ID, Google Workspace, Keycloak) mapped to the three roles, local accounts kept for small installs (C6, decision O7).
6. Customer questions: add by hand, export the open ones as an Excel 質問管理表 for the customer meeting, and notify approvers by mail or a webhook when a run raises questions or ends (E4).

Acceptance: a benchmark run on the provider chosen in O1 shows its cost per stage in the dashboard and stops at a hard budget, and a person signs in through OIDC.

### Phase 21: pilot on a real engagement

Not a spec but a review record (`docs/pilot-001.md`). A partner SIer team runs one real engagement, or replays a finished past one, through MasterBA with its own templates and model, while delivering the usual way in parallel. Recorded: effort with and without MasterBA per document, the reviewer's rubric scores, every edit the team had to make after generation, the questions MasterBA raised against the questions the customer actually had to answer, and incidents. The edits become benchmark cases and the next round of prompt and checklist work.

Production ready is declared when the pilot meets the criteria of section 2 and the owner accepts the record.

### After the pilot

- UAT stage (A8): `run uat` from the BRD, reusing `run_design_test_team` with the BRD as the design side and a `uat.toml` checklist; links `verifies`. Size M. It moves before the pilot if the pilot partner needs it (decision O5).
- Import of existing workbooks (E2): the calibration mapping read in reverse, each row becoming an item with a stable id and a `derives_from` link to the imported file. Size M.
- Phase 10 (code generation), as in [../specs/10-dev-extension.md](../specs/10-dev-extension.md), only when a pilot asks for it.

## 5. Order and size

| Step | Size | Depends on |
|---|---|---|
| Owner decisions O1 to O4 | S | nothing; blocks the Phase 16 baseline and Phase 17 |
| Phase 16: benchmark set, runner, rubric, baseline | M | O1, O2 |
| Phase 17: convergence and scale | L | Phase 16 baseline, O4 |
| Phase 18 items 1 to 4 and 6 to 8 (labels, cover, sections, derived sheets, edits, intake formats, Japanese UI) | M | nothing; in parallel with Phase 17 |
| Phase 18 item 5 (renderer features, first real template) | M | O3 (a real sample) |
| Phase 19: operations | M | nothing; in parallel with Phases 17 and 18 |
| Phase 20: governance | M | O1, Phase 19 item 4 (metrics) |
| Phase 21: pilot | L (calendar time) | Phases 16 to 20, O3 |

Phase 18 items that need no real sample, and all of Phase 19, can start at once, alongside the Phase 16 spec.

## 6. Decisions for the owner

| # | Decision | Why it matters |
|---|---|---|
| O1 | The production model(s) and provider, and whether data must stay in Japan | fixes the benchmark model, Phase 17 tuning and the Phase 20 provider profiles |
| O2 | Who scores the benchmark (an SIer reviewer), and the threshold score | without a human score, "good enough" stays undefined |
| O3 | The pilot partner, one real anonymised intake and one real company template | the critical path; A2 and the pilot cannot start without them |
| O4 | The spec 14 branch: merge parts into Phase 17, or close it | it holds 12 commits of convergence work and is 80 commits behind `main` |
| O5 | UAT in the first production release or after it | completes the V; size M |
| O6 | A separate worker process (Phase 19 item 3), or runs kept in the web process for small installs | operational simplicity against robustness |
| O7 | OIDC in the first release, or local accounts only | depends on the pilot partner's IT rules |
| O8 | Diagrams: generate Mermaid diagrams rendered as images in the workbook, or keep "attached separately" | Japanese reviewers expect 構成図, 業務フロー図 and ER図; generated diagrams are a new kind of output to check |
| O9 | Masking of personal data in intakes: required, optional, or not needed | depends on O1 and the customers' contracts |
| O10 | Hosting: one installation per SIer company on its own server, or a shared service for several companies | a shared service needs tenant isolation, which the single-work-tree design does not have |

## 7. Risks

- **The benchmark shows the documents are not good enough.** That is the purpose of Phase 16; it is cheaper to learn before the pilot than during it. Phases 17 and 18 are sized for prompt, checklist and structure changes, not a redesign.
- **The production model differs from the one the prompts were tuned on.** Phase 16 records results per model; the supported-models table lists only what was measured.
- **No real template or intake arrives.** Phase 18 item 5 and the pilot wait; everything else proceeds. The synthetic benchmark keeps the work honest but cannot replace O3.
- **Chunked generation breaks consistency across items.** The whole-document gate and QA pass stay, and the benchmark scores catch regressions.
