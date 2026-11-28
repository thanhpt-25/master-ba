// The guided journey (spec 19 section 13): one next step for every situation.
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
const i18n = await import("../i18n.js");
i18n.setLang("en");
const { nextStep, phaseOfDocument } = await import("../views/journey.js");

const PID = "PRJ-001";

function overview({ stages = {}, job = null, pending = [], gates = true } = {}) {
  const base = ["brd", "srs", "basic", "detail"].map((stage) => ({
    stage,
    status: "not_started",
    review: "not_started",
    documents: [],
    last_run: null,
    waiting_for: null,
    open_questions: 0,
    ...(stages[stage] ?? {}),
  }));
  return { project: { review_gates: gates }, stages: base, job, pending_drs: pending, counts: {}, open_questions: [] };
}

test("a fresh project asks for the intake and the BRD run", () => {
  const step = nextStep(overview(), PID);
  assert.equal(step.action.kind, "upload");
  assert.equal(step.action.reuse, false);
  assert.match(step.title, /intake/);
});

test("a running job has no action", () => {
  const step = nextStep(overview({ job: { kind: "stage:srs", status: "running" } }), PID);
  assert.equal(step.state, "running");
  assert.equal(step.action, null);
  assert.match(step.title, /SRS is running/);
});

test("an approved DR with documents to revise comes before the phases", () => {
  const step = nextStep(overview({ pending: [{ id: "DR-0002", description: "SMS too" }] }), PID);
  assert.deepEqual(step.action, { kind: "link", href: "#/p/PRJ-001/drs/DR-0002", label: "Open DR-0002" });
});

test("a run waiting for input sends the reviewer to the questions", () => {
  const step = nextStep(overview({ stages: { brd: { status: "waiting_for_input", last_run: { run_id: "RUN-0001", waiting_questions: [{ id: "Q-0001" }], resumable: false } } } }), PID);
  assert.equal(step.state, "waiting_for_input");
  assert.equal(step.action.href, "#/p/PRJ-001/questions");
  assert.match(step.title, /Answer 1 customer question/);
});

test("a run whose blockers are settled resumes", () => {
  const brd = { status: "done", review: "approved" };
  const srs = { status: "waiting_for_input", last_run: { run_id: "RUN-0002", waiting_questions: [], resumable: true } };
  const step = nextStep(overview({ stages: { brd, srs } }), PID);
  assert.deepEqual([step.action.kind, step.action.runId, step.action.stage], ["resume", "RUN-0002", "srs"]);
});

test("an escalated later phase resumes one round; an escalated BRD asks for the intake again", () => {
  const brd = { status: "done", review: "approved" };
  const srs = { status: "escalated", last_run: { run_id: "RUN-0003", resumable: true } };
  assert.equal(nextStep(overview({ stages: { brd, srs } }), PID).action.kind, "resume");
  const stuck = nextStep(overview({ stages: { brd, srs: { ...srs, last_run: { run_id: "RUN-0003", resumable: false } } } }), PID);
  assert.deepEqual([stuck.action.kind, stuck.action.stage], ["run", "srs"]);
  const first = nextStep(overview({ stages: { brd: { status: "escalated" } } }), PID);
  assert.deepEqual([first.action.kind, first.action.reuse], ["upload", true]);
});

test("a phase in review links to its first document", () => {
  const step = nextStep(overview({ stages: { brd: { status: "done", review: "approved" }, srs: { status: "done", review: "in_review" } } }), PID);
  assert.equal(step.state, "in_review");
  assert.equal(step.action.href, "#/p/PRJ-001/documents/DOC-SRS-0001");
});

test("an approved phase makes the next one runnable", () => {
  const step = nextStep(overview({ stages: { brd: { status: "done", review: "approved" }, srs: { status: "done", review: "approved" } } }), PID);
  assert.deepEqual([step.action.kind, step.action.stage], ["run", "basic"]);
});

test("when every phase is approved the next step is a Decision Record", () => {
  const done = { status: "done", review: "approved" };
  const step = nextStep(overview({ stages: { brd: done, srs: done, basic: done, detail: done } }), PID);
  assert.equal(step.action.href, "#/p/PRJ-001/drs");
  assert.equal(step.title, "Every phase is approved.");
});

test("without review gates every phase is done, not approved", () => {
  const done = { status: "done", review: "not_started" };
  const step = nextStep(overview({ gates: false, stages: { brd: done, srs: done, basic: done, detail: done } }), PID);
  assert.equal(step.title, "Every phase is done.");
  assert.equal(step.action.href, "#/p/PRJ-001/drs");
});

test("documents map to the phase whose review covers them", () => {
  assert.equal(phaseOfDocument("DOC-TEST_IT-0001"), "basic");
  assert.equal(phaseOfDocument("DOC-TEST_UT-0001"), "detail");
  assert.equal(phaseOfDocument("DOC-BRD-0001"), "brd");
  assert.equal(phaseOfDocument("DOC-TEST_UAT-0001"), null);
});

test("Japanese is the default language and English text is the fallback", () => {
  assert.equal(i18n.loadLang("nobody"), "ja");
  assert.equal(i18n.t("No such English text"), "No such English text");
  assert.equal(i18n.t("Run {phase}", { phase: "X" }).includes("X"), true);
  i18n.setLang("en");
});
