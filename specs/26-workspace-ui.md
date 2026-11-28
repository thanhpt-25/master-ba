# Spec 26 — Workspace: a modern look for the dashboard

Status: approved (2026-11-28). The owner compared three directions (Workspace, Studio, Control room) and chose Workspace.

## Goal

The design ledger of spec 25 fixed colour roles and flows, but the dashboard still read as old-fashioned: every block was a bordered box inside another box, document ids in a typewriter face everywhere, the V drawn as a staircase of cards longer than one screen, flat grey ground and one text weight, and no quick way to jump between projects and pages. This spec gives the dashboard the look of a current SaaS work tool while keeping the spec 25 identity (藍 indigo for everything you can act on, 朱 vermilion only for the seal and approval) and every flow. It changes `frontend/` only: no API, model or storage change, the no-build CSP-safe vanilla JS stack stays, and no new runtime dependency.

## Decisions

### 1. Tokens and type

- Interface face: Inter (variable, Latin subset, self-hosted as `frontend/fonts/inter-latin-wght-normal.woff2`, OFL licence beside it) followed by the Japanese system faces (Hiragino Sans, Noto Sans JP, Yu Gothic UI, Meiryo UI). The CSP stays `default-src 'self'`. Mincho stays only on the printed cover sheet.
- Indigo moves slightly towards blue-violet and gains chroma so a primary button reads as the one action on a screen; dark theme follows. Neutrals keep a slight indigo bias. Ground is lighter so surfaces stand out by a soft shadow, not only a border.
- Radius: 6 / 8 / 10 / 12 px by size. Panels get a 1 px hairline plus a very soft shadow (`--shadow-card`); floating things keep `--shadow-float`.
- Document ids keep the mono face but at the small size in secondary ink, so they read as references, not as the content.

### 2. Shell

- **Project rail** (52 px, left edge): the seal 要 (to Projects), one square per project the user can open (its number, e.g. `001`, with the id as tooltip and accessible name; the current one ringed in indigo) and a `+` to Projects. It is filled after the first paint from `GET /api/projects` and kept for the session; switching projects is one click from any page.
- **Sidebar** (216 px): inside a project it starts with the project switcher (id and company), then the project's sections. 顧客確認事項 shows the open question count. Workspace and 管理 follow as in spec 25.
- **Top bar**: breadcrumb, a search field that opens the command palette, the account menu.
- **Command palette** (`frontend/palette.js`, ⌘K / Ctrl+K, or the search field): one input over a list of projects, the current project's sections, workspace and admin pages (by role), and actions (theme, language, sign out). Matching is by substring on the label and its keywords, case and width insensitive (`filterCommands`, pure, unit tested). Arrow keys move, Enter runs, Escape closes, focus returns to where it was. It is a `modal()` dialog, so the focus trap and `aria-modal` are the existing ones.
- Below 760 px the rail and sidebar give way to the existing top bar and tab strip; the palette stays available.

### 3. Status

`badge()` keeps icon and word (colour is never the only signal). Calm states (done, draft, running, not started) are drawn as coloured icon plus word without a fill; states that ask for attention (in review, waiting, escalated, failed) keep a soft fill; approval keeps the seal ring.

### 4. Overview

Order: header (id, status, project facts as one dotted line), the next step (tinted, one action), the figures as an unboxed strip, a running job, the V, the phases, then project settings (admins, folded). On wide screens recent activity and open customer questions sit in a right column beside all of this; on narrower screens they follow below.

- **The V** (`vDiagram(overview, pid)`) is a compact drawing that fits one screen: eight nodes, three columns wide on a twelve-column grid, design phases stepping down the left arm, test levels stepping up the right arm level with them, each pair joined by a dashed line labelled with the trace it carries (BRD ↔ UAT …), 実装 at the vertex. A node shows its title, a status mark and word, and its document id; a node with a document links to it. The current phase is ringed. Below 760 px it becomes a two-column list of pairs.
- **The phases** list (`phaseList`) holds what the V cards held in spec 25: per design phase its documents with version and status, open questions, the last run, the review gate state, and its one action (review box, waiting hint, run). The run or upload control of the current phase stays only in the next-step panel.

### 5. Other screens

They change through tokens and shared components only (panels, tables, badges, page header, toolbar): lighter table headers, row hover, softer panels. No flow changes.

## Acceptance

- `node --test` in `frontend/` and `uv run pytest tests/test_frontend.py` pass; every new string has a Japanese entry.
- Checked in Chromium at 1440 × 900 and 390 × 844, Japanese, light and dark: no console error, no horizontal page scroll; Projects, Overview (all stages done, and a phase in review), Documents.
- The palette opens with ⌘K and Ctrl+K, filters, runs with Enter, closes with Escape and returns focus.
- The CSP is unchanged: no inline style attribute (CSSOM only), no external resource; the font is served from the app's own origin.
