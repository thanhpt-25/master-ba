import { append, badge, clear, empty, fmtTime, h, icon, liveDot, monogram, statusLabel } from "../dom.js";
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
  if (action.kind === "link") return h("a", { class: "button primary", href: action.href }, action.label, h("span", { "aria-hidden": "true" }, " →"));
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
      h("span", { class: "next-mark", "aria-hidden": "true" }, icon("shield", 18)),
      h("div", { class: "next-copy" }, h("p", { class: "eyebrow" }, t("Next step")), h("h2", { id: "next-title" }, step.title), h("p", { class: "muted" }, step.detail)),
      h("div", { class: "next-action" }, actionButton(step.action, ctx)),
    ),
  );
}

const STAGE_TONE = { approved: "done", done: "done", in_review: "review", running: "review", escalated: "warn", waiting_for_input: "warn", ready: "ready", locked: "locked" };
const GATE_LABEL = { open: N_("Approved"), waiting: N_("Waiting for review"), closed: N_("Review gate") };

// The delivery pipeline: one row per phase, the review gate between them, and what feeds the phases.
function pipelinePanel(overview, pid) {
  const flow = workflowSteps(overview.stages, overview.project.review_gates);
  const rows = [];
  flow.steps.forEach((step, i) => {
    const info = overview.stages.find((s) => s.stage === step.key);
    const docs = info?.documents ?? [];
    const tone = STAGE_TONE[step.state] ?? "locked";
    rows.push(h(
      "li",
      { class: `stage-row ${tone}`, "aria-current": flow.current === step.key ? "step" : null },
      h("span", { class: "stage-number", "aria-hidden": "true" }, String(i + 1).padStart(2, "0")),
      h("span", { class: "stage-marker", "aria-hidden": "true" }, tone === "done" ? icon("check", 14) : tone === "review" || tone === "warn" ? icon("clock", 14) : null),
      h("span", { class: "stage-name" },
        h("strong", { class: "wf-title" }, step.title),
        h("span", { class: "sub" }, step.sub, docs.length ? ` · v${Math.max(...docs.map((d) => d.version))}` : ""),
      ),
      badge(step.state),
    ));
    if (i < flow.gates.length) {
      const gate = flow.gates[i];
      rows.push(h("li", { class: `stage-gate ${gate}` }, h("span", { "aria-hidden": "true" }, gate === "open" ? "✓" : "◆"), t("Review gate: {state}", { state: t(GATE_LABEL[gate]) })));
    }
  });
  const c = overview.counts;
  return h(
    "section",
    { class: "panel pipeline-panel", "aria-labelledby": "wf-title" },
    h("div", { class: "panel-heading" }, h("div", {}, h("p", { class: "eyebrow" }, t("Delivery pipeline")), h("h2", { id: "wf-title" }, t("V-model progress")))),
    h("ol", { class: "stage-list", "aria-label": t("Phases in order") }, rows),
    h(
      "ul",
      { class: "wf-loops", "aria-label": t("What feeds the phases") },
      h("li", {}, icon("questions", 15), h("a", { href: `#/p/${pid}/questions` }, t("{n} open customer question(s)", { n: c.open_questions })), h("span", { class: "sub" }, ` · ${t("later phases may not decide them")}`)),
      h("li", {}, icon("drs", 15), h("a", { href: `#/p/${pid}/drs` }, t("{n} open Decision Record(s)", { n: c.open_drs })), h("span", { class: "sub" }, ` · ${t("changes and review revisions")}`)),
      h("li", {}, icon("knowledge", 15), h("a", { href: `#/p/${pid}/knowledge` }, t("Knowledge base")), h("span", { class: "sub" }, ` · ${t("passages the writers cite")}`)),
      overview.project.review_gates ? null : h("li", { class: "sub" }, t("Review gates are off for this project: stages run back to back.")),
    ),
  );
}

