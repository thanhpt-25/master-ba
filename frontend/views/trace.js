import { badge, clear, empty, h, spinner } from "../dom.js";

const DOC_TYPES = {
  BRD: "Business requirements",
  SRS: "System requirements",
  BASIC_DESIGN: "Basic design",
  DETAIL_DESIGN: "Detail design",
  TEST_IT: "Integration test",
  TEST_ST: "System test",
  TEST_UT: "Unit test",
  TEST_UAT: "Acceptance test",
};

function artifactType(id, kind) {
  if (kind === "requirement") return "Requirement";
  if (id.startsWith("TC-")) return "Test case";
  const documentType = id.match(/^DOC-([^#]+)/)?.[1];
  return DOC_TYPES[documentType] ?? (documentType ? "Document item" : "Trace item");
}

function nodeCard(id, info, index, onExplore) {
  const action = h("button", {
    class: "trace-explore",
    type: "button",
    onClick: () => onExplore(id),
    "aria-label": `Explore impact from ${id}`,
  }, "Explore impact", h("span", { "aria-hidden": "true" }, "↗"));
  return h(
    "li",
    { class: `trace-step${info.kind === "requirement" ? " is-requirement" : ""}` },
    h("article", { class: "trace-node" },
      h("div", { class: "trace-node-top" },
        h("span", { class: "trace-kind" }, artifactType(id, info.kind)),
        info.status ? badge(info.status) : null,
      ),
      h("code", { class: "trace-id" }, id),
      info.text ? h("p", { class: "trace-node-text" }, info.text) : null,
      h("div", { class: "trace-node-bottom" },
        h("span", { class: "trace-step-number", "aria-label": `Step ${index + 1}` }, String(index + 1).padStart(2, "0")),
        action,
      ),
    ),
  );
}

function impactCard(row, onExplore) {
  return h("li", { class: "impact-item" },
    h("div", { class: "impact-item-main" },
      h("div", { class: "impact-meta" },
        h("span", { class: "impact-depth" }, `Depth ${row.depth}`),
        h("span", { class: "impact-link-type" }, String(row.link_type).replaceAll("_", " ")),
        h("span", { class: "impact-direction" }, row.direction === "upstream" ? "Upstream" : "Downstream"),
      ),
      h("code", {}, row.node_id),
      row.text ? h("p", {}, row.text) : null,
    ),
    h("button", { class: "trace-explore", type: "button", onClick: () => onExplore(row.node_id) }, "Explore from here", h("span", { "aria-hidden": "true" }, "↗")),
  );
}

export async function render({ main, api, params, toast }) {
  const pid = params.pid;
  const requirements = await api.get(`/projects/${pid}/requirements`);
  const result = h("section", { class: "trace-results", "aria-live": "polite", "aria-busy": "false" });
  const impact = h("div", { class: "trace-impact-results", "aria-live": "polite" });

  const select = h("select", { id: "req", "aria-label": "Select a requirement" },
    h("option", { value: "" }, "Choose a requirement…"),
    requirements.map((r) => h("option", { value: r.id }, `${r.id} — ${r.text}`)),
  );
  const requirementSearch = h("input", {
    type: "search", id: "req-search", placeholder: "Filter by ID or keyword", autocomplete: "off",
    "aria-label": "Filter requirements by ID or text",
  });
  const traceStart = h("div", { class: "trace-start" });
  const pathList = h("div", { class: "trace-path-list" });

  const node = h("input", { type: "text", id: "node", name: "node", autocomplete: "off", spellcheck: "false", placeholder: "REQ-0001 or DOC-SRS-0001#item.2", "aria-describedby": "trace-impact-help" });
  const direction = h("select", { id: "dir", "aria-label": "Impact direction" },
    h("option", { value: "downstream" }, "Downstream · what this item affects"),
    h("option", { value: "upstream" }, "Upstream · what this item depends on"),
    h("option", { value: "both" }, "Both directions"),
  );
  const findBtn = h("button", { class: "primary", type: "submit" }, "Find impact");
  const impactForm = h("form", { class: "trace-impact-form" },
    h("div", { class: "trace-field trace-node-field" }, h("label", { for: "node" }, "Start from an item"), node),
    h("div", { class: "trace-field trace-direction-field" }, h("label", { for: "dir" }, "Explore"), direction),
    findBtn,
  );

  async function findImpact(startId = node.value.trim()) {
    if (!startId) {
      node.focus();
      return toast("Enter or choose an item ID first.", "error");
    }
    node.value = startId;
    findBtn.disabled = true;
    impact.setAttribute("aria-busy", "true");
    clear(impact).append(spinner("Finding connected items…"));
    try {
      const rows = await api.get(`/projects/${pid}/impact?node=${encodeURIComponent(startId)}&direction=${direction.value}`);
      clear(impact);
      if (!rows.length) {
        impact.append(empty("No connected items were found in this direction. Try another direction or start from a linked item."));
        return;
      }
      impact.append(
        h("div", { class: "trace-section-heading" },
          h("h3", {}, `${rows.length} connected item${rows.length === 1 ? "" : "s"}`),
          h("p", { class: "muted" }, `Starting from ${startId}`),
        ),
        h("ul", { class: "impact-list" }, rows.map((row) => impactCard(row, findImpact))),
      );
    } catch (error) {
      clear(impact).append(h("p", { class: "error" }, error.message));
      toast(error.message, "error");
    } finally {
      impact.removeAttribute("aria-busy");
      findBtn.disabled = false;
    }
  }

  async function load(id) {
    if (!id) {
      traceStart.replaceChildren();
      pathList.replaceChildren(empty("Choose a requirement to follow its path through design and test cases."));
      result.setAttribute("aria-busy", "false");
      return;
    }
    result.setAttribute("aria-busy", "true");
    clear(pathList).append(spinner("Loading trace paths…"));
    try {
      const data = await api.get(`/projects/${pid}/rtm/${id}`);
      const paths = data.paths ?? [];
      const allNodes = [...new Set(paths.flat())];
      const testCases = new Set(allNodes.filter((item) => item.startsWith("TC-") || item.includes("TEST_") && /#item\.\d+$/.test(item)));
      const requirement = requirements.find((item) => item.id === id);
      clear(traceStart).append(
        h("div", { class: "trace-selected-mark" }, "Selected requirement"),
        h("div", { class: "trace-selected-copy" }, h("code", {}, id), h("p", {}, requirement?.text ?? "")),
      );
      node.value = id;
      clear(pathList);
      if (!paths.length) {
        pathList.append(empty(`${id} is not connected to a test case yet. You can still explore upstream or downstream links below.`));
        return;
      }
      pathList.append(
        h("div", { class: "trace-stats", "aria-label": "Trace summary" },
          stat(paths.length, "Trace paths"),
          stat(allNodes.length, "Unique items"),
          stat(testCases.size, "Test endpoints"),
        ),
        h("div", { class: "trace-path-heading" }, h("h3", {}, "Requirement coverage"), h("p", { class: "muted" }, "Follow each path from the requirement to its test endpoint.")),
        h("ol", { class: "trace-paths" }, paths.map((path, index) => h("li", { class: "trace-path-card" },
          h("div", { class: "trace-path-card-head" },
            h("span", { class: "trace-path-label" }, `Path ${String(index + 1).padStart(2, "0")}`),
            h("span", { class: "trace-path-length" }, `${path.length} steps`),
          ),
          h("ol", { class: "trace-steps", "aria-label": `Path ${index + 1}` }, path.map((item, step) => nodeCard(item, data.nodes[item] ?? {}, step, findImpact))),
        ))),
      );
    } catch (error) {
      clear(traceStart);
      clear(pathList).append(h("p", { class: "error" }, `Could not load trace: ${error.message}`));
      toast(error.message, "error");
    } finally {
      result.removeAttribute("aria-busy");
    }
  }

  function stat(value, label) {
    return h("div", {}, h("dd", {}, String(value)), h("dt", {}, label));
  }

  requirementSearch.addEventListener("input", () => {
    const query = requirementSearch.value.trim().toLocaleLowerCase();
    const current = select.value;
    const matches = requirements.filter((item) => `${item.id} ${item.text}`.toLocaleLowerCase().includes(query));
    clear(select).append(
      h("option", { value: "" }, query ? `${matches.length} matching requirement${matches.length === 1 ? "" : "s"}` : "Choose a requirement…"),
      matches.map((item) => h("option", { value: item.id }, `${item.id} — ${item.text}`)),
    );
    if (matches.some((item) => item.id === current)) {
      select.value = current;
    } else if (current) {
      select.value = "";
      load("");
    }
  });
  select.addEventListener("change", () => load(select.value));
  impactForm.addEventListener("submit", (event) => {
    event.preventDefault();
    findImpact().catch((error) => toast(error.message, "error"));
  });

  const first = params.rest[0] ?? requirements[0]?.id ?? "";
  select.value = first;
  clear(main).append(
    h("header", { class: "page-heading trace-page-heading" },
      h("div", {}, h("p", { class: "eyebrow" }, "Traceability"), h("h1", {}, "Follow every requirement"), h("p", { class: "muted" }, "See how a requirement flows through design and reaches its test cases.")),
      h("span", { class: "trace-count" }, `${requirements.length} requirements`),
    ),
    h("section", { class: "panel trace-explorer", "aria-labelledby": "trace-explorer-title" },
      h("div", { class: "trace-section-heading" }, h("div", {}, h("h2", { id: "trace-explorer-title" }, "Requirement coverage"), h("p", { class: "muted" }, "Choose a requirement to see every recorded path to testing."))),
      h("div", { class: "trace-picker" },
        h("div", { class: "trace-field" }, h("label", { for: "req-search" }, "Filter requirements"), requirementSearch),
        h("div", { class: "trace-field trace-picker-select" }, h("label", { for: "req" }, "Requirement"), select),
      ),
      result,
      traceStart,
      pathList,
    ),
    h("section", { class: "panel trace-impact", "aria-labelledby": "impact-title" },
      h("div", { class: "trace-section-heading" }, h("div", {}, h("p", { class: "eyebrow" }, "Change analysis"), h("h2", { id: "impact-title" }, "Explore impact"), h("p", { id: "trace-impact-help", class: "muted" }, "Find the upstream and downstream items connected to any requirement, document item, or test case."))),
      impactForm,
      impact,
    ),
  );
  await load(first);
}
