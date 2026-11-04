import { append, badge, clear, confirmDialog, empty, fmtTime, h, liveDot } from "../dom.js";

const LEFT = [
  { key: "brd", title: "BRD", sub: "業務要件定義書", needs: "Intake text" },
  { key: "srs", title: "SRS", sub: "システム要件定義書", needs: "BRD" },
  { key: "basic", title: "Basic Design", sub: "基本設計書", needs: "SRS" },
  { key: "detail", title: "Detail Design", sub: "詳細設計書", needs: "Basic Design" },
];
const RIGHT = [
  { title: "UAT", sub: "受入テスト", doc: null, link: "BRD ↔ UAT" },
  { title: "System tests (ST)", sub: "システムテスト", doc: "DOC-TEST_ST-0001", stage: "basic", link: "SRS ↔ ST" },
  { title: "Integration tests (IT)", sub: "結合テスト", doc: "DOC-TEST_IT-0001", stage: "basic", link: "Basic ↔ IT" },
  { title: "Unit tests (UT)", sub: "単体テスト", doc: "DOC-TEST_UT-0001", stage: "detail", link: "Detail ↔ UT" },
];

// The workflow strip (spec 15 section 7): where each phase stands and what to do next.
export function workflowSteps(stages, gates) {
  const steps = LEFT.map((phase) => {
    const info = stages.find((s) => s.stage === phase.key) || { status: "not_started", review: "not_started" };
    let state;
    if (info.status === "running") state = "running";
    else if (info.review === "in_review") state = "in_review";
    else if (info.review === "approved") state = "approved";
    else if (info.status === "escalated") state = "escalated";
    else if (info.status === "done") state = "done";
    else state = "ready";
    return { key: phase.key, title: phase.title, sub: phase.sub, state, waiting: info.waiting_for || null };
  });
  // Finished means the next phase may start. With gates, a fresh run is in_review until approved;
  // a `done` phase (documents in draft) only exists without gates or after a Decision Record.
  const finished = (s) => s.state === "approved" || s.state === "done";
  steps.forEach((step, i) => {
    if (step.state === "ready" && i > 0 && (!finished(steps[i - 1]) || step.waiting)) step.state = "locked";
  });
  const gatesBetween = gates
    ? steps.slice(0, -1).map((s) => (finished(s) ? "open" : s.state === "in_review" ? "waiting" : "closed"))
    : [];
  const current = steps.find((s) => !finished(s)) || null;
  return { steps, gates: gatesBetween, current: current ? current.key : null, next: nextAction(current) };
}

function nextAction(step) {
  if (!step) return "Every phase is finished. Changes from here go through a Decision Record.";
  if (step.state === "in_review") return `Review the ${step.title} phase: approve it, or reject it with comments.`;
  if (step.state === "running") return `${step.title} is running.`;
  if (step.state === "escalated") return `${step.title} escalated: resume it, or raise a Decision Record from the run.`;
  if (step.state === "locked") return `${step.title} waits for the phase before it.`;
  return step.key === "brd" ? "Upload the customer's intake and run the BRD stage." : `Run the ${step.title} stage.`;
}

function workflowStrip(overview, pid) {
  const flow = workflowSteps(overview.stages, overview.project.review_gates);
  const items = [];
  flow.steps.forEach((step, i) => {
    items.push(
      h(
        "li",
        { class: `wf-step ${step.state}`, "aria-current": flow.current === step.key ? "step" : null },
        h("span", { class: "wf-title" }, step.title),
        h("span", { class: "sub" }, step.sub),
        badge(step.state),
      ),
    );
    if (i < flow.gates.length) {
      const gate = flow.gates[i];
      const label = { open: "Approved", waiting: "Waiting for review", closed: "Review gate" }[gate];
      items.push(h("li", { class: `wf-gate ${gate}`, "aria-label": `Review gate: ${label}` }, h("span", { "aria-hidden": "true" }, gate === "open" ? "✓" : "◆"), h("span", { class: "sub" }, label)));
    }
  });
  const c = overview.counts;
  return h(
    "section",
    { class: "panel workflow", "aria-labelledby": "wf-title" },
    h("h2", { id: "wf-title" }, "Workflow"),
    h("ol", { class: "wf-track", "aria-label": "Phases in order" }, items),
    h("p", { class: "wf-next" }, h("strong", {}, "Next: "), flow.next),
    h(
      "ul",
      { class: "wf-loops", "aria-label": "What feeds the phases" },
      h("li", {}, h("a", { href: `#/p/${pid}/questions` }, `${c.open_questions} open customer question(s)`), h("span", { class: "sub" }, " · later phases may not decide them")),
      h("li", {}, h("a", { href: `#/p/${pid}/drs` }, `${c.open_drs} open Decision Record(s)`), h("span", { class: "sub" }, " · changes and review revisions")),
      h("li", {}, h("a", { href: `#/p/${pid}/knowledge` }, "Knowledge base"), h("span", { class: "sub" }, " · passages the writers cite")),
      overview.project.review_gates ? null : h("li", { class: "sub" }, "Review gates are off for this project: stages run back to back."),
    ),
  );
}

