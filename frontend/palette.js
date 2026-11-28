// The command palette (spec 26 section 2): one field over projects, pages and actions.
// filterCommands is pure so the tests can check matching without a DOM.

import { clear, h, icon, modal } from "./dom.js";
import { t } from "./i18n.js";

// The short label of a project on the rail: its trailing number ("PRJ-001" -> "001").
export function railLabel(pid) {
  const digits = String(pid).match(/(\d+)$/);
  return digits ? digits[1].slice(-3) : String(pid).slice(0, 3).toUpperCase();
}

// Lower case and full-width ASCII folded to half-width, so "ＰＲＪ" finds "PRJ-001".
export function fold(text) {
  return String(text)
    .replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .toLowerCase();
}

// commands: [{ id, label, group, keywords?, hint?, icon?, run }]. Every word of the query must
// appear in the label, hint or keywords; a label that starts with the query ranks first.
export function filterCommands(commands, query) {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return commands.slice();
  const scored = [];
  commands.forEach((command, index) => {
    const label = fold(command.label);
    const haystack = `${label} ${fold(command.hint ?? "")} ${fold((command.keywords ?? []).join(" "))}`;
    if (!words.every((word) => haystack.includes(word))) return;
    const score = label.startsWith(words[0]) ? 0 : label.includes(words[0]) ? 1 : 2;
    scored.push({ command, score, index });
  });
  scored.sort((a, b) => a.score - b.score || a.index - b.index);
  return scored.map((entry) => entry.command);
}

// Opens the palette over `commands`. Arrow keys move, Enter runs, Escape closes (modal()).
export function openPalette(commands) {
  let results = commands;
  let active = 0;
  const list = h("ul", { class: "palette-list", role: "listbox", id: "palette-list", "aria-label": t("Results") });
  const input = h("input", {
    type: "text",
    class: "palette-input",
    id: "palette-input",
    autocomplete: "off",
    spellcheck: "false",
    role: "combobox",
    "aria-expanded": "true",
    "aria-controls": "palette-list",
    "aria-autocomplete": "list",
    placeholder: t("Search projects, pages and actions"),
    "aria-label": t("Search projects, pages and actions"),
  });
  let close = null;

  const run = (command) => {
    if (!command) return;
    close();
    command.run();
  };

  const draw = () => {
    clear(list);
    if (!results.length) {
      list.append(h("li", { class: "palette-empty", role: "presentation" }, t("Nothing matches.")));
      input.removeAttribute("aria-activedescendant");
      return;
    }
    let group = null;
    results.forEach((command, i) => {
      if (command.group !== group) {
        group = command.group;
        list.append(h("li", { class: "palette-group", role: "presentation" }, group));
      }
      const id = `palette-opt-${i}`;
      list.append(h("li", {
        id,
        class: "palette-item",
        role: "option",
        "aria-selected": i === active ? "true" : "false",
        onClick: () => run(command),
        onMousemove: () => { if (active !== i) { active = i; mark(); } },
      },
      icon(command.icon ?? "next", 16),
      h("span", { class: "palette-label" }, command.label),
      command.hint ? h("span", { class: "palette-hint" }, command.hint) : null));
    });
    mark();
  };

  const mark = () => {
    list.querySelectorAll(".palette-item").forEach((item, i) => item.setAttribute("aria-selected", i === active ? "true" : "false"));
    const current = list.querySelector(`#palette-opt-${active}`);
    if (current) {
      input.setAttribute("aria-activedescendant", current.id);
      current.scrollIntoView?.({ block: "nearest" });
    }
  };

  input.addEventListener("input", () => {
    results = filterCommands(commands, input.value);
    active = 0;
    draw();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!results.length) return;
      active = (active + (event.key === "ArrowDown" ? 1 : results.length - 1)) % results.length;
      mark();
    } else if (event.key === "Enter") {
      event.preventDefault();
      run(results[active]);
    }
  });

  close = modal(
    () => h("div", { class: "dialog palette" },
      h("h2", { id: "palette-title", class: "sr-only" }, t("Command palette")),
      h("div", { class: "palette-field" }, icon("search", 18), input, h("kbd", {}, "Esc")),
      list,
      h("p", { class: "palette-foot" }, h("span", {}, h("kbd", {}, "↑"), h("kbd", {}, "↓"), " ", t("move")), h("span", {}, h("kbd", {}, "Enter"), " ", t("open"))),
    ),
    { labelledBy: "palette-title" },
  );
  draw();
  input.focus({ preventScroll: true });
  return close;
}
