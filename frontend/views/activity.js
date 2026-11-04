import { asyncView, badge, clear, empty, fmtTime, h, spinner, table } from "../dom.js";

function runDetail(data) {
  const { summary, tasks = [], mailbox = [] } = data;
  return h(
    "section",
    { class: "panel" },
    h("h3", {}, `${summary.run_id} · ${summary.stage} · ${summary.trigger}`),
    summary.escalations.length ? h("ul", {}, summary.escalations.map((e) => h("li", {}, e))) : null,
    h("h4", {}, "Tasks"),
    tasks.length ? table(["Task", "Title", "Owner", "Status"], tasks.map((t) => [h("code", {}, t.id), t.title, t.owner, badge(t.status === "in_progress" ? "running" : t.status === "blocked" ? "escalated" : t.status)]), "Tasks") : empty("No tasks."),
    h("h4", {}, "Mailbox"),
    mailbox.length
      ? table(["Round", "From", "To", "Type", "About", "Message"], mailbox.map((m) => [m.round, m.sender, m.to, m.type, m.ref ? h("code", {}, m.ref) : "", m.body]), "Mailbox")
      : empty("No messages: the team agreed without discussion."),
  );
}

// A BRD run needs its intake file again, so only the later stages resume from here.
const RESUMABLE = { SRS: "srs", BASIC_DESIGN: "basic", DETAIL_DESIGN: "detail" };

export async function render({ main, api, params, toast, me, go }) {
  const pid = params.pid;
  const canRun = ["approver", "admin"].includes(me?.role);
  const resume = async (r) => {
    try {
      await api.post(`/projects/${pid}/stages/${RESUMABLE[r.stage]}/run`, { resume: r.run_id });
      toast(`Resuming ${r.run_id}; follow it on the overview.`);
      go?.(`#/p/${pid}/overview`);
    } catch (error) {
      toast(error.message, "error");
    }
  };
  const actions = (r) =>
    h(
      "span",
      {},
      h("button", { class: "link", onClick: () => show(r.run_id) }, "Open"),
      canRun && r.resumable && RESUMABLE[r.stage] ? h("button", { class: "link", onClick: () => resume(r) }, "Resume") : null,
    );
  const detail = h("div", {});
  const show = async (runId) => {
    detail.setAttribute("aria-busy", "true");
    clear(detail).append(h("section", { class: "panel" }, spinner("Loading run…")));
    try {
      clear(detail).append(runDetail(await api.get(`/projects/${pid}/runs/${runId}`)));
    } catch (error) {
      clear(detail);
      toast(error.message, "error");
    } finally {
      detail.removeAttribute("aria-busy");
    }
  };

  clear(main).append(h("h1", {}, "Activity"));
  const runsHost = h("div", {});
  const logHost = h("div", {});
  const runsSection = h("section", {}, h("h2", {}, "Team runs"), runsHost);
  const logSection = h("section", {}, h("h2", {}, "Audit log"), h("p", { class: "muted" }, "Every action is a git commit; this is the project's history, newest first."), logHost);
  main.append(runsSection, detail, logSection);

  asyncView(
    runsHost,
    () => api.get(`/projects/${pid}/runs`),
    (runs, host) => {
      host.append(
        runs.length
          ? table(
              ["Run", "Stage", "Trigger", "Status", "Rounds", "Issues", "Tokens", ""],
              runs.map((r) => [h("code", {}, r.run_id), r.stage, r.trigger, badge(r.status), r.rounds, `${r.issues_resolved}/${r.issues_raised}`, r.tokens_used ?? "", actions(r)]),
              "Team runs",
              { dense: true, stickyFirst: true },
            )
          : empty("No team has run yet."),
      );
    },
    { rows: 4 },
  );

  asyncView(
    logHost,
    () => api.get(`/projects/${pid}/activity?limit=100`),
    (log, host) => {
      host.append(
        log.length
          ? table(["Time", "By", "Commit", "Action"], log.map((e) => [fmtTime(e.time), e.author, h("code", {}, e.commit), e.subject]), "Audit log", { dense: true, stickyFirst: true })
          : empty("Nothing recorded yet."),
      );
    },
    { rows: 6 },
  );

  if (params.rest[0]) await show(params.rest[0]);
}
