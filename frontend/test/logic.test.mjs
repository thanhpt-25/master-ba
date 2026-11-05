// View-logic and routing tests: pure functions from overview.js and app.js's
// hash parser. Run with: node --test  (from the frontend directory)
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

const env = install();

// app.js runs route() at import, which reads location.hash and calls the API.
// Stub location/history and fetch so importing it to reach parseHash() is
// harmless and offline: /me resolves as a clean 401, which app.js handles by
// routing to login without any network.
globalThis.location = { hash: "", reload() {} };
globalThis.history = { pushState() {} };
globalThis.fetch = async () => ({ ok: false, status: 401, statusText: "Unauthorized", json: async () => ({ detail: "offline" }) });
const overview = await import("../views/overview.js");

test("parseComments splits lines and recognises item refs", () => {
  const parsed = overview.parseComments(
    "DOC-SRS-0001#item.3: Split this obligation\n\n  a plain remark  \n",
  );
  assert.equal(parsed.length, 2);
  assert.deepEqual(parsed[0], { ref: "DOC-SRS-0001#item.3", text: "Split this obligation" });
  assert.deepEqual(parsed[1], { ref: null, text: "a plain remark" });
});

test("parseComments returns nothing for blank input", () => {
  assert.deepEqual(overview.parseComments("\n   \n"), []);
});

test("workflowSteps locks a phase until the one before it is finished", () => {
  const stages = [
    { stage: "brd", status: "done", review: "approved" },
    { stage: "srs", status: "not_started", review: "not_started" },
    { stage: "basic", status: "not_started", review: "not_started" },
    { stage: "detail", status: "not_started", review: "not_started" },
  ];
  const flow = overview.workflowSteps(stages, true);
  const byKey = Object.fromEntries(flow.steps.map((s) => [s.key, s.state]));
  assert.equal(byKey.brd, "approved");
  assert.equal(byKey.srs, "ready", "next phase is ready once its predecessor is approved");
  assert.equal(byKey.basic, "locked", "later phases stay locked");
  assert.equal(flow.current, "srs");
});

test("workflowSteps surfaces an in-review phase as the current one", () => {
  const stages = [
    { stage: "brd", status: "done", review: "in_review" },
    { stage: "srs", status: "not_started", review: "not_started" },
  ];
  const flow = overview.workflowSteps(stages, true);
  assert.equal(flow.steps[0].state, "in_review");
  assert.equal(flow.current, "brd");
  assert.match(flow.next, /Review the BRD/);
});

test("parseHash routes a project section", async () => {
  const app = await import("../app.js");
  const r = app.parseHash("#/p/PRJ-001/documents/DOC-SRS-0001");
  assert.equal(r.name, "documents");
  assert.equal(r.pid, "PRJ-001");
  assert.deepEqual(r.rest, ["DOC-SRS-0001"]);
});

test("parseHash defaults to projects and overview", async () => {
  const app = await import("../app.js");
  assert.deepEqual(app.parseHash(""), { name: "projects", pid: null, rest: [] });
  assert.equal(app.parseHash("#/p/PRJ-001").name, "overview");
  assert.equal(app.parseHash("#/login").name, "login");
});
