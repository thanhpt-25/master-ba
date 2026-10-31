# Spec 10 — Development and unit-test execution extension (backlog)

Status: v0.1 (2026-10-31), **backlog spec only**. No plan, no tasks and no code exist for this phase; it is kept until a real need appears. Sources: [concept-design.md](../docs/concept-design.md) section 12 (Vietnamese), [roadmap-phases.md](../docs/roadmap-phases.md) Phase 10, [06-detail-design-and-ut.md](06-detail-design-and-ut.md), [07-change-management.md](07-change-management.md), [00-constitution.md](00-constitution.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

Show, with enough detail to be checked against the code that exists today, that the original requirement #6 ("extend to development and executable unit tests") needs **no change to the base architecture**: two new agents fit the existing pattern *content agent -> JSON -> trace store -> (render if people must read it)*. Where the base needs a small additive extension, this spec names it, so nobody discovers it later.

## Non-goals

- No implementation, no CLI command, no dashboard view in this phase.
- Not a choice of target language or framework: the agents are language-neutral and take them from `ProjectConfig`.
- Not a replacement for human code review or for the project's own CI; generated code is a proposal committed to a branch, never merged by the system.

## 1. Where the extension sits

```
DETAIL_DESIGN (spec 06)  --implements-->  CODE_UNIT   (new node kind, section 3)
TEST_UT       (spec 06)  --verifies / tests-->  CODE_UNIT   (the test cases exercise the unit)
                 |
   unit-test-codegen-agent -> executable test files -> run -> results -> TEST_UT version n+1 -> re-render xlsx
```

Everything above the line exists. The extension adds two agents, one node kind, one optional result field and one execution sandbox; it does not touch rendering, the QA reviewer, the team runtime, change management or the dashboard's data model.

## 2. Agents

| Agent | Input | Output | Pattern reused |
|---|---|---|---|
| `dev-agent` | one `DETAIL_DESIGN` document (latest version) plus the project's language and style config | `CodeDraft`: a list of code units, each with a stable id, the path of its file, the item refs of the design it implements, and the source text | writer in a Writer + QA team (spec 04): same `run_writer_review`, QA checklist `code.toml` |
| `unit-test-codegen-agent` | the `TEST_UT` document and the code units it covers | `TestCodeDraft`: test files, one function per `TC-UT-####`, named after the test id | designer + tester loop (specs 05 and 06): the tester asks the designer questions through the mailbox when a case cannot be implemented as written |

Both return structured data through a forced tool call (`submit_code`, `submit_test_code`) exactly like the existing agents; both are run through `LLM`, so `FakeLLM` tests work unchanged. A QA checklist `code.toml` is added to `skills/qa-review/checklists/` (the QA reviewer is already stage-neutral): every unit implements at least one design item, no unit implements an item that is not in the design, every design item of kind function or class has a unit, no secrets or network calls the design does not mention.

## 3. Additive extension of the base (the only changes)

1. **A node kind for code.** `NodeId` accepts `CODE-<project-local-number>` (for example `CODE-0007`), one id per code unit (a file or a class, decided by the language profile). `known_nodes` (trace store) reports the kind `code_unit`, read from a new per-project index `code/index.json` (id, path, design refs, content hash). The `implements` and `tests` link types already exist in `LinkType`; they only gain the new endpoint kind. ID Stability applies to code ids exactly as to item ids: a new version of the code may not drop or revive an id.
2. **Test results on test cases.** `TestCaseItem` gains optional `last_result` (`passed | failed | skipped | error`), `run_id` and `run_at`. They are optional, so existing documents and schemas stay valid; the schema file is regenerated and drift-tested as always. A run that changes results creates a new `TEST_UT` version (never overwrites), and the diff classifier treats a result change as `result_only`, neither reworded nor structural, so it never triggers downstream propagation.
3. **A sandbox for execution** (section 5). This is the only new runtime component.

Nothing else in the base changes: documents, versions, decision records, the V-order list, impact analysis (it already walks any link type), the RTM (gains one more column, "code"), the dashboard (a Code tab can read `code/index.json` later; not required).

## 4. Change management still works

A DR that touches a requirement already reaches `DETAIL_DESIGN` and `TEST_UT` through the existing impact walk. With code in the graph the walk continues one hop further along `implements`, so the impact list also names the **code units** that implement a changed design item. Propagation does not rewrite code automatically in the first version: the DR's propagation result lists "code units to review", and the `dev-agent` is run on demand (`masterba run code --project PRJ-001`) with the changed design items, producing a new code version on a branch. This keeps the manual gate that spec 07 chose for documents (concept-design section 13.4) and makes the rest of the flow an opt-in.

## 5. Execution safety (the real design problem)

Running generated code is the only part of this extension with new risk, so it is designed first:

- Tests run only inside a throw-away container or equivalent sandbox with no network, a read-only copy of the repository, a CPU, memory and wall-clock limit, and no access to `.masterba/`, any key or the host's other projects.
- The sandbox is a function `run_tests(units, tests, limits) -> Results` behind a Protocol, with a fake implementation for unit tests of everything else.
- Results are parsed from the runner's machine-readable output (JUnit XML), never from text the generated code printed; stdout and stderr are stored as transcripts, not interpreted.
- A failed or timed-out run records `error`, never `passed`; absence of a result is `skipped`.
- The agents never receive the contents of other projects, secrets or the environment; the prompt carries the design and test documents only.

## 6. Acceptance criteria (for the day this phase is started)

- [ ] A plan and tasks are written and approved before any code (this spec is then updated, not replaced).
- [ ] The node-kind and result-field extensions of section 3 are shown to pass the existing 500+ tests unchanged (additive only), with new tests for the code index, the `implements` and `tests` links to `CODE-` ids and the `result_only` classification.
- [ ] A fake-model run produces code units and test files for the demo chain, links them, runs them in the fake sandbox and writes a `TEST_UT` version whose results re-render to xlsx.
- [ ] The sandbox refuses network, host paths and over-limit runs; a hostile test file cannot read `.masterba/`.
- [ ] A DR on the demo chain lists the affected code units in its impact.

## 7. Review of the claim "no change to the base"

Checked against the code of Phases 1 to 9:

- `LinkType` already has `implements` and `tests`; `query_impact` and `rtm` walk edges of any type (spec 01 and `trace_store/graph.py`).
- `add_trace_link` validates endpoints through `known_nodes`; adding a kind there is a local change, not a model change.
- The writer-QA loop, the designer-tester loop, the token budget, escalation and transcripts are parameterised by agents and checklists, not by document type.
- The renderer needs nothing for code (it is not an Excel document); `TEST_UT` is re-rendered by the existing engine, whose template gains no new field unless a company wants a result column (then through spec 09 calibration, `last_result` becoming one more mappable field).
- Conclusion: the extension is additive. The one point that would be a real base change is storing code **inside** the JSON content; this spec avoids it by keeping code as files under `code/` with an index, so documents stay small and diffable.

## 8. Open points

1. **Granularity of a code unit** (file, class or function) per language; the language profile decides, and the choice affects only the index and the ids.
2. **Where generated code lives**: a `code/` folder in the project, or the customer's repository through a pull request. The second needs credentials and is a separate decision.
3. **Coverage as evidence**: whether coverage data from the sandbox is stored with the results to support "every item verified by a passing test" in the RTM.
