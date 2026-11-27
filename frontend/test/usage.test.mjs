// Usage windows and the limit banner (spec 23 section 8).
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
(await import("../i18n.js")).setLang("en");
const { usageLimitText, usageNotice, usageMeter, windowName } = await import("../dom.js");

const w = (window, used, limit, extra = {}) => ({
  window, used, limit, percent: limit === null ? null : Math.min(100, Math.round((used * 100) / (limit || 1))),
  reached: limit !== null && used >= limit, started: null, resets_at: "2026-11-27T20:00:00+00:00", ...extra,
});

test("no banner below 80 % or without limits", () => {
  assert.equal(usageNotice([w("session", 10, 100), w("weekly", 5, null)]), null);
  assert.equal(usageNotice(undefined), null);
});

test("a warning from 80 % names the fullest window", () => {
  const notice = usageNotice([w("session", 85, 100), w("weekly", 95, 100)]);
  assert.equal(notice.level, "warn");
  assert.match(notice.text, /95% of your Weekly limit/);
});

test("a reached window wins and gives the reset time", () => {
  const notice = usageNotice([w("session", 50, 100), w("weekly", 120, 100)]);
  assert.equal(notice.level, "bad");
  assert.match(notice.text, /reached your Weekly limit \(120 of 100 tokens\)\. It resets at/);
});

test("a zero limit without a window asks for an administrator", () => {
  assert.match(usageLimitText({ window: "session", used: 0, limit: 0, resets_at: null }), /5-hour limit is 0 tokens\. Ask an administrator/);
  assert.equal(windowName("weekly"), "Weekly limit");
});

test("the meter shows used of limit, or no limit", () => {
  assert.match(usageMeter(w("session", 30, 100)).textContent, /30 of 100 tokens/);
  assert.match(usageMeter(w("weekly", 30, null)).textContent, /30 tokens · no limit/);
});
