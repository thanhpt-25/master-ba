import { clear, empty, h, table } from "../dom.js";

function chain(path, nodes) {
  const parts = [];
  path.forEach((id, i) => {
    const info = nodes[id] ?? { text: "", kind: "item" };
    if (i) parts.push(h("span", { class: "arrow", "aria-hidden": "true" }, "→"));
    parts.push(
      h(
        "li",
        { class: `node ${info.kind}` },
        h("code", {}, id.startsWith("REQ") ? id : id.split("#")[1] ? `${id.split("#")[0].replace("DOC-", "")} #${id.split("#")[1].replace("item.", "")}` : id),
        h("span", {}, info.text),
      ),
    );
  });
  return h("ol", { class: "chain", "aria-label": `Trace path ${path.join(" to ")}` }, parts);
}

export async function render({ main, api, params, toast }) {
  const pid = params.pid;
  const requirements = await api.get(`/projects/${pid}/requirements`);
  const result = h("div", {});
  const select = h(
    "select",
    { id: "req", "aria-label": "Requirement" },
    h("option", { value: "" }, "Choose a requirement…"),
    requirements.map((r) => h("option", { value: r.id }, `${r.id} — ${r.text.slice(0, 70)}`)),
  );

  async function load(id) {
    if (!id) return clear(result).append(empty("Pick a requirement to see how it is carried through the documents and tests."));
    const data = await api.get(`/projects/${pid}/rtm/${id}`);
    clear(result);
    if (!data.paths.length) {
      result.append(empty(`${id} has no path to a test case yet.`));
      return;
    }
    result.append(h("h2", {}, `${id} → test cases`), ...data.paths.map((p) => chain(p, data.nodes)));
  }
  select.addEventListener("change", () => load(select.value).catch((e) => toast(e.message, "error")));

  const node = h("input", { type: "text", id: "node", placeholder: "REQ-0001 or DOC-SRS-0001#item.2 or TC-IT-0001" });
  const direction = h("select", { id: "dir", "aria-label": "Direction" }, ["downstream", "upstream", "both"].map((d) => h("option", { value: d }, d)));
  const impact = h("div", {});
  const find = async () => {
    try {
      const rows = await api.get(`/projects/${pid}/impact?node=${encodeURIComponent(node.value)}&direction=${direction.value}`);
      clear(impact).append(
        rows.length
          ? table(["Node", "Depth", "Link", "Direction", "Text"], rows.map((r) => [h("code", {}, r.node_id), r.depth, r.link_type, r.direction, r.text]), "Impact")
          : empty("Nothing is connected in that direction."),
      );
    } catch (error) {
      toast(error.message, "error");
    }
  };

  clear(main).append(
    h("h1", {}, "Traceability"),
    h("div", { class: "toolbar" }, h("label", { for: "req" }, "Requirement"), select),
    result,
    h(
      "section",
      { class: "panel" },
      h("h2", {}, "Impact of an item"),
      h("p", { class: "muted" }, "What a change to any requirement, item or test case would touch."),
      h("div", { class: "toolbar" }, h("label", { for: "node" }, "Item"), node, h("label", { for: "dir" }, "Direction"), direction, h("button", { onClick: find }, "Find")),
      impact,
    ),
  );
  const first = params.rest[0] ?? requirements[0]?.id ?? "";
  select.value = first;
  await load(first);
}
