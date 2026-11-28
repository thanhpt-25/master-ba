# Spec 29 — Template library: pick, share, switch

Status: v0.1 (2026-11-28), phase 1 of the owner's proposal "Chọn và chia sẻ template tài liệu" (approved 2026-11-28: approved versions are not re-rendered automatically; making a set public needs no admin approval; start with phase 1). Sources: [02-excel-rendering.md](02-excel-rendering.md), [09-template-calibration.md](09-template-calibration.md), [23-multi-user-and-usage-limits.md](23-multi-user-and-usage-limits.md), [28-print-ready-workbooks.md](28-print-ready-workbooks.md).

## Goal

A project chooses its template set from the sets its user may see: the built-in MasterBA set, the user's own uploads, sets shared with the user, and public sets. An uploaded set is private to its owner until the owner shares it with named users or makes it public. Before a project switches, the user sees which data the new set prints and which it drops (the coverage report) and can download a preview of a real project document. Switching only renders again: no model call, no Decision Record, no new document version.

## Non-goals (phase 2)

- Immutable set versions and per-version pins (`DOC.vN.render.json`).
- Deleting or archiving a set.
- Re-rendering every approved version in bulk. Phase 1 gives a re-issue of one approved version (section 5.3).

## 1. Template sets

A template set is a folder under `templates/companies/<set>/` (unchanged storage, spec 09), plus the built-in set `default`. The id rules of `valid_company` stay.

### 1.1 Built-in set

`default` is the set the app ships. `doctor --init` used to copy it into the work tree once, so an upgraded server kept rendering with old defaults. `library.sync_builtin(root)` now copies every file of the bundled `templates/default/` over the work tree's copy when the bytes differ (no commit, the folder is not tracked by `doctor --init`). It runs when the API app starts and in `masterba doctor`. It does nothing when the work tree is the repository itself.

### 1.2 Access (`library/access.py`, `.masterba/template_access.json`, not in git)

One entry per set: `owner`, `visibility` (`private`, `shared`, `public`), `shared_with` (user names), `title` (optional display name, at most 80 characters).

| Who | sees the set | uses it in a project | changes sharing | clones it | calibrates, maps, confirms |
| --- | --- | --- | --- | --- | --- |
| owner | yes | yes | yes | yes (approver+) | yes |
| global admin | yes | yes | yes | yes | yes |
| named user (`shared`) | yes | yes | no | yes (approver+) | no |
| anyone signed in (`public`) | yes | yes | no | yes (approver+) | no |

- `default` is seen by everyone, is managed by nobody, cannot be cloned onto itself and has no entry.
- `shared` with an empty list behaves like `private`. Named users must exist.
- Making a set public needs no approval. The response and the page warn that sample text left in the shell is visible to everyone.
- Revoking a share or making a set private again does not change a project that already uses it: the project keeps rendering with it, and only its owner or an admin sees the set in the picker.
- Migration: the first read gives every folder in `templates/companies/` without an entry to the first admin as `private`, except `sample-sier`, which becomes `public` with the title `Mẫu SIer (dữ liệu giả)`. With no admin yet, nothing is written and the next read tries again.
- Removing a user hands their sets to the admin who removed them (like projects, spec 23) and drops them from every `shared_with`.

### 1.3 Clone

`clone(root, source, target, owner)` copies the set's files (definition, shell, sample, calibration record, confirmation markers) to a new private set owned by `owner`, rewrites `company_id` in each definition, and commits `template(<target>): clone of <source>`. The built-in set can be cloned into a company set only by calibrating; cloning `default` is refused.

## 2. Coverage report (`library/coverage.py`, no LLM, no I/O beyond reading templates)

For a set and a document type, compare the set's bindings with the built-in set's bindings for that type. The data kinds are:

- `header:<source>` for every header source the built-in set prints (`$document.author`, `$document.approver`...).
- `field:<name>` for every item field a built-in table column binds (`$code` included).
- `list:<source>` for every list source (`$revisions`, `$trace`, `$exclusions`, `$questions`).
- `section:<key>` for every prose section.

Each kind is `printed` (the set binds it too) or `dropped`. A type the set has no confirmed template for falls back to the built-in set (`resolve_template`), so its report is `fallback` with nothing dropped. The report lists every type the project has a document for (all seven types when the project has none), each with `state` (`calibrated`, `fallback`) and its rows. `gaps` counts dropped kinds.

## 3. Preview

`render_bytes(store, doc_id, templates_root, version=None, company_id=None)` renders the latest (or given) version with the given set instead of the project's and writes nothing. The API serves it as `GET /api/projects/{pid}/template/preview/{doc_id}.xlsx?set=<set>`.

