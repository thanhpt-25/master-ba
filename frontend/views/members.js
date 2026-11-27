// Who may open this project (spec 23): the owner, members and their project roles.
import { clear, confirmDialog, empty, field, h, icon, table } from "../dom.js";
import { t } from "../i18n.js";

const MEMBER_ROLES = [["viewer", "Viewer"], ["approver", "Approver"]];

function roleSelect(value, label) {
  return h("select", { "aria-label": label }, MEMBER_ROLES.map(([role, name]) => h("option", { value: role, selected: role === value ? "" : null }, t(name))));
}

export async function render({ main, params, api, toast }) {
  const pid = params.pid;
  const refresh = async () => draw(await api.get(`/projects/${pid}/access`));

  const act = async (work, done) => {
    try {
      draw(await work());
      toast(done);
    } catch (error) {
      toast(error.message, "error");
    }
  };

  function draw(access) {
    const manage = access.my_role === "admin";
    const rows = [
      [h("strong", {}, access.owner ?? "–"), t("Project owner"), t("Can change settings, members and run every stage."), ""],
      ...access.members.map((m) => {
        const role = manage ? roleSelect(m.role, t("Role of {name}", { name: m.name })) : t(m.role === "viewer" ? "Viewer" : "Approver");
        if (manage) role.addEventListener("change", () => act(() => api.post(`/projects/${pid}/members`, { name: m.name, role: role.value }), t("Updated {name}", { name: m.name })));
        const remove = manage
          ? h("button", { type: "button", class: "link danger", onClick: async () => {
              if (await confirmDialog({ title: t("Remove {name} from {pid}?", { name: m.name, pid }), message: t("They can no longer open this project."), confirmLabel: t("Remove"), danger: true })) {
                await act(() => api.del(`/projects/${pid}/members/${encodeURIComponent(m.name)}`), t("Removed {name}", { name: m.name }));
              }
            } }, t("Remove"))
          : "";
        return [m.name, role, m.role === "viewer" ? t("Can read documents, questions and decisions.") : t("Can also run stages, answer questions and approve."), remove];
      }),
    ];
    const name = h("input", { type: "text", maxlength: "40", autocomplete: "off", spellcheck: "false", required: true, placeholder: t("User name") });
    const role = roleSelect("viewer", t("Role"));
    const heir = h("input", { type: "text", maxlength: "40", autocomplete: "off", spellcheck: "false", required: true, placeholder: t("User name") });
    clear(main).append(
      h("div", { class: "page-heading" },
        h("div", {}, h("h1", {}, t("Members")),
          h("p", { class: "muted" }, t("Only the people listed here can see this project.")),
        ),
      ),
      h("section", { class: "panel", "aria-labelledby": "members-list" },
        h("h2", { id: "members-list" }, t("People with access")),
        table([t("User"), t("Role"), t("Can do"), ""], rows, t("People with access"), { dense: true }),
        access.members.length ? null : empty(t("Not shared with anyone yet.")),
      ),
      manage
        ? h("form", { class: "panel form-grid", onSubmit: (event) => {
            event.preventDefault();
            act(() => api.post(`/projects/${pid}/members`, { name: name.value.trim(), role: role.value }), t("Shared with {name}", { name: name.value.trim() }));
          } },
          h("h2", {}, t("Share this project")),
          h("div", { class: "field-pair" }, field(t("User name"), name, t("The sign-in name of the person.")), field(t("Role"), role)),
          h("button", { class: "primary", type: "submit" }, icon("plus", 16), t("Share")),
        )
        : h("p", { class: "hint" }, t("The owner or an administrator manages who has access.")),
      manage
        ? h("form", { class: "panel form-grid", onSubmit: async (event) => {
            event.preventDefault();
            const to = heir.value.trim();
            if (await confirmDialog({ title: t("Hand {pid} to {name}?", { pid, name: to }), message: t("The new owner manages the project; you stay as an approver member."), confirmLabel: t("Hand over") })) {
              await act(() => api.post(`/projects/${pid}/owner`, { name: to }), t("{name} now owns {pid}", { name: to, pid }));
            }
          } },
          h("h2", {}, t("Hand over ownership")),
          field(t("New owner"), heir),
          h("button", { type: "submit" }, t("Hand over")),
        )
        : null,
    );
  }

  await refresh();
}
