import { badge, clear, empty, fmtTime, h } from "../dom.js";

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
  const approve = () => {
    const open = ctx.openQuestions.length;
    const warning = open ? `\n\n${open} customer question(s) are still open; they stay open and later stages may not decide them.` : "";
    if (!confirm(`Approve the ${stage.title} phase? The next stage can then start.${warning}`)) return;
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
  let shown = null;

  const draw = (overview, job) => {
    const stages = overview.stages;
    const ctx = { ...context, pid, start, approve, reject, openQuestions: overview.open_questions };
    clear(main).append(
      h("h1", {}, pid),
      h(
        "p",
        { class: "muted" },
        `${overview.counts.requirements} requirements · ${overview.counts.links} trace links · ${overview.counts.open_drs} open decision record(s) · ${overview.counts.open_questions} open question(s) · documents in ${overview.project.document_language === "ja" ? "Japanese" : "English"}`,
      ),
      h(
        "div",
        { class: "vmodel", role: "group", "aria-label": "V-model stages" },
        LEFT.map((stage, i) => leftCard(stage, stages.find((s) => s.stage === stage.key), i, ctx)),
        RIGHT.map((card, i) => rightCard(card, i, stages)),
        RIGHT.map((card, i) => h("div", { class: "link-label", style: `--i:${i}`, "aria-hidden": "true" }, card.link)),
      ),
      jobPanel(job),
      overview.open_questions.length
        ? h("section", { class: "panel" }, h("h2", {}, "Open questions for the customer"), h("ul", {}, overview.open_questions.map((q) => h("li", {}, q))), h("p", {}, h("a", { href: `#/p/${pid}/questions` }, "Answer them in the Questions tab")))
        : null,
    );
  };

  async function start(stage, body) {
    const started = await api.post(`/projects/${pid}/stages/${stage}/run`, body);
    toast(`Started ${stage}`);
    shown = started.id;
    await refresh();
  }

  async function approve(stage) {
    const done = await api.post(`/projects/${pid}/stages/${stage}/approve`);
    toast(`Approved ${stage} (${done.review.id})`);
    await refresh();
  }

  async function reject(stage, comments) {
    const started = await api.post(`/projects/${pid}/stages/${stage}/reject`, { comments });
    toast(`Rejected ${stage}; revising`);
    shown = started.id;
    await refresh();
  }

  async function refresh() {
    if (stopped) return;
    const overview = await api.get(`/projects/${pid}`);
    let job = overview.job;
    if (!job && shown) job = await api.get(`/jobs/${shown}`);
    draw(overview, job);
    const active = job && ["queued", "running"].includes(job.status);
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
