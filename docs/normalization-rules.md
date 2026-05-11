# Normalization Rules

Metadata normalization is currently an audit and planning workflow. The system
reads FLAC tags, identifies quality issues, and generates proposed updates for
human review. It does not automatically write corrected tags back to media
files.

```text
audit
  ->
normalization proposal generation
  ->
human review
  ->
future gated remediation
```

## Philosophy

- Read first, plan second, mutate only after an explicit future gate.
- Prefer deterministic normalization rules over opaque inference.
- Preserve evidence in JSON and CSV reports so proposals can be reviewed before
  any file metadata changes.
- Treat AI assistance as analysis support for reviewing proposed changes, not
  as an automatic tag writer.

## Read-Only Audit Behavior

`metadata-audit` inspects FLAC files and reports metadata quality issues. It
detects missing tags, malformed metadata, inconsistent artist naming,
inconsistent titles, duplicate whitespace, trailing spaces, separator issues,
and probable junk suffixes.

The audit output is evidence only. It does not modify FLAC files.

## Proposed Update Planning

`metadata-plan` creates `reports/metadata_plan/tag_update_plan.csv` and
`reports/metadata_plan/metadata_plan_summary.json`. The current evidence shows
627 readable FLAC files and 2063 proposed metadata updates.

The plan provides candidate updates by field, including artist, album artist,
title, and genre. These rows are intended for review before any remediation is
implemented.

## Why Writes Are Not Automatic

Bulk metadata mutation can damage curated libraries if identity evidence is
wrong, if an edge case is missed, or if a field has intentional local wording.
The safer operational model is to separate detection, proposal generation,
review, and any future remediation gate.

This keeps the current workflow auditable and recoverable:

- Audit outputs explain what was observed.
- Plan outputs explain what would change.
- Human review can accept, reject, or defer proposed changes.
- No tag write engine is implied by the current implementation.

## Deterministic Normalization Rules

The normalization workflow focuses on concrete, inspectable rule categories:

- Malformed metadata detection: identifies tag values with structural or content
  issues that should be reviewed.
- Artist casing normalization: proposes consistent artist naming where observed
  casing differs from the organized evidence.
- Title cleanup rules: proposes cleaner title values when filenames or tags
  include removable noise.
- Separator cleanup: detects separator symbols that should be normalized for
  consistent metadata.
- Junk suffix detection: flags probable suffixes that look like source,
  encoding, or artifact noise rather than canonical title text.
- Duplicate whitespace cleanup: detects repeated whitespace and trailing spaces.

## AI-Assisted Review Boundary

AI can help summarize audit findings, group similar proposed updates, identify
risky rows, and support duplicate or metadata remediation planning. It should
not be described as autonomously mutating the library. The authoritative
workflow remains deterministic CLI execution with human review checkpoints.
