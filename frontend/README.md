# MasterBA frontend

The control-room UI for MasterBA — a V-model document workflow tool (requirements → design → test, with review gates and change control). It is a **vanilla-JS single-page app**: no framework, no build step, no runtime dependencies. You serve the files as-is and the browser runs them.

## Running it locally

The app uses native ES modules (`import`), so it must be served over **HTTP** — opening `index.html` from `file://` will not load the modules.

```sh
npm run serve        # python3 -m http.server 8000
# then open http://localhost:8000/
```

Any static file server works; `npm run serve` is just a convenience. In production the same files are served behind the app's own `/api` backend (the frontend expects `/api/*` on the same origin, with a session cookie).

## Vercel

The repository-root `vercel.json` selects the **Other** framework preset and publishes this directory as static output. This prevents Vercel from treating the repository's `pyproject.toml` as a FastAPI deployment. The SPA can be built and served as static files, but its `/api/*` requests still require a MasterBA backend at the same origin or a Vercel rewrite to a separately deployed backend. Static frontend hosting alone does not provide the API, project data, or session authentication.

## Architecture

```
index.html          Shell: skip link, #app mount, #toasts live region.
app.js              Boot, hash router, workspace shell, page metadata, error boundary, "?" help.
api.js              JSON client for /api (CSRF header, ApiError with .status).
dom.js              All DOM + UI primitives. No view touches the DOM directly.
app.css             Token-driven styles (light/dark, reduced-motion, forced-colors).
views/*.js          One module per screen, each exporting async render(context).
test/               Zero-dependency test harness (node --test).
```

### Routing

Hash-based. `app.js` `parseHash()` maps the URL to a view:

- `#/projects` — project list (default)
- `#/login` — sign in
- `#/p/<PID>/<section>` — a project section (`overview`, `documents`, `trace`, `activity`, `questions`, `knowledge`, `drs`), with any extra path segments in `rest` (e.g. a selected document or record).

Views are code-split (`import()` on demand). While a view's module loads and runs its first fetch, the router shows a **skeleton** so the main area never flashes blank. A view may return a cleanup function; the router calls it on navigation so timers and listeners never leak.

### The `dom.js` primitives

Everything is built from a tiny `h(tag, attrs, ...children)` helper that inserts text only as text nodes (never HTML). The shared building blocks:

- `badge(status)` — status as **icon + word** (colour is never the only signal).
- `table(headers, rows, caption, { dense, stickyFirst })` — scrollable, labelled tables; wide audit/diff/impact tables use `dense` + `stickyFirst`.
- `empty(text, action?)` — empty state with an optional next-step action.
- `spinner()`, `skeleton(rows)` — loading placeholders.
- `asyncView(host, load, render)` — runs an async load into a host: skeleton → content, or an error block with a **Retry** button.
- `errorBox(message, onRetry?)`, `loadError(error, onRetry)` — consistent error surfaces; a 401 routes to login.
- `field(label, control, hint?)` — labelled form field; inline validation toggles `.invalid` and appends a `role="alert"` message.
- `liveDot(active, label)` — live-status pulse paired with a word.
- `splitNav(label, children)` — list nav that collapses behind a disclosure toggle on narrow screens.
- `confirmDialog(opts)` — focus-trapped `alertdialog` replacing `window.confirm`; resolves `true`/`false`.
- `shortcutsDialog(list)` — focus-trapped keyboard-shortcut help.
- `modal(build, opts)` — the shared focus-trap both dialogs are built on (Escape + backdrop close, Tab wraps, restores focus, one open at a time).

### Styling

`app.css` is driven entirely by CSS custom properties (colour, type, spacing, radius, motion). It ships:

- Light and dark themes (`prefers-color-scheme`).
- `prefers-reduced-motion` and `forced-colors` support.
- No hard-coded colours in component rules — everything references a token.
- Theme control cycles System, Light, and Dark and remembers the selection locally.
- Workspace navigation stays in a compact sidebar on desktop and moves into the top bar on small screens.

The Projects screen supports search by project ID or company and filtering by document language. Project overview surfaces the four key counts before the workflow and V-model detail.

Page titles and descriptions update with the active route so browser tabs and shared links identify the current screen.

### Accessibility conventions

- Status is always **icon + word**, never colour alone.
- Skip link, `focus-visible` rings, `tabindex="-1"` main region focused on navigation.
- Toasts and errors use `aria-live` / `role="alert"`; dialogs are `aria-modal` with a real focus trap.
- Forms use real `<label>`s; inline errors carry `role="alert"` and `aria-invalid`.

### Resilience

- Every view-load failure is caught by the router and shown with a Retry button.
- An unexpected throw (in a timer, a callback, or an unhandled promise) is caught by the **global error boundary** in `app.js`, which shows a recoverable panel with **Reload** / **Try to continue** instead of a blank screen.
- Polling views (Overview, Decision Records) idle when the browser tab is backgrounded and resume on return.

## Keyboard shortcuts

| Key   | Action                                                     |
| ----- | ---------------------------------------------------------- |
| `?`   | Show the keyboard-shortcut help overlay                    |
| `P`   | Pause / resume live polling (Overview, Decision Records)   |
| `Esc` | Close an open dialog                                       |

Shortcuts are ignored while typing in a field and when a modifier (Ctrl/Cmd/Alt) is held.

## Tests

A **zero-dependency** harness runs under plain Node — no jsdom, no browser, no install. `test/dom-shim.js` is a minimal DOM shim covering exactly the API the code under test touches.

```sh
npm test             # node --test
```

Coverage spans the critical flows:

- **dom.js primitives** — `h`, `badge`, `empty`, `table` options, `errorBox` retry, `skeleton`, `liveDot`.
- **Dialogs** — `confirmDialog` resolve paths (confirm / cancel / Escape), the danger variant, one-dialog-at-a-time, `shortcutsDialog`, and the focus-trap Tab wrap.
- **View logic** — `parseComments`, `workflowSteps` gating, and the `parseHash` router.

The shim is a test aid, not a browser substitute — the real DOM behaviour is exercised by running the app over HTTP.
