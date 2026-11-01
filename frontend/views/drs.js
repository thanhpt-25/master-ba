import { badge, cellText, clear, empty, field, h, table } from "../dom.js";

const TRIGGERS = {
  requirement_change: "Requirement change",
  design_change: "Design change",
  defect: "Defect",
  clarification: "Clarification",
};

function impactPreview(impact) {
  if (!impact) return empty("Impact is calculated when the record is approved. The documents listed on the record are the preview.");
  return h(
    "div",
    {},
    h("h3", {}, "Documents that will be revised, in order"),
    h("ol", { class: "order" }, impact.documents.map((d) => h("li", {}, h("code", {}, d)))),
    impact.entries.length
      ? table(["Item", "Depth", "Link"], impact.entries.map((e) => [h("code", {}, e.node_id), e.depth, `${e.link_type} (${e.direction})`]), "Affected items")
      : empty("Nothing else is connected to the impacted items."),
  );
}

function progress(propagation) {
  if (!propagation) return null;
  return h(
    "div",
    {},
    h("h3", {}, "Propagation"),
    table(
      ["Document", "Outcome", "Version", "Run"],
      Object.entries(propagation.documents).map(([doc, v]) => [h("code", {}, doc), v.outcome, v.version ? `v${v.version}` : "unchanged", h("code", {}, v.run_id)]),
      "Propagation progress",
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
        h("a", { href: `#/p/${pid}/drs/${d.id}`, "aria-current": d.id === drId ? "page" : null }, h("code", {}, d.id), h("span", {}, TRIGGERS[d.trigger]), badge(d.status)),
      ),
    ),
  );

  const trigger = h("select", { id: "trigger" }, Object.entries(TRIGGERS).map(([v, l]) => h("option", { value: v }, l)));
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
              toast(`Created ${made.id}`);
              go(`#/p/${pid}/drs/${made.id}`);
            } catch (error) {
              toast(error.message, "error");
            }
          },
        },
        h("h2", {}, "Propose a change"),
        field("Kind of change", trigger),
        field("What changes and why", description),
        field("Affected requirements or items", items, "One id per line. A clarification may have none."),
        h("button", { type: "submit", class: "primary" }, "Propose"),
      )
    : null;

  const detail = h("div", { class: "doc-detail" });
  clear(main).append(
    h("h1", {}, "Decision Records"),
    h("div", { class: "split" }, h("nav", { "aria-label": "Decision records" }, drs.length ? list : empty("No decision records."), createForm), detail),
  );
  if (!drId) {
    detail.append(empty("Select a record to see its impact and decide."));
    return;
  }

  async function draw() {
    if (stopped) return;
    const data = await api.get(`/projects/${pid}/drs/${drId}`);
    const dr = data.dr;
    const decision = h("textarea", { id: "decision", rows: "2" });
    const rationale = h("textarea", { id: "rationale", rows: "2" });
    const act = async (path, body) => {
      try {
        await api.post(`/projects/${pid}/drs/${drId}/${path}`, body);
        await draw();
      } catch (error) {
        toast(error.message, "error");
      }
    };
    const children = [
      h("div", { class: "vcard-head" }, h("h2", {}, h("code", {}, dr.id), " ", TRIGGERS[dr.trigger]), badge(dr.status)),
      h("p", { class: "muted" }, `Proposed ${dr.date}${dr.approver ? ` · decided by ${dr.approver}` : ""}`),
      h("p", { class: "prose" }, dr.description),
      dr.decision ? h("p", {}, h("strong", {}, "Decision: "), dr.decision, dr.rationale ? ` — ${dr.rationale}` : "") : null,
      h("p", {}, h("strong", {}, "Impacted: "), dr.impacted_items.length ? dr.impacted_items.map((i) => h("code", { class: "chip" }, i)) : "none named"),
      dr.status === "proposed" ? h("div", {}, h("h3", {}, "Affected documents (preview)"), h("ol", { class: "order" }, dr.affected_documents.map((d) => h("li", {}, h("code", {}, d))))) : impactPreview(data.impact),
      progress(data.propagation),
    ];
    if (canAct && dr.status === "proposed") {
      children.push(
        h(
          "section",
          { class: "panel" },
          h("h3", {}, "Decide"),
          field("Decision", decision, "Recorded with your name."),
          field("Rationale (optional)", rationale),
          h(
            "div",
            { class: "toolbar" },
            h("button", { class: "primary", onClick: () => (decision.value.trim() ? act("approve", { decision: decision.value, rationale: rationale.value || null }) : toast("Write the decision first.", "error")) }, "Approve"),
            h("button", { onClick: () => (decision.value.trim() ? confirm("Reject this record? It is closed and never propagated.") && act("reject", { decision: decision.value, rationale: rationale.value || null }) : toast("Write the decision first.", "error")) }, "Reject"),
          ),
        ),
      );
    }
    if (canAct && dr.status === "approved") {
      children.push(
        h("section", { class: "panel propagate" }, h("h3", {}, "Propagate"), h("p", { class: "muted" }, "Revises the documents above as new versions. This calls the models."), h("button", { class: "primary", onClick: () => confirm("Propagate now? The models revise every affected document.") && act("propagate").then(poll) }, "Propagate")),
      );
    }
    if (canAct && dr.status === "propagated") {
      children.push(h("button", { onClick: () => confirm("Close this record? It cannot be reopened.") && act("close") }, "Close record"));
    }
    if (["propagated", "closed"].includes(dr.status) && data.propagation) {
      const diff = await api.get(`/projects/${pid}/drs/${drId}/diff`);
      children.push(
        h("h3", {}, "What changed"),
        diff.documents.length
          ? diff.documents.map((d) =>
              h("section", {}, h("h4", {}, h("code", {}, d.doc_id), ` v${d.old_version} → v${d.new_version}`), table(["Item", "Field", "Old", "New", "Kind"], d.rows.map((r) => [h("code", {}, r.item_id.split("#")[1] ?? r.item_id), r.field ?? r.change, cellText(r.old), cellText(r.new), r.classification.replace("_", " ")]), "Differences")),
            )
          : empty("No document needed a change."),
      );
    }
    clear(detail).append(...children.flat().filter(Boolean));
  }

  async function poll() {
    if (stopped) return;
    const jobs = await api.get(`/projects/${pid}/jobs`);
    const job = jobs.find((j) => j.kind === `propagate:${drId}`);
    if (job && ["queued", "running"].includes(job.status)) {
      detail.querySelector(".job")?.remove();
      detail.querySelector(".propagate")?.remove();
      detail.append(h("section", { class: "panel job" }, h("div", { class: "vcard-head" }, h("h3", {}, "Propagating"), badge(job.status)), h("pre", { class: "log", tabindex: "0", "aria-label": "Job log" }, job.log.join("\n"))));
      timer = setTimeout(() => poll().catch((e) => toast(e.message, "error")), 2000);
    } else {
      await draw();
      if (job?.status === "escalated") toast("A document could not be revised: see the run in Activity.", "error");
      if (job?.status === "failed") toast(job.error, "error");
    }
  }

  await draw();
  await poll();
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}
