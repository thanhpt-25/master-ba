# Spec 08 — Dashboard: API, local auth and web UI

Status: v0.1 (2026-10-31), draft. Sources: [concept-design.md](../docs/concept-design.md) sections 10 and 13.2 (Vietnamese), [roadmap-phases.md](../docs/roadmap-phases.md) Phase 8, [07-change-management.md](07-change-management.md), [04-srs-qa-and-team-runtime.md](04-srs-qa-and-team-runtime.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

A business analyst who does not know the command line can, in a browser: create or open a project, upload an intake, watch each V-model stage run, read the documents and download the Excel files, follow a requirement through the traceability matrix, and raise, approve, propagate and review Decision Records. Every action goes through the same Python functions the CLI uses; the dashboard adds a thin API, local authentication with three roles, background jobs and a small web app. It does not reimplement any business logic.

## Non-goals

- No SSO or external identity provider (the auth module is isolated so one can replace it later, concept-design 13.2).
- No multi-user concurrency control beyond one running job per project; no websocket push (the UI polls).
- No template upload or calibration UI (Phase 9) and no user-management UI (a CLI command creates users).
- No new storage: the git-backed project folders stay the only source of truth; the audit log is `git log` (concept-design section 10).
- No frontend build chain or framework dependency (decision 2).

## 1. Decisions

1. **One process, one repository root.** `masterba serve --root DIR [--host 127.0.0.1] [--port 8000]` serves the API and the web app for the projects under `DIR/projects`. The default host is loopback; binding elsewhere is an explicit choice of the operator.
2. **The web app is plain ES modules, HTML and CSS served as static files** from `frontend/` with no build step and no runtime dependency. The roadmap said React/Next; a build chain is not needed for six read-mostly views and would add an install step and a supply-chain surface. The API is a clean JSON contract, so a framework front end can replace it later without backend changes.
3. **FastAPI** for the API (async-capable, schema-first, test client). New runtime dependencies: `fastapi`, `uvicorn`, `python-multipart`; new dev dependency: `httpx` (test client).
4. **Business actions reuse the library**: stage runs call `run_brd`, `run_srs`, `run_basic_design`, `run_detail_design`; DR actions call `masterba.change`; reads call `trace_store`. Each action therefore makes the same git commits as on the command line.
5. **Models come from the server's environment**, not from the browser: `ANTHROPIC_API_KEY` (and optional `ANTHROPIC_BASE_URL`) are read by the server only; the browser never sees a key. Model names: `MASTERBA_MODEL`, `MASTERBA_QA_MODEL`, `MASTERBA_TEST_MODEL` (defaults as in the CLI).

## 2. Authentication and roles

Local users in `DIR/.masterba/users.json` (not committed: `.masterba/` is gitignored), created with `masterba user add NAME --role admin|approver|viewer` (password prompted, or `--password-stdin`), listed with `masterba user list`, removed with `masterba user remove NAME`.

- Passwords: PBKDF2-HMAC-SHA256, 600,000 iterations, 16-byte random salt per user, constant-time comparison. No plaintext is stored or logged.
- Session: `POST /api/login` sets a cookie `masterba_session` (HttpOnly, SameSite=Strict, Path=/, `Secure` when the request is HTTPS) holding `name.expiry.signature` (HMAC-SHA256 with a random secret created at first start in `.masterba/secret`, file mode 0600). Sessions last 8 hours; `POST /api/logout` clears the cookie. Roles are read from the users file on every request, so removing a user or changing a role takes effect at once.
- CSRF: every state-changing request (`POST`, `PUT`, `DELETE`) must carry the header `X-MasterBA: 1`; browsers cannot add it cross-site without a preflight, which the server does not allow. Cookies are SameSite=Strict as well.
- Login throttling: 5 failed attempts for a name within 5 minutes lock that name for 5 minutes (in memory); the response never says whether the name exists.

| Role | May do |
|---|---|
| `viewer` | everything read-only: projects, documents, versions, diffs, downloads, RTM, runs, DRs |
| `approver` | viewer + upload intake, run stages, create DRs, approve, reject, propagate, close |
| `admin` | approver + create projects |

Approving a DR records the signed-in user's name as `approver`; the browser cannot choose it. (Concept-design 13.2 reserves "Propagate" to approvers; this spec also lets them run stages because the analyst who approves changes is the one driving the pipeline. A stricter split is a one-line change in the permission table.)

## 3. API (JSON under `/api`)

Errors: `{"detail": "..."}` with 400 (invalid input or domain rule broken, including lifecycle errors), 401 (not signed in), 403 (role too low), 404 (unknown project, document, DR, job), 409 (a job is already running for the project), 422 (schema validation), never a stack trace. Ids in paths are validated against the id patterns before any file is touched, so a path can never leave `DIR/projects`.

| Method and path | Role | Purpose |
|---|---|---|
| `POST /login`, `POST /logout`, `GET /me` | any | session |
| `GET /projects`, `POST /projects` | viewer, admin | list; create (`project_id`, `company_id`, `document_language`, `team_max_rounds`, `team_token_budget`) |
| `GET /projects/{pid}` | viewer | overview: config; for every stage its document ids, latest version, status, latest run; counts of requirements, links, open DRs; the running job if any |
| `POST /projects/{pid}/intake` | approver | multipart upload of a `.txt` or `.md` file (max 200,000 characters, UTF-8), kept in `DIR/.masterba/uploads/{pid}/`, not committed; returns its name |
| `POST /projects/{pid}/stages/{brd,srs,basic,detail}/run` | approver | starts a job (body: `intake` name for `brd`, optional `reuse_intake`); 409 if one is running; the stage precondition errors of the CLI become 400 |
| `GET /projects/{pid}/jobs`, `GET /jobs/{id}` | viewer | job state: `queued`, `running`, `done`, `escalated`, `failed`; start and end time; the result summary (the same JSON the CLI prints) or the error; the last 200 log lines |
| `GET /projects/{pid}/documents` | viewer | latest version of each document with all version numbers |
| `GET /projects/{pid}/documents/{doc_id}?version=` | viewer | the document and its content |
| `GET /projects/{pid}/documents/{doc_id}/xlsx?version=` | viewer | the rendered file as a download (404 if never rendered) |
| `GET /projects/{pid}/documents/{doc_id}/diff?from=&to=&structural_only=` | viewer | rows `item id, field, old, new, classification` (spec 07 section 6) |
| `GET /projects/{pid}/requirements`, `GET /projects/{pid}/rtm/{req_id}` | viewer | requirements; trace paths from a requirement to its test cases, with each node's text |
| `GET /projects/{pid}/impact?node=&direction=` | viewer | `query_impact` for any node |
| `GET /projects/{pid}/runs`, `GET /projects/{pid}/runs/{run_id}` | viewer | team activity: summaries; one run with tasks and mailbox |
| `GET /projects/{pid}/activity?limit=` | viewer | the audit log: git commits touching the project (subject, author time), newest first |
| `GET /projects/{pid}/drs`, `GET /projects/{pid}/drs/{dr_id}` | viewer | DRs; one DR with stored impact and propagation progress |
| `POST /projects/{pid}/drs` | approver | create (`trigger`, `description`, `items`); `POST .../drs/from-run` (`run_id`) |
| `POST /projects/{pid}/drs/{dr_id}/approve`, `/reject` | approver | `decision`, optional `rationale`; the approver is the session user |
| `POST /projects/{pid}/drs/{dr_id}/propagate` | approver | starts a job (like a stage) |
| `POST /projects/{pid}/drs/{dr_id}/close` | approver | close after propagation |
| `GET /projects/{pid}/drs/{dr_id}/diff?structural_only=` | viewer | all documents revised by the DR |

### 3.1 Jobs

A job runs in a worker thread so the request returns at once with `202` and the job id. One job per project at a time (a per-project lock); jobs of different projects may run together. The worker builds the model clients from the server environment, calls the library function and stores its result. Escalated stages end `escalated` (the same as exit code 3), exceptions `failed` with the message. Job state is kept in memory (it is a progress view, not an audit trail: the committed run records are the audit trail); after a restart a job that was running is shown as `failed: server restarted` and the project is usable again because nothing is held on disk. Log lines are the stage's progress events: the worker reports round starts and ends, the final status and the run id (a small `progress` callback used by the team loop only to feed this log; the loop's behaviour is unchanged).

