// User administration (spec 23, 24): accounts, roles, status, usage and token limits. Admins only.
import { badge, clear, confirmDialog, empty, field, fmtTime, h, icon, modal, table, tokens, usageMeter } from "../dom.js";
import { N_, t } from "../i18n.js";

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

// The users a search and a status filter keep (spec 24 section 7).
export function matchUsers(users, query, status) {
  const q = String(query ?? "").trim().toLowerCase();
  return users.filter((u) => {
    if (status === "active" && u.disabled) return false;
    if (status === "disabled" && !u.disabled) return false;
    if (status === "limited" && !u.usage.some((w) => w.percent !== null && w.percent >= 80)) return false;
    if (["viewer", "approver", "admin"].includes(status) && u.role !== status) return false;
    return !q || u.name.toLowerCase().includes(q);
  });
}

const FILTERS = [["", N_("All users")], ["active", N_("Active")], ["disabled", N_("Disabled")], ["limited", N_("Near a limit")], ["admin", N_("Admin")], ["approver", N_("Approver")], ["viewer", N_("Viewer")]];
let query = "";
let status = "";

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

  const confirmThen = async (options, work, done) => {
    if (await confirmDialog(options)) await act(work, done);
  };
  const path = (user, action) => `/admin/users/${encodeURIComponent(user.name)}/${action}`;

  function actions(user) {
    const self = user.name === me.name;
    return h("span", { class: "row" },
      h("button", { type: "button", class: "link", onClick: () => editDialog(user) }, t("Edit")),
      h("button", { type: "button", class: "link", onClick: () => act(() => api.post(path(user, "reset-usage")), t("Usage of {name} starts again now", { name: user.name })) }, t("Reset usage")),
      self ? null : h("button", { type: "button", class: "link", onClick: () => confirmThen(
        { title: t("Sign {name} out everywhere?", { name: user.name }), message: t("Every open session of this user ends now; they can sign in again."), confirmLabel: t("Sign out everywhere") },
        () => api.post(path(user, "signout")), t("{name} was signed out everywhere", { name: user.name })) }, t("Sign out everywhere")),
      self ? null : user.disabled
        ? h("button", { type: "button", class: "link", onClick: () => act(() => api.post(path(user, "enable")), t("{name} can sign in again", { name: user.name })) }, t("Enable"))
        : h("button", { type: "button", class: "link danger", onClick: () => confirmThen(
          { title: t("Disable {name}?", { name: user.name }), message: t("They are signed out at once and cannot sign in. Projects, memberships, limits and history stay."), confirmLabel: t("Disable"), danger: true },
          () => api.post(path(user, "disable")), t("{name} is disabled", { name: user.name })) }, t("Disable")),
      self ? null : h("button", { type: "button", class: "link danger", onClick: () => confirmThen(
        { title: t("Remove {name}?", { name: user.name }), message: t("Their projects move to you; their usage history is kept."), confirmLabel: t("Remove"), danger: true },
        () => api.del(`/admin/users/${encodeURIComponent(user.name)}`), t("Removed {name}", { name: user.name })) }, t("Remove")),
    );
  }

  function draw(data) {
    const listHost = h("div", {});
    const paint = () => {
      const shown = matchUsers(data.users, query, status);
      count.textContent = t("{shown} of {total} users", { shown: shown.length, total: data.users.length });
      clear(listHost).append(shown.length
        ? table([t("User"), t("Status"), t("Role"), t("Usage"), t("Limits"), t("Last sign-in"), ""], shown.map((user) => [
            h("span", { class: "user-cell" }, h("span", { class: "avatar", "aria-hidden": "true" }, user.name.slice(0, 1).toUpperCase()), h("strong", {}, user.name), user.name === me.name ? h("span", { class: "muted" }, ` (${t("you")})`) : null),
            user.disabled ? badge("disabled") : badge("active"),
            t(ROLES.find(([r]) => r === user.role)?.[1] ?? user.role),
            h("div", { class: "usage-cells" }, user.usage.map((w) => usageMeter(w, { compact: true }))),
            h("span", {}, user.custom_limits ? h("span", { class: "badge run" }, t("Custom")) : null, " ", limitText(user.limits), user.custom_limits ? "" : h("span", { class: "muted" }, ` (${t("default")})`)),
            h("span", { class: "when" }, user.last_login ? fmtTime(user.last_login) : h("span", { class: "muted" }, t("Never")), user.created ? h("span", { class: "muted" }, t("Added {time}", { time: fmtTime(user.created) })) : null),
            actions(user),
          ]), t("All users"), { dense: true, stickyFirst: true })
        : empty(t("No user matches this filter.")));
    };
    const search = h("input", { type: "search", value: query, placeholder: t("Search by name"), "aria-label": t("Search users") });
    const filter = h("select", { "aria-label": t("Show") }, FILTERS.map(([value, label]) => h("option", { value, selected: value === status }, t(label))));
    const count = h("span", { class: "muted" });
    search.addEventListener("input", () => { query = search.value; paint(); });
    filter.addEventListener("change", () => { status = filter.value; paint(); });
    paint();

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
        h("div", { class: "panel-heading" },
          h("h2", { id: "users-list" }, t("All users")),
          h("div", { class: "table-tools" }, h("label", { class: "project-search" }, icon("search", 16), search), filter, count),
        ),
        listHost,
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
