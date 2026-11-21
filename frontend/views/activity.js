import { asyncView, badge, clear, empty, fmtTime, h, spinner, table } from "../dom.js";
import { t } from "../i18n.js";
import { STAGE_NAMES } from "./questions.js";

const stageName = (stage) => t(STAGE_NAMES[stage] ?? stage);

function runDetail(data) {
  const { summary, tasks = [], mailbox = [] } = data;
  return h(
    "section",
    { class: "panel" },
    h("h3", {}, `${summary.run_id} · ${stageName(summary.stage)} · ${summary.trigger}`),
    h("p", { class: "muted" }, `${t("Tokens")}: ${summary.tokens_used ?? 0}${summary.token_budget ? ` / ${summary.token_budget}` : ` · ${t("no cap")}`}`),
    summary.escalations.length ? h("ul", {}, summary.escalations.map((e) => h("li", {}, e))) : null,
    h("h4", {}, t("Tasks")),
    tasks.length ? table([t("Task"), t("Title"), t("Owner"), t("Status")], tasks.map((t) => [h("code", {}, t.id), t.title, t.owner, badge(t.status === "in_progress" ? "running" : t.status === "blocked" ? "escalated" : t.status)]), t("Tasks")) : empty(t("No tasks.")),
    h("h4", {}, t("Mailbox")),
    mailbox.length
      ? table([t("Round"), t("From"), t("To"), t("Type"), t("About"), t("Message")], mailbox.map((m) => [m.round, m.sender, m.to, m.type, m.ref ? h("code", {}, m.ref) : "", m.body]), t("Mailbox"))
      : empty(t("No messages: the team agreed without discussion.")),
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
      toast(t("Resuming {id}; follow it on the overview.", { id: r.run_id }));
      go?.(`#/p/${pid}/overview`);
    } catch (error) {
      toast(error.message, "error");
    }
  };
  const actions = (r) =>
    h(
      "span",
      {},
      h("button", { class: "link", onClick: () => show(r.run_id) }, t("Open")),
      canRun && r.resumable && RESUMABLE[r.stage] ? h("button", { class: "link", onClick: () => resume(r) }, t("Resume")) : null,
      r.waiting_questions?.length ? h("a", { class: "link", href: `#/p/${pid}/questions` }, t("Answer {n} blocker question(s)", { n: r.waiting_questions.length })) : null,
    );
  const detail = h("div", {});
  const show = async (runId) => {
    detail.setAttribute("aria-busy", "true");
    clear(detail).append(h("section", { class: "panel" }, spinner(t("Loading run…"))));
    try {
      clear(detail).append(runDetail(await api.get(`/projects/${pid}/runs/${runId}`)));
    } catch (error) {
      clear(detail);
      toast(error.message, "error");
    } finally {
      detail.removeAttribute("aria-busy");
    }
  };

  clear(main).append(h("h1", {}, t("Activity")));
  const runsHost = h("div", {});
  const logHost = h("div", {});
  const runsSection = h("section", {}, h("h2", {}, t("Team runs")), runsHost);
  const logSection = h("section", {}, h("h2", {}, t("Audit log")), h("p", { class: "muted" }, t("Every action is a git commit; this is the project's history, newest first.")), logHost);
  main.append(runsSection, detail, logSection);

  asyncView(
    runsHost,
    () => api.get(`/projects/${pid}/runs`),
    (runs, host) => {
      host.append(
        runs.length
          ? table(
              [t("Run"), t("Stage"), t("Trigger"), t("Status"), t("Rounds"), t("Issues"), t("Tokens"), ""],
              runs.map((r) => [h("code", {}, r.run_id), stageName(r.stage), r.trigger, badge(r.status), r.rounds, `${r.issues_resolved}/${r.issues_raised}`, `${r.tokens_used ?? 0}${r.token_budget ? ` / ${r.token_budget}` : " / ∞"}`, actions(r)]),
              t("Team runs"),
              { dense: true, stickyFirst: true },
            )
          : empty(t("No team has run yet.")),
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
          ? table([t("Time"), t("By"), t("Commit"), t("Action")], log.map((e) => [fmtTime(e.time), e.author, h("code", {}, e.commit), e.subject]), t("Audit log"), { dense: true, stickyFirst: true })
          : empty(t("Nothing recorded yet.")),
      );
    },
    { rows: 6 },
  );

  if (params.rest[0]) await show(params.rest[0]);
}