## 4. Web app (`frontend/`)

`index.html`, `app.css`, `app.js` and view modules in `frontend/views/`. A hash router (`#/projects`, `#/p/PRJ-001/overview`, `#/p/PRJ-001/documents`, `.../trace`, `.../activity`, `.../drs`). No external network requests; fonts are system fonts.

| View | Content |
|---|---|
| Sign in | name and password; errors without detail |
| Projects | list and (admin) create form |
| Overview | the V as two columns (left: BRD, SRS, Basic Design, Detail Design; right: UAT placeholder, ST, IT, UT) joined by tracing arrows; each stage card shows status (not started, running, done, escalated), document version, last run, and a **Run** button for approvers (the BRD card has the intake upload); a running job panel with its log; an "open questions" list from the latest runs' summaries |
| Documents | document list with version and status; a viewer table of the items (id, fields); version selector; diff between two versions (table with the classification, filter to hide `reworded_only`); **Download Excel** |
| Traceability | requirement picker; the chain of nodes per path down to the test cases, each with its text; reverse lookup from any item |
| Activity | team runs (rounds, issues, escalations, mailbox of a selected run) and the git audit log |
| Decision Records | inbox of proposed DRs; detail with description, impacted items, **impact preview** (documents in V order) before approving; approve / reject with decision text (approvers); propagate with job progress; diff after propagation; close |

