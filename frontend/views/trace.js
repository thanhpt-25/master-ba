import { clear, empty, h, spinner, table } from "../dom.js";

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
    clear(result).append(spinner("Loading trace…"));
    const data = await api.get(`/projects/${pid}/rtm/${id}`);
    clear(result);
    if (!data.paths.length) {
      result.append(empty(`${id} has no path to a test case yet.`));
      return;
    }
    result.append(h("h2", {}, `${id} → test cases`), ...data.paths.map((p) => chain(p, data.nodes)));
  }
  select.addEventListener("change", () => load(select.value).catch((e) => { clear(result); toast(e.message, "error"); }));

  const node = h("input", { type: "text", id: "node", name: "node", autocomplete: "off", spellcheck: "false", placeholder: "REQ-0001, DOC-SRS-0001#item.2 or TC-IT-0001…" });
  const direction = h("select", { id: "dir", "aria-label": "Direction" }, ["downstream", "upstream", "both"].map((d) => h("option", { value: d }, d)));
  const impact = h("div", {});
  const findBtn = h("button", {}, "Find");
  findBtn.addEventListener("click", () => find());
  const find = async () => {
    if (!node.value.trim()) return toast("Enter an item id first.", "error");
    findBtn.disabled = true;
    clear(impact).append(spinner("Finding impact…"));
    try {
      const rows = await api.get(`/projects/${pid}/impact?node=${encodeURIComponent(node.value)}&direction=${direction.value}`);
      clear(impact).append(
        rows.length
          ? table(["Node", "Depth", "Link", "Direction", "Text"], rows.map((r) => [h("code", {}, r.node_id), r.depth, r.link_type, r.direction, r.text]), "Impact", { dense: true, stickyFirst: true })
          : empty("Nothing is connected in that direction."),
      );
    } catch (error) {
      clear(impact);
      toast(error.message, "error");
    } finally {
      findBtn.disabled = false;
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
      h("div", { class: "toolbar" }, h("label", { for: "node" }, "Item"), node, h("label", { for: "dir" }, "Direction"), direction, findBtn),
      impact,
    ),
  );
  const first = params.rest[0] ?? requirements[0]?.id ?? "";
  select.value = first;
  await load(first);
}
