// Spec 30: the intake upload warning and the data-protection row of Project settings.
import { h } from "../dom.js";
import { N_, t } from "../i18n.js";

const KIND_LABEL = {
  email: N_("e-mail address"),
  phone: N_("phone number"),
  my_number: N_("My Number"),
  card: N_("card number"),
  ipv4: N_("IP address"),
};

// "3 personal values found (e-mail address ×2, phone number)", or null when nothing was found.
export function findingsNote(findings) {
  if (!Array.isArray(findings) || findings.length === 0) return null;
  const counts = new Map();
  for (const f of findings) counts.set(f.kind, (counts.get(f.kind) ?? 0) + 1);
  const kinds = [...counts].map(([kind, n]) => `${t(KIND_LABEL[kind] ?? kind)}${n > 1 ? ` ×${n}` : ""}`).join(", ");
  return t("Personal data found in the intake: {count} ({kinds}). It is masked before each model call while data protection is on.", { count: findings.length, kinds });
}

// Terms typed one per line or comma-separated, trimmed, without repeats.
export function parseTerms(text) {
  const seen = new Set();
  const out = [];
  for (const raw of String(text).split(/[\n,、]/)) {
    const term = raw.trim();
    if (term.length >= 2 && !seen.has(term.toLowerCase())) {
      seen.add(term.toLowerCase());
      out.push(term);
    }
  }
  return out;
}

export function guardSettings(pid, project, { api, toast, refresh, me }) {
  const on = project.pii_masking !== false;
  const terms = h("textarea", {
    rows: "2",
    "aria-label": t("Words to mask (customer and product names), one per line"),
    placeholder: t("Words to mask (customer and product names), one per line"),
  });
  terms.value = (project.masking_terms ?? []).join("\n");
  const save = async (pii) => {
    try {
      await api.post(`/projects/${pid}/settings/guard`, { pii_masking: pii, masking_terms: parseTerms(terms.value) });
      toast(t("Data protection updated"));
      await refresh();
    } catch (error) {
      toast(error.message, "error");
    }
  };
  // Only a global administrator may switch masking off (spec 30 section 2.3).
  const toggle = on && me?.role !== "admin"
    ? null
    : h("button", { type: "button", onClick: () => save(!on) }, on ? t("Switch masking off") : t("Switch masking on"));
  return h("div", { class: "setting-row" },
    h("div", {},
      h("h3", {}, t("Data protection")),
      h("p", { class: "muted" }, on
        ? t("Personal data and the words below are masked before each model call; secrets are always blocked.")
        : t("Masking is off: personal data is sent to the model as written. Secrets are still blocked.")),
    ),
    h("form", { onSubmit: (event) => { event.preventDefault(); save(on); } },
      terms,
      h("button", { type: "submit" }, t("Save words")),
      toggle,
    ),
  );
}