// The latest commits of the project, newest first; every business action is one commit.
function activityPanel(activity, pid) {
  const items = (activity ?? []).slice(0, 6);
  return h(
    "section",
    { class: "panel activity-panel", "aria-labelledby": "latest-title" },
    h("div", { class: "panel-heading" },
      h("div", {}, h("p", { class: "eyebrow" }, t("The latest")), h("h2", { id: "latest-title" }, t("Recent activity"))),
      h("a", { class: "text-action", href: `#/p/${pid}/activity` }, t("View activity"), icon("next", 14)),
    ),
    items.length
      ? h("ol", { class: "activity-list" }, items.map((item) => h("li", {},
          h("span", { class: "activity-avatar", "aria-hidden": "true" }, monogram(item.author)),
          h("span", { class: "activity-copy" }, h("span", { class: "activity-subject" }, item.subject), h("span", { class: "sub" }, `${item.author} · ${fmtTime(item.time)}`)),
        )))
      : h("p", { class: "muted" }, activity ? t("No activity yet.") : t("Activity is not available right now.")),
  );
}

function docLine(pid, doc) {
  return h("li", {}, h("a", { href: `#/p/${pid}/documents/${doc.id}` }, h("code", {}, doc.id)), h("span", { class: "ver" }, `v${doc.version}`), doc.status ? badge(doc.status) : null);
}

function leftCard(phase, info, index, ctx) {
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
    action = h("button", { class: "primary", disabled: true, title: t("Approve {phase} first", { phase: before }) }, t("Waiting for the {phase} review", { phase: before }));
  } else if (may && ctx.locked.has(phase.key)) {
    action = h("button", { class: "primary", disabled: true }, t("Waiting for {phase}", { phase: t(phase.needs) }));
  } else if (info.status === "waiting_for_input") {
    action = h("p", { class: "hint" }, t("This run is waiting for customer input."), " ", h("a", { href: `#/p/${ctx.pid}/questions` }, t("Answer its blocker questions")));
  } else if (may && info.status === "done") {
    // A stage refuses to run over its own documents; changes go through a Decision Record.
    action = h("p", { class: "hint" }, t("To change these documents, raise a Decision Record."), " ", h("a", { href: `#/p/${ctx.pid}/drs` }, t("Decision Records")));
  } else if (may && info.status !== "running") {
    action = phase.key === "brd"
      ? uploadBox(ctx, { reuse: info.status === "escalated", label: t("Upload and run") })
      : h("button", { class: "primary", onClick: () => ctx.start(phase.key, {}).catch((e) => ctx.toast(e.message, "error")) }, t("Run stage"));
  }
  const last = info.last_run;
  const asked = info.open_questions ?? 0;
  return h(
    "section",
    { class: `vcard left ${info.status}`, style: `--i:${index}`, "aria-labelledby": `st-${phase.key}` },
    h("div", { class: "vcard-head" }, h("h3", { id: `st-${phase.key}` }, t(phase.title)), badge(info.status), info.review === "in_review" || info.review === "approved" ? badge(info.review) : null),
    h("p", { class: "sub" }, phase.sub),
    info.documents.length ? h("ul", { class: "docs" }, info.documents.map((d) => docLine(ctx.pid, d))) : h("p", { class: "muted" }, t("Needs: {what}", { what: t(phase.needs) })),
    asked ? h("p", { class: "blocker" }, h("span", { "aria-hidden": "true" }, "●"), " ", h("a", { href: `#/p/${ctx.pid}/questions` }, t("{n} open customer question(s)", { n: asked }))) : null,
    last
      ? h("p", { class: "muted" }, t("Last run {id}: {status}, {rounds} round(s), {issues} issue(s)", { id: last.run_id, status: statusLabel(last.status), rounds: last.rounds, issues: last.issues_raised }))
      : null,
    action,
  );
}

