---
name: template-calibration
description: How a customer's Excel sample becomes a confirmed company template. Used by the template-calibrator agent and the masterba template commands.
---

# template-calibration

Spec: `specs/09-template-calibration.md`.

## Flow

1. `profile_workbook` reads the sample (no macros, no external links): header row, merged ranges,
   widths, first rows, warnings.
2. `heuristic_draft` maps header labels to item fields with a Japanese and English synonym table.
3. Optional: the `template-calibrator` agent refines the draft; `validate_mapping` is the gate; one
   retry; otherwise the heuristic draft is kept.
4. `build_template` writes the draft into `templates/companies/<company>/` (template JSON, cleaned
   shell, the untouched sample, the calibration record). One commit.
5. A human looks (`template show`, `template preview`), fixes columns (`template set`), runs
   `template check`, then `template confirm`.

## Safety rules

| Rule | Enforcement |
|---|---|
| A draft never changes a rendered document | `resolve_template` ignores a `calibrated_from_sample` template without the `.confirmed` marker |
| Only plain small `.xlsx` files are read | `check_sample` refuses other suffixes, large files and non-zip files before parsing |
| The model cannot invent fields or cells | `validate_mapping` checks every sheet, cell, field and column against the profile and the item class |
| Any edit needs a new confirmation | `set_column` removes `.confirmed`; so does `calibrate --replace` |
| Content is never regenerated | calibration changes only the template files; documents are re-rendered, not rewritten |

## Known limits

Merged data cells, several tables per sheet, multi-row headers, formulas, images and charts are not
reproduced; the profile reports them as warnings.
