# Operational Workflow

This document describes the operational lifecycle used by the Music Library
Intelligence Platform. The workflow is deterministic and human-in-the-loop:
each stage produces evidence, reports, plans, or ledger records that can be
reviewed before file-moving operations are executed.

Repository-safe evidence includes:

- 632 collected tests, summarized in the
  [test coverage map](test-coverage-map.md)
- validation pass boundaries summarized in the
  [validation evidence ledger](validation-evidence-ledger.md)
- MusicBrainz 50k validation summaries
- sanitized sample outputs
- golden regression fixtures
- metadata-only external validation workflow

## 1. Intake

Purpose: bring local files into the observed workflow and record filesystem
evidence.

Inputs: local media files, configured source paths, and the local SQLite
database.

Outputs: scan runs, file observations, hashes, tag observations, probe results,
and later placement plans.

Safety boundary: source scanning observes files before any organized placement
or quarantine action. File movement is handled by separate commands.

Operational value: creates a repeatable evidence base for identity resolution,
classification, placement planning, duplicate detection, and reporting.

## 2. Metadata Audit

Purpose: inspect FLAC tag quality and identify missing, malformed, or
inconsistent metadata.

Inputs: organized library files and readable FLAC metadata.

Outputs: `reports/metadata_audit/metadata_summary.json`,
`reports/metadata_audit/missing_tags.csv`,
`reports/metadata_audit/malformed_tags.csv`,
`reports/metadata_audit/inconsistent_artists.csv`, and
`reports/metadata_audit/inconsistent_titles.csv`.

Safety boundary: audit is read-only and does not write tags to media files.

Operational value: exposes tag quality issues using evidence that can be
reviewed, filtered, and compared over time.

## 3. Duplicate Detection

Purpose: identify active duplicate candidates in the organized library.

Inputs: organized library files, file hashes, identity evidence, and scan run
records.

Outputs: `reports/duplicates_scan_1/duplicate_summary.json`,
`reports/duplicates_scan_1/exact_hash_duplicates.csv`,
`reports/duplicates_scan_1/same_artist_title_duplicates.csv`, and
`reports/duplicates_scan_1/probable_variants.csv`.

Safety boundary: duplicate reporting is read-only. It does not move, quarantine,
or delete files.

Operational value: separates duplicate evidence generation from remediation so
operators can inspect candidate groups before deciding what to keep or remove.

## 4. Duplicate Review Planning

Purpose: convert duplicate evidence into reviewable decisions.

Inputs: duplicate report records and duplicate report IDs.

Outputs: `reports/duplicate_review_scan_1/duplicate_review_summary.json` and
`reports/duplicate_review_scan_1/duplicate_review_plan.csv`.

Safety boundary: review planning produces keep, remove-candidate, and
manual-review recommendations. It does not move files.

Operational value: creates an auditable bridge between detection and execution,
allowing human review to focus on concrete rows rather
than ad hoc filesystem inspection.

## 5. Human Review Checkpoints

Purpose: ensure that remediation decisions are reviewed before file-changing
commands run.

Inputs: QA reports, duplicate plans, metadata audit outputs, metadata update
plans, and read-only UI routes.

Outputs: approved duplicate review plans, accepted operational findings, or
items held for manual review.

Safety boundary: review checkpoints sit between evidence generation and
execution. Operators can stop after any report or plan command.

Operational value: keeps the workflow accountable. AI assistance can summarize
evidence, identify risky rows, and support remediation planning, but approval is
still a human checkpoint.

## 6. Quarantine Execution

Purpose: move approved duplicate remove candidates out of the active library
without deleting them.

Inputs: duplicate review plan IDs, remove-candidate rows, and a quarantine root.

Outputs: quarantine run records, moved files, and quarantine evidence in QA and
UI reports.

Safety boundary: quarantine targets only rows marked as remove candidates and
supports dry-run execution. The operation moves files to quarantine instead of
deleting them.

Operational value: reduces active duplicate state while preserving recovery
options and a record of what changed.

## 7. Restore / Rollback Workflow

Purpose: restore quarantined files from recorded quarantine ledger entries.

Inputs: quarantine run IDs, recorded source paths, recorded quarantine paths, and
dry-run restore checks.

Outputs: restore attempts, restored files when execution is approved, and
updated operational evidence.

Safety boundary: restore uses ledger records and avoids overwriting existing
restore targets. Dry-run mode supports inspection before recovery.

Operational value: provides a practical rollback model for duplicate remediation
without relying on memory or manual path reconstruction.

## 8. Metadata Normalization Planning

Purpose: produce reviewable metadata update proposals from organized paths and
observed tag issues.

Inputs: organized library files, current FLAC tags, inferred identity evidence,
and deterministic normalization rules.

Outputs: `reports/metadata_plan/metadata_plan_summary.json` and
`reports/metadata_plan/tag_update_plan.csv`.

Safety boundary: the current workflow plans metadata updates only. It does not
automatically mutate FLAC tags.

Operational value: gives operators a concrete remediation backlog for missing
and inconsistent metadata while avoiding uncontrolled bulk writes.

## 9. Reporting + Evidence Generation

Purpose: provide operational visibility into library state, quarantine state,
metadata quality, duplicate status, and review queues.

Inputs: generated reports, organized library files, quarantine state, and ledger
records.

Outputs: JSON and CSV report artifacts plus read-only UI routes such as
`/reports`, `/reports/artists`, `/reports/genres`, `/reports/quarantine`,
`/reports/file-health`, `/reports/duplicates`, `/review`, and
`/review/quarantine`. Validation source quality comparison writes
`reports/source_quality/source_quality_summary.json` and
`reports/source_quality/source_quality_by_source.csv` from existing
`reports/runs/<source>/<run_label>/` evidence.

Safety boundary: report generation and UI views are read-only.

Operational value: creates evidence-driven outputs that can be shared, audited,
reviewed, or used to guide assisted analysis.

## 10. Test Verification

Purpose: verify the deterministic workflow behavior across scanning, identity,
classification, placement, reporting, duplicate review, quarantine, restore,
metadata audit, metadata planning, and UI helpers.

Inputs: the repository test suite.

Outputs: pytest results. Current collection evidence records 632 tests; see the
[test coverage map](test-coverage-map.md) for a practical coverage summary and
the [validation evidence ledger](validation-evidence-ledger.md) for pass/fail
evidence boundaries.

Safety boundary: tests exercise behavior without requiring operators to mutate
the production library.

Operational value: keeps workflow changes grounded in executable verification
instead of relying only on documentation or manual inspection.
