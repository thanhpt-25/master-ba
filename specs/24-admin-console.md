# Spec 24 — Admin console and administration dashboard

Status: approved and implemented (2026-11-27).

## Goal

Spec 23 let several people share one server. This spec gives the administrator the tools to run it: one dashboard that shows how the whole server is used and where work is stuck, the full life cycle of an account, oversight of every project, model prices for a cost estimate, and an audit log of who changed what. Every figure comes from data the server already keeps or now records; nothing is estimated or invented.

## Decisions

1. **Account life cycle.** `users.json` entries gain `created`, `last_login`, `disabled` and `sessions_after` (all optional, so existing files load unchanged).
   - *Disable* stops a user from signing in and ends their open sessions at once; their projects, memberships, limits and history stay. *Enable* lets them sign in again. An admin cannot disable or remove themselves or take away their own admin role.
   - *Sign out everywhere* ends every session of a user. A password change by an admin does the same.
   - The session cookie now carries the time it was issued (`name\nexpiry\nissued`); a cookie issued before `sessions_after` is refused. Cookies of the old two-part form are treated as issued `session_hours` before their expiry, so nobody is signed out by the upgrade.
   - A job already running for a disabled user finishes; new jobs cannot start because the user cannot sign in.

2. **Audit log.** `.masterba/audit.sqlite3` (not in git, like the other account files) keeps one row per administrative or security event: time, actor, action, target, project, detail (JSON) and source (`api` with the client address, or `cli`). It is append-only; the API has no route that changes or deletes a row. Recorded actions:

   | Action | When |
   |---|---|
   | `auth.login`, `auth.login_failed`, `auth.logout` | sign-in and sign-out (a failed sign-in names the attempted user as target) |
   | `user.create`, `user.role`, `user.password`, `user.limits`, `user.usage_reset`, `user.disable`, `user.enable`, `user.signout`, `user.remove` | account changes in the API and the CLI |
   | `limits.default`, `prices.set` | default limits and model prices |
   | `project.create`, `project.owner`, `project.member_set`, `project.member_remove` | ownership and sharing |
   | `job.start` | a stage run, propagation or phase rejection was started (detail: job id and kind) |

   Passwords and password hashes are never written to the log.

3. **Limit hits are recorded.** The usage ledger gets a `limit_events` table. A row is added when a job is refused with 429 (`context: job_start`), when an automatic propagation is not started (`auto_propagation`) and when a model call inside a run is stopped by `UsageLimitError` (`run`).

4. **Model prices (optional).** `.masterba/prices.json` holds a currency and, per model id, the price per million input and output tokens. Cost on the dashboard is `input × price_in + output × price_out` over recorded calls. A model without a price counts as *unpriced*; the dashboard shows the unpriced tokens instead of guessing. With no prices set, no cost is shown. This is a planning estimate, not a bill.

5. **Administration dashboard.** `GET /api/admin/dashboard?days=7|30|90&tz=<minutes>` (admin only) returns, for the period and the period before it:
   - KPIs: users (total, active = made a model call or signed in, disabled, admins), projects (total, active = a call or a job in the period), tokens (input, output, calls, previous period), cost, jobs by end state and running now, limit hits, users at and near (≥ 80 %) a limit, sign-ins and failed sign-ins.
   - Tokens per day (input and output, calls, users) with every day of the period present, days counted in the browser's time zone (`tz` is `Date.getTimezoneOffset()`).
   - Top 10 users and projects by tokens, tokens by model and by job kind, each with cost when priced.
   - Delivery status across every project: documents by status (draft, in review, approved, superseded), stages by status, phases waiting for approval, open customer questions and open Decision Records.
   - The latest failed, escalated or interrupted jobs, running jobs, recent limit hits, users near a limit and the latest audit events.

6. **Project oversight.** `GET /api/admin/projects` lists every project with owner, members, company, language, the four stages and their review state, open questions, open DRs, tokens in the last 30 days, last activity and the running job. The admin changes ownership and members with the existing routes of spec 23 (a global admin is project admin everywhere).

7. **Dashboard pages** (admin only, Japanese by default, English switch, light and dark):
   - *管理ダッシュボード* (`#/admin`): KPI strip, tokens-per-day chart (stacked input/output bars with hover values and a table view), top users and projects, models with cost, delivery status, attention lists (failed jobs, waiting reviews, users near a limit), recent audit events. A period switch (7, 30, 90 days).
   - *ユーザー管理*: adds status (active, disabled), created and last sign-in, a search box and status filter, and the actions disable, enable and sign out everywhere.
   - *全プロジェクト* (`#/admin-projects`): the table of decision 6 with search, hand-over (choose a user) and a link to the Members tab.
   - *監査ログ* (`#/audit`): filters by actor, action group, target and period, paging, and a CSV download.
   - The sidebar gets a *管理* section with these pages and Templates.

## API

| Method and path | Role | Purpose |
|---|---|---|
| `GET /api/admin/dashboard?days=&tz=` | admin | decision 5 |
| `GET /api/admin/projects` | admin | decision 6 |
| `POST /api/admin/users/{name}/disable` | admin | disable and end sessions (not yourself) |
| `POST /api/admin/users/{name}/enable` | admin | enable |
| `POST /api/admin/users/{name}/signout` | admin | end every session |
| `GET /api/admin/audit?actor=&action=&target=&days=&before=&limit=` | admin | events, newest first; `next` is the cursor for `before` |
| `GET /api/admin/audit.csv?…` | admin | the same filter as CSV (at most 10 000 rows) |
| `GET`/`PUT /api/admin/prices` `{currency, models: {id: {input, output}}}` | admin | model prices |

`GET /api/admin/users` now also returns `disabled`, `created` and `last_login` per user.

CLI: `masterba user disable|enable|signout NAME`; every `masterba user` and `masterba access` change is written to the audit log with actor `cli`. `masterba audit [--actor] [--action] [--limit]` prints events.

## Acceptance criteria

- A disabled user cannot sign in, and a session they had open answers 401 at the next request; after enable they sign in again.
- *Sign out everywhere* and an admin password reset end the user's open sessions; the admin's own session is not affected by changes to another user.
- Every action in decision 2 writes exactly one audit row with the right actor; no row contains a password.
- A 429 refusal and a limit reached during a run each add a limit event, and the dashboard counts them.
- The dashboard totals equal the sum of the recorded calls in the period; every day of the period is present; a model without a price is reported as unpriced, and cost is `null` with no prices.
- Non-admins get 403 for every route in this spec.
- The admin pages render in Japanese and English and in light and dark mode with no console errors.

## Non-goals

- Identity providers, self-service sign-up, email invitations and password reset by email (spec 21).
- Billing and invoices; prices give an estimate only.
- Retention or export of the audit log to an external system (a SIEM can read the CSV).
- Per-project token limits (the project token budget of spec 16 stays per run).