Design requirements: the UI must look purpose-built for a document-driven V-model process (a clear V layout, status colour with text and icon so colour is never the only signal, designed focus states, light and dark themes via `prefers-color-scheme`, keyboard operable, semantic HTML with labelled controls, responsive down to 360 px). All text content from the API is inserted with `textContent` (never `innerHTML`), so stored text cannot inject markup. The server sends a strict Content-Security-Policy (`default-src 'self'`; no inline script), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`.

## 5. Layout

```
src/masterba/api/
  __init__.py  app.py  auth.py  deps.py  jobs.py  routes_projects.py  routes_docs.py
  routes_drs.py  routes_trace.py  settings.py  schemas.py
src/masterba/cli.py            (serve, user add|list|remove)
frontend/  index.html  app.css  app.js  api.js  views/*.js
tests/api/  tests/test_cli_serve.py
```

## 6. Acceptance Criteria

- [ ] Passwords are stored as salted PBKDF2 hashes; a wrong password, an unknown name and a locked name all return the same 401 body; five failures lock the name for five minutes; roles are re-read on every request.
- [ ] A tampered, expired or foreign-signed session cookie is rejected; state-changing requests without `X-MasterBA` get 403.
- [ ] The permission table of section 2 holds for every route (a parametrised test calls each route with each role and compares with the expected status).
- [ ] Ids in paths that do not match their pattern, and upload names that are not a plain `.txt`/`.md` name, are rejected without touching the file system; a path traversal attempt cannot read or write outside `DIR/projects`.
- [ ] Through the API alone (fake models): create a project, upload an intake, run `brd`, `srs`, `basic`, `detail` as jobs, read every document, download an xlsx that opens, view a diff, read the RTM for a requirement and the run records; the git history is the same as the CLI produces.
- [ ] A second job on a busy project gets 409; an escalated stage ends the job `escalated` with the reasons; an exception ends it `failed` with a message and no trace.
- [ ] Through the API alone: create a DR, see its impact preview, approve it (the approver recorded is the session user), propagate as a job, view the diff, close it; reject path; `from-run` path.
- [ ] A role below the required one cannot create projects, run stages or act on DRs; a viewer can read everything.
- [ ] The static app is served with the security headers of section 4; `GET /` returns `index.html`; unknown `/api/...` returns 404 JSON.
- [ ] The web app is exercised in a real browser against a seeded project (fake models): sign in, overview with the V and statuses, run a stage and see its log, open a document, diff, download, trace a requirement, approve and propagate a DR; screenshots at 360, 768 and 1280 px, light and dark; keyboard-only pass over the main flows; no console errors. The result is recorded in section 7.
- [ ] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass.

## 7. Manual review record

To be filled after the browser pass.

## 8. Open points (do not block implementation)

1. **Framework front end.** If the team prefers React/Next, the API is the stable seam; the views are small enough to port.
2. **Real-time updates.** Polling every 2 seconds while a job runs is enough for now; server-sent events can replace it.
3. **Backups and multi-host.** The project folders are the state; hosting several dashboard processes on one repository is not supported (single writer).
4. **Upload formats.** `.docx`, `.pdf` and email conversion to numbered text (spec 03 open point 2) remain future work; the upload route is the place for a converter.
