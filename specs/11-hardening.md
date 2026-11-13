# Spec 11 — Hardening: QA signal, convergence, resume, CI, containers

Status: v0.5 (2026-11-03), v0.5: a failed model request escalates the run (1.6); implemented; the live runs of 2.3 reached `done` on the timesheet example (10.3); see sections 9 and 10. v0.3: CI run on GitHub, dry-run 1 recorded, QA rule for open upstream facts. v0.4: dry-run 4 on a Japanese HRM intake with the sample company, SRS prompt and checklist changes. Sources: [next-steps-phases-11-12.md](../docs/archive/next-steps-phases-11-12.md) Phase 11 (owner decisions in 12.5, item 6 for containers), [04-srs-qa-and-team-runtime.md](04-srs-qa-and-team-runtime.md), [05-basic-design-and-tests.md](05-basic-design-and-tests.md) section 9 (live findings 3 and 5), [08-dashboard.md](08-dashboard.md), [00-constitution.md](00-constitution.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

Make the existing pipeline dependable before Phase 12 changes prompts and gates. QA issues that do not ask for a change stop blocking a run, the design stages can finish on an ordinary model, an escalated run can continue instead of starting over, every push is checked, a new user can install and run the system in one step, and the whole system runs in containers with Docker Compose.

## Non-goals

- No new document type. UAT generation stays out of this phase and gets its own spec when the owner asks for it.
- No change to rendering, change management or calibration behaviour.
- No queue or multi-worker job runner; the dashboard keeps one job per project.
- No orchestration beyond Docker Compose (no Kubernetes manifests).
- No automatic tuning of prompts by a model; prompt changes are written by hand from recorded runs.

## 1. QA signal: blocking means "change this"

### 1.1 Problem

Live run 4 of spec 05 ended with one blocking issue whose own message said the test case "is acceptable as written" (spec 05 section 9, finding 3). Matching phrases such as "acceptable" in free text is unreliable across languages and wording, so spec 05 finding 5 left the fix open. This spec makes the model state the required change explicitly and lets code decide from that structure.

### 1.2 Report model

`QaIssue` (agents/qa_reviewer.py) gains two fields, and the JSON schema of `QaReport` is regenerated:

| Field | Type | Meaning |
|---|---|---|
| `action_required` | `str \| None` | The concrete change the writer must make, in one sentence. Required for a blocking issue to stay blocking. |
| `customer_question` | `bool`, default `false` | The issue cannot be fixed from the upstream document; only the customer can answer it. |

### 1.3 Deterministic normalisation

After `validate_report` and `cap_severity`, a new pure function `normalise_report(report) -> (report, notes)` applies, in this order:

1. A blocking issue with `customer_question = true` becomes advisory and is added to the stage's customer questions (1.4).
2. A blocking issue with an empty or missing `action_required` becomes advisory.
3. Every downgrade adds a note `"[<checklist_id>] <ref>: downgraded (<reason>)"`, posted to the mailbox from `qa` to `writer` with type `feedback`, so the run record shows each change.

The verdict is still computed (`QaReport.passed`); the model never sets it. The QA prompt (`agents/qa-reviewer.md`) is updated to explain both fields and to say that a blocking issue without an action does not count.

### 1.4 Customer questions in both loops

The design-test loop already keeps `unresolved` customer questions. The writer-review loop (team/loop.py) gains the same list, returned with the accepted draft. Both are written to the run summary: `TeamRun` gains `customer_questions: list[str]` (default empty, an additive schema change). The SRS stage merges them with the writer's own `open_questions`.

### 1.5 New blocking issues only in the first review

Dry-run 4 (10.3): on 30 requirements the Basic Design team raised about ten new blocking points in every round, some contradicting each other, and did not converge in 7 rounds and 378,007 tokens. A reviewer that samples a different part of the same draft each time never runs out of new points.

The rule, applied by the code and not told to the model: for each reviewed artifact (`draft`, `design`, `tests`) the first QA review of a run may raise any blocking issue. In every later review of that artifact, a blocking issue stays blocking only if the same pair (checklist id, item reference) was blocking in an earlier review; any other blocking issue becomes advisory with the note `[id] ref: downgraded (new after the first review)`. It stays in `advisory_issues` and in the mailbox. The pairs are saved in the checkpoint (`blocking_seen`, an additive field with an empty default), so a resumed run does not get a second first review: in dry-run 4 a resume that did restored the flood, with 35 new blocking points in one review.

The cost is accepted: a problem that a revision introduces and QA notices only later is reported but does not block, so a person reads the advisory issues. The gain is that a run ends when the issues of its first review are fixed.

### 1.6 A model answer that does not fit its schema

An `LLMOutputError` from a writer, designer or tester call (dry-run 4: a design item without `realizes`) is a gate error. It is posted as feedback (`the last answer could not be used: ...`), the round ends, and the same role is called again in the next round with its previous draft, so the round limit and the token budget still apply. The tokens of the failed call are charged when the model reports them (they are carried on the error). An unusable QA report keeps its own retry.

A model request that fails (timeout, connection, gateway error, `LLMError` other than `LLMOutputError`) ends the run as `escalated` with the reason `model request failed in <role>: <error>`, instead of raising out of the loop. The summary, tasks and mailbox are committed as for any escalation and the last validated drafts stay in the checkpoint, so `--resume` continues the run. Before this change such a run left a run folder with no summary and could not be resumed (2026-11-03: the tester call of a 67-item Basic Design timed out). A configuration error (`LLMConfigError`, for example a missing key) still raises before any call.

Request limits are set in the environment of the server or the CLI: `MASTERBA_REQUEST_TIMEOUT` (seconds per request, default 180) and `MASTERBA_MAX_TOKENS` (output tokens per call, default 16000). A large intake needs higher values for the Basic and Detail Design tester calls.

## 2. Convergence on ordinary models

### 2.1 Per-stage round limits

`ProjectConfig` gains `team_max_rounds_by_stage: dict[DocType, int]` (default empty). A stage uses its entry when present, otherwise `team_max_rounds`. `init-project` gains `--rounds STAGE=N` (repeatable). The dashboard project page shows the per-stage values read-only in this phase.

### 2.2 Prompt revisions from recorded runs

A script `scripts/qa_issue_stats.py` (development only, not part of the package) reads `runs/*/mailbox.json` of a project and lists QA issues by checklist id, stage and frequency. The designer, tester, detail and unit-test prompts are revised by hand to pre-empt the five most frequent issues of the recorded spec 05 runs. Each prompt change is listed in section 10 with the issue it targets.

### 2.3 Success measure

A live `run basic` and `run detail` on the demo intake reach `done` with a named model, recorded in section 10 with rounds, issues raised and resolved, and tokens. If a run still escalates, section 10 records which checklist ids blocked, and the phase is not accepted until it passes or the owner accepts the recorded result.

## 3. Resume after escalation

### 3.1 Checkpoint

Each round, after the gate passes and before QA, the loop writes `runs/RUN-####/checkpoint.json` (values below are illustrative):

```json
{
  "stage": "BASIC_DESIGN",
  "round": 4,
  "upstream": {"DOC-SRS-0001": 2},
  "drafts": {"design": {"...": "..."}, "tests": {"...": "..."}},
  "feedback": {"designer": ["..."], "tester": ["..."]},
  "customer_questions": ["..."],
  "tokens_used": 120000
}
```

The checkpoint holds drafts, not business data, and stays on the machine: the run's `.gitignore` lists it next to `transcripts/`. Nothing is written to the store on escalation, as before.

### 3.2 Command

```
masterba run basic --project PRJ-001 --resume RUN-0004 [--rounds N]
```

`--resume` is accepted for every stage (`brd`, `srs`, `basic`, `detail`). It:

1. refuses unless the run exists, belongs to the same stage, ended `escalated`, and has a checkpoint;
2. refuses if any upstream document listed in `upstream` now has a different latest version, or if the stage's target document already exists;
3. reopens the same `Team` (same run id), restores drafts, feedback, customer questions and token count, and runs up to `N` more rounds (default: the stage's round limit), with the token budget counting from the restored total;
4. on finish rewrites the summary and commits `run(<project>): RUN-#### <status> (resumed)`. `TeamRun` gains `resumed: int` (number of resumes, default 0).

The dashboard shows a "Resume" button on an escalated or waiting run that has a checkpoint. Waiting runs unlock only after every QA blocker question is answered or withdrawn. Dashboard resume adds one round by default; token usage remains cumulative.

## 4. Continuous integration

`.github/workflows/ci.yml`:

| Job | Runs on | Steps |
|---|---|---|
| `quick` | every push and pull request | `uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy src tests`, `pytest -m "not slow and not live" --no-cov` |
| `full` | push to `main`, and pull requests that touch `src/` or `tests/` | `pytest -m "not live"` with coverage |
| `image` | push to `main`, and pull requests that touch the Dockerfile, `compose.yaml` or `pyproject.toml` | build the image, run `masterba doctor` and the quick test job inside it, check that the image holds no key (5.3) |

A `slow` marker is registered in `pyproject.toml`. Tests are marked slow from measured durations (`pytest --durations=50`), not by guess; the target is a `quick` job under one minute on the CI runner. The `live` marker stays excluded everywhere.

## 5. Containers (Docker Compose)

### 5.1 Image

`Dockerfile`, multi-stage:

- builder: `python:3.11-slim`, `uv` copied from its official image, `uv sync --frozen --no-dev` (plus `--extra $EXTRAS` when that build argument is set; Phase 12 uses `EXTRAS=rag`);
- runtime: `python:3.11-slim` with `git` installed, the virtualenv and the source copied from the builder, a user `masterba` whose uid and gid come from the build arguments `UID` and `GID` (default 1000), working directory `/work`, `git config --system safe.directory /work`, entrypoint `masterba --root /work`.

`.dockerignore` excludes `.venv`, `.git`, caches, `projects/`, `.masterba/`, `.env` and test output, so neither data nor secrets reach the build context.

### 5.2 Compose

`compose.yaml` has one service:

```yaml
services:
  masterba:
    build: { context: ., args: { UID: "${UID:-1000}", GID: "${GID:-1000}" } }
    command: ["serve", "--host", "0.0.0.0", "--port", "8000"]
    ports: ["127.0.0.1:8000:8000"]
    env_file: [.env]
    environment:
      GIT_AUTHOR_NAME: "${GIT_AUTHOR_NAME:-MasterBA}"
      GIT_AUTHOR_EMAIL: "${GIT_AUTHOR_EMAIL:-masterba@localhost}"
      GIT_COMMITTER_NAME: "${GIT_AUTHOR_NAME:-MasterBA}"
      GIT_COMMITTER_EMAIL: "${GIT_AUTHOR_EMAIL:-masterba@localhost}"
    extra_hosts: ["host.docker.internal:host-gateway"]
    volumes: ["${MASTERBA_WORK:-./work}:/work"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
      interval: 30s
```

- The work tree is a bind mount, so the store stays a git repository the user can open on the host. `masterba doctor --init` (section 6) prepares it when the folder is empty.
- The port is published on 127.0.0.1 only. Exposing it further is the operator's choice and is documented with a warning: the dashboard has local accounts and no TLS.
- The CLI runs in the same service: `docker compose run --rm masterba run brd --project PRJ-001 --input intake.txt`.
- A model gateway on the host is reached as `host.docker.internal`; the README shows the `ANTHROPIC_BASE_URL` to use.

### 5.3 Secrets

Keys come only from `.env`, which is gitignored; a committed `.env.example` lists the variable names with empty values. The image never contains a key: the `image` CI job fails if `docker history` or a scan of the image filesystem finds `ANTHROPIC_API_KEY=` followed by a value, or a `.env` file.

### 5.4 Health endpoint

`GET /api/health` returns `{"status": "ok", "version": "<package version>"}` without authentication. It reads nothing from the store and reveals no project data.

### 5.5 Same code paths

The container fixes the runtime, the user and the paths; the application runs the same code as with `uv run`. Every test keeps running without Docker.

## 6. Install and onboarding: `masterba doctor`

`masterba doctor [--init]` prints one line per check and exits 0 when all required checks pass, 1 otherwise:

| Check | Pass condition | Fix printed on failure |
|---|---|---|
| git | `git` is on `PATH` and an author name and email resolve (git config or `GIT_*` variables) | how to set them |
| work tree | `--root` is inside a git work tree with at least one commit | `--init` runs `git init` and an empty commit, only when the folder is empty |
| templates | `templates/default/` has the eight template pairs and `load_template` accepts each | copy them, or regenerate with `python -m masterba.rendering.shells` |
| state | `.masterba/` is writable; at least one dashboard user exists (warning only) | `masterba user add` |
| model | `ANTHROPIC_API_KEY` is set (warning only; tests and the dashboard start without it) | the variables to export |

The README setup section gains the `doctor` step and the Docker Compose quick start.

## 7. Repository clean-up

- Remove `backend/` and `mcp-configs/`; each holds only `.gitkeep`. The backend lives in `src/masterba/api/`, and no MCP configuration exists yet.
- Amend `specs/00-constitution.md`, in Vietnamese as that file is written, with a dated note: the frontend is plain ES modules without a build step (decision of spec 08), and the two folders were removed by this spec. The toolchain table keeps its history.
- Bring the architecture section of `CLAUDE.md` up to the Phase 9 state.

## 8. Persistent dashboard jobs

- `JobManager` writes each job to `.masterba/jobs/<project_id>/<job_id>.json` on every state change and log line, by atomic replace: kind, status, start and end times, result, error and log lines.
- On startup it loads these files; a job that was `queued` or `running` becomes `interrupted` with the log line "server restarted". The project's job list shows past and interrupted jobs.
- The 50 newest jobs per project are kept; older files are deleted at startup.
- Still one running job per project, and an interrupted job does not block a new one. After an interruption the user resumes with `--resume` (section 3) if the run escalated, or starts a fresh run otherwise.

## 9. Acceptance criteria

- [x] `normalise_report` has unit tests for both downgrade rules and the note it posts; a regression test replays the spec 05 run 4 issue ("acceptable as written", no action) and the run finishes `done`; the `QaReport` and `TeamRun` schemas are regenerated and drift-tested.
- [x] Customer questions from both loops reach `TeamRun.customer_questions`, and the SRS stage merges them with `open_questions`.
- [x] `team_max_rounds_by_stage` overrides the default per stage and is set through `init-project --rounds`.
- [x] A blocking issue that is new after the first review of an artifact is downgraded to advisory, and a schema-invalid model answer is fed back to its role instead of ending the run (1.5, 1.6). *Implemented and unit tested; the first-review limit was checked on a live run (10.3, dry-run 5), the schema retry was not seen live.*
- [x] Live `run basic` and `run detail` reach `done` with a named model, recorded in section 10, or the owner accepts the recorded escalation (2.3). *Done 2026-11-03: the full run on `timesheet_ja.md` (60 requirements, 67 SRS items) reached `done` in every stage with `kr/claude-opus-5.5` (10.3). Dry-run 4 (30 requirements) had escalated in Basic Design after 7 rounds.*
- [x] `--resume` continues an escalated run with the fake model for every stage; it refuses a run that is done, of another stage, without a checkpoint, with a changed upstream version, or whose target document exists; the commit subject says `(resumed)`.
- [x] The CI jobs `quick`, `full` and `image` are green on `main`, and `quick` runs in under one minute. *(2026-10-31: run 41208337518, `quick` 32 s; 10.4.)*
- [x] `docker compose up` serves the dashboard on 127.0.0.1:8000 and the health check passes; `docker compose run --rm masterba init-project ...` and a fake-model stage run create commits visible in the host work tree, authored with the configured name; the container runs as a non-root user; no key is in the image. *A stage run in the container needs a model key and was not tried (10.5).*
- [x] `masterba doctor` passes on a prepared root, reports each failing check with its fix, and `--init` prepares an empty folder but refuses a non-empty one.
- [x] `backend/` and `mcp-configs/` are gone, spec 00 carries the dated amendment, and `CLAUDE.md` describes the current state (Phase 11).
- [x] Dashboard jobs survive a restart (interrupted jobs shown as such), and retention keeps 50 per project.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass. *(2026-10-31: 597 passed, coverage 97.55%.)*

## 10. Manual review record

### 10.1 Implementation decisions

1. The checkpoint is written after the gate passes, as specified, and written again after a QA review that blocks, so a resumed run gets QA's feedback and not only the draft.
2. The BRD stage records its upstream as `intake/<file name>: 1`; a stored intake never changes, and resume requires the same `--input` file. The dashboard offers Resume for SRS, Basic and Detail only, because a BRD run needs its intake file again.
3. A resumed run keeps the tasks and mailbox of the earlier attempt (its tasks stay `blocked`); the `done` check covers only the tasks of the resumed attempt. Escalation reasons start empty for each attempt, and the summary is rewritten.
4. The `--rounds STAGE=N` option accepts `brd`, `srs`, `basic`, `detail` or a document type such as `BASIC_DESIGN`.
5. `ensure_ready` accepts `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` in place of git config, which the container needs.
6. `doctor --init` also writes a `.gitignore` with `.masterba/` (users, session secret, uploads) and copies the default templates; without the copy the templates check would fail right after `--init`.
7. The image keeps the source at `/app` as an editable install, because prompts, skills, templates and the web app are found relative to the source tree. The image has no development tools, so the `image` CI job runs `doctor --init`, `init-project` and checks the commit author, the non-root user and the key scan, instead of the quick tests inside the image.
8. The `full` and `image` jobs run on `main` and on every pull request, without path filters; they run more often than specified, never less.
9. A job file that cannot be written is logged and does not fail the job; the run's results are already in git.

### 10.2 Prompt changes (2.2)

`scripts/qa_issue_stats.py` on the recorded spec 05 runs (RUN-0005 to RUN-0008, Basic Design): TS-04 18, TS-01 17, TS-02 15, TS-05 14, BD-01 12, TS-03 11, BD-04 8, BD-02 4.

| Prompt | Change | Targets |
|---|---|---|
| `basic-test-design.md` rule 1 | An IT case says which design item passes what to which; a user's journey is an ST case | TS-04 (IT cases written as user flows) |
| `basic-test-design.md` rule 3 | Where an item says wrong input or failure is rejected or handled, at least one error case on what is stated; every expected result is OK/NG | TS-02, TS-01 |
| `basic-test-design.md` rule 4 (new) | Non-functional cases only with a stated figure, otherwise an exclusion `no measurable criterion: ...` | TS-01, TS-05 (availability and performance cases that only observe) |
| `basic-design.md` rule 1 | `interface` only for a named external system, `data_entity` only for information an SRS item says is kept; non-functional items realised by the items they constrain | BD-01 (unrequested email interface and data entities) |
| `unit-test-design.md` rule 3, `detail-design.md` rule 1 | The same two rules at detail level | carried over; no recorded detail runs |
| `qa-reviewer.md` rule 6 (new), checklist `tests.toml` TS-05 | When a requirement depends on a fact the upstream leaves open (the event a deadline counts from, an error condition, a figure), QA does not demand a case, check or exclusion for the open part, and an exclusion naming that fact is convincing; such a point is a `customer_question` | TS-05, TS-02 (dry-run 1 below: QA called the same open start event a customer question in one issue and a blocking gap in another) |
| `tests.toml` TS-02, `basic-test-design.md` rule 5, `unit-test-design.md` rule 4 | A limit that cannot be measured because a fact it depends on is open needs no boundary cases; when only part of an item depends on an open fact, the tester tests the stated part and does not exclude the item | TS-02, and the gate error `exclusion n: ... is also tested` (dry-run 2: QA still asked for boundary cases of the open deadline, and the tester then excluded items it also tested) |
| `checklists/srs.toml` SRS-01 | The check names the Japanese obligation endings (〜すること, 〜できること, 〜しなければならない) and says a statement in that form is correct | SRS-01 (dry-run 4: QA asked for the word "shall" on correct Japanese statements and raised 52 issues) |
| `srs-writer.md` rule 8 (new) | A BRD requirement that only states the purpose of the system gets no statement of its own; it is cited in `derives_from` of the statements that realise it | SRS-02, SRS-06 (dry-run 4: one goal-type requirement kept the SRS from converging over 9 rounds) |

### 10.3 Live runs (2.3)

Dry-run 1, 2026-10-31: local Anthropic-compatible gateway, model `cx/gpt-6-luna` for writers and QA, synthetic intake `tests/fixtures/intake/leave_management.txt`, language `en`, scratch work tree.

| Stage | Result | Rounds | Issues raised / resolved | Tokens |
|---|---|---|---|---|
| BRD | done, 5 requirements | 1 | 0 / 0 | 2,458 |
| SRS | done | 2 | 2 / 2 | 5,799 |
| Basic Design | escalated | 3 | 8 / 3 | 34,305 |
| Basic Design, `--resume RUN-0003 --rounds 3` | escalated | 6 in total | 12 / 9 | 60,629 |

Normalisation and resume behaved as specified: issues that depend on the customer became advisory and reached `open_questions` (7 after the resume); the resumed run kept `RUN-0003`, added its rounds and committed `RUN-0003 escalated (resumed)`; nothing business-related was written. The last blocking ids were TS-01, TS-02 and TS-05. TS-05 contradicted another issue of the same review about the three-business-day approval limit, whose start event the intake leaves open; this led to the `qa-reviewer.md` change in 10.2. Detail Design was not run because Basic Design did not finish.

Dry-run 2, same setup, after the `qa-reviewer.md` rule only: Basic Design `RUN-0004` escalated after 3 rounds (34 issues raised, 9 resolved, 48,965 tokens). QA still asked for boundary cases of the open deadline (TS-02) and then blocked the cases written for it (TS-01, TS-03); the tester excluded the deadline part of items it also tested, so the last round failed the gate.

Dry-run 3, same setup, after the TS-02 and tester changes in 10.2:

| Stage | Result | Rounds | Issues raised / resolved | Tokens |
|---|---|---|---|---|
| Basic Design `RUN-0005` | done; 5 design items, 6 IT and 5 ST cases, 3 open questions | 1 | 0 / 0 | 20,460 |
| Detail Design `RUN-0006` | done; 10 detail items, 23 UT cases | 2 | 0 / 0 | 40,027 |

All seven workbooks were rendered. No case asserts a figure the intake does not give. Because the intake has five lines, many inputs stay generic ("request details the system accepts; fields are not specified") and the deadline cases refer to "the applicable start point". This is one run on one model; it shows the stages can finish, not that they finish reliably.

Dry-run 4, same gateway model, on a Japanese HRM intake: `tests/fixtures/intake/hrm_employee_ja.txt` (15 lines), project language `ja`, company `sample-sier` whose seven templates were calibrated from SIer-style samples made by `scripts/make_sier_samples.py` (cover sheet, revision history, document-info block, dark header row, bordered cells). Every column mapped to its field except 備考, and the previews showed no layout difference.

| Stage | Result | Rounds | Issues raised / resolved | Tokens |
|---|---|---|---|---|
| `brd` | done; 30 requirements (27 in scope, 3 out of scope), each citing its intake line | 1 | 0 / 0 | 7,354 |
| `srs` `RUN-0002` | escalated (QA asked for "shall" on correct Japanese statements) | 3 | 52 / 36 | 38,023 |
| `srs` `RUN-0003`, resumed twice | escalated (one goal-type requirement left) | 9 | 26 / 25 | 109,024 |
| `srs` `RUN-0005`, after the two prompt changes in 10.2 | done; 29 items | 1 | 0 / 0 | 8,811 |
| `basic`, first try | error: the designer returned an item without `realizes`; no run record | - | - | - |
| `basic` `RUN-0007`, then resumed to 7 rounds | escalated | 7 | 56 / 45 | 378,007 |
| `detail` | not run | - | - | - |

The BRD and SRS workbooks were opened and checked: the three sheets of the company layout are kept, the document-info cells hold the ID, version, project and status, the header keeps its fill, font, borders, freeze pane and landscape A4 setting, and 対象範囲 shows 対象. Findings are in section 11, items 4 to 6.

Dry-run 5, same intake and model, after the code changes of 1.5 and 1.6 (Basic Design only; the schema error did not recur, it is covered by unit tests):

| Attempt | Rounds | Issues raised / resolved | Tokens | Blocking left |
|---|---|---|---|---|
| `RUN-0007` before the change, resumed to 7 rounds | 7 | 56 / 45 | 378,007 | 25 QA issues |
| `RUN-0008` fresh, after the change | 3 | 18 / 13 | 172,418 | 5 QA issues; 41 advisory |
| `RUN-0009` fresh, then resumed three times | 12 | 25 / 22 | 513,292 | gate errors only: `exclusion n: ... is also tested` |

The first-review limit works: QA stopped producing a new set of blocking points each round (25 in 12 rounds against 56 in 7). What remained was a different loop: the tester rewrote the whole test list each round and, answering one gate error, broke another (an item tested and excluded at once, then an item with neither). `RUN-0009` did not reach `done`.

Still open: the runs used a gateway model on a synthetic intake; the owner accepts this record or repeats the runs with the model intended for production.

Full run on the owner's example, 2026-11-03: `tests/fixtures/intake/timesheet_ja.md` (a timesheet system, 77 lines of Japanese), model `kr/claude-opus-5.5` through the gateway, default templates, no knowledge base, `MASTERBA_REQUEST_TIMEOUT=900` for Basic Design and 1800 for Detail Design, `MASTERBA_MAX_TOKENS=32000`. Every stage reached `done`; the escalations along the way each found a defect that was fixed before the next attempt.

| Stage | Run | Result | Rounds | Tokens | Output |
|---|---|---|---|---|---|
| BRD | `RUN-0001` | done | 2 | 15,931 | 60 requirements, 11 customer questions |
| SRS | `RUN-0002`, resumed once | done | 4 | 40,738 | 67 items (53 functional, 14 non-functional), 5 questions |
| Basic Design | `RUN-0005`, resumed once | done | 5 | 150,713 | 55 design items, 68 IT cases, 64 ST cases (2 exclusions), 4 questions |
| Detail Design | `RUN-0007` | done | 3 | 149,523 | 66 detail items, 148 UT cases (5 exclusions) |

Total 421,345 tokens including the escalated attempts; 20 customer questions in the ledger.

What the attempts found:
1. SRS `RUN-0002` first escalated: the writer kept answering open question Q-0007 (manual or automatic lock) in an acceptance hint, and QA blocked it each round under the new open-questions rule (spec 13 section 5.1). `srs-writer.md` rule 7 now leaves `acceptance_hint` null instead of choosing; the resumed run passed.
2. Basic Design `RUN-0003` and `RUN-0004` died with no summary: the tester call (a 61 KB prompt for 67 SRS items) timed out three times at 180 s. A failed request now escalates the run (1.6) and the limits come from the environment.
3. Detail Design `RUN-0006` escalated: the unit-test writer named exclusion and question fields `item`. `unit-test-design.md` now names `item_ref` and `ref`.

### 10.4 CI timings (4)

Measured locally (macOS, 2026-10-31): the full suite takes 304 s for 595 tests. The `slow` marker is set per module in `tests/conftest.py` (pipeline, propagation, CLI, API flow, permissions and security, calibration); the quick selection is 402 tests in 45 to 58 s. On GitHub (run 41208337518, commit `8a7eff9`): `quick` 32 s, `full` 1 min 26 s, `image` 29 s. The first run failed in the `image` key check because `find` exits 1 on unreadable folders as the non-root user; fixed in `8a7eff9`.

### 10.5 Container check (5)

Docker 29.9.2, 2026-10-31: the image builds; `docker run ... doctor --init` on an empty bind-mounted folder prepares it (git, author from `GIT_AUTHOR_*`, 8 templates) and `init-project` writes a commit visible on the host with the configured author; `docker compose up --wait` reports the service healthy on 127.0.0.1:8000 and `/api/health` returns the version; the container user is `masterba` (uid 1000); `docker history` and the image filesystem hold no key and no `.env`. A stage run inside the container was not tried, because the CLI has no fake model; it needs a key.

## 11. Open points (do not block implementation)

1. Checkpoints stay on one machine. Committing them on escalation would let another machine resume, at the cost of drafts in git history; decide when a team works from more than one machine.
2. A second QA opinion when the same item is flagged twice in a row was another candidate from spec 05 finding 5. It is left out until the structured fields of section 1 have been tried on live runs.
3. Publishing the image to a registry is not covered; images are built locally or in CI.
4. *Done (1.6).* A model answer that does not fit its schema is fed back to its role. Not yet seen again in a live run.
5. *Done (1.5).* New blocking issues after the first review are advisory. On 30 requirements QA now settles, but see item 7.
7. The tester can oscillate between gate errors (dry-run 5: `also tested`, then `no IT case and no exclusion`) because it rewrites the whole list in each round. The gate message could name what to do (an item with a case needs no exclusion), or the code could drop an exclusion for an item that has a case and record it, which departs from the rule that gates never repair a draft. The owner decides.
6. The rendered workbook shows enum values in English (`functional`, `draft`) where a Japanese SIer document expects 機能 or 草稿, and the cover sheet is not filled; only the `scope` value map exists.
