import { badge, cellText, clear, confirmDialog, empty, field, h, liveDot, table } from "../dom.js";
import { N_, t } from "../i18n.js";

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

function impactPreview(impact) {
  if (!impact) return empty(t("Impact is calculated when the record is approved. The documents listed on the record are the preview."));
  return h(
    "div",
    {},
    h("h3", {}, t("Documents that will be revised, in order")),
    h("ol", { class: "order" }, impact.documents.map((d) => h("li", {}, h("code", {}, d)))),
    impact.entries.length
      ? table([t("Item"), t("Depth"), t("Link")], impact.entries.map((e) => [h("code", {}, e.node_id), e.depth, `${e.link_type} (${e.direction})`]), t("Affected items"))
      : empty(t("Nothing else is connected to the impacted items.")),
  );
}

function progress(propagation) {
  if (!propagation) return null;
  return h(
    "div",
    {},
    h("h3", {}, t("Propagation")),
    table(
      [t("Document"), t("Outcome"), t("Version"), t("Run")],
      Object.entries(propagation.documents).map(([doc, v]) => [h("code", {}, doc), v.outcome, v.version ? `v${v.version}` : t("unchanged"), h("code", {}, v.run_id)]),
      t("Propagation progress"),
    ),
  );
}

export async function render({ main, api, params, me, toast, go }) {
  const pid = params.pid;
  const drId = params.rest[0] ?? null;
  const canAct = ["approver", "admin"].includes(me.role);
  let timer = null;
  let stopped = false;

  const drs = await api.get(`/projects/${pid}/drs`);
  const list = h(
    "ul",
    { class: "doc-list" },
    drs.map((d) =>
      h(
        "li",
        {},
        h("a", { href: `#/p/${pid}/drs/${d.id}`, "aria-current": d.id === drId ? "page" : null }, h("code", {}, d.id), h("span", {}, trigger_(d.trigger)), badge(d.status)),
      ),
    ),
  );

  const trigger = h("select", { id: "trigger" }, PROPOSABLE.map((v) => h("option", { value: v }, trigger_(v))));
  const description = h("textarea", { id: "description", rows: "3", required: true });
  const items = h("textarea", { id: "items", rows: "3", spellcheck: "false", autocomplete: "off", placeholder: "REQ-0002\nDOC-SRS-0001#item.2…" });
  const createForm = canAct
    ? h(
        "form",
        {
          class: "panel",
          onSubmit: async (event) => {
            event.preventDefault();
            try {
              const made = await api.post(`/projects/${pid}/drs`, {
                trigger: trigger.value,
                description: description.value,
                items: items.value.split("\n").map((s) => s.trim()).filter(Boolean),
              });
              toast(t("Created {id}", { id: made.id }));
              go(`#/p/${pid}/drs/${made.id}`);
            } catch (error) {
              toast(error.message, "error");
            }
          },
        },
        h("h2", {}, t("Propose a change")),
        field(t("Kind of change"), trigger),
        field(t("What changes and why"), description),
        field(t("Affected requirements or items"), items, t("One id per line. A clarification may have none.")),
        h("button", { type: "submit", class: "primary" }, t("Propose")),
      )
    : null;

  const detail = h("div", { class: "doc-detail" });
  clear(main).append(
    h("h1", {}, t("Decision Records")),
    h("div", { class: "split" }, h("nav", { "aria-label": t("Decision Records") }, drs.length ? list : empty(t("No decision records.")), createForm), detail),
  );
  if (!drId) {
    detail.append(empty(t("Select a record to see its impact and decide.")));
    return;
  }

  async function draw() {
    if (stopped) return;
    const data = await api.get(`/projects/${pid}/drs/${drId}`);
    const dr = data.dr;
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
    const children = [
      h("div", { class: "vcard-head" }, h("h2", {}, h("code", {}, dr.id), " ", trigger_(dr.trigger)), badge(dr.status)),
      h("p", { class: "muted" }, `${t("Proposed {date}", { date: dr.date })}${dr.approver ? ` · ${t("decided by {name}", { name: dr.approver })}` : ""}`),
      h("p", { class: "prose" }, dr.description),
      dr.decision ? h("p", {}, h("strong", {}, t("Decision: ")), dr.decision, dr.rationale ? ` · ${dr.rationale}` : "") : null,
      h("p", {}, h("strong", {}, t("Impacted: ")), dr.impacted_items.length ? dr.impacted_items.map((i) => h("code", { class: "chip" }, i)) : t("none named")),
      dr.status === "proposed" ? h("div", {}, h("h3", {}, t("Affected documents (preview)")), h("ol", { class: "order" }, dr.affected_documents.map((d) => h("li", {}, h("code", {}, d))))) : impactPreview(data.impact),
      progress(data.propagation),
    ];
    if (canAct && dr.status === "proposed") {
      const reject = async () => {
        if (!requireDecision()) return;
        const ok = await confirmDialog({ title: t("Reject this record?"), message: t("It is closed and never propagated."), confirmLabel: t("Reject"), danger: true });
        if (ok) act("reject", { decision: decision.value, rationale: rationale.value || null });
      };
      children.push(
        h(
          "section",
          { class: "panel" },
          h("h3", {}, t("Decide")),
          decisionField,
          field(t("Rationale (optional)"), rationale),
          h(
            "div",
            { class: "toolbar" },
            h("button", { class: "primary", onClick: () => requireDecision() && act("approve", { decision: decision.value, rationale: rationale.value || null }) }, t("Approve")),
            h("button", { onClick: reject }, t("Reject")),
          ),
        ),
      );
    }
    if (canAct && dr.status === "approved") {
      const propagate = async () => {
        const ok = await confirmDialog({ title: t("Propagate now?"), message: t("The models revise every affected document as new versions."), confirmLabel: t("Propagate") });
        if (ok) act("propagate").then(poll).catch((e) => toast(e.message, "error"));
      };
      children.push(
        h("section", { class: "panel propagate" }, h("h3", {}, t("Propagate")), h("p", { class: "muted" }, t("Revises the documents above as new versions. This calls the models.")), h("button", { class: "primary", onClick: propagate }, t("Propagate"))),
      );
    }
    if (canAct && dr.status === "propagated") {
      const close = async () => {
        const ok = await confirmDialog({ title: t("Close this record?"), message: t("It cannot be reopened."), confirmLabel: t("Close record") });
        if (ok) act("close");
      };
      children.push(h("button", { onClick: close }, t("Close record")));
    }
    if (["propagated", "closed"].includes(dr.status) && data.propagation) {
      const diff = await api.get(`/projects/${pid}/drs/${drId}/diff`);
      children.push(
        h("h3", {}, t("What changed")),
        diff.documents.length
          ? diff.documents.map((d) =>
              h("section", {}, h("h4", {}, h("code", {}, d.doc_id), ` v${d.old_version} → v${d.new_version}`), table([t("Item"), t("Field"), t("Old"), t("New"), t("Kind")], d.rows.map((r) => [h("code", {}, r.item_id.split("#")[1] ?? r.item_id), r.field ?? r.change, cellText(r.old), cellText(r.new), r.classification.replace("_", " ")]), t("Differences"))),
            )
          : empty(t("No document needed a change.")),
      );
    }
    clear(detail).append(...children.flat().filter(Boolean));
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
    detail.querySelector(".job")?.remove();
    detail.querySelector(".propagate")?.remove();
    detail.append(
      h(
        "section",
        { class: "panel job" },
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
