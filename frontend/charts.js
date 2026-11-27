// Small charts for the admin dashboard (spec 24), drawn with DOM calls only: no markup strings,
// no inline style attributes (sizes go through CSSOM), so the Content-Security-Policy holds.
// Every chart comes with a table view, and identity is never carried by colour alone.

import { h, table } from "./dom.js";
import { locale, t } from "./i18n.js";

const SVG = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) el.setAttribute(key, String(value));
  }
  for (const child of children.flat()) if (child) el.append(child);
  return el;
}

function svgText(attrs, text) {
  const el = svg("text", attrs);
  el.textContent = text;
  return el;
}

// Round tick steps (1, 2, 2.5, 5 × 10^n) so the axis reads at a glance.
export function niceTicks(max, count = 4) {
  if (!(max > 0)) return [0];
  const raw = max / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw);
  const ticks = [];
  for (let v = 0; v < max + step * 0.999; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

// 12,345 → "12K" (or "1.2万" in Japanese); used on axes where space is short.
export function compact(n) {
  return new Intl.NumberFormat(locale(), { notation: "compact", maximumFractionDigits: 1 }).format(Number(n ?? 0));
}

export function number(n) {
  return new Intl.NumberFormat(locale()).format(Number(n ?? 0));
}

export function money(amount, currency) {
  if (amount === null || amount === undefined) return "–";
  const digits = currency === "JPY" ? 0 : 2;
  try {
    return new Intl.NumberFormat(locale(), { style: "currency", currency, minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, amount < 1 ? 4 : 2) }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

// "2026-11-27" → "11/27" in the UI locale, read as a calendar date (no time-zone shift).
export function shortDate(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  if (!y || !m || !d) return String(iso);
  return new Intl.DateTimeFormat(locale(), { month: "numeric", day: "numeric", timeZone: "UTC" }).format(Date.UTC(y, m - 1, d));
}

// Which x labels to print: about `want` evenly spaced, always the last one.
export function labelIndexes(length, want = 6) {
  if (length <= want) return [...Array(length).keys()];
  const every = Math.ceil(length / want);
  const picked = [];
  for (let i = length - 1; i >= 0; i -= every) picked.unshift(i);
  return picked;
}

function topRounded(x, y, w, hgt, r) {
  const radius = Math.min(r, w / 2, hgt);
  return `M${x},${y + hgt}V${y + radius}Q${x},${y} ${x + radius},${y}H${x + w - radius}Q${x + w},${y} ${x + w},${y + radius}V${y + hgt}Z`;
}

// Stacked daily bars. series: [{ key, label, cls }]; the first series sits on the baseline.
export function stackedBars(rows, { series, title, valueLabel = number }) {
  const legend = h("ul", { class: "chart-legend", "aria-hidden": "true" },
    series.map((s) => h("li", {}, h("span", { class: `swatch ${s.cls}` }), s.label)),
  );
  const tip = h("div", { class: "chart-tip", role: "status", hidden: true });
  const frame = h("div", { class: "chart-frame" }, tip);
  const tableView = table(
    [t("Date"), ...series.map((s) => s.label), t("Total")],
    rows.map((r) => [r.date, ...series.map((s) => number(r[s.key])), number(series.reduce((n, s) => n + r[s.key], 0))]),
    title,
    { dense: true },
  );
  tableView.hidden = true;
  const toggle = h("button", { type: "button", class: "link chart-toggle", "aria-expanded": "false" }, t("Show as table"));
  toggle.addEventListener("click", () => {
    const show = tableView.hidden;
    tableView.hidden = !show;
    frame.hidden = show;
    toggle.setAttribute("aria-expanded", show ? "true" : "false");
    toggle.textContent = show ? t("Show as chart") : t("Show as table");
  });

  const draw = (width) => {
    const W = Math.max(300, Math.round(width || 720));
    const H = 220;
    const pad = { top: 12, right: 8, bottom: 26, left: 48 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;
    const totals = rows.map((r) => series.reduce((n, s) => n + (r[s.key] || 0), 0));
    const ticks = niceTicks(Math.max(...totals, 0));
    const top = ticks[ticks.length - 1] || 1;
    const y = (v) => pad.top + plotH - (v / top) * plotH;
    const slot = plotW / Math.max(rows.length, 1);
    const barW = Math.max(2, Math.min(28, slot * 0.66));
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": title, class: "chart" });
    for (const v of ticks) {
      chart.append(svg("line", { x1: pad.left, x2: W - pad.right, y1: y(v), y2: y(v), class: v === 0 ? "axis" : "grid" }));
      chart.append(svgText({ x: pad.left - 8, y: y(v) + 4, "text-anchor": "end", class: "tick" }, compact(v)));
    }
    for (const i of labelIndexes(rows.length, Math.max(3, Math.floor(plotW / 70)))) {
      chart.append(svgText({ x: pad.left + slot * i + slot / 2, y: H - 8, "text-anchor": "middle", class: "tick" }, shortDate(rows[i].date)));
    }
    rows.forEach((row, i) => {
      const x = pad.left + slot * i + (slot - barW) / 2;
      const group = svg("g", { class: "bar-group" });
      let base = 0;
      const drawn = series.filter((s) => row[s.key] > 0);
      drawn.forEach((s, n) => {
        const value = row[s.key];
        const y0 = y(base);
        const y1 = y(base + value);
        // 2px surface gap between stacked segments.
        const gap = n > 0 ? 2 : 0;
        const height = Math.max(1, y0 - y1 - gap);
        const last = n === drawn.length - 1;
        group.append(last
          ? svg("path", { d: topRounded(x, y1, barW, height, 4), class: `bar ${s.cls}` })
          : svg("rect", { x, y: y1 + gap, width: barW, height, class: `bar ${s.cls}` }));
        base += value;
      });
      // A hit target taller and wider than the bar.
      const hit = svg("rect", { x: pad.left + slot * i, y: pad.top, width: slot, height: plotH, class: "hit" });
      const show = () => {
        group.classList.add("hover");
        tip.replaceChildren(
          h("strong", {}, shortDate(row.date)),
          ...series.map((s) => h("span", {}, h("span", { class: `swatch ${s.cls}` }), `${s.label}: ${valueLabel(row[s.key])}`)),
          h("span", { class: "muted" }, t("{n} call(s)", { n: number(row.calls ?? 0) })),
        );
        tip.hidden = false;
        const left = ((pad.left + slot * i + slot / 2) / W) * 100;
        tip.style.setProperty("left", `${Math.min(82, Math.max(18, left))}%`);
      };
      const hide = () => { group.classList.remove("hover"); tip.hidden = true; };
      hit.addEventListener("pointerenter", show);
      hit.addEventListener("pointerleave", hide);
      group.append(hit);
      chart.append(group);
    });
    frame.querySelector("svg")?.remove();
    frame.append(chart);
  };
  draw(720);
  if (typeof ResizeObserver === "function") {
    let last = 0;
    const observer = new ResizeObserver((entries) => {
      const width = Math.round(entries[0]?.contentRect?.width ?? 0);
      if (width && Math.abs(width - last) > 8) { last = width; draw(width); }
    });
    queueMicrotask(() => observer.observe(frame));
  }
  return h("div", { class: "chart-block" }, h("div", { class: "chart-head" }, legend, toggle), frame, tableView);
}

// Horizontal bars for a ranked list. items: [{ label, value, href?, note? }].
export function barList(items, { valueLabel = number, caption = "" } = {}) {
  const max = Math.max(...items.map((i) => i.value), 0) || 1;
  return h("ol", { class: "bar-list", "aria-label": caption || null },
    items.map((item) => h("li", {},
      h("div", { class: "bar-line" },
        item.href ? h("a", { href: item.href, class: "bar-name" }, item.label) : h("span", { class: "bar-name" }, item.label),
        h("span", { class: "bar-value" }, valueLabel(item.value)),
      ),
      h("div", { class: "bar-track", "aria-hidden": "true" }, h("span", { class: "bar-fill", style: `--w:${Math.max(1.5, (item.value / max) * 100).toFixed(2)}%` })),
      item.note ? h("p", { class: "bar-note" }, item.note) : null,
    )),
  );
}

// Change against the previous period, as a signed percentage with an arrow (not colour alone).
export function delta(current, previous) {
  if (!previous) return current ? { text: t("new"), dir: "up" } : null;
  const change = Math.round(((current - previous) / previous) * 100);
  if (change === 0) return { text: "±0%", dir: "flat" };
  const size = Math.abs(change) > 999 ? ">999" : String(Math.abs(change));
  return { text: `${change > 0 ? "▲" : "▼"} ${size}%`, dir: change > 0 ? "up" : "down" };
}
