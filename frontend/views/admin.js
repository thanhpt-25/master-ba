// Administration dashboard (spec 24 section 5): how the server is used and where work is stuck.
// Every figure comes from GET /api/admin/dashboard; nothing is estimated in the browser.
import { barList, compact, delta, money, number, stackedBars } from "../charts.js";
import { badge, clear, empty, field, fmtTime, h, icon, loadError, modal, skeleton, table, usageMeter } from "../dom.js";
import { N_, t } from "../i18n.js";
import { STAGE_LABELS, actionLabel, kindLabel } from "./audit.js";

const PERIODS = [7, 30, 90];
const DOC_STATES = [["draft", N_("Draft")], ["in_review", N_("In review")], ["approved", N_("Approved")], ["superseded", N_("Superseded")]];
const STAGE_STATES = ["done", "running", "escalated", "waiting_for_input", "not_started"];
let chosen = 30;
try { chosen = Number(localStorage.getItem("masterba-admin-days")) || 30; } catch { /* storage may be disabled */ }
if (!PERIODS.includes(chosen)) chosen = 30;

function kpi(iconName, tone, label, value, note = null, change = null) {
  return h("div", { class: "kpi" },
    h("div", { class: "kpi-top" },
      h("span", { class: `metric-icon ${tone}` }, icon(iconName, 16)),
      h("span", { class: "kpi-label" }, label),
    ),
    h("strong", { class: "kpi-value" }, value),
    h("p", { class: "kpi-note" },
      change ? h("span", { class: `delta ${change.dir}` }, change.text) : null,
      change && note ? " " : null,
      note,
    ),
  );
}

function panel(id, title, body, action = null) {
  return h("section", { class: "panel", "aria-labelledby": id },
    h("div", { class: "panel-heading" }, h("h2", { id }, title), action),
    body,
  );
}

function pricesDialog(api, data, onSaved, toast) {
  const currency = h("input", { type: "text", value: data.currency, maxlength: "3", pattern: "[A-Z]{3}", required: true, spellcheck: "false" });
  const models = [...new Set([...Object.keys(data.models), ...data.seen_models])].sort();
  const inputs = models.map((model) => {
    const price = data.models[model] ?? {};
    return {
      model,
      input: h("input", { type: "number", min: "0", step: "0.01", value: price.input ?? "", placeholder: t("Not priced"), "aria-label": t("{model}: input price", { model }) }),
      output: h("input", { type: "number", min: "0", step: "0.01", value: price.output ?? "", placeholder: t("Not priced"), "aria-label": t("{model}: output price", { model }) }),
    };
  });
  modal((close) => h("form", {
    class: "dialog create-dialog wide-dialog",
    onSubmit: async (event) => {
      event.preventDefault();
      const body = { currency: currency.value.trim().toUpperCase(), models: {} };
      for (const row of inputs) {
        if (row.input.value === "" && row.output.value === "") continue;
        body.models[row.model] = { input: Number(row.input.value || 0), output: Number(row.output.value || 0) };
      }
      try {
        await api.put("/admin/prices", body);
        close();
        toast(t("Model prices saved"));
        onSaved();
      } catch (error) {
        toast(error.message, "error");
      }
    },
  },
  h("div", { class: "dialog-top" },
    h("span", { class: "dialog-icon", "aria-hidden": "true" }, icon("gauge", 18)),
    h("h2", { id: "prices-title" }, t("Model prices")),
    h("button", { type: "button", class: "icon-button", "aria-label": t("Close"), onClick: close }, icon("close", 18)),
  ),
  h("p", { class: "hint" }, t("Price per million tokens. Cost on the dashboard is an estimate from recorded tokens; a model without a price is shown as unpriced.")),
  field(t("Currency"), currency, t("A three-letter code such as USD or JPY.")),
  inputs.length
    ? table([t("Model"), t("Input / 1M tokens"), t("Output / 1M tokens")], inputs.map((r) => [h("code", {}, r.model), r.input, r.output]), t("Model prices"), { dense: true })
    : empty(t("No model has been called yet.")),
  h("div", { class: "dialog-actions" },
    h("button", { type: "button", onClick: close }, t("Cancel")),
    h("button", { type: "submit", class: "primary" }, t("Save")),
  ),
  ), { labelledBy: "prices-title" });
}