function rightCard(card, index, stages, pid) {
  const info = card.stage ? stages.find((s) => s.stage === card.stage) : null;
  const doc = info?.documents.find((d) => d.id === card.doc);
  const status = card.doc === null ? "planned" : doc ? "done" : ["escalated", "waiting_for_input"].includes(info?.status) ? info.status : "not_started";
  return h(
    "section",
    { class: `vcard right ${status}`, style: `--i:${index}` },
    h("div", { class: "vcard-head" }, h("h3", {}, t(card.title)), badge(status)),
    h("p", { class: "sub" }, card.sub),
    doc ? h("ul", { class: "docs" }, docLine(pid, doc)) : h("p", { class: "muted" }, card.doc ? t("Written with its design stage") : t("Not generated by this system yet")),
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

  const modeToggle = (overview) => {
    if (context.me.role !== "admin") return null;
    const auto = overview.project.propagation_mode === "auto";
    return h("button", {
      class: "link",
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
    }, auto ? t("Switch to manual updates") : t("Switch to automatic updates"));
  };

  const facts = (project) => [
    project.document_language === "ja" ? t("Japanese documents") : t("English documents"),
    project.review_gates ? t("Review gates on") : t("Review gates off"),
    project.propagation_mode === "auto" ? t("Document updates automatic") : t("Document updates manual"),
  ].join(" · ");

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
        h("div", { class: "project-title-line" },
          h("span", { class: "monogram big", "aria-hidden": "true" }, overview.project.company_id && overview.project.company_id !== "default" ? monogram(overview.project.company_id) : pid.replace(/\D/g, "").slice(-2)),
          h("div", {}, h("p", { class: "eyebrow" }, t("Project overview")), h("h1", {}, pid), h("p", { class: "muted" }, facts(overview.project)), modeToggle(overview)),
        ),
        h("div", { class: "title-side" }, liveBar(lastActive), badge(summary.status)),
      ),
      nextStepPanel({ ...overview, job: job ?? overview.job }, ctx),
      h("dl", { class: "overview-stats", "aria-label": t("Project summary") },
        h("div", {}, h("dt", {}, t("Documents")), h("dd", {}, summary.documents), h("p", { class: "stat-note" }, icon("documents", 13), t("Phases complete"), ` ${finished} / ${PHASES.length}`)),
        h("div", {}, h("dt", {}, t("Requirements")), h("dd", {}, overview.counts.requirements), h("p", { class: "stat-note" }, icon("requirements", 13), t("{n} open customer question(s)", { n: overview.counts.open_questions }))),
        h("div", {}, h("dt", {}, t("Trace links")), h("dd", {}, overview.counts.links), h("p", { class: "stat-note" }, icon("trace", 13), h("a", { href: `#/p/${pid}/trace` }, t("Traceability")))),
        h("div", {}, h("dt", {}, t("Open decisions")), h("dd", {}, overview.counts.open_drs), h("p", { class: "stat-note" }, icon("clock", 13), t("Reviews waiting"), ` ${summary.reviews}`)),
      ),
      h("div", { class: "overview-columns" }, pipelinePanel(overview, pid), activityPanel(activity, pid)),
      h("h2", { class: "section-title" }, t("V-model stages")),
      h(
        "div",
        { class: "vmodel", role: "group", "aria-label": t("V-model stages") },
        PHASES.map((phase, i) => leftCard(phase, stages.find((s) => s.stage === phase.key), i, ctx)),
        RIGHT.map((card, i) => rightCard(card, i, stages, pid)),
        RIGHT.map((card, i) => h("div", { class: "link-label", style: `--i:${i}`, "aria-hidden": "true" }, card.link)),
      ),
      jobPanel(job),
      h(
        "section",
        { class: "panel" },
        h("h2", {}, t("Open questions for the customer")),
        overview.open_questions.length
          ? h("div", {}, h("ul", {}, overview.open_questions.map((q) => h("li", {}, q))), h("p", {}, h("a", { href: `#/p/${pid}/questions` }, t("Answer them in the Questions tab"))))
          : empty(t("No open questions. Agents raise one here when only the customer can settle something.")),
      ),
      context.me?.role === "admin" ? budgetPanel(overview.project) : null,
    ]);
  };

  async function start(stage, body) {
    paused = false;
    const started = await api.post(`/projects/${pid}/stages/${stage}/run`, body);
    toast(t("Started {phase}", { phase: phaseTitle(stage) }));
    shown = started.id;
    await refresh();
  }

  function budgetPanel(project) {
    const input = h("input", {
      type: "number", min: "1", value: project.team_token_budget ?? "", placeholder: t("No cap"),
      "aria-label": t("Token budget per run"),
    });
    return h("form", {
      class: "panel form-grid",
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
    }, h("h2", {}, t("Run token budget")),
    h("p", { class: "muted" }, t("Applies to future runs and resumes. Existing run usage is retained.")),
    input, h("button", { class: "primary", type: "submit" }, t("Save budget")));
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
