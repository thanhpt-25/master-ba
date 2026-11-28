// 変更管理 (spec 26 section 7): Decision Records listed on the left with a status filter, the
// selected record on the right as four sheets (変更管理票, 影響分析, 反映結果, 履歴) under the
// action of its state.

import { badge, clear, confirmDialog, empty, field, fmtTime, h, icon, liveDot, modal, pageHeader, statusLabel } from "../dom.js";
import { N_, t } from "../i18n.js";
import { sheetTabs } from "./documents.js";
import { describeCommit } from "./history.js";

const TRIGGERS = {
  requirement_change: N_("Requirement change"),
  design_change: N_("Design change"),
  defect: N_("Defect"),
  clarification: N_("Clarification"),
  knowledge_change: N_("Knowledge change"),
  review_feedback: N_("Review feedback"),
};
// Triggers a person proposes by hand; the others come from answers, reviews and the knowledge base.
const PROPOSABLE = ["requirement_change", "design_change", "defect", "clarification"];
const trigger_ = (key) => t(TRIGGERS[key] ?? key);

export const DR_STATUSES = ["proposed", "approved", "propagated", "closed"];
const OUTCOMES = { revised: N_("Revised"), unchanged: N_("Unchanged") };

// Counts per status for the filter chips; "all" counts every record.
export function statusCounts(drs) {
  const counts = { all: drs.length };
  for (const s of DR_STATUSES) counts[s] = drs.filter((d) => d.status === s).length;
  return counts;
}

// The records a reader sees: newest first, one status or all, and a text filter over id, kind and text.
export function filterRecords(drs, status = "all", query = "") {
  const q = String(query).trim().toLowerCase();
  return drs
    .filter((d) => status === "all" || d.status === status)
    .filter((d) => !q || `${d.id} ${trigger_(d.trigger)} ${d.trigger} ${d.description}`.toLowerCase().includes(q))
    .sort((a, b) => b.id.localeCompare(a.id));
}

// The records whose affected documents include a document, for the Documents preview.
export function recordsFor(drs, docId) {
  return drs.filter((d) => (d.affected_documents ?? []).includes(docId)).sort((a, b) => b.id.localeCompare(a.id));
}

// The four sheets of a record, in the shape sheetTabs draws (pure: the tests read them).
export function drSheets(dr, { impact = null, propagation = null, diff = null, history = [] } = {}) {
  const none = "—";
  const form = {
    key: "form",
    kind: "cover",
    name: "変更管理票",
    title: "変更管理票",
    rows: [
      ["管理番号", dr.id],
      ["変更区分", trigger_(dr.trigger)],
      ["起票日", dr.date],
      ["状態", statusLabel(dr.status)],
      ["変更内容", dr.description],
      ["対象項目", dr.impacted_items.join("\n") || none],
      ["影響文書", (impact?.documents ?? dr.affected_documents).join("\n") || none],
      ["判断", dr.decision ?? none],
      ["理由", dr.rationale ?? none],
      ["承認者", dr.approver ?? none],
    ],
  };
  let impactSheet;
  if (!impact) {
    impactSheet = {
      key: "impact", kind: "table", name: "影響分析",
      note: t("Impact is calculated when the record is approved. The documents listed on the record are the preview."),
      columns: [t("Order"), t("Document")],
      rows: dr.affected_documents.map((d, i) => [String(i + 1), d]),
    };
  } else {
    const order = impact.documents.map((d, i) => `${i + 1}. ${d}`).join("\n");
    impactSheet = {
      key: "impact", kind: "table", name: "影響分析",
      note: order ? `${t("Documents that will be revised, in order")}:\n${order}` : null,
      columns: [t("Item"), t("Depth"), t("Link")],
      rows: impact.entries.map((e) => [e.node_id, String(e.depth), `${e.link_type} (${e.direction})`]),
    };
  }
  // 反映結果: one row per document, or one per changed item once the record is propagated.
  let result;
  if (!propagation) {
    result = { key: "result", kind: "note", name: "反映結果", note: t("Not propagated yet. Approve the record, then propagate it.") };
  } else {
    const changed = new Map((diff?.documents ?? []).map((d) => [d.doc_id, d]));
    // The store sorts JSON keys; print the documents in V order (the impact analysis order).
    const order = impact?.documents ?? dr.affected_documents ?? [];
    const rank = (doc) => (order.includes(doc) ? order.indexOf(doc) : order.length);
    const entries = Object.entries(propagation.documents).sort(([a], [b]) => rank(a) - rank(b));
    const rows = entries.flatMap(([doc, v]) => {
      const outcome = t(OUTCOMES[v.outcome] ?? v.outcome);
      const version = v.version ? `v${v.version}` : t("unchanged");
      const d = changed.get(doc);
      if (!d || !d.rows.length) return [[doc, outcome, version, "", "", "", ""]];
      return d.rows.map((r) => [doc, outcome, `v${d.old_version}→v${d.new_version}`, r.item_id.split("#")[1] ?? r.item_id, r.field ?? r.change, cellString(r.old), cellString(r.new)]);
    });
    result = {
      key: "result", kind: "table", name: "反映結果",
      note: diff ? null : t("Propagation per document. What changed shows once the record is propagated."),
      columns: [t("Document"), t("Outcome"), t("Version"), t("Item"), t("Field"), t("Old"), t("New")],
      rows,
    };
  }
  const sheets = [form, impactSheet, result];
  sheets.push({
    key: "history", kind: "table", name: "履歴",
    columns: [t("When"), t("Who"), t("What")],
    rows: history.map((e) => {
      const said = describeCommit(e.subject);
      return [fmtTime(e.time), e.author, `${said.label}: ${said.detail}`];
    }),
  });
  return sheets;
}

