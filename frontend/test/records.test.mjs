// Spec 26 section 7: the 変更管理 list filter, its four sheets and the links from documents.
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
const i18n = await import("../i18n.js");
i18n.setLang("en");
const { drSheets, filterRecords, recordsFor, statusCounts } = await import("../views/drs.js");

const dr = (id, status, extra = {}) => ({
  id,
  date: "2026-11-28",
  trigger: "requirement_change",
  description: `Change ${id}`,
  decision: status === "proposed" ? null : "Go",
  rationale: null,
  impacted_items: ["REQ-0002"],
  affected_documents: ["DOC-BRD-0001", "DOC-SRS-0001"],
  status,
  approver: status === "proposed" ? null : "neo",
  ...extra,
});
const drs = [dr("DR-0001", "closed"), dr("DR-0003", "proposed", { trigger: "defect", affected_documents: ["DOC-TEST_UT-0001"] }), dr("DR-0002", "approved")];

test("the chips count every status and all records", () => {
  assert.deepEqual(statusCounts(drs), { all: 3, proposed: 1, approved: 1, propagated: 0, closed: 1 });
});

test("the list is newest first and filters by status and text", () => {
  assert.deepEqual(filterRecords(drs).map((d) => d.id), ["DR-0003", "DR-0002", "DR-0001"]);
  assert.deepEqual(filterRecords(drs, "approved").map((d) => d.id), ["DR-0002"]);
  assert.deepEqual(filterRecords(drs, "all", "defect").map((d) => d.id), ["DR-0003"]);
  assert.deepEqual(filterRecords(drs, "all", "0001").map((d) => d.id), ["DR-0001"]);
  assert.deepEqual(filterRecords(drs, "propagated"), []);
});

test("a document links to the records that name it", () => {
  assert.deepEqual(recordsFor(drs, "DOC-SRS-0001").map((d) => d.id), ["DR-0002", "DR-0001"]);
  assert.deepEqual(recordsFor(drs, "DOC-TEST_UT-0001").map((d) => d.id), ["DR-0003"]);
  assert.deepEqual(recordsFor(drs, "DOC-TEST_IT-0001"), []);
});

test("a proposed record prints the form, the impact preview, no result yet and its history", () => {
  const sheets = drSheets(drs[1], { history: [{ time: "2026-11-28T01:00:00Z", author: "neo", subject: "dr(PRJ-001): create DR-0003" }] });
  assert.deepEqual(sheets.map((s) => s.name), ["変更管理票", "影響分析", "反映結果", "履歴"]);
  const form = Object.fromEntries(sheets[0].rows);
  assert.equal(form["管理番号"], "DR-0003");
  assert.equal(form["判断"], "—");
  assert.equal(form["影響文書"], "DOC-TEST_UT-0001");
  assert.deepEqual(sheets[1].rows, [["1", "DOC-TEST_UT-0001"]]);
  assert.equal(sheets[2].kind, "note");
  assert.equal(sheets[3].rows.length, 1);
  assert.match(sheets[3].rows[0][2], /DR-0003/);
});

test("a propagated record prints the impact, the result per document and what changed", () => {
  const impact = { documents: ["DOC-SRS-0001"], entries: [{ node_id: "DOC-SRS-0001#item.1", depth: 1, link_type: "derives", direction: "down" }] };
  const propagation = { documents: { "DOC-SRS-0001": { outcome: "revised", version: 2, run_id: "RUN-0009" } } };
  const diff = { documents: [{ doc_id: "DOC-SRS-0001", old_version: 1, new_version: 2, rows: [{ item_id: "DOC-SRS-0001#item.1", change: "field_changed", field: "statement", old: "A", new: "B" }] }] };
  const sheets = drSheets(dr("DR-0004", "propagated"), { impact, propagation, diff });
  assert.deepEqual(sheets.map((s) => s.name), ["変更管理票", "影響分析", "反映結果", "履歴"]);
  assert.equal(Object.fromEntries(sheets[0].rows)["影響文書"], "DOC-SRS-0001");
  assert.deepEqual(sheets[1].rows, [["DOC-SRS-0001#item.1", "1", "derives (down)"]]);
  assert.deepEqual(sheets[2].rows, [["DOC-SRS-0001", "Revised", "v1→v2", "item.1", "statement", "A", "B"]]);
  // Before the diff is read, each document has one row with its version.
  const plain = drSheets(dr("DR-0004", "propagated"), { impact, propagation });
  assert.deepEqual(plain[2].rows, [["DOC-SRS-0001", "Revised", "v2", "", "", "", ""]]);
});

test("反映結果 lists the documents in V order, not in the order the stored keys sort", () => {
  // The store writes JSON with sorted keys, so DOC-BASIC_DESIGN comes back before DOC-BRD.
  const propagation = { documents: {
    "DOC-BASIC_DESIGN-0001": { outcome: "unchanged", version: null, run_id: "RUN-0007" },
    "DOC-BRD-0001": { outcome: "revised", version: 2, run_id: "RUN-0005" },
    "DOC-SRS-0001": { outcome: "unchanged", version: null, run_id: "RUN-0006" },
  } };
  const record = dr("DR-0005", "propagated", { affected_documents: ["DOC-BRD-0001", "DOC-SRS-0001", "DOC-BASIC_DESIGN-0001"] });
  assert.deepEqual(drSheets(record, { propagation })[2].rows.map((r) => r[0]), ["DOC-BRD-0001", "DOC-SRS-0001", "DOC-BASIC_DESIGN-0001"]);
  // The impact analysis stored at approval wins over the record's own list.
  const impact = { documents: ["DOC-BRD-0001", "DOC-BASIC_DESIGN-0001", "DOC-SRS-0001"], entries: [] };
  assert.deepEqual(drSheets(record, { impact, propagation })[2].rows.map((r) => r[0]), ["DOC-BRD-0001", "DOC-BASIC_DESIGN-0001", "DOC-SRS-0001"]);
});
