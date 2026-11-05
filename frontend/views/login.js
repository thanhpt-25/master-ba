import { clear, field, h } from "../dom.js";

export async function render({ main, api, go }) {
  const message = h("p", { class: "error", role: "alert", hidden: true });
  const name = h("input", { type: "text", name: "name", autocomplete: "username", required: true });
  const password = h("input", { type: "password", name: "password", autocomplete: "current-password", required: true });
  const submit = h("button", { type: "submit", class: "primary" }, "Sign in");
  const form = h(
    "form",
    {
      class: "login-card",
      onSubmit: async (event) => {
        event.preventDefault();
        message.hidden = true;
        submit.disabled = true;
        submit.textContent = "Signing in\u2026";
        try {
          await api.post("/login", { name: name.value, password: password.value });
          location.hash = "#/projects";
          location.reload();
        } catch (error) {
          message.textContent = "Sign-in failed. Check the name and password.";
          message.hidden = false;
          submit.disabled = false;
          submit.textContent = "Sign in";
        }
      },
    },
    h("span", { class: "seal big", "aria-hidden": "true" }, "要"),
    h("h1", {}, "MasterBA"),
    h("p", { class: "lede" }, "Requirements to design, test and change control."),
    field("Name", name),
    field("Password", password),
    message,
    submit,
  );
  clear(main).append(h("div", { class: "login-wrap" }, form));
  name.focus();
}