function cellString(value) {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

const FILTER_KEY = "masterba-dr-filter";
function savedFilter() {
  try {
    const value = localStorage.getItem(FILTER_KEY);
    return value && (value === "all" || DR_STATUSES.includes(value)) ? value : "all";
  } catch {
    return "all";
  }
}

export async function render({ main, api, params, me, toast, go }) {
  const pid = params.pid;
  const drId = params.rest[0] ?? null;
  const canAct = ["approver", "admin"].includes(me.role);
  let timer = null;
  let stopped = false;

  const drs = await api.get(`/projects/${pid}/drs`);
  let status = savedFilter();
  const counts = statusCounts(drs);
  const listHost = h("ul", { class: "record-list" });
  const search = h("input", { type: "search", id: "dr-filter", placeholder: t("Filter by id, kind or text"), "aria-label": t("Filter by id, kind or text"), autocomplete: "off" });
  const chips = ["all", ...DR_STATUSES].map((key) =>
    h("button", { type: "button", class: "filter-chip", "data-status": key, "aria-pressed": String(key === status) },
      key === "all" ? t("All") : statusLabel(key), h("span", { class: "count" }, String(counts[key]))));
  const drawList = () => {
    const shown = filterRecords(drs, status, search.value);
    const rows = shown.length
        ? shown.map((d) =>
            h("li", {}, h("a", { href: `#/p/${pid}/drs/${d.id}`, "aria-current": d.id === drId ? "page" : null },
              h("span", { class: "record-top" }, h("code", {}, d.id), badge(d.status)),
              h("span", { class: "record-kind" }, trigger_(d.trigger), " · ", d.date),
              h("span", { class: "record-text" }, d.description))))
        : [h("li", { class: "muted record-none" }, drs.length ? t("No record matches the filter.") : t("No decision records."))];
    clear(listHost).append(...rows);
  };
  for (const chip of chips) {
    chip.addEventListener("click", () => {
      status = chip.dataset.status;
      for (const c of chips) c.setAttribute("aria-pressed", String(c === chip));
      try { localStorage.setItem(FILTER_KEY, status); } catch { /* kept for this page only */ }
      drawList();
    });
  }
  search.addEventListener("input", drawList);
  drawList();

  // Proposing a change is an occasional action: a dialog from the page header, not a form in the list.
  const openCreate = () => modal((close) => {
    const trigger = h("select", { id: "trigger" }, PROPOSABLE.map((v) => h("option", { value: v }, trigger_(v))));
    const description = h("textarea", { id: "description", rows: "3", required: true });
    const items = h("textarea", { id: "items", rows: "3", spellcheck: "false", autocomplete: "off", placeholder: "REQ-0002\nDOC-SRS-0001#item.2…" });
    queueMicrotask(() => trigger.focus({ preventScroll: true }));
    return h(
      "form",
      {
        class: "dialog create-dialog",
        onSubmit: async (event) => {
          event.preventDefault();
          try {
            const made = await api.post(`/projects/${pid}/drs`, {
              trigger: trigger.value,
              description: description.value,
              items: items.value.split("\n").map((s) => s.trim()).filter(Boolean),
            });
            close();
            toast(t("Created {id}", { id: made.id }));
            go(`#/p/${pid}/drs/${made.id}`);
          } catch (error) {
            toast(error.message, "error");
          }
        },
      },
      h("div", { class: "dialog-top" },
        h("span", { class: "dialog-icon", "aria-hidden": "true" }, icon("drs", 18)),
        h("h2", { id: "dr-create-title" }, t("Propose a change")),
        h("button", { type: "button", class: "icon-button", "aria-label": t("Close"), onClick: close }, icon("close", 18)),
      ),
      field(t("Kind of change"), trigger),
      field(t("What changes and why"), description),
      field(t("Affected requirements or items"), items, t("One id per line. A clarification may have none.")),
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", onClick: close }, t("Cancel")),
        h("button", { type: "submit", class: "primary" }, t("Propose")),
      ),
    );
  }, { labelledBy: "dr-create-title" });

  const detail = h("section", { class: "explorer-preview", "aria-label": t("Preview") });
  const explorer = h("div", { class: "explorer records", "data-view": drId ? "preview" : "tree" },
    h("aside", { class: "explorer-tree", "aria-label": t("Decision Records") },
      h("div", { class: "explorer-tools" }, h("div", { class: "filter-chips", role: "group", "aria-label": t("Filter by status") }, chips), search),
      h("nav", { class: "tree-host", "aria-label": t("Decision Records") }, listHost)),
    detail);
  clear(main).append(
    pageHeader(t("Decision Records"), t("Every change request as a form: its impact, how it was carried into the documents, and its history."),
      canAct ? h("button", { class: "primary", type: "button", onClick: openCreate }, icon("plus", 16), t("Propose a change")) : null),
    explorer,
  );
  if (!drId) {
    detail.append(drs.length
      ? empty(t("Select a record to see its impact and decide."))
      : empty(t("No Decision Record yet. Propose one when a requirement or design has to change; its impact is analysed before anything is rewritten."),
        canAct ? h("button", { class: "primary", type: "button", onClick: openCreate }, icon("plus", 16), t("Propose a change")) : null));
    return;
  }

  const band = h("div", { class: "action-host" });
  async function draw() {
    if (stopped) return;
    const [data, history] = await Promise.all([
      api.get(`/projects/${pid}/drs/${drId}`),
      api.get(`/projects/${pid}/drs/${drId}/history`).catch(() => []),
    ]);
    const dr = data.dr;
    const diff = ["propagated", "closed"].includes(dr.status) && data.propagation
      ? await api.get(`/projects/${pid}/drs/${drId}/diff`).catch(() => null)
      : null;
    const act = async (path, body) => {
      try {
        const done = await api.post(`/projects/${pid}/drs/${drId}/${path}`, body);
        if (done?.propagation_note) toast(done.propagation_note, "error");
        await draw();
        if (done?.job) poll().catch((e) => toast(e.message, "error"));
      } catch (error) {
        toast(error.message, "error");
      }
    };
    clear(band);
    const action = canAct ? actionBand(dr, act) : null;
    if (action) band.append(action);
    const back = h("button", { type: "button", class: "explorer-back", onClick: () => { explorer.dataset.view = "tree"; } }, icon("back", 15), t("Records"));
    clear(detail).append(
      back,
      h("nav", { class: "crumbs", "aria-label": t("Path") }, h("ol", {}, h("li", {}, pid), h("li", {}, t("Decision Records")), h("li", { "aria-current": "location" }, dr.id))),
      h("header", { class: "preview-head" },
        h("span", { class: "preview-icon", "aria-hidden": "true" }, icon("drs", 22)),
        h("div", { class: "preview-title" }, h("h2", {}, h("code", {}, dr.id), " ", trigger_(dr.trigger)),
          h("p", { class: "muted" }, `${t("Proposed {date}", { date: dr.date })}${dr.approver ? ` · ${t("decided by {name}", { name: dr.approver })}` : ""}`)),
        badge(dr.status)),
      band,
      h("div", { class: "workbook" }, sheetTabs(drSheets(dr, { impact: data.impact, propagation: data.propagation, diff, history }))),
    );
  }

  // The one action of the record's state, above the sheets like the review band of a document.
  function actionBand(dr, act) {
    if (dr.status === "proposed") {
      const decision = h("textarea", { id: "decision", rows: "2" });
      const rationale = h("textarea", { id: "rationale", rows: "2" });
      const decisionField = field(t("Decision"), decision, t("Recorded with your name."));
      const setDecisionError = (msg) => {
        decisionField.classList.toggle("invalid", Boolean(msg));
        decisionField.querySelector(".field-error")?.remove();
        if (msg) {
          decision.setAttribute("aria-invalid", "true");
          decisionField.append(h("p", { class: "field-error", role: "alert" }, msg));
        } else {
          decision.removeAttribute("aria-invalid");
        }
      };
      decision.addEventListener("input", () => { if (decision.value.trim()) setDecisionError(null); });
      const requireDecision = () => {
        if (decision.value.trim()) return true;
        setDecisionError(t("Write the decision first."));
        decision.focus();
        return false;
      };
      const reject = async () => {
        if (!requireDecision()) return;
        const ok = await confirmDialog({ title: t("Reject this record?"), message: t("It is closed and never propagated."), confirmLabel: t("Reject"), danger: true });
        if (ok) act("reject", { decision: decision.value, rationale: rationale.value || null });
      };
      return h("section", { class: "action-band", "aria-labelledby": "decide-title" },
        h("h3", { id: "decide-title" }, t("Decide")),
        h("p", { class: "muted" }, t("Read the impact analysis, then approve or reject the change.")),
        h("div", { class: "field-pair" }, decisionField, field(t("Rationale (optional)"), rationale)),
        h("div", { class: "band-actions" },
          h("button", { class: "primary", type: "button", onClick: () => requireDecision() && act("approve", { decision: decision.value, rationale: rationale.value || null }) }, t("Approve")),
          h("button", { type: "button", onClick: reject }, t("Reject"))));
    }
    if (dr.status === "approved") {
      const propagate = async () => {
        const ok = await confirmDialog({ title: t("Propagate now?"), message: t("The models revise every affected document as new versions."), confirmLabel: t("Propagate") });
        if (ok) act("propagate").then(poll).catch((e) => toast(e.message, "error"));
      };
      return h("section", { class: "action-band propagate" },
        h("div", {}, h("h3", {}, t("Propagate")), h("p", { class: "muted" }, t("Revises the documents in the impact analysis as new versions. This calls the models."))),
        h("button", { class: "primary", type: "button", onClick: propagate }, t("Propagate")));
    }
    if (dr.status === "propagated") {
      const close = async () => {
        const ok = await confirmDialog({ title: t("Close this record?"), message: t("It cannot be reopened."), confirmLabel: t("Close record") });
        if (ok) act("close");
      };
      return h("section", { class: "action-band" },
        h("div", {}, h("h3", {}, t("Close record")), h("p", { class: "muted" }, t("Check the result sheet, then close the record."))),
        h("button", { type: "button", onClick: close }, t("Close record")));
    }
    return null;
  }

  let polling = false;
  let paused = false;

  // Shared by the Pause/Resume button and the "P" shortcut so they stay in sync.
  const togglePause = () => {
    if (!polling) return;
    paused = !paused;
    clearTimeout(timer);
    if (!paused) poll().catch((e) => toast(e.message, "error"));
    else refreshJobPanel();
  };

  const liveBar = () => {
    const toggle = h(
      "button",
      { class: "link", type: "button", onClick: togglePause, title: t("Pause or resume live updates (P)") },
      paused ? t("Resume updates (P)") : t("Pause updates (P)"),
    );
    return h("div", { class: "live-bar" }, liveDot(!paused, paused ? t("Paused") : t("Live")), toggle);
  };

  // Redraws the propagating panel from the last known job (used when pausing,
  // so the live bar reflects the paused state without a fresh fetch).
  let lastJob = null;
  const refreshJobPanel = () => {
    if (!lastJob) return;
    clear(band).append(
      h(
        "section",
        { class: "action-band job" },
        h("div", { class: "vcard-head" }, h("h3", {}, t("Propagating")), badge(lastJob.status), liveBar()),
        h("pre", { class: "log", tabindex: "0", "aria-label": t("Job log") }, lastJob.log.join("\n")),
      ),
    );
  };

  async function poll() {
    if (stopped || paused) return;
    const jobs = await api.get(`/projects/${pid}/jobs`);
    const job = jobs.find((j) => j.kind === `propagate:${drId}`);
    if (job && ["queued", "running"].includes(job.status)) {
      polling = true;
      lastJob = job;
      refreshJobPanel();
      if (!document.hidden) timer = setTimeout(() => poll().catch((e) => toast(e.message, "error")), 2000);
    } else {
      polling = false;
      lastJob = null;
      await draw();
      if (job?.status === "escalated") toast(t("A document could not be revised: see the run in Activity."), "error");
      if (job?.status === "waiting_for_input") toast(t("A reviewer needs a customer answer: answer the new questions in Questions, then press Propagate again."), "error");
      if (job?.status === "failed") toast(job.error, "error");
    }
  }

  // Idle the poll while the tab is backgrounded; resume on return.
  const onVisibility = () => {
    if (document.hidden) {
      clearTimeout(timer);
    } else if (!stopped && !paused && polling) {
      poll().catch((e) => toast(e.message, "error"));
    }
  };
  document.addEventListener("visibilitychange", onVisibility);

  // "P" toggles live polling, mirroring the Pause/Resume button. Skip while
  // typing in a field or with a modifier held, and only while a job is polling.
  const onKey = (event) => {
    if (event.key !== "p" && event.key !== "P") return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const el = document.activeElement;
    if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
    if (!polling) return;
    event.preventDefault();
    togglePause();
  };
  document.addEventListener("keydown", onKey);

  await draw();
  await poll();
  return () => {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibility);
    document.removeEventListener("keydown", onKey);
  };
}
