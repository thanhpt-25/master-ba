// The guided journey (spec 19 section 13): the one step a project waits for, as data.
// Pure, so the tests can walk every situation without a DOM or a server.

import { N_, t } from "../i18n.js";

export const PHASES = [
  { key: "brd", title: N_("BRD"), sub: "業務要件定義書", needs: N_("Intake text"), doc: "DOC-BRD-0001" },
  { key: "srs", title: N_("SRS"), sub: "システム要件定義書", needs: N_("BRD"), doc: "DOC-SRS-0001" },
  { key: "basic", title: N_("Basic Design"), sub: "基本設計書", needs: N_("SRS"), doc: "DOC-BASIC_DESIGN-0001" },
  { key: "detail", title: N_("Detail Design"), sub: "詳細設計書", needs: N_("Basic Design"), doc: "DOC-DETAIL_DESIGN-0001" },
];

// The phase whose review covers a document, from the document id.
const PHASE_OF_TYPE = {
  BRD: "brd",
  SRS: "srs",
  BASIC_DESIGN: "basic",
  TEST_IT: "basic",
  TEST_ST: "basic",
  DETAIL_DESIGN: "detail",
  TEST_UT: "detail",
};

export function phaseOfDocument(docId) {
  const type = String(docId).match(/^DOC-([A-Z_]+)-\d{4}$/)?.[1];
  return PHASE_OF_TYPE[type] ?? null;
}

export function phaseTitle(key) {
  const phase = PHASES.find((p) => p.key === key);
  return phase ? t(phase.title) : key;
}

// Where each phase stands (spec 15 section 7); a phase is locked until the one before it is finished.
export function workflowSteps(stages, gates) {
  const steps = PHASES.map((phase) => {
    const info = stages.find((s) => s.stage === phase.key) || { status: "not_started", review: "not_started" };
    let state;
    if (info.status === "running") state = "running";
    else if (info.status === "waiting_for_input") state = "waiting_for_input";
    else if (info.status === "escalated") state = "escalated";
    else if (info.review === "in_review") state = "in_review";
    else if (info.review === "approved") state = "approved";
    else if (info.status === "done") state = "done";
    else state = "ready";
    return { key: phase.key, title: t(phase.title), sub: phase.sub, state, waiting: info.waiting_for || null };
  });
  // Finished means the next phase may start. With gates, a fresh run is in_review until approved;
  // a `done` phase (documents in draft) only exists without gates or after a Decision Record.
  const finished = (s) => s.state === "approved" || s.state === "done";
  steps.forEach((step, i) => {
    if (step.state === "ready" && i > 0 && (!finished(steps[i - 1]) || step.waiting)) step.state = "locked";
  });
  const gatesBetween = gates
    ? steps.slice(0, -1).map((s) => (finished(s) ? "open" : s.state === "in_review" ? "waiting" : "closed"))
    : [];
  const current = steps.find((s) => !finished(s)) || null;
  return { steps, gates: gatesBetween, current: current ? current.key : null };
}

function jobTitle(kind) {
  const [what, target] = String(kind).split(":");
  if (what === "stage") return t("{phase} is running.", { phase: phaseTitle(target) });
  if (what === "propagate") return t("{id} is updating the affected documents.", { id: target });
  if (what === "review") return t("The rejected phase is being revised.");
  return t("A job is running.");
}

// The next step of a project: { state, title, detail, action }. `action` is null, or
// { kind: "link", href, label } | { kind: "run" | "upload" | "resume", stage, label, runId?, reuse? }.
export function nextStep(overview, pid) {
  const job = overview.job;
  if (job && ["queued", "running"].includes(job.status)) {
    return { state: "running", title: jobTitle(job.kind), detail: t("Follow it in the job panel below. You can leave this page; the run continues on the server."), action: null };
  }
  const pending = overview.pending_drs ?? [];
  if (pending.length) {
    const dr = pending[0];
    return {
      state: "approved",
      title: t("Propagate {id} to the documents", { id: dr.id }),
      detail: t("The decision is approved, but the documents it affects are not revised yet: {text}", { text: dr.description }),
      action: { kind: "link", href: `#/p/${pid}/drs/${dr.id}`, label: t("Open {id}", { id: dr.id }) },
    };
  }
  const flow = workflowSteps(overview.stages, overview.project.review_gates);
  const step = flow.steps.find((s) => s.key === flow.current);
  if (!step) {
    return {
      state: "approved",
      title: t("Every phase is approved."),
      detail: t("Changes from here go through a Decision Record, which revises the affected documents as new versions."),
      action: { kind: "link", href: `#/p/${pid}/drs`, label: t("Open Decision Records") },
    };
  }
  const info = overview.stages.find((s) => s.stage === step.key) ?? {};
  const last = info.last_run ?? null;
  const phase = PHASES.find((p) => p.key === step.key);
  if (step.state === "waiting_for_input") {
    const n = last?.waiting_questions?.length ?? info.open_questions ?? 0;
    if (n === 0 && last?.resumable) {
      return { state: "ready", title: t("Resume the {phase} run", { phase: step.title }), detail: t("Its blocker questions are settled. The run continues where it stopped."), action: { kind: "resume", stage: step.key, runId: last.run_id, label: t("Resume the run") } };
    }
    return {
      state: "waiting_for_input",
      title: t("Answer {n} customer question(s) that block {phase}", { n, phase: step.title }),
      detail: t("The QA reviewer cannot pass the draft without the customer's answer. Record the answers, then resume the run."),
      action: { kind: "link", href: `#/p/${pid}/questions`, label: t("Answer the questions") },
    };
  }
  if (step.state === "escalated") {
    if (step.key === "brd") {
      return { state: "escalated", title: t("The BRD run stopped without agreement"), detail: t("Upload the intake again to rerun it, or raise a Decision Record from the run in Activity."), action: { kind: "upload", stage: "brd", reuse: true, label: t("Upload and rerun") } };
    }
    if (last?.resumable) {
      return { state: "escalated", title: t("The {phase} run stopped without agreement", { phase: step.title }), detail: t("Resume it for one more round, or read the escalation in Activity first."), action: { kind: "resume", stage: step.key, runId: last.run_id, label: t("Resume one round") } };
    }
    return { state: "escalated", title: t("The {phase} run stopped without agreement", { phase: step.title }), detail: t("Read the escalation in Activity and raise a Decision Record from the run."), action: { kind: "link", href: `#/p/${pid}/activity`, label: t("Open Activity") } };
  }
  if (step.state === "in_review") {
    return {
      state: "in_review",
      title: t("Review {phase}", { phase: step.title }),
      detail: t("Read the document, then approve it or reject it with comments. The next phase starts after approval."),
      action: { kind: "link", href: `#/p/${pid}/documents/${phase.doc}`, label: t("Open the document") },
    };
  }
  if (step.state === "locked") {
    return { state: "locked", title: t("{phase} waits for the phase before it", { phase: step.title }), detail: t("Approve the earlier phase first."), action: null };
  }
  if (step.key === "brd") {
    return { state: "ready", title: t("Upload the customer's intake and run the BRD"), detail: t("The customer's requirements as .txt, .md, Word, PDF or Excel. Word, PDF and Excel are converted to text, and every requirement cites its lines."), action: { kind: "upload", stage: "brd", reuse: false, label: t("Upload and run") } };
  }
  return { state: "ready", title: t("Run {phase}", { phase: step.title }), detail: t("The writer drafts it from the approved phase before; QA reviews every draft."), action: { kind: "run", stage: step.key, label: t("Run {phase}", { phase: step.title }) } };
}
