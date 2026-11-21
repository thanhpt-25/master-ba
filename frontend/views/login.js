import { clear, field, h } from "../dom.js";
import { lang, setLang, t } from "../i18n.js";

export async function render({ main, api, go }) {
  const message = h("p", { class: "error", role: "alert", hidden: true });
  const name = h("input", { type: "text", name: "name", autocomplete: "username", required: true });
  const password = h("input", { type: "password", name: "password", autocomplete: "current-password", required: true });
  const submit = h("button", { type: "submit", class: "primary" }, t("Sign in"));
  const form = h(
    "form",
    {
      class: "login-card",
      onSubmit: async (event) => {
        event.preventDefault();
        message.hidden = true;
        submit.disabled = true;
        submit.textContent = t("Signing in…");
        try {
          await api.post("/login", { name: name.value, password: password.value });
          location.hash = "#/projects";
          location.reload();
        } catch (error) {
          message.textContent = t("Sign-in failed. Check the name and password.");
          message.hidden = false;
          submit.disabled = false;
          submit.textContent = t("Sign in");
        }
      },
    },
    h("span", { class: "seal big", "aria-hidden": "true" }, "要"),
    h("h1", {}, "MasterBA"),
    h("p", { class: "lede" }, t("Requirements to design, test and change control.")),
    field(t("Name"), name),
    field(t("Password"), password),
    message,
    submit,
    h("button", {
      type: "button",
      class: "link lang-toggle",
      lang: lang() === "ja" ? "en" : "ja",
      onClick: () => { setLang(lang() === "ja" ? "en" : "ja"); render({ main, api, go }); },
    }, lang() === "ja" ? "English" : "日本語"),
  );
  clear(main).append(h("div", { class: "login-wrap" }, form));
  name.focus();
}
