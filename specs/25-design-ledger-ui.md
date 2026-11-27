# Spec 25 — Design ledger: dashboard UI/UX refactor

Status: approved and implemented (2026-11-27). The owner chose the indigo-and-seal direction from the before/after proposal.

## Goal

The pilot needs a dashboard a Japanese SIer team reads as a professional tool. Spec 19 part 5 ported a mock-up's look; this spec turns it into one design system and fixes the flows that still confused people. It changes the frontend only (`frontend/`): no API, model or storage change. The no-build, CSP-safe vanilla JS stack stays.

Problems found in the review of every screen (light, dark, phone):

- Vermilion was the colour of everything: primary buttons, links, document ids, eyebrow labels. Document ids looked like errors, and approval had no colour of its own.
- The Overview said the same thing three times (stat tiles, a pipeline list, and a grid of V cards) and was about three screens long. Project settings sat in the middle of the work.
- Inside a project, the project's sections were below the workspace and administration sections, under the fold at 900 px.
- Recent activity printed raw commit subjects (`render(PRJ-001): xlsx DOC-… v1`).
- Template chrome: an all-caps eyebrow above every heading, zero-padded counts (`00`, `01`), "01" monograms on projects, arrows appended to buttons.
- Wide rows with five link buttons (Users), a project-creation error shown as raw validation JSON, and the Open button of a team run translated as 未回答 (the status word).

## Decisions

### 1. Tokens (the design ledger, 設計台帳)

- Cool paper neutrals; ink in three steps, each at least 4.5:1 on surface and background.
- **藍 indigo** (`--accent`) is the only interactive colour: buttons, links, focus, the current item.
- **朱 vermilion** (`--seal`) is reserved for the seal: the brand mark 要 and approval. `badge("approved")` uses the new `seal` class (vermilion ring around the word, as stamped in a 承認 box). Nothing else is red unless it is an error (`--bad`).
- Status colours (ok, warn, run, bad) always come with an icon and a word.
- Dark theme redefines the same tokens (explicit `data-theme="dark"` and the system preference).
- One Japanese-first sans for the interface; Mincho only where the printed deliverable is shown (the document cover sheet). Interface text 14 px, reading text 15 px, a fixed scale from 11 to 24 px.
- Radius grows with the size of the thing (4 / 6 / 8 / 10 px). Only floating things (menus, dialogs, toasts) have a shadow; panels are ruled with a border.

`frontend/app.css` is rewritten in nine ordered sections (tokens, base, shell, controls, surfaces, data, feedback, screens, responsive and preferences); components read tokens only. The previous file had grown by appending override layers.

### 2. Shell

- Inside a project the sidebar starts with a project block (id and a 切り替え link to the project list) and the project's sections, then the workspace, then 管理. 管理 is a disclosure: open on administration pages and outside projects, folded inside a project.
- The breadcrumb drops the constant "Workspace" root. The account menu separates Sign out.
- Below 760 px the sidebar becomes a top bar and project sections become the tab strip, as before.

### 3. Page header

`dom.js` `pageHeader(title, description, ...actions)` is the one header: title, one line on what the page is for, actions on the right. Every screen uses it or the same `.page-heading` markup. Eyebrows and zero padding are removed.

### 4. Components

- Figures are a ruled strip (label, number, one note) instead of icon tiles: Projects, Overview, Admin KPIs, Traceability.
- Tables: sentence-case headers, row hover in surface tint, `position: relative` on the scroll box so screen-reader text cannot widen the page.
- `dom.js` `rowMenu(label, items)`: secondary row actions behind one "more" button, placed against the viewport so a scrolling table does not clip it; closes on Escape, outside click or scroll. Users keeps Edit visible and moves Reset usage, Sign out everywhere, Disable and Remove into the menu.
- Occasional forms move into dialogs opened from the page header: Propose a change (Decision Records) and Add user (Users). The New project dialog validates the company id inline with the server's rule.
- `api.js` turns FastAPI 422 details into one sentence (field and what is wrong) instead of JSON.

### 5. Overview

Order: header (id, status, project facts as small tags), the next step, the figures strip, a running job, the V, then recent activity beside open customer questions, then 「プロジェクト設定」 (admins only, folded).

The V is the page's one drawing (`pipelinePanel(overview, pid, ctx)`): design phases step down the left arm, their test levels step up the right arm level with them, each pair joined by a dashed line labelled with the trace it carries (BRD ↔ UAT …), the review gate between design phases, 実装 at the vertex. A node shows its documents with version and status, open questions, the last run and one action. The run or upload control of the current phase lives only in the next-step panel; the node points there, so a page never shows the same control twice. Review (approve or reject) stays on the node. Below 760 px the V becomes one column of pairs.

### 6. Activity in plain words

`views/history.js` `describeCommit(subject)` maps the commit kinds of the store (`project`, `intake`, `req`, `doc`, `render`, `trace`, `run`, `review`, `dr`, `question`, `kb`, `template`) to a label, an icon and the detail with its verb (`DOC-BRD-0001 v1 を出力`); run status uses the status words. `foldCommits` folds consecutive commits of one kind into one line (トレースリンク 11 件), except runs and reviews. The Activity view shows label and detail with the raw subject as a tooltip and the commit hash in its own column.

### 7. Projects

The project list is a register: one ruled row per project with the name, the current stage and a four-segment phase track (coloured by phase state), facts, and the status. It stays readable with many projects. All projects (admin) uses the same phase track with each segment's state as screen-reader text.

## Acceptance

- `node --test` in `frontend/` and `uv run pytest tests/test_frontend.py` pass; every new string has a Japanese entry and no catalog entry is stale (the i18n test now also reads `api.js`).
- Checked in Chromium at 1440 × 900 and 375 × 800, Japanese and English, light and dark: no console error, no horizontal page scroll on any screen.
- The CSP is unchanged: no inline style attribute (CSSOM only), no external resource.