## 4. Switching (`library/switch.py`)

`switch_template(store, templates_root, set_id, *, accept_gaps)`:

1. Refuses an unknown set (no folder and not `default`).
2. Computes the coverage report; with gaps and without `accept_gaps` it raises `CoverageGapError` (API 409 with the report).
3. Writes `company_id` to `project.json`, renders the latest version of every document whose status is `draft` or `in_review` with the new set, and commits all files once: `project(<P>): template <set>` (`render(<P>): ...` subjects are not used, so the history page shows one step).
4. Leaves `approved` and `superseded` versions untouched: their committed workbook is the issued file.

It returns the rendered documents and the approved ones left as they were. Visibility is checked by the caller (API, CLI has no users). Switching to the set already in use renders again (a no-op in git when nothing changed).

## 5. Downloads and re-issue

### 5.1 Download

`GET .../documents/{id}/xlsx` keeps rendering on request (spec 28) for `draft` and `in_review` versions. For an `approved` or `superseded` version it serves the committed workbook when there is one, so a template switch never changes a file that was issued. Without a committed file it renders.

### 5.2 Approval

Approving a phase still renders its documents with the project's current set (spec 15), which is what is issued.

### 5.3 Re-issue

`POST /api/projects/{pid}/documents/{id}/reissue` (approver+) and `masterba project reissue --project P --doc DOC-... [--version n]` render one approved version again with the current set and commit it (`render(<P>): reissue <DOC> v<n> (<set>)`). The document version, status and content are unchanged.

## 6. Interfaces

### 6.1 API

- `GET /api/template-sets` (signed in): the visible sets: `id`, `title`, `owner`, `visibility`, `shared_with` (only for those who manage it), `can_manage`, `builtin`, `types` (doc type to `confirmed` / `draft`).
- `POST /api/template-sets/{set}/visibility` `{visibility, shared_with?}` (manager): sets visibility and, for `shared`, the user list. Audit `template.visibility`.
- `POST /api/template-sets/{set}/title` `{title}` (manager).
- `POST /api/template-sets/{set}/clone` `{target}` (approver+ who sees it): audit `template.clone`.
- `GET /api/projects/{pid}/template` (viewer): current set, `can_change`, and the sets the user may pick.
- `GET /api/projects/{pid}/template/coverage?set=` (viewer, set visible).
- `GET /api/projects/{pid}/template/preview/{doc_id}.xlsx?set=` (viewer, set visible).
- `PUT /api/projects/{pid}/template` `{set, accept_gaps}` (project admin, set visible): audit `project.template`.
- `POST /api/projects/{pid}/documents/{id}/reissue` (approver+).
- `POST /api/projects` refuses a `company_id` the creator cannot see.
- `/api/templates` (calibration, spec 09) opens to signed-in users: reading needs the set to be visible; calibrating a new set needs approver+ and makes the caller its owner; calibrating again, mapping, preview, confirm and unconfirm need a manager of the set. The list shows only visible sets.

### 6.2 CLI (no users; the CLI acts as the operator)

- `masterba project set-template --project P --template <set> [--accept-gaps]` prints the report and the rendered and kept documents; exit 1 on gaps without `--accept-gaps`.
- `masterba project coverage --project P --template <set>`.
- `masterba project reissue --project P --doc DOC-... [--version n]`.
- `masterba template sets`, `masterba template share --company C --visibility private|shared|public [--users a,b]`, `masterba template clone --company C --to NEW --owner NAME`.

### 6.3 Dashboard

- 設定 (project settings, shown to the project's admins): テンプレート row with the current set, a picker of visible sets, the coverage report per type (green printed, yellow dropped), a preview download per document, and 適用. With gaps the apply button stays disabled until 印字されない項目を確認しました is ticked. Approved documents are listed as kept, each with 再発行.
- Templates page is in the Workspace section for every user: the set register (name, owner, visibility, types) with share controls and clone for a set the user may manage or see; the calibration panel only for approvers and admins.

## 7. Acceptance criteria

1. A private set is listed only for its owner and admins; a shared set also for the named users; a public set for everyone.
2. A user cannot pick, preview or calibrate a set they cannot see (404), and cannot change sharing of a set they do not manage (403).
3. Switching a project re-renders its draft and in-review documents with the new set in one commit, leaves approved files byte-identical, and writes no Decision Record and no new version.
4. Switching to a set that drops data is refused without `accept_gaps`.
5. The coverage report of the `sample-sier` BRD lists the kinds the sample does not print as dropped, and of the built-in set lists nothing dropped.
6. After a switch, downloading an approved version returns the committed bytes; re-issuing it renders the new set.
7. An upgraded server renders with the bundled built-in set.