export async function render({ main, api, toast }) {
  let token = 0;
  const body = h("div", { class: "admin-body" });
  const updated = h("span", { class: "muted admin-updated" });
  const switcher = h("div", { class: "segmented", role: "group", "aria-label": t("Period") },
    PERIODS.map((days) => h("button", {
      type: "button",
      "aria-pressed": days === chosen ? "true" : "false",
      onClick: (event) => {
        chosen = days;
        try { localStorage.setItem("masterba-admin-days", String(days)); } catch { /* not kept */ }
        for (const b of event.currentTarget.parentElement.children) b.setAttribute("aria-pressed", b === event.currentTarget ? "true" : "false");
        load();
      },
    }, t("{n} days", { n: days }))),
  );

  clear(main).append(
    h("div", { class: "page-heading" },
      h("div", {}, h("h1", {}, t("Admin dashboard")),
        h("p", { class: "muted" }, t("Usage, cost, delivery and security across every user and project.")),
      ),
      h("div", { class: "admin-tools" }, switcher,
        h("button", { type: "button", onClick: () => load() }, t("Refresh")),
      ),
    ),
    updated,
    body,
  );

  async function load() {
    const mine = ++token;
    clear(body).append(skeleton(8));
    const tz = new Date().getTimezoneOffset();
    try {
      const data = await api.get(`/admin/dashboard?days=${chosen}&tz=${tz}`);
      if (mine !== token) return;
      updated.textContent = t("Updated {time}", { time: fmtTime(data.generated) });
      clear(body).append(...draw(data));
    } catch (error) {
      if (mine !== token) return;
      clear(body).append(loadError(error, load));
    }
  }

  async function editPrices() {
    try {
      pricesDialog(api, await api.get("/admin/prices"), load, toast);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function draw(data) {
    const k = data.kpis;
    const currency = k.cost.currency;
    const tokenNote = t("{input} in · {output} out", { input: compact(k.tokens.input), output: compact(k.tokens.output) });
    const costValue = k.cost.priced ? money(k.cost.total, currency) : "–";
    const costNote = k.cost.priced
      ? (k.cost.unpriced_tokens ? t("{n} tokens unpriced", { n: compact(k.cost.unpriced_tokens) }) : t("all models priced"))
      : t("Set model prices to see cost");
    const failedJobs = k.jobs.failed + k.jobs.interrupted;
    const kpis = h("section", { class: "kpi-grid", "aria-label": t("Key figures") },
      kpi("gauge", "accent", t("Tokens"), compact(k.tokens.tokens), tokenNote, delta(k.tokens.tokens, k.tokens.previous)),
      kpi("shield", "run", t("Estimated cost"), costValue, costNote, k.cost.priced ? delta(k.cost.total ?? 0, k.cost.previous ?? 0) : null),
      kpi("users", "run", t("Active users"), `${number(k.users.active)} / ${number(k.users.total)}`, k.users.disabled ? t("{n} disabled", { n: k.users.disabled }) : t("{n} admin(s)", { n: k.users.admins })),
      kpi("projects", "accent", t("Active projects"), `${number(k.projects.active)} / ${number(k.projects.total)}`, t("{n} running job(s)", { n: k.jobs.running })),
      kpi("workflow", "run", t("Jobs"), number(k.jobs.total), t("{done} done · {esc} escalated · {failed} failed", { done: k.jobs.done, esc: k.jobs.escalated + k.jobs.waiting_for_input, failed: failedJobs })),
      kpi("clock", k.limits.hits ? "warn" : "run", t("Limit hits"), number(k.limits.hits), t("{at} at limit · {near} near", { at: k.limits.at_limit, near: k.limits.near })),
      kpi("shield", k.sign_ins.failed ? "warn" : "run", t("Sign-ins"), number(k.sign_ins.ok), t("{n} failed", { n: k.sign_ins.failed })),
      kpi("documents", data.delivery.waiting_reviews.length ? "warn" : "run", t("Reviews waiting"), number(data.delivery.waiting_reviews.length), t("{q} open question(s) · {d} open DR(s)", { q: data.delivery.open_questions, d: data.delivery.open_drs })),
    );

    const hasCalls = k.tokens.calls > 0;
    const chart = panel("chart-title", t("Tokens per day"),
      hasCalls
        ? stackedBars(data.daily, { title: t("Tokens per day"), series: [{ key: "input", label: t("Input tokens"), cls: "s1" }, { key: "output", label: t("Output tokens"), cls: "s2" }] })
        : empty(t("No model calls in this period.")),
      h("span", { class: "muted" }, t("{calls} calls · {n} days", { calls: number(k.tokens.calls), n: data.period.days })),
    );

    const users = panel("top-users", t("Top users"),
      data.top_users.length
        ? barList(data.top_users.map((u) => ({ label: u.name, value: u.tokens, note: t("{calls} calls · {cost}", { calls: number(u.calls), cost: k.cost.priced ? money(u.cost, currency) : t("cost not set") }) })), { valueLabel: compact, caption: t("Top users") })
        : empty(t("No model calls in this period.")),
      h("a", { href: "#/users", class: "text-action" }, t("Manage users")),
    );
    const projects = panel("top-projects", t("Top projects"),
      data.top_projects.length
        ? barList(data.top_projects.map((p) => ({ label: p.project_id ?? "–", href: p.project_id ? `#/p/${p.project_id}/overview` : null, value: p.tokens, note: t("{calls} calls · {cost}", { calls: number(p.calls), cost: k.cost.priced ? money(p.cost, currency) : t("cost not set") }) })), { valueLabel: compact, caption: t("Top projects") })
        : empty(t("No model calls in this period.")),
      h("a", { href: "#/admin-projects", class: "text-action" }, t("All projects")),
    );

    const models = panel("models-title", t("Models and cost"),
      data.models.length
        ? table(
            [t("Model"), t("Calls"), t("Input tokens"), t("Output tokens"), t("Estimated cost")],
            data.models.map((m) => [h("code", {}, m.model ?? "–"), number(m.calls), number(m.input), number(m.output), m.cost === null ? h("span", { class: "muted" }, k.cost.priced ? t("Not priced") : "–") : money(m.cost, currency)]),
            t("Models and cost"),
            { dense: true },
          )
        : empty(t("No model calls in this period.")),
      h("button", { type: "button", class: "link", onClick: editPrices }, t("Edit prices")),
    );
    const kinds = panel("kinds-title", t("Tokens by job type"),
      data.kinds.length
        ? barList(data.kinds.map((x) => ({ label: kindLabel(x.kind), value: x.tokens, note: t("{calls} calls", { calls: number(x.calls) }) })), { valueLabel: compact, caption: t("Tokens by job type") })
        : empty(t("No model calls in this period.")),
    );

    const d = data.delivery;
    const delivery = panel("delivery-title", t("Delivery status"),
      h("div", { class: "delivery" },
        h("dl", { class: "doc-states" }, DOC_STATES.map(([key, label]) => h("div", { class: `doc-state ${key}` }, h("dt", {}, t(label)), h("dd", {}, number(d.documents[key] ?? 0))))),
        table(
          [t("Phase"), ...STAGE_STATES.map((s) => badge(s))],
          Object.entries(d.stages).map(([stage, counts]) => [t(STAGE_LABELS[stage] ?? stage), ...STAGE_STATES.map((s) => counts[s] ? h("strong", {}, number(counts[s])) : h("span", { class: "muted" }, "0"))]),
          t("Phases by status across projects"),
          { dense: true },
        ),
      ),
      h("span", { class: "muted" }, t("{n} project(s)", { n: k.projects.total })),
    );

    const a = data.attention;
    const attentionItems = [
      ...d.waiting_reviews.map((r) => h("li", {}, badge("in_review"), " ", h("a", { href: `#/p/${r.project_id}/overview` }, h("code", {}, r.project_id)), " ", t("{stage} is waiting for approval", { stage: t(STAGE_LABELS[r.stage] ?? r.stage) }))),
      ...a.jobs.map((j) => h("li", {}, badge(j.status), " ", h("a", { href: `#/p/${j.project_id}/activity` }, h("code", {}, j.project_id)), " ", kindLabel(j.kind), " · ", j.user ?? "–", " · ", h("span", { class: "muted" }, fmtTime(j.finished ?? j.started)), j.error ? h("p", { class: "attention-error" }, j.error) : null)),
      ...a.running.map((j) => h("li", {}, badge("running"), " ", h("a", { href: `#/p/${j.project_id}/activity` }, h("code", {}, j.project_id)), " ", kindLabel(j.kind), " · ", j.user ?? "–")),
    ];
    const attention = panel("attention-title", t("Needs attention"),
      attentionItems.length ? h("ul", { class: "attention-list" }, attentionItems) : empty(t("Nothing is waiting.")),
    );
    const limits = panel("limits-title", t("Users near a limit"),
      [
        a.near_limit.length
          ? h("ul", { class: "near-list" }, a.near_limit.map((w) => h("li", {}, h("strong", {}, w.name), usageMeter(w, { compact: true }))))
          : empty(t("No user is at 80% of a limit.")),
        a.limit_hits.length
          ? h("details", { class: "hits" }, h("summary", {}, t("{n} recent limit hit(s)", { n: a.limit_hits.length })),
              table([t("Time"), t("User"), t("Window"), t("Where")], a.limit_hits.map((e) => [fmtTime(e.at), e.user, t(e.window === "session" ? "5-hour limit" : "Weekly limit"), t(HIT_CONTEXT[e.context] ?? e.context)]), t("Recent limit hits"), { dense: true }))
          : null,
      ],
    );

    const audit = panel("audit-title", t("Recent administration"),
      data.audit.length
        ? table([t("Time"), t("Actor"), t("Action"), t("Target")], data.audit.map((e) => [fmtTime(e.at), e.actor === "anonymous" ? h("span", { class: "muted" }, t("not signed in")) : e.actor, actionLabel(e.action), e.project_id ? `${e.target ?? ""} · ${e.project_id}` : e.target ?? "–"]), t("Recent administration"), { dense: true })
        : empty(t("No events yet.")),
      h("a", { href: "#/audit", class: "text-action" }, t("Open the audit log")),
    );

    return [
      kpis,
      chart,
      h("div", { class: "admin-columns" }, users, projects),
      h("div", { class: "admin-columns" }, models, kinds),
      h("div", { class: "admin-columns" }, attention, limits),
      delivery,
      audit,
    ];
  }

  await load();
  return () => { token++; };
}

const HIT_CONTEXT = { job_start: N_("Job refused"), run: N_("Run stopped"), auto_propagation: N_("Propagation not started") };
