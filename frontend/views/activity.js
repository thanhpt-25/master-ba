import { badge, clear, empty, fmtTime, h, table } from "../dom.js";

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

export async function render({ main, api, params, toast }) {
  const pid = params.pid;
  const [runs, log] = await Promise.all([api.get(`/projects/${pid}/runs`), api.get(`/projects/${pid}/activity?limit=100`)]);
  const detail = h("div", {});
  const show = async (runId) => {
    try {
      clear(detail).append(runDetail(await api.get(`/projects/${pid}/runs/${runId}`)));
    } catch (error) {
      toast(error.message, "error");
    }
  };
  clear(main).append(
    h("h1", {}, "Activity"),
    h("section", {}, h("h2", {}, "Team runs"),
      runs.length
        ? table(
            ["Run", "Stage", "Trigger", "Status", "Rounds", "Issues", "Tokens", ""],
            runs.map((r) => [h("code", {}, r.run_id), r.stage, r.trigger, badge(r.status), r.rounds, `${r.issues_resolved}/${r.issues_raised}`, r.tokens_used ?? "", h("button", { class: "link", onClick: () => show(r.run_id) }, "Open")]),
            "Team runs",
          )
        : empty("No team has run yet.")),
    detail,
    h("section", {}, h("h2", {}, "Audit log"), h("p", { class: "muted" }, "Every action is a git commit; this is the project's history, newest first."),
      log.length
        ? table(["Time", "By", "Commit", "Action"], log.map((e) => [fmtTime(e.time), e.author, h("code", {}, e.commit), e.subject]), "Audit log")
        : empty("Nothing recorded yet.")),
  );
  if (params.rest[0]) await show(params.rest[0]);
}
