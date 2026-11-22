// Project summaries on the Projects cards and the shared icon/monogram helpers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
(await import("../i18n.js")).setLang("en");
const { projectSummary } = await import("../views/projects.js");
const { monogram, icon } = await import("../dom.js");

const st = (stage, status, review, docs = 0) =>
  ({ stage, status, review, waiting_for: null, documents: Array.from({ length: docs }, (_, i) => ({ id: `D${i}`, version: 1 })) });
const overview = (stages, gates = true) => ({ project: { review_gates: gates }, stages, counts: { open_questions: 2 } });

test("a fresh project has not started and sits at the BRD", () => {
  const s = projectSummary(overview(["brd", "srs", "basic", "detail"].map((k) => st(k, "not_started", "not_started"))));
  assert.equal(s.status, "not_started");
  assert.equal(s.stage, "BRD");
  assert.equal(s.progress, 0);
  assert.equal(s.questions, 2);
});

test("a phase in review counts half and names the waiting review", () => {
  const s = projectSummary(overview([st("brd", "done", "approved", 1), st("srs", "done", "in_review", 1), st("basic", "not_started", "not_started"), st("detail", "not_started", "not_started")]));
  assert.equal(s.status, "in_review");
  assert.equal(s.stage, "SRS");
  assert.equal(s.progress, 38);
  assert.equal(s.documents, 2);
  assert.equal(s.reviews, 1);
});

test("every phase finished is done", () => {
  const s = projectSummary(overview(["brd", "srs", "basic", "detail"].map((k) => st(k, "done", "draft", 1)), false));
  assert.equal(s.status, "done");
  assert.equal(s.progress, 100);
  assert.equal(s.stage, "All phases complete");
});

test("no overview gives no summary", () => {
  assert.equal(projectSummary(null), null);
});

test("monogram takes two letters", () => {
  assert.equal(monogram("Koyo Manufacturing"), "KM");
  assert.equal(monogram("acme"), "AC");
  assert.equal(monogram(""), "?");
});

test("icon is decorative and unknown names give nothing", () => {
  assert.equal(icon("nope"), null);
  const svg = icon("check");
  if (svg) assert.equal(svg.getAttribute("aria-hidden"), "true");
});
