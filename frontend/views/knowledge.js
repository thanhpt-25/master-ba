// Knowledge tab: sources of the project knowledge base and a search box (spec 12, Requirement 14).

import { badge, clear, confirmDialog, empty, field, fmtTime, h, spinner, table } from "../dom.js";

const ACCEPT = ".md,.txt,.xlsx,.docx,.pdf";

export function passageList(passages) {
  if (!passages.length) return empty("No passages found.");
  return h(
    "ol",
    { class: "passages" },
    passages.map((p) =>
      h(
        "li",
        {},
        h("code", { class: "chip" }, p.chunk_ref),
        p.heading_path.length ? h("span", { class: "muted" }, " ", p.heading_path.join(" › ")) : null,
        p.sheet ? h("span", { class: "muted" }, " ", p.sheet) : null,
        h("p", { class: "prose" }, p.text),
      ),
    ),
  );
}

export async function render({ main, api, params, me, toast }) {
  const pid = params.pid;
  const base = `/projects/${pid}/knowledge`;
  const canAct = ["approver", "admin"].includes(me.role);
  const list = h("div", {});
  const results = h("div", { "aria-live": "polite" });

  // On error the API's detail is shown and the table is left as it was.
  async function act(work, done) {
    try {
      const reply = await work();
      toast(done(reply));
      await drawList();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function picker(id, label) {
    return h("input", { type: "file", accept: ACCEPT, id, "aria-label": label });
  }

  function rowActions(s) {
    if (!canAct) return "";
    const file = picker(`replace-${s.id}`, `Replacement file for ${s.id}`);
    const replace = () => {
      if (!file.files[0]) return toast("Choose a replacement file first.", "error");
      return act(() => api.upload(`${base}/${s.id}`, file.files[0], "PUT"), (r) => `Replaced ${s.id}${r.dr_id ? `; proposed ${r.dr_id}` : ""}`);
    };
    const remove = async () => {
      const ok = await confirmDialog({ title: `Remove ${s.id}?`, message: "Its passages stop being used by the stages.", confirmLabel: "Remove", danger: true });
      if (ok) act(() => api.del(`${base}/${s.id}`), (r) => `Removed ${s.id}${r.dr_id ? `; proposed ${r.dr_id}` : ""}`);
    };
    return h("div", { class: "toolbar" }, file, h("button", { type: "button", onClick: replace }, "Replace"), h("button", { type: "button", onClick: remove }, "Remove"));
  }

  async function drawList() {
    const sources = await api.get(base);
    const rows = sources.map((s) => [
      h("code", {}, s.id),
      s.file_name,
      s.added_by,
      fmtTime(s.added_at),
      h("span", {}, badge(s.status), s.reason ? h("span", { class: "muted" }, ` ${s.reason}`) : null),
      rowActions(s),
    ]);
    clear(list).append(
      sources.length
        ? table(["Source", "File", "Added by", "Added at", "Status", canAct ? "Actions" : ""], rows, "Knowledge sources")
        : empty("The knowledge base is empty."),
    );
  }

  const upload = picker("kb-upload", "Knowledge file to add");
  const query = h("input", { type: "search", id: "kb-query", maxlength: "1000", autocomplete: "off" });
  const searchBtn = h("button", { type: "submit" }, "Search");
  const search = async (event) => {
    event.preventDefault();
    if (!query.value.trim()) return toast("Type something to search for.", "error");
    searchBtn.disabled = true;
    clear(results).append(h("div", { class: "panel" }, spinner("Searching…")));
    try {
      const found = await api.get(`${base}/search?q=${encodeURIComponent(query.value)}&k=5`);
      clear(results).append(found.mode === "keyword" ? h("p", { class: "muted" }, "Only keyword search was used.") : null, passageList(found.passages));
    } catch (error) {
      clear(results);
      toast(error.message, "error");
    } finally {
      searchBtn.disabled = false;
    }
  };

  clear(main).append(
    h("h1", {}, "Knowledge base"),
    h("p", { class: "muted" }, "Files the stages may quote from. Writers cite passages by ref; QA checks drafts against them."),
    canAct
      ? h(
          "section",
          { class: "panel" },
          field("Add a file (.md, .txt, .xlsx, .docx, .pdf; up to 20 MB)", upload),
          h("button", {
            type: "button",
            class: "primary",
            onClick: () => {
              if (!upload.files[0]) return toast("Choose a file first.", "error");
              return act(() => api.upload(base, upload.files[0]), (r) => `Added ${r.id}: ${r.status}`);
            },
          }, "Add to knowledge base"),
        )
      : null,
    list,
    h("form", { class: "panel", role: "search", onSubmit: search }, field("Search the knowledge base", query), searchBtn),
    results,
  );
  await drawList();
}
