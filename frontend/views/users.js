// User administration (spec 23): accounts, roles, usage and token limits. Admins only.
import { clear, confirmDialog, field, h, icon, modal, table, tokens, usageMeter } from "../dom.js";
import { t } from "../i18n.js";

const ROLES = [["viewer", "Viewer"], ["approver", "Approver"], ["admin", "Admin"]];

function roleSelect(value) {
  return h("select", { name: "role" }, ROLES.map(([role, name]) => h("option", { value: role, selected: role === value }, t(name))));
}

// A token count input where blank means no limit.
function limitInput(value, label) {
  return h("input", { type: "number", min: "0", step: "1000", value: value ?? "", placeholder: t("No limit"), "aria-label": label });
}

const limitValue = (input) => (input.value.trim() === "" ? null : Number(input.value));

function limitText(limits) {
  const part = (n) => (n === null ? t("no limit") : tokens(n));
  return t("5 h: {session} · week: {weekly}", { session: part(limits.session), weekly: part(limits.weekly) });
}

export async function render({ main, api, me, toast }) {
  const refresh = async () => draw(await api.get("/admin/users"));
  const act = async (work, done) => {
    try {
      await work();
      toast(done);
      await refresh();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  function editDialog(user) {
    const role = roleSelect(user.role);
    const password = h("input", { type: "password", autocomplete: "new-password", minlength: "8", placeholder: t("Leave blank to keep") });
    const custom = h("input", { type: "checkbox", checked: user.custom_limits });
    const session = limitInput(user.limits.session, t("Tokens per 5 hours"));
    const weekly = limitInput(user.limits.weekly, t("Tokens per week"));
    const sync = () => { session.disabled = !custom.checked; weekly.disabled = !custom.checked; };
    custom.addEventListener("change", sync);
    sync();
    modal((close) => h("form", {
      class: "dialog create-dialog",
      onSubmit: async (event) => {
        event.preventDefault();
        const body = { role: role.value, limits: custom.checked ? { session: limitValue(session), weekly: limitValue(weekly) } : null };
        if (password.value) body.password = password.value;
        try {
          await api.patch(`/admin/users/${encodeURIComponent(user.name)}`, body);
          close();
          toast(t("Updated {name}", { name: user.name }));
          await refresh();
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    h("div", { class: "dialog-top" },
      h("span", { class: "dialog-icon", "aria-hidden": "true" }, icon("users", 18)),
      h("h2", { id: "user-title" }, t("Edit {name}", { name: user.name })),
      h("button", { type: "button", class: "icon-button", "aria-label": t("Close"), onClick: close }, icon("close", 18)),
    ),
    field(t("Role"), role, t("Viewers read, approvers also create projects and run stages, admins manage everything.")),
    field(t("New password"), password, t("At least 8 characters.")),
    h("label", { class: "check" }, custom, " ", t("Give this user their own limits")),
    h("div", { class: "field-pair" }, field(t("Tokens per 5 hours"), session), field(t("Tokens per week"), weekly)),
    h("p", { class: "hint" }, t("Blank means no limit; 0 stops this user's model use.")),
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", onClick: close }, t("Cancel")),
      h("button", { type: "submit", class: "primary" }, t("Save")),
    ),
    ), { labelledBy: "user-title" });
  }

  function draw(data) {
    const rows = data.users.map((user) => [
      h("span", { class: "user-cell" }, h("span", { class: "avatar", "aria-hidden": "true" }, user.name.slice(0, 1).toUpperCase()), h("strong", {}, user.name), user.name === me.name ? h("span", { class: "muted" }, ` (${t("you")})`) : null),
      t(ROLES.find(([r]) => r === user.role)?.[1] ?? user.role),
      h("div", { class: "usage-cells" }, user.usage.map((w) => usageMeter(w, { compact: true }))),
      h("span", {}, user.custom_limits ? h("span", { class: "badge run" }, t("Custom")) : null, " ", limitText(user.limits), user.custom_limits ? "" : h("span", { class: "muted" }, ` (${t("default")})`)),
      h("span", { class: "row" },
        h("button", { type: "button", class: "link", onClick: () => editDialog(user) }, t("Edit")),
        h("button", { type: "button", class: "link", onClick: () => act(() => api.post(`/admin/users/${encodeURIComponent(user.name)}/reset-usage`), t("Usage of {name} starts again now", { name: user.name })) }, t("Reset usage")),
        user.name === me.name ? null : h("button", { type: "button", class: "link danger", onClick: async () => {
          if (await confirmDialog({ title: t("Remove {name}?", { name: user.name }), message: t("Their projects move to you; their usage history is kept."), confirmLabel: t("Remove"), danger: true })) {
            await act(() => api.del(`/admin/users/${encodeURIComponent(user.name)}`), t("Removed {name}", { name: user.name }));
          }
        } }, t("Remove")),
      ),
    ]);

    const name = h("input", { type: "text", maxlength: "40", autocomplete: "off", spellcheck: "false", required: true, pattern: "[A-Za-z0-9._\\-]{1,40}" });
    const role = roleSelect("approver");
    const password = h("input", { type: "password", autocomplete: "new-password", minlength: "8", required: true });
    const session = limitInput(data.default_limits.session, t("Tokens per 5 hours"));
    const weekly = limitInput(data.default_limits.weekly, t("Tokens per week"));

    clear(main).append(
      h("div", { class: "page-heading" },
        h("div", {}, h("p", { class: "eyebrow" }, t("Administration")), h("h1", {}, t("Users")),
          h("p", { class: "muted" }, t("Accounts, their roles and how many model tokens each may use.")),
        ),
      ),
      h("section", { class: "panel", "aria-labelledby": "users-list" },
        h("h2", { id: "users-list" }, t("All users")),
        table([t("User"), t("Role"), t("Usage"), t("Limits"), ""], rows, t("All users"), { dense: true, stickyFirst: true }),
      ),
      h("div", { class: "overview-columns" },
        h("form", { class: "panel form-grid", onSubmit: (event) => {
          event.preventDefault();
          act(() => api.post("/admin/users", { name: name.value.trim(), role: role.value, password: password.value }), t("Added {name}", { name: name.value.trim() }));
        } },
        h("h2", {}, t("Add a user")),
        field(t("User name"), name, t("Letters, digits, dots, dashes or underscores.")),
        h("div", { class: "field-pair" }, field(t("Role"), role), field(t("Password"), password, t("At least 8 characters."))),
        h("button", { class: "primary", type: "submit" }, icon("plus", 16), t("Add user")),
        ),
        h("form", { class: "panel form-grid", onSubmit: (event) => {
          event.preventDefault();
          act(() => api.put("/admin/limits", { session: limitValue(session), weekly: limitValue(weekly) }), t("Default limits saved"));
        } },
        h("h2", {}, t("Default limits")),
        h("p", { class: "muted" }, t("Apply to every user without their own limits. Blank means no limit.")),
        h("div", { class: "field-pair" }, field(t("Tokens per 5 hours"), session), field(t("Tokens per week"), weekly)),
        h("button", { class: "primary", type: "submit" }, t("Save default limits")),
        ),
      ),
    );
  }

  await refresh();
}
