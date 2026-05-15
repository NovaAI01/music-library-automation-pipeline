# Metadata Suggestion Workflow

This workflow adds a controlled suggestion layer between metadata evidence and
any future tag-writing capability. Version 1 is review-only: it reads existing
metadata audit and normalization plan artifacts, generates structured cleanup
suggestions, and stops at the human approval boundary.

## Flow

```text
metadata audit
  -> metadata normalization plan
  -> metadata suggestions
  -> human review
  -> future gated execution
```

## Inputs

- `reports/metadata_plan/metadata_plan.csv`, or another explicit plan CSV path
  passed with `--metadata-plan`
- `reports/metadata_audit/`, including malformed, missing, and inconsistent tag
  CSV outputs

## Command

```bash
python -m app.main metadata-suggestions \
  --metadata-plan reports/metadata_plan/metadata_plan.csv \
  --metadata-audit reports/metadata_audit \
  --out reports
```

The command writes:

- `reports/metadata_suggestions/metadata_suggestions.json`
- `reports/metadata_suggestions/metadata_suggestions.csv`
- `reports/metadata_suggestions/metadata_suggestion_summary.json`

## Review Boundary

Every suggestion has `requires_human_review=true` in v1. Suggestions contain the
file path, field, current value, proposed value, suggestion type, confidence,
rationale, and source evidence. They are designed as an operational review queue,
not as executable instructions.

The v1 command does not write tags, mutate media files, move files, add agents,
use vector databases, or run autonomous remediation.

## Automation Constraint

Deterministic local rules create the proposed values. v1 does not call external
AI services, remote APIs, or use environment-driven rationale enrichment. Rationale wording,
`proposed_value`, confidence, suggestion type, source evidence, and the human
review requirement all remain local and deterministic.

This keeps the approval boundary clear: audit evidence and deterministic
normalization rules produce the suggested cleanup value, humans review the row,
and any future execution command must be separately gated.
