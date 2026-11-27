// Your usage (spec 23): one bar per window, use per project and the latest model calls.
import { clear, empty, fmtTime, h, table, tokens, usageMeter } from "../dom.js";
import { t } from "../i18n.js";

export async function render({ main, api }) {
  const data = await api.get("/me/usage");
  const limited = data.windows.some((w) => w.limit !== null);
  clear(main).append(
    h("div", { class: "page-heading" },
      h("div", {}, h("h1", {}, t("Usage")),
        h("p", { class: "muted" }, t("Model tokens used for you across all your projects.")),
      ),
    ),
    h("section", { class: "panel usage-panel", "aria-labelledby": "usage-limits" },
      h("h2", { id: "usage-limits" }, t("Plan usage limits")),
      h("div", { class: "usage-grid" }, data.windows.map((w) => usageMeter(w))),
      h("p", { class: "hint" }, limited
        ? t("Every model call made for you counts its input and output tokens. A window starts with your first call and resets when its time is up; a run that reaches a limit stops and can be resumed after the reset.")
        : t("No usage limit is set for your account. An administrator can set one.")),
    ),
    h("section", { class: "panel", "aria-labelledby": "usage-projects" },
      h("h2", { id: "usage-projects" }, t("By project, last 7 days")),
      data.by_project.length
        ? table(
            [t("Project"), t("Calls"), t("Input tokens"), t("Output tokens"), t("Total")],
            data.by_project.map((p) => [p.project_id ? h("a", { href: `#/p/${p.project_id}/overview` }, h("code", {}, p.project_id)) : "–", tokens(p.calls), tokens(p.input_tokens), tokens(p.output_tokens), h("strong", {}, tokens(p.tokens))]),
            t("Usage by project"),
            { dense: true },
          )
        : empty(t("No model calls in the last 7 days.")),
    ),
    h("section", { class: "panel", "aria-labelledby": "usage-recent" },
      h("h2", { id: "usage-recent" }, t("Recent model calls")),
      data.recent.length
        ? table(
            [t("Time"), t("Project"), t("Job"), t("Model"), t("Input tokens"), t("Output tokens")],
            data.recent.map((c) => [fmtTime(c.at), c.project_id ? h("code", {}, c.project_id) : "–", c.kind ?? "–", c.model ?? "–", tokens(c.input_tokens), tokens(c.output_tokens)]),
            t("Recent model calls"),
            { dense: true },
          )
        : empty(t("No model calls yet.")),
    ),
  );
}
