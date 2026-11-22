// UI language (spec 19 section 15). English text is the key; ./i18n-ja.js maps it to Japanese.
// `N_` only marks a static label for the catalog test; it is translated where it is shown.

import { JA } from "./i18n-ja.js";

export const LANGUAGES = ["ja", "en"];
const LOCALES = { ja: "ja-JP", en: "en-US" };
let current = "ja";

export const N_ = (text) => text;

export function t(text, vars = null) {
  const template = current === "ja" ? (JA[text] ?? text) : text;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, key) => (key in vars ? String(vars[key]) : match));
}

export function lang() {
  return current;
}

export function locale() {
  return LOCALES[current];
}

function storageKey(user) {
  return `masterba-lang:${user ?? ""}`;
}

export function setLang(value, user = null) {
  current = LANGUAGES.includes(value) ? value : "ja";
  if (typeof document !== "undefined" && document.documentElement) document.documentElement.lang = current;
  try {
    localStorage.setItem(storageKey(user), current);
    localStorage.setItem("masterba-lang", current); // the sign-in page has no user yet
  } catch { /* storage may be disabled */ }
  return current;
}

// The saved choice of this user in this browser; Japanese when there is none.
export function loadLang(user = null) {
  let saved = null;
  try {
    saved = (user !== null && localStorage.getItem(storageKey(user))) || localStorage.getItem("masterba-lang");
  } catch { /* storage may be disabled */ }
  current = LANGUAGES.includes(saved) ? saved : "ja";
  if (typeof document !== "undefined" && document.documentElement) document.documentElement.lang = current;
  return current;
}
