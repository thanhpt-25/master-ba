# Spec 23 — Multiple users, project isolation and per-user usage limits

Status: approved and implemented (2026-11-27).

## Goal

Let several people share one MasterBA server the way a Claude account works: each person signs in to their own workspace, sees only the projects that belong to them or were shared with them, can see how many model tokens they have used, and is stopped with a clear message when they reach the limit an administrator set. The limit resets on its own after a fixed period.

The existing single-workspace install (one admin, `PRJ-001` under `./work`) keeps working with no manual step.

## Decisions

1. **Projects stay where they are.** A project is still `projects/PRJ-###/` in the one git work tree, so ids, trace links, commits and the CLI do not change. Who may open a project is recorded beside it, in `.masterba/access.json` (not in git, like `users.json`):

   ```json
   {"version": 1, "projects": {"PRJ-001": {"owner": "admin", "members": {"alice": "approver"}}}}
   ```

2. **Roles.** The global role in `users.json` stays and now means what an account may do outside a project:
   - `viewer`: may open projects shared with them; may not create projects.
   - `approver`: may also create projects (they become the owner).
   - `admin`: sees and manages every project, every user and every limit, and calibrates templates.

   Inside a project the role that counts is the **project role**: `admin` for the owner and for global admins, otherwise the role the owner gave the member (`viewer` or `approver`). A signed-in user with no project role gets `404 no such project` for every route under `/api/projects/{pid}` and for `/api/jobs/{id}` of that project, so other people's projects are not even revealed. `GET /api/projects` lists only the projects the user may open.

3. **Migration of existing data.** The first time the access file is read and does not exist, every existing project is given to the first admin (by name) as owner, and every other existing user becomes a member with their current global role, so nobody loses the access they had. A project found later without an entry (created with `masterba init-project`) is given to the first admin with no members. Project files are never moved or rewritten.

4. **Sharing.** The project admin (owner or global admin) adds, changes and removes members and may hand the project to another user (`/api/projects/{pid}/members`, `/owner`). Removing a user (admin only) hands their projects to the admin who removed them and drops their memberships.

5. **Usage is metered on every model call made for a signed-in user.** Every model the API creates (stage runs, DR propagation, phase rejection) is wrapped in `MeteredLLM`. Before each call it checks the user's limits; after each call (including a call whose answer did not fit the schema, which still used tokens) it records `input_tokens + output_tokens` with user, project, job kind and model in `.masterba/usage.sqlite3`. The CLI acts as the operator and is not metered.

6. **Limits work like Claude's.** Two windows per user:
   - `session`: 5 hours, starting with the first model call after the previous window ended;
   - `weekly`: 7 days, the same way.

   Used tokens in a window are the sum of calls since the window started; the window resets at `start + length`, and the next call after that starts a new one. Each user has `session` and `weekly` limits in tokens, or `null` for no limit. The defaults for all users come from `.masterba/limits.json` (`default`), then the environment (`MASTERBA_LIMIT_SESSION_TOKENS`, `MASTERBA_LIMIT_WEEKLY_TOKENS`), otherwise no limit. An admin may give one user their own limits, which replace the defaults, or `0` to stop that user's model use.

7. **Enforcement.**
   - Starting a job (stage run, Propagate, phase Reject) while a limit is reached is refused with `429` and a detail object `{"code": "usage_limit", "window", "used", "limit", "resets_at", "message"}`. An automatic propagation after an approval or an answer is not started and the response says why (`propagation_note`).
   - A limit reached during a run makes the next model call raise `UsageLimitError` (an `LLMError`), so the run escalates with its checkpoint like any failed model request (spec 11 section 1.6). It can be resumed after the reset. A call already sent finishes and is counted, so usage may go slightly above the limit, as with Claude.
   - The project's `team_token_budget` per run (spec 16) still applies on top.

8. **What the user sees.** `GET /api/me` returns the windows (`used`, `limit`, `resets_at`, `percent`). The dashboard shows a banner from 80 % of a window and a stronger one at 100 % with the reset time, an account-menu entry *Usage* (使用量) with one bar per window, the reset time, and use per project and recent calls. Refused actions show the same translated message.

9. **What the admin sees.** *Users* (ユーザー管理), admin only: every user with role, usage of both windows and limits; add a user, change role, reset a password, set or clear their own limits, reset their current windows, remove the user; and the default limits for everyone. The same actions exist in the CLI: `masterba user role|password|limit|usage`, `masterba access show|owner|share|unshare`.

## API

| Method and path | Role | Purpose |
|---|---|---|
| `GET /api/me` | signed in | name, global role, usage windows |
| `GET /api/me/usage` | signed in | windows, effective limits, use per project for 7 days, last 20 calls |
| `GET /api/projects/{pid}/access` | project viewer | owner, members, my project role |
| `POST /api/projects/{pid}/members` `{name, role}` | project admin | add or change a member |
| `DELETE /api/projects/{pid}/members/{name}` | project admin | remove a member |
| `POST /api/projects/{pid}/owner` `{name}` | project admin | hand the project over |
| `GET /api/admin/users` | admin | users with usage and limits |
| `POST /api/admin/users` `{name, role, password}` | admin | add a user |
| `PATCH /api/admin/users/{name}` `{role?, password?, limits?}` | admin | change; `limits: null` returns to the defaults |
| `POST /api/admin/users/{name}/reset-usage` | admin | start new windows now |
| `DELETE /api/admin/users/{name}` | admin | remove (not yourself) |
| `GET`/`PUT /api/admin/limits` `{session, weekly}` | admin | default limits |

`POST /api/projects` now needs the global role `approver`, and the new project's owner is the caller.

## Acceptance criteria

- An upgraded install with `PRJ-001` and an admin opens with the admin as owner of `PRJ-001`; users who existed keep their access.
- A user sees and opens only their own and shared projects; any route of another project answers 404; job ids of another project answer 404.
- A member with project role `viewer` cannot run a stage; an `approver` member can; only the project admin changes settings and members.
- Every model call of an API job is recorded for the user who started it; tokens of an unusable answer are recorded too.
- With a limit reached, starting a job answers 429 with the reset time; a limit reached during a run escalates it with a checkpoint; after the reset the run resumes.
- The session window resets 5 hours after its first call and the weekly window 7 days after its first call.
- The admin can add, change and remove users, set per-user and default limits and reset usage; non-admins get 403.
- The dashboard shows usage, the warning banner, the admin Users page and the project Members page, in Japanese and English.

## Non-goals

- Sign-in through an identity provider (spec 21, OIDC) and self-service sign-up.
- Prices and cost; limits are in tokens (spec 21 adds a price table).
- Separate git work trees per user. Isolation is enforced by the server; anyone with shell access to the work tree can read every project, as before.
- Metering CLI runs.
