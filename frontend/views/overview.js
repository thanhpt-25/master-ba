import { append, badge, clear, empty, fmtTime, h, icon, liveDot, statusLabel } from "../dom.js";
import { foldCommits } from "./history.js";
import { N_, t } from "../i18n.js";
import { nextStep, PHASES, phaseTitle, workflowSteps } from "./journey.js";
import { templateSettings } from "./library.js";
import { projectSummary } from "./projects.js";
import { parseComments, reviewBox } from "./review.js";

export { nextStep, parseComments, workflowSteps };

export const RIGHT = [
  { title: N_("Acceptance test"), short: "UAT", doc: null, link: "BRD ↔ UAT" },
  { title: N_("System test"), short: "ST", doc: "DOC-TEST_ST-0001", stage: "basic", link: "SRS ↔ ST" },
  { title: N_("Integration test"), short: "IT", doc: "DOC-TEST_IT-0001", stage: "basic", link: "Basic ↔ IT" },
  { title: N_("Unit test"), short: "UT", doc: "DOC-TEST_UT-0001", stage: "detail", link: "Detail ↔ UT" },
];

const canAct = (me) => ["approver", "admin"].includes(me?.role);

// An intake picker and the button that uploads it and starts the BRD run.
function uploadBox(ctx, { reuse, label }) {
  const file = h("input", { type: "file", accept: ".txt,.md,.docx,.pdf,.xlsx", id: "intake-file", "aria-label": t("Intake file (.txt, .md, .docx, .pdf or .xlsx)") });
  const go = async () => {
    if (!file.files[0]) return ctx.toast(t("Choose an intake file first."), "error");
    try {
      const stored = await ctx.api.upload(`/projects/${ctx.pid}/intake`, file.files[0]);
      await ctx.start("brd", { intake: stored.name, reuse_intake: reuse });
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  };
  return h("div", { class: "run-box" }, file, h("button", { class: "primary", type: "button", onClick: go }, label));
}

function actionButton(action, ctx) {
  if (!action) return null;
  if (action.kind === "link") return h("a", { class: "button primary", href: action.href }, action.label);
  if (!canAct(ctx.me)) return h("p", { class: "hint" }, t("An approver or administrator takes this step."));
  if (action.kind === "upload") return uploadBox(ctx, action);
  const body = action.kind === "resume" ? { resume: action.runId } : {};
  return h("button", { class: "primary", type: "button", onClick: () => ctx.start(action.stage, body).catch((e) => ctx.toast(e.message, "error")) }, action.label);
}

// The one step the project waits for (spec 19 section 13), at the top of the page.
function nextStepPanel(overview, ctx) {
  const step = nextStep(overview, ctx.pid);
  return h(
    "section",
    { class: `panel next-step ${step.state}`, "aria-labelledby": "next-title" },
    h("div", { class: "next-body" },
      h("span", { class: "next-mark", "aria-hidden": "true" }, icon(NEXT_ICON[step.state] ?? "next", 18)),
      h("div", { class: "next-copy" }, h("h2", { id: "next-title" }, h("span", { class: "sr-only" }, `${t("Next step")}: `), step.title), h("p", { class: "muted" }, step.detail)),
      h("div", { class: "next-action" }, actionButton(step.action, ctx)),
    ),
  );
}

const NEXT_ICON = { approved: "check", done: "check", in_review: "shield", waiting_for_input: "questions", escalated: "clock", running: "workflow", ready: "next" };
const GATE_LABEL = { open: N_("Approved"), waiting: N_("Waiting for review"), closed: N_("Not reviewed yet") };

function docLine(pid, doc) {
  return h("li", {}, h("a", { href: `#/p/${pid}/documents/${doc.id}` }, doc.id), h("span", { class: "ver" }, `v${doc.version}`), doc.status ? badge(doc.status) : null);
}

// Where a test level stands, from the design stage that writes it (spec 25 section 5).
export function testLevelState(card, stages) {
  const info = card.stage ? stages.find((s) => s.stage === card.stage) : null;
  const doc = info?.documents.find((d) => d.id === card.doc) ?? null;
  const status = card.doc === null ? "planned" : doc ? "done" : ["escalated", "waiting_for_input"].includes(info?.status) ? info.status : "not_started";
  return { status, doc };
}

// The V as one compact drawing (spec 26 section 4): eight nodes, each three columns wide on a
// twelve-column grid, design phases stepping down the left arm, test levels stepping up the
// right arm on the same rows. Grid lines are 1-based; a pair line runs between the two nodes.
export function vLayout(index) {
  return { row: index + 1, left: index + 1, right: 10 - index, pairFrom: index + 4, pairTo: 10 - index };
}

const TONE = { approved: "ok", done: "ok", in_review: "warn", waiting_for_input: "warn", escalated: "warn", running: "run", ready: "run", failed: "bad" };

function vNode({ side, layout, title, short, state, doc, pid, current, note }) {
  const tone = TONE[state] ?? "idle";
  const body = [
    h("span", { class: "vd-title" }, h("span", { class: `vd-dot ${tone}`, "aria-hidden": "true" }), h("strong", {}, title), h("span", { class: "vd-short" }, short)),
    h("span", { class: `vd-state ${tone}` }, statusLabel(state)),
    h("span", { class: "vd-doc" }, doc ? doc.id : note),
  ];
  const attrs = {
    class: `vd-node ${side} ${tone}`,
    style: `--row:${layout.row};--col:${side === "left" ? layout.left : layout.right}`,
    "aria-current": current ? "step" : null,
  };
  return h("li", attrs, doc ? h("a", { class: "vd-card", href: `#/p/${pid}/documents/${doc.id}` }, body) : h("div", { class: "vd-card" }, body));
}

function vDiagram(overview, pid) {
  const flow = workflowSteps(overview.stages, overview.project.review_gates);
  const items = [];
  PHASES.forEach((phase, i) => {
    const layout = vLayout(i);
    const info = overview.stages.find((s) => s.stage === phase.key) ?? { documents: [], status: "not_started" };
    const step = flow.steps.find((s) => s.key === phase.key);
    const own = info.documents.find((d) => d.id === phase.doc) ?? null;
    items.push(vNode({ side: "left", layout, title: t(phase.title), short: phase.short, state: step?.state ?? info.status, doc: own, pid, current: flow.current === phase.key, note: t("Needs: {what}", { what: t(phase.needs) }) }));
    const card = RIGHT[i];
    const level = testLevelState(card, overview.stages);
    items.push(vNode({ side: "right", layout, title: t(card.title), short: card.short, state: level.status, doc: level.doc, pid, current: false, note: card.doc ? t("Written with its design stage") : t("Not generated by this system yet") }));
    if (layout.pairTo > layout.pairFrom) {
      items.push(h("li", { class: "vd-pair", "aria-hidden": "true", style: `--row:${layout.row};--from:${layout.pairFrom};--to:${layout.pairTo}` }, h("span", {}, card.link)));
    }
  });
  items.push(h("li", { class: "vd-base", "aria-hidden": "true" }, h("span", {}, t("Implementation"))));
  return h("ol", { class: "vdiagram", "aria-label": t("V-model: design phases and the test levels that verify them") }, items);
}

// One design phase as a row (spec 26 section 4): its documents, what blocks it, the gate after it, and its one action.
function phaseRow(phase, info, step, index, ctx, current, gate) {
  const stage = { key: phase.key, title: t(phase.title) };
  const may = canAct(ctx.me);
  let action = null;
  if (info.review === "in_review" && info.status !== "running") {
    action = may
      ? reviewBox(stage, { ...ctx, openQuestions: info.open_questions }, { placeholderRef: `${phase.doc}#item.1` })
      : h("p", { class: "hint" }, t("Waiting for an approver's review."));
  } else if (may && info.waiting_for && info.status !== "running" && info.status !== "done") {
    // The gate (spec 15 section 3.2): the server refuses too; this only explains why.
    const before = phaseTitle(info.waiting_for);
    action = h("button", { type: "button", disabled: true, title: t("Approve {phase} first", { phase: before }) }, t("Waiting for the {phase} review", { phase: before }));
  } else if (may && ctx.locked.has(phase.key)) {
    action = h("p", { class: "hint" }, t("Waiting for {phase}", { phase: t(phase.needs) }));
  } else if (info.status === "waiting_for_input") {
    action = h("p", { class: "hint" }, t("This run is waiting for customer input."), " ", h("a", { href: `#/p/${ctx.pid}/questions` }, t("Answer its blocker questions")));
  } else if (may && info.status === "done") {
    // A stage refuses to run over its own documents; changes go through a Decision Record.
    action = null;
  } else if (may && info.status !== "running" && current) {
    // The next-step panel at the top already offers this run; one control per action.
    action = h("p", { class: "hint" }, t("Start it from the next step above."));
  } else if (may && info.status !== "running") {
    action = phase.key === "brd"
      ? uploadBox(ctx, { reuse: info.status === "escalated", label: t("Upload and run") })
      : h("button", { class: "primary", type: "button", onClick: () => ctx.start(phase.key, {}).catch((e) => ctx.toast(e.message, "error")) }, t("Run stage"));
  }
  const last = info.last_run;
  const asked = info.open_questions ?? 0;
  const state = step?.state ?? info.status;
  return h(
    "li",
    { class: `phase-row ${TONE[state] ?? "idle"}`, "aria-current": current ? "step" : null, "aria-labelledby": `st-${phase.key}` },
    h("div", { class: "phase-row-head" },
      h("span", { class: "phase-num", "aria-hidden": "true" }, String(index + 1)),
      h("div", { class: "phase-row-title" }, h("h3", { id: `st-${phase.key}` }, t(phase.title)), h("p", { class: "vnode-sub" }, phase.sub)),
      badge(state),
    ),
    h("div", { class: "phase-row-body" },
      info.documents.length ? h("ul", { class: "docs" }, info.documents.map((d) => docLine(ctx.pid, d))) : h("p", { class: "muted" }, t("Needs: {what}", { what: t(phase.needs) })),
      asked ? h("p", { class: "blocker" }, icon("questions", 13), h("a", { href: `#/p/${ctx.pid}/questions` }, t("{n} open customer question(s)", { n: asked }))) : null,
      last
        ? h("p", { class: "muted" }, t("Last run {id}: {status}, {rounds} round(s), {issues} issue(s)", { id: last.run_id, status: statusLabel(last.status), rounds: last.rounds, issues: last.issues_raised }))
        : null,
      gate ? h("p", { class: `phase-gate ${gate}` }, icon(gate === "open" ? "check" : "shield", 12), t("Review gate: {state}", { state: t(GATE_LABEL[gate]) })) : null,
    ),
    action ? h("div", { class: "phase-row-action" }, action) : null,
  );
}

// The delivery pipeline (spec 26 section 4): the V drawing, then one row per design phase.
function pipelinePanel(overview, pid, ctx) {
  const flow = workflowSteps(overview.stages, overview.project.review_gates);
  const c = overview.counts;
  const rows = PHASES.map((phase, i) => {
    const info = overview.stages.find((s) => s.stage === phase.key);
    const step = flow.steps.find((s) => s.key === phase.key);
    return phaseRow(phase, info, step, i, ctx, flow.current === phase.key, flow.gates[i] ?? null);
  });
  return [
    h(
      "section",
      { class: "panel pipeline-panel", "aria-labelledby": "wf-title" },
      h("div", { class: "panel-heading" },
        h("div", { class: "panel-title" }, h("h2", { id: "wf-title" }, t("V-model progress")), h("span", { class: "muted" }, t("Each design phase is joined to the test level that verifies it."))),
        h("a", { class: "text-action", href: `#/p/${pid}/documents` }, t("Documents"), icon("next", 14)),
      ),
      vDiagram(overview, pid),
      h(
        "ul",
        { class: "wf-loops", "aria-label": t("What feeds the phases") },
        h("li", {}, icon("questions", 15), h("a", { href: `#/p/${pid}/questions` }, t("{n} open customer question(s)", { n: c.open_questions })), h("span", { class: "muted" }, t("later phases may not decide them"))),
        h("li", {}, icon("drs", 15), h("a", { href: `#/p/${pid}/drs` }, t("{n} open Decision Record(s)", { n: c.open_drs })), h("span", { class: "muted" }, t("changes and review revisions"))),
        h("li", {}, icon("knowledge", 15), h("a", { href: `#/p/${pid}/knowledge` }, t("Knowledge base")), h("span", { class: "muted" }, t("passages the writers cite"))),
        overview.project.review_gates ? null : h("li", { class: "muted" }, t("Review gates are off for this project: stages run back to back.")),
      ),
    ),
    h(
      "section",
      { class: "phase-section", "aria-labelledby": "ph-title" },
      h("div", { class: "section-heading" }, h("h2", { id: "ph-title" }, t("Phases")), h("span", { class: "muted" }, t("Documents, last run and the one action of each design phase."))),
      h("ol", { class: "phase-list", "aria-label": t("Phases in order") }, rows),
    ),
  ];
}

// Japanese particles attach to the word before them; other text gets a space.
const joiner = (text) => (/^[をにのが]/.test(text) ? text : ` ${text}`);

// The latest commits of the project in plain words, newest first; runs of one kind fold together.
function activityPanel(activity, pid) {
  const items = foldCommits(activity ?? [], 7);
  return h(
    "section",
    { class: "panel activity-panel", "aria-labelledby": "latest-title" },
    h("div", { class: "panel-heading" },
      h("h2", { id: "latest-title" }, t("Recent activity")),
      h("a", { class: "text-action", href: `#/p/${pid}/activity` }, t("View activity"), icon("next", 14)),
    ),
    items.length
      ? h("ol", { class: "activity-list" }, items.map(({ item, info, count }) => h("li", {},
          h("span", { class: `activity-kind ${info.tone}`, "aria-hidden": "true" }, icon(info.icon, 14)),
          h("span", { class: "activity-copy" },
            h("span", { class: "activity-subject" }, h("strong", {}, info.label), joiner(count > 1 ? t("{n} changes", { n: count }) : info.detail)),
            h("span", { class: "sub" }, `${item.author} · ${fmtTime(item.time)}`),
          ),
        )))
      : h("p", { class: "muted" }, activity ? t("No activity yet.") : t("Activity is not available right now.")),
  );
}

function jobPanel(job) {
  if (!job) return null;
  const [what, target] = job.kind.split(":");
  const title = what === "stage" ? phaseTitle(target) : target;
  return h(
    "section",
    { class: "panel", "aria-labelledby": "job-title" },
    h("div", { class: "vcard-head" }, h("h2", { id: "job-title" }, t("Job · {what}", { what: title })), badge(job.status)),
    h("p", { class: "muted" }, job.finished ? t("Started {start}, finished {end}", { start: fmtTime(job.started), end: fmtTime(job.finished) }) : t("Started {start}", { start: fmtTime(job.started) })),
    job.error ? h("p", { class: "error", role: "alert" }, job.error) : null,
    job.result?.escalations?.length
      ? h("div", {}, h("h3", {}, t("Escalated because")), h("ul", {}, job.result.escalations.map((e) => h("li", {}, e))))
      : null,
    h("pre", { class: "log", tabindex: "0", "aria-label": t("Job log") }, job.log.length ? job.log.join("\n") : t("Waiting for the first message…")),
  );
}

export async function render(context) {
  const { main, api, params, toast } = context;
  const pid = params.pid;
  let timer = null;
  let stopped = false;
  let paused = false;
  let shown = null;
  let lastActive = false;
  let activity = null;
  let activityAt = 0;
  let settingsOpen = false;
  // Built once and kept across redraws, so a poll does not reset the picker (spec 29).
  let templateRow = null;

  // Shared by the Pause/Resume button and the keyboard shortcut so they stay in sync.
  const togglePause = () => {
    paused = !paused;
    if (!paused) refresh().catch((e) => toast(e.message, "error"));
    else {
      clearTimeout(timer);
      draw.last && draw.last();
    }
  };

  const liveBar = (active) => {
    if (!active && !paused) return null;
    const toggle = h(
      "button",
      { class: "link", type: "button", onClick: togglePause, title: t("Pause or resume live updates (P)") },
      paused ? t("Resume updates (P)") : t("Pause updates (P)"),
    );
    return h("div", { class: "live-bar" }, liveDot(active && !paused, paused ? t("Paused") : t("Live")), toggle);
  };

  const facts = (project) => [
    project.document_language === "ja" ? t("Japanese documents") : t("English documents"),
    project.review_gates ? t("Review gates on") : t("Review gates off"),
    project.propagation_mode === "auto" ? t("Document updates automatic") : t("Document updates manual"),
  ];

  const draw = (overview, job) => {
    const stages = overview.stages;
    const flow = workflowSteps(stages, overview.project.review_gates);
    const locked = new Set(flow.steps.filter((s) => s.state === "locked").map((s) => s.key));
    const ctx = { ...context, pid, start, approve, reject, locked };
    draw.last = () => draw(overview, { ...job });
    const finished = flow.steps.filter((step) => ["approved", "done"].includes(step.state)).length;
    const summary = projectSummary(overview);
    // dom.js append skips empty sections; the native one would print "null".
    append(clear(main), [
      h("div", { class: "overview-layout" },
        h("div", { class: "overview-main" },
          h("div", { class: "page-heading project-title-row" },
            h("div", {},
              h("div", { class: "project-title-line" }, h("h1", {}, pid), badge(summary.status)),
              h("ul", { class: "project-facts", "aria-label": t("Project settings") }, facts(overview.project).map((fact) => h("li", {}, fact))),
            ),
            h("div", { class: "title-side" }, liveBar(lastActive)),
          ),
          nextStepPanel({ ...overview, job: job ?? overview.job }, ctx),
          h("dl", { class: "overview-stats", "aria-label": t("Project summary") },
            h("div", {}, h("dt", {}, t("Documents")), h("dd", {}, summary.documents), h("p", { class: "stat-note" }, t("Phases complete"), ` ${finished} / ${PHASES.length}`)),
            h("div", {}, h("dt", {}, t("Requirements")), h("dd", {}, overview.counts.requirements), h("p", { class: "stat-note" }, h("a", { href: `#/p/${pid}/questions` }, t("{n} open customer question(s)", { n: overview.counts.open_questions })))),
            h("div", {}, h("dt", {}, t("Trace links")), h("dd", {}, overview.counts.links), h("p", { class: "stat-note" }, h("a", { href: `#/p/${pid}/trace` }, t("Traceability")))),
            h("div", {}, h("dt", {}, t("Open decisions")), h("dd", {}, overview.counts.open_drs), h("p", { class: "stat-note" }, t("Reviews waiting"), ` ${summary.reviews}`)),
          ),
          jobPanel(job),
          pipelinePanel(overview, pid, ctx),
          overview.project.my_role === "admin" ? settingsPanel(overview) : null,
        ),
        h("aside", { class: "overview-aside", "aria-label": t("Recent activity and open questions") },
          activityPanel(activity, pid),
          h(
            "section",
            { class: "panel", "aria-labelledby": "oq-title" },
            h("div", { class: "panel-heading" },
              h("h2", { id: "oq-title" }, t("Open questions for the customer")),
              overview.open_questions.length ? h("a", { class: "text-action", href: `#/p/${pid}/questions` }, t("Answer them"), icon("next", 14)) : null,
            ),
            overview.open_questions.length
              ? h("ul", { class: "question-list" }, overview.open_questions.map((q) => h("li", {}, q)))
              : empty(t("No open questions. Agents raise one here when only the customer can settle something.")),
          ),
        ),
      ),
    ]);
  };

  async function start(stage, body) {
    paused = false;
    const started = await api.post(`/projects/${pid}/stages/${stage}/run`, body);
    toast(t("Started {phase}", { phase: phaseTitle(stage) }));
    shown = started.id;
    await refresh();
  }

  // Project settings an administrator changes now and then, folded below the work (spec 25 section 5).
  function settingsPanel(overview) {
    const project = overview.project;
    const auto = project.propagation_mode === "auto";
    const input = h("input", {
      type: "number", min: "1", value: project.team_token_budget ?? "", placeholder: t("No cap"),
      "aria-label": t("Token budget per run"),
    });
    // Remember the fold across redraws while a job polls.
    const panel = h("details", { class: "panel settings-panel", open: settingsOpen, onToggle: () => { settingsOpen = panel.open; } },
      h("summary", {}, icon("chevron", 14), t("Project settings")),
      h("div", { class: "settings-body" },
        templateRow ??= templateSettings(pid, { api, toast, refresh }),
        h("div", { class: "setting-row" },
          h("div", {}, h("h3", {}, t("Document updates after a decision")), h("p", { class: "muted" }, auto ? t("Document updates automatic") : t("Document updates manual"))),
          h("button", {
            type: "button",
            onClick: async () => {
              try {
                await api.post(`/projects/${pid}/settings/propagation-mode`, { propagation_mode: auto ? "manual_gate" : "auto" });
                toast(auto ? t("Document updates are now manual") : t("Document updates are now automatic"));
                await refresh();
              } catch (error) {
                toast(error.message, "error");
              }
            },
          }, auto ? t("Switch to manual updates") : t("Switch to automatic updates")),
        ),
        h("div", { class: "setting-row" },
          h("div", {}, h("h3", {}, t("Run token budget")), h("p", { class: "muted" }, t("Applies to future runs and resumes. Existing run usage is retained."))),
          h("form", {
            onSubmit: async (event) => {
              event.preventDefault();
              try {
                await api.post(`/projects/${pid}/settings/token-budget`, {
                  team_token_budget: input.value.trim() ? Number(input.value) : null,
                });
                toast(t("Project token budget updated"));
                await refresh();
              } catch (error) { toast(error.message, "error"); }
            },
          }, input, h("button", { type: "submit" }, t("Save budget"))),
        ),
      ),
    );
    return panel;
  }

  async function approve(stage) {
    paused = false;
    const done = await api.post(`/projects/${pid}/stages/${stage}/approve`);
    toast(t("Approved {phase} ({id})", { phase: phaseTitle(stage), id: done.review.id }));
    await refresh();
  }

  async function reject(stage, comments) {
    paused = false;
    const started = await api.post(`/projects/${pid}/stages/${stage}/reject`, { comments });
    toast(t("Rejected {phase}; revising", { phase: phaseTitle(stage) }));
    shown = started.id;
    await refresh();
  }

  async function refresh() {
    if (stopped || paused) return;
    const overview = await api.get(`/projects/${pid}`);
    // Activity is a git log read; refresh it at most every 10 s while a job polls.
    if (Date.now() - activityAt > 10000) {
      activityAt = Date.now();
      activity = await api.get(`/projects/${pid}/activity`).catch(() => null);
    }
    let job = overview.job;
    if (!job && shown) job = await api.get(`/jobs/${shown}`);
    const active = Boolean(job && ["queued", "running"].includes(job.status));
    lastActive = active;
    draw(overview, job);
    if (active && !document.hidden) {
      timer = setTimeout(() => refresh().catch((e) => toast(e.message, "error")), 2000);
    } else if (!active) {
      shown = null;
    }
  }

  // Idle the poll while the tab is backgrounded; resume on return.
  const onVisibility = () => {
    if (document.hidden) {
      clearTimeout(timer);
    } else if (!stopped && !paused && lastActive) {
      refresh().catch((e) => toast(e.message, "error"));
    }
  };
  document.addEventListener("visibilitychange", onVisibility);

  // "P" toggles live polling, mirroring the Pause/Resume button. Skip while
  // typing in a field or with a modifier held, and only when the bar is shown.
  const onKey = (event) => {
    if (event.key !== "p" && event.key !== "P") return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const el = document.activeElement;
    if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
    if (!lastActive && !paused) return;
    event.preventDefault();
    togglePause();
  };
  document.addEventListener("keydown", onKey);

  await refresh();
  if (!main.firstChild) main.append(empty(t("Nothing to show.")));
  return () => {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibility);
    document.removeEventListener("keydown", onKey);
  };
}