function docLine(doc) {
  return h("li", {}, h("code", {}, doc.id), h("span", { class: "ver" }, `v${doc.version}`));
}

const ITEM_PREFIX = /^\s*(DOC-[A-Z_]+-\d{4}#item\.\d+)\s*:\s*(.*)$/;

// One comment per line; a line may start with an item ref (spec 15 section 7).
export function parseComments(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(ITEM_PREFIX);
      return match ? { ref: match[1], text: match[2].trim() } : { ref: null, text: line };
    });
}

function reviewBox(stage, ctx) {
  const comments = h("textarea", {
    id: `reject-${stage.key}`,
    rows: "3",
    maxlength: "20000",
    spellcheck: "false",
    "aria-label": `Comments for rejecting ${stage.title}, one per line`,
    placeholder: "DOC-SRS-0001#item.3: Split this obligation…",
  });
  const approve = async () => {
    const open = ctx.openQuestions.length;
    const warning = open ? ` ${open} customer question(s) are still open; they stay open and later stages may not decide them.` : "";
    const ok = await confirmDialog({
      title: `Approve ${stage.title}?`,
      message: `The next stage can then start.${warning}`,
      confirmLabel: "Approve",
    });
    if (!ok) return;
    ctx.approve(stage.key).catch((e) => ctx.toast(e.message, "error"));
  };
  const reject = () => {
    const parsed = parseComments(comments.value);
    if (!parsed.length) return ctx.toast("Write at least one comment.", "error");
    ctx.reject(stage.key, parsed).catch((e) => ctx.toast(e.message, "error"));
  };
  return h(
    "div",
    { class: "review-box" },
    h("p", { class: "hint" }, "Waiting for your review."),
    h("button", { class: "primary", type: "button", onClick: approve }, "Approve"),
    comments,
    h("button", { type: "button", onClick: reject }, "Reject with comments"),
  );
}

function leftCard(stage, info, index, ctx) {
  const canRun = ["approver", "admin"].includes(ctx.me.role);
  const run = (body = {}) => ctx.start(stage.key, body);
  let action = null;
  if (info.review === "in_review" && info.status !== "running") {
    action = canRun ? reviewBox(stage, ctx) : h("p", { class: "hint" }, "Waiting for an approver's review.");
  } else if (canRun && info.waiting_for && info.status !== "running" && info.status !== "done") {
    // The gate (spec 15 section 3.2): the server refuses too; this only explains why.
    action = h("button", { class: "primary", disabled: true, title: `Approve ${info.waiting_for} first` }, `Waiting for the ${info.waiting_for} review`);
  } else if (canRun && ctx.locked.has(stage.key)) {
    action = h("button", { class: "primary", disabled: true }, `Waiting for ${stage.needs}`);
  } else if (canRun && info.status === "done") {
    // A stage refuses to run over its own documents; changes go through a Decision Record.
    action = h("p", { class: "hint" }, "To change these documents, raise a ", h("a", { href: `#/p/${ctx.pid}/drs` }, "Decision Record"), ".");
  } else if (canRun && info.status !== "running") {
    if (stage.key === "brd") {
      const file = h("input", { type: "file", accept: ".txt,.md", id: "intake-file", "aria-label": "Intake file (.txt or .md)" });
      action = h(
        "div",
        { class: "run-box" },
        file,
        h(
          "button",
          {
            class: "primary",
            onClick: async () => {
              if (!file.files[0]) return ctx.toast("Choose an intake file first.", "error");
              try {
                const stored = await ctx.api.upload(`/projects/${ctx.pid}/intake`, file.files[0]);
                await run({ intake: stored.name, reuse_intake: info.status === "escalated" });
              } catch (error) {
                ctx.toast(error.message, "error");
              }
            },
          },
          "Upload and run",
        ),
      );
    } else {
      action = h("button", { class: "primary", onClick: () => run().catch((e) => ctx.toast(e.message, "error")) }, "Run stage");
    }
  }
  const last = info.last_run;
  return h(
    "section",
    { class: `vcard left ${info.status}`, style: `--i:${index}`, "aria-labelledby": `st-${stage.key}` },
    h("div", { class: "vcard-head" }, h("h3", { id: `st-${stage.key}` }, stage.title), badge(info.status), info.review === "in_review" || info.review === "approved" ? badge(info.review) : null),
    h("p", { class: "sub" }, stage.sub),
    info.documents.length ? h("ul", { class: "docs" }, info.documents.map(docLine)) : h("p", { class: "muted" }, `Needs: ${stage.needs}`),
    last
      ? h("p", { class: "muted" }, `Last run ${last.run_id}: ${last.status}, ${last.rounds} round(s), ${last.issues_raised} issue(s)`)
      : null,
    action,
  );
}

