import { append, badge, clear, empty, fmtTime, h, icon, liveDot, statusLabel } from "../dom.js";
import { foldCommits } from "./history.js";
import { N_, t } from "../i18n.js";
import { nextStep, PHASES, phaseTitle, workflowSteps } from "./journey.js";
import { projectSummary } from "./projects.js";
import { parseComments, reviewBox } from "./review.js";

export { nextStep, parseComments, workflowSteps };

const RIGHT = [
  { title: N_("UAT"), sub: "受入テスト", doc: null, link: "BRD ↔ UAT" },
  { title: N_("System tests (ST)"), sub: "総合テスト", doc: "DOC-TEST_ST-0001", stage: "basic", link: "SRS ↔ ST" },
  { title: N_("Integration tests (IT)"), sub: "結合テスト", doc: "DOC-TEST_IT-0001", stage: "basic", link: "Basic ↔ IT" },
  { title: N_("Unit tests (UT)"), sub: "単体テスト", doc: "DOC-TEST_UT-0001", stage: "detail", link: "Detail ↔ UT" },
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

// One design phase on the left arm of the V: its documents, what blocks it, and the one action.
function leftNode(phase, info, step, index, ctx, current) {
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
  return h(
    "li",
    { class: `vnode left ${step?.state ?? info.status}`, style: `--i:${index}`, "aria-current": current ? "step" : null, "aria-labelledby": `st-${phase.key}` },
    h("div", { class: "vnode-head" }, h("h3", { id: `st-${phase.key}` }, t(phase.title)), badge(step?.state ?? info.status)),
    h("p", { class: "vnode-sub" }, phase.sub),
    info.documents.length ? h("ul", { class: "docs" }, info.documents.map((d) => docLine(ctx.pid, d))) : h("p", { class: "muted" }, t("Needs: {what}", { what: t(phase.needs) })),
    asked ? h("p", { class: "blocker" }, icon("questions", 13), h("a", { href: `#/p/${ctx.pid}/questions` }, t("{n} open customer question(s)", { n: asked }))) : null,
    last
      ? h("p", { class: "muted" }, t("Last run {id}: {status}, {rounds} round(s), {issues} issue(s)", { id: last.run_id, status: statusLabel(last.status), rounds: last.rounds, issues: last.issues_raised }))
      : null,
    action,
  );
}

// One test level on the right arm, level with the design phase it verifies.
function rightNode(card, index, stages, pid) {
  const info = card.stage ? stages.find((s) => s.stage === card.stage) : null;
  const doc = info?.documents.find((d) => d.id === card.doc);
  const status = card.doc === null ? "planned" : doc ? "done" : ["escalated", "waiting_for_input"].includes(info?.status) ? info.status : "not_started";
  return h(
    "li",
    { class: `vnode right ${status}`, style: `--i:${index}` },
    h("div", { class: "vnode-head" }, h("h3", {}, t(card.title)), badge(status)),
    h("p", { class: "vnode-sub" }, card.sub),
    doc ? h("ul", { class: "docs" }, docLine(pid, doc)) : h("p", { class: "muted" }, card.doc ? t("Written with its design stage") : t("Not generated by this system yet")),
  );
}

// The delivery pipeline drawn as the V (spec 25 section 5): design down the left arm with the
// review gate between phases, tests up the right arm, each pair joined by the trace it carries.
function pipelinePanel(overview, pid, ctx) {
  const flow = workflowSteps(overview.stages, overview.project.review_gates);
  const rows = [];
  PHASES.forEach((phase, i) => {
    const info = overview.stages.find((s) => s.stage === phase.key);
    const step = flow.steps.find((s) => s.key === phase.key);
    rows.push(
      leftNode(phase, info, step, i, ctx, flow.current === phase.key),
      h("li", { class: "vlink", "aria-hidden": "true" }, h("span", {}, RIGHT[i].link)),
      rightNode(RIGHT[i], i, overview.stages, pid),
    );
    if (i < flow.gates.length) {
      const gate = flow.gates[i];
      rows.push(h("li", { class: `vgate stage-gate ${gate}`, style: `--i:${i}` }, icon(gate === "open" ? "check" : "shield", 12), t("Review gate: {state}", { state: t(GATE_LABEL[gate]) })));
    }
  });
  const c = overview.counts;
  return h(
    "section",
    { class: "panel pipeline-panel", "aria-labelledby": "wf-title" },
    h("div", { class: "panel-heading" }, h("h2", { id: "wf-title" }, t("V-model progress")), h("a", { class: "text-action", href: `#/p/${pid}/documents` }, t("Documents"), icon("next", 14))),
    h("ol", { class: "vgrid", "aria-label": t("Phases in order") }, rows, h("li", { class: "vbase", "aria-hidden": "true" }, h("span", {}, t("Implementation")))),
    h(
      "ul",
      { class: "wf-loops", "aria-label": t("What feeds the phases") },
      h("li", {}, icon("questions", 15), h("a", { href: `#/p/${pid}/questions` }, t("{n} open customer question(s)", { n: c.open_questions })), h("span", { class: "muted" }, t("later phases may not decide them"))),
      h("li", {}, icon("drs", 15), h("a", { href: `#/p/${pid}/drs` }, t("{n} open Decision Record(s)", { n: c.open_drs })), h("span", { class: "muted" }, t("changes and review revisions"))),
      h("li", {}, icon("knowledge", 15), h("a", { href: `#/p/${pid}/knowledge` }, t("Knowledge base")), h("span", { class: "muted" }, t("passages the writers cite"))),
      overview.project.review_gates ? null : h("li", { class: "muted" }, t("Review gates are off for this project: stages run back to back.")),
    ),
  );
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
      h("div", { class: "overview-columns" },
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
      context.me?.role === "admin" ? settingsPanel(overview) : null,
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
