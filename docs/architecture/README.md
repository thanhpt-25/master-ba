# MasterBA architecture documents

These documents explain how MasterBA works as built: what the parts are, where data lives, how a
document travels from a customer's text to Excel workbooks, and which part of the system decides
what. They describe the code as it is today (Phase 11); the planned work is in
[../next-steps.md](../next-steps.md).

| # | Document | Read it to learn |
|---|---|---|
| 1 | [System overview](01-system-overview.md) | what MasterBA does, its layers, and the rules that hold everywhere |
| 2 | [Data model and storage](02-data-model-and-storage.md) | the entities, the ID scheme, the files on disk, the git history, the trace graph |
| 3 | [Pipeline data flow](03-pipeline-data-flow.md) | how data moves through BRD, SRS, Basic Design and Detail Design, and what each stage writes |
| 4 | [Team runtime control flow](04-team-runtime-control-flow.md) | who decides what inside a stage: writers, gates, QA, escalation, resume |
| 5 | [Change management flow](05-change-management-flow.md) | how a Decision Record finds the affected documents and rewrites them |
| 6 | [Interfaces and deployment](06-interfaces-and-deployment.md) | CLI, dashboard, background jobs, rendering and templates, security, containers, CI |
| 7 | [Customer questions](07-customer-questions.md) | how a point only the customer can settle is recorded, answered as a Decision Record and given back to the agents |

## Suggested reading order

- **New to the project:** 1, then 3. Read the end-to-end diagram in 3 before anything else.
- **Fixing or extending a stage:** 3, then 4, then the stage's spec under [../../specs](../../specs).
- **Touching storage or IDs:** 2 first. The ID Stability Rule there is binding for every change.
- **Operating the system:** 6, then the README at the repository root.

## Terms used throughout

| Term | Meaning |
|---|---|
| Intake | The customer's raw text (one `.txt` file) that starts a project |
| Requirement (`REQ-####`) | One business need cut out of the intake, with a citation of the lines it came from |
| Document | A versioned deliverable (`DOC-<TYPE>-####`): BRD, SRS, Basic Design, Detail Design, or a test specification |
| Item | One numbered row of a document (`DOC-SRS-0001#item.3`) |
| Trace link | A directed edge between two ids, from the upstream thing to the downstream thing |
| Stage | One pipeline step that creates documents: `brd`, `srs`, `basic`, `detail` |
| Team run (`RUN-####`) | One execution of a stage by writer agents and the QA reviewer; kept under `runs/` |
| Gate | A deterministic check written in code; it never calls a model |
| Escalation | A team run that stopped without an accepted result; nothing business-related is stored |
| Question (`Q-####`) | A point only the customer can settle, kept in the project ledger until a person answers it |
| Decision Record (`DR-####`) | An approved change request that is propagated to the documents it touches |
| Template | The Excel layout a document is rendered into; a default set ships with the repository |
| Work tree | The git repository MasterBA runs in (`--root`); every project lives inside it |

The original concept (in Vietnamese) is [../concept-design.md](../concept-design.md) and the phase
plan is [../roadmap-phases.md](../roadmap-phases.md). The binding conventions are in
[../../specs/00-constitution.md](../../specs/00-constitution.md).
