// Commit subjects in plain words (spec 25 section 6). Every business action is one git commit
// with a subject like "render(PRJ-001): xlsx DOC-BRD-0001 v1"; people should not have to read that.

import { statusLabel } from "../dom.js";
import { N_, t } from "../i18n.js";

const SUBJECT = /^([a-z_]+)\(([^)]*)\):\s*(.*)$/;

// kind -> [icon name, tone, label]. Tone "seal" marks approvals, "run" marks team runs.
const KINDS = {
  project: ["projects", "", N_("Project")],
  intake: ["requirements", "", N_("Intake")],
  req: ["requirements", "", N_("Requirement")],
  doc: ["documents", "", N_("Document")],
  render: ["documents", "", N_("Excel output")],
  trace: ["trace", "", N_("Trace link")],
  run: ["workflow", "run", N_("Team run")],
  review: ["shield", "seal", N_("Review")],
  dr: ["drs", "", N_("Decision Record")],
  question: ["questions", "", N_("Customer question")],
  kb: ["knowledge", "", N_("Knowledge base")],
  template: ["templates", "", N_("Template")],
};

const VERBS = {
  create: N_("created"),
  add: N_("added"),
  update: N_("updated"),
  approve: N_("approved"),
  reject: N_("rejected"),
  close: N_("closed"),
  propagate: N_("propagated"),
  remove: N_("removed"),
  replace: N_("replaced"),
  answer: N_("answered"),
  withdraw: N_("withdrawn"),
  supersede: N_("superseded"),
  link: N_("linked"),
  xlsx: N_("written"),
  calibrate: N_("calibrated"),
  confirm: N_("confirmed"),
  edit: N_("edited"),
  unconfirm: N_("unconfirmed"),
};

// { kind, icon, tone, label, detail } for one subject; unknown subjects pass through unchanged.
export function describeCommit(subject) {
  const match = SUBJECT.exec(String(subject ?? ""));
  if (!match || !KINDS[match[1]]) return { kind: "other", icon: "activity", tone: "", label: t("Change"), detail: String(subject ?? "") };
  const [, kind, , rest] = match;
  const [iconName, tone, label] = KINDS[kind];
  let detail = rest.replace(/ -> /g, " → ");
  if (kind === "run") {
    // "RUN-0004 done" or "RUN-0004 escalated (resumed)"
    const run = /^(\S+)\s+(\S+)(.*)$/.exec(rest);
    if (run) detail = `${run[1]} ${statusLabel(run[2])}${run[3] ? ` ${run[3].trim()}` : ""}`;
  } else {
    const [verb, ...tail] = rest.split(" ");
    if (VERBS[verb]) detail = `${tail.join(" ").replace(/ -> /g, " → ")} ${t(VERBS[verb])}`.trim();
  }
  return { kind, icon: iconName, tone, label: t(label), detail };
}

// Consecutive commits of the same kind fold into one line ("Trace link ×12"), newest first.
export function foldCommits(items, limit = 6) {
  const out = [];
  for (const item of items ?? []) {
    const info = describeCommit(item.subject);
    const last = out[out.length - 1];
    if (last && last.info.kind === info.kind && info.kind !== "run" && info.kind !== "review") {
      last.count += 1;
      continue;
    }
    if (out.length === limit) break;
    out.push({ item, info, count: 1 });
  }
  return out;
}
