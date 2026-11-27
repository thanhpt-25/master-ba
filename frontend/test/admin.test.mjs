// Spec 24: chart helpers and the filters of the admin pages.
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
(await import("../i18n.js")).setLang("en");
const { barList, delta, labelIndexes, money, niceTicks, shortDate, stackedBars } = await import("../charts.js");
const { auditQuery, kindLabel, actionLabel } = await import("../views/audit.js");
const { matchUsers } = await import("../views/users.js");
const { matchProjects } = await import("../views/admin-projects.js");

test("axis ticks are round and cover the maximum", () => {
  assert.deepEqual(niceTicks(0), [0]);
  assert.deepEqual(niceTicks(95), [0, 25, 50, 75, 100]);
  assert.deepEqual(niceTicks(1200), [0, 500, 1000, 1500]);
  const ticks = niceTicks(7);
  assert.ok(ticks[ticks.length - 1] >= 7);
});

test("x labels are spread out and always include the last day", () => {
  assert.deepEqual(labelIndexes(4, 6), [0, 1, 2, 3]);
  const picked = labelIndexes(30, 6);
  assert.equal(picked[picked.length - 1], 29);
  assert.ok(picked.length <= 7);
});

test("dates, money and change are formatted for reading", () => {
  assert.equal(shortDate("2026-11-27"), "11/27");
  assert.equal(money(null, "USD"), "–");
  assert.equal(money(1.5, "USD"), "$1.50");
  assert.equal(money(1200, "JPY"), "¥1,200");
  assert.equal(delta(0, 0), null);
  assert.deepEqual(delta(5, 0), { text: "new", dir: "up" });
  assert.deepEqual(delta(150, 100), { text: "▲ 50%", dir: "up" });
  assert.deepEqual(delta(50, 100), { text: "▼ 50%", dir: "down" });
  assert.deepEqual(delta(100, 100), { text: "±0%", dir: "flat" });
});

test("the daily chart draws one bar group per day and a matching table", () => {
  const rows = [
    { date: "2026-11-26", input: 100, output: 50, calls: 2 },
    { date: "2026-11-27", input: 0, output: 0, calls: 0 },
  ];
  const chart = stackedBars(rows, { title: "Tokens", series: [{ key: "input", label: "In", cls: "s1" }, { key: "output", label: "Out", cls: "s2" }] });
  assert.equal(chart.querySelectorAll(".bar-group").length, 2);
  assert.equal(chart.querySelectorAll(".bar").length, 2);
  assert.match(chart.textContent, /2026-11-26.*100.*50.*150/s);
});

test("a ranked list scales bars to the largest value", () => {
  const list = barList([{ label: "alice", value: 200 }, { label: "bob", value: 50, href: "#/x" }]);
  const fills = list.querySelectorAll(".bar-fill");
  assert.equal(fills[0].style.getPropertyValue("--w"), "100.00%");
  assert.equal(fills[1].style.getPropertyValue("--w"), "25.00%");
});

test("job kinds and actions read as words", () => {
  assert.equal(kindLabel("stage:brd"), "BRD run");
  assert.equal(kindLabel("propagate:DR-0003"), "Change propagation DR-0003");
  assert.equal(kindLabel("propagate"), "Change propagation");
  assert.equal(kindLabel("review:srs"), "SRS rejection");
  assert.equal(kindLabel(null), "Other");
  assert.equal(actionLabel("user.disable"), "User disabled");
  assert.equal(actionLabel("x.unknown"), "x.unknown");
  assert.equal(auditQuery({ actor: "root", action: "", target: "", days: "7" }).toString(), "actor=root&days=7");
});

test("users and projects are filtered by search and status", () => {
  const w = (percent) => ({ window: "session", percent });
  const users = [
    { name: "alice", role: "approver", disabled: false, usage: [w(90)] },
    { name: "bob", role: "viewer", disabled: true, usage: [w(null)] },
    { name: "root", role: "admin", disabled: false, usage: [w(10)] },
  ];
  assert.deepEqual(matchUsers(users, "", "disabled").map((u) => u.name), ["bob"]);
  assert.deepEqual(matchUsers(users, "", "active").map((u) => u.name), ["alice", "root"]);
  assert.deepEqual(matchUsers(users, "", "limited").map((u) => u.name), ["alice"]);
  assert.deepEqual(matchUsers(users, "RO", "").map((u) => u.name), ["root"]);
  assert.deepEqual(matchUsers(users, "", "viewer").map((u) => u.name), ["bob"]);
  const projects = [
    { project_id: "PRJ-001", owner: "root", company_id: "default", members: [{ name: "alice" }] },
    { project_id: "PRJ-002", owner: "bob", company_id: "acme", members: [] },
  ];
  assert.equal(matchProjects(projects, "").length, 2);
  assert.deepEqual(matchProjects(projects, "alice").map((p) => p.project_id), ["PRJ-001"]);
  assert.deepEqual(matchProjects(projects, "acme").map((p) => p.project_id), ["PRJ-002"]);
});