function rightCard(card, index, stages) {
  const info = card.stage ? stages.find((s) => s.stage === card.stage) : null;
  const doc = info?.documents.find((d) => d.id === card.doc);
  const status = card.doc === null ? "planned" : doc ? "done" : info?.status === "escalated" ? "escalated" : "not_started";
  return h(
    "section",
    { class: `vcard right ${status}`, style: `--i:${index}` },
    h("div", { class: "vcard-head" }, h("h3", {}, card.title), badge(status)),
    h("p", { class: "sub" }, card.sub),
    doc ? h("ul", { class: "docs" }, docLine(doc)) : h("p", { class: "muted" }, card.doc ? "Written with its design stage" : "Not generated by this system yet"),
  );
}

function jobPanel(job) {
  if (!job) return null;
  return h(
    "section",
    { class: "panel", "aria-labelledby": "job-title" },
    h("div", { class: "vcard-head" }, h("h2", { id: "job-title" }, job.kind.replace(":", " · ")), badge(job.status)),
    h("p", { class: "muted" }, `Started ${fmtTime(job.started)}${job.finished ? `, finished ${fmtTime(job.finished)}` : ""}`),
    job.error ? h("p", { class: "error", role: "alert" }, job.error) : null,
    job.result?.escalations?.length
      ? h("div", {}, h("h3", {}, "Escalated because"), h("ul", {}, job.result.escalations.map((e) => h("li", {}, e))))
      : null,
    h("pre", { class: "log", tabindex: "0", "aria-label": "Job log" }, job.log.length ? job.log.join("\n") : "Waiting for the first message…"),
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

  const liveBar = (active) => {
    if (!active && !paused) return null;
    const toggle = h(
      "button",
      { class: "link", type: "button", onClick: () => {
        paused = !paused;
        if (!paused) refresh().catch((e) => toast(e.message, "error"));
        else { clearTimeout(timer); draw.last && draw.last(); }
      } },
      paused ? "Resume updates" : "Pause updates",
    );
    return h("div", { class: "live-bar" }, liveDot(active && !paused, paused ? "Paused" : "Live"), toggle);
  };

  const draw = (overview, job) => {
    const stages = overview.stages;
    const flow = workflowSteps(stages, overview.project.review_gates);
    const locked = new Set(flow.steps.filter((s) => s.state === "locked").map((s) => s.key));
    const ctx = { ...context, pid, start, approve, reject, locked, openQuestions: overview.open_questions };
    draw.last = () => draw(overview, job);
    // dom.js append skips empty sections; the native one would print "null".
    append(clear(main), [
      h("div", { class: "vcard-head" }, h("h1", {}, pid), liveBar(lastActive)),
      h(
        "p",
        { class: "muted" },
        `${overview.counts.requirements} requirements · ${overview.counts.links} trace links · ${overview.counts.open_drs} open decision record(s) · ${overview.counts.open_questions} open question(s) · documents in ${overview.project.document_language === "ja" ? "Japanese" : "English"}`,
      ),
      workflowStrip(overview, pid),
      h(
        "div",
        { class: "vmodel", role: "group", "aria-label": "V-model stages" },
        LEFT.map((stage, i) => leftCard(stage, stages.find((s) => s.stage === stage.key), i, ctx)),
        RIGHT.map((card, i) => rightCard(card, i, stages)),
        RIGHT.map((card, i) => h("div", { class: "link-label", style: `--i:${i}`, "aria-hidden": "true" }, card.link)),
      ),
      jobPanel(job),
      h(
        "section",
        { class: "panel" },
        h("h2", {}, "Open questions for the customer"),
        overview.open_questions.length
          ? h("div", {}, h("ul", {}, overview.open_questions.map((q) => h("li", {}, q))), h("p", {}, h("a", { href: `#/p/${pid}/questions` }, "Answer them in the Questions tab")))
          : empty("No open questions. Agents raise one here when only the customer can settle something.", h("a", { class: "button", href: `#/p/${pid}/questions` }, "Review the Questions tab")),
      ),
    ]);
  };

  async function start(stage, body) {
    paused = false;
    const started = await api.post(`/projects/${pid}/stages/${stage}/run`, body);
    toast(`Started ${stage}`);
    shown = started.id;
    await refresh();
  }

  async function approve(stage) {
    paused = false;
    const done = await api.post(`/projects/${pid}/stages/${stage}/approve`);
    toast(`Approved ${stage} (${done.review.id})`);
    await refresh();
  }

  async function reject(stage, comments) {
    paused = false;
    const started = await api.post(`/projects/${pid}/stages/${stage}/reject`, { comments });
    toast(`Rejected ${stage}; revising`);
    shown = started.id;
    await refresh();
  }

  async function refresh() {
    if (stopped || paused) return;
    const overview = await api.get(`/projects/${pid}`);
    let job = overview.job;
    if (!job && shown) job = await api.get(`/jobs/${shown}`);
    const active = Boolean(job && ["queued", "running"].includes(job.status));
    lastActive = active;
    draw(overview, job);
    if (active) {
      timer = setTimeout(() => refresh().catch((e) => toast(e.message, "error")), 2000);
    } else {
      shown = null;
    }
  }

  await refresh();
  if (!main.firstChild) main.append(empty("Nothing to show."));
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}
