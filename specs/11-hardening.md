# Spec 11 — Hardening: QA signal, convergence, resume, CI, containers

Status: v0.1 (2026-10-31), draft. Sources: [next-steps.md](../docs/next-steps.md) Phase 11 (owner decisions in 12.5, item 6 for containers), [04-srs-qa-and-team-runtime.md](04-srs-qa-and-team-runtime.md), [05-basic-design-and-tests.md](05-basic-design-and-tests.md) section 9 (live findings 3 and 5), [08-dashboard.md](08-dashboard.md), [00-constitution.md](00-constitution.md).

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

The dashboard shows a "Resume" button on an escalated run that has a checkpoint, calling the same function as a background job.

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

- [ ] `normalise_report` has unit tests for both downgrade rules and the note it posts; a regression test replays the spec 05 run 4 issue ("acceptable as written", no action) and the run finishes `done`; the `QaReport` and `TeamRun` schemas are regenerated and drift-tested.
- [ ] Customer questions from both loops reach `TeamRun.customer_questions`, and the SRS stage merges them with `open_questions`.
- [ ] `team_max_rounds_by_stage` overrides the default per stage and is set through `init-project --rounds`.
- [ ] Live `run basic` and `run detail` reach `done` with a named model, recorded in section 10, or the owner accepts the recorded escalation (2.3).
- [ ] `--resume` continues an escalated run with the fake model for every stage; it refuses a run that is done, of another stage, without a checkpoint, with a changed upstream version, or whose target document exists; the commit subject says `(resumed)`.
- [ ] The CI jobs `quick`, `full` and `image` are green on `main`, and `quick` runs in under one minute.
- [ ] `docker compose up` serves the dashboard on 127.0.0.1:8000 and the health check passes; `docker compose run --rm masterba init-project ...` and a fake-model stage run create commits visible in the host work tree, authored with the configured name; the container runs as a non-root user; no key is in the image.
- [ ] `masterba doctor` passes on a prepared root, reports each failing check with its fix, and `--init` prepares an empty folder but refuses a non-empty one.
- [ ] `backend/` and `mcp-configs/` are gone, spec 00 carries the dated amendment, and `CLAUDE.md` describes the Phase 9 state.
- [ ] Dashboard jobs survive a restart (interrupted jobs shown as such), and retention keeps 50 per project.
- [ ] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass.

## 10. Manual review record

To be filled while implementing: the prompt changes with the issue each targets (2.2), the live runs (2.3), the CI timings (4) and the container check (5).

## 11. Open points (do not block implementation)

1. Checkpoints stay on one machine. Committing them on escalation would let another machine resume, at the cost of drafts in git history; decide when a team works from more than one machine.
2. A second QA opinion when the same item is flagged twice in a row was another candidate from spec 05 finding 5. It is left out until the structured fields of section 1 have been tried on live runs.
3. Publishing the image to a registry is not covered; images are built locally or in CI.
