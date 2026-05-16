# Demo Workflow

This end-to-end demonstration shows how to regenerate the operational evidence
used by the repository documentation. Paths below match the current local
evidence. Adjust them only when running against a different library or
quarantine directory.

```bash
LIBRARY_ROOT="$HOME/Music/Organised_Library"
QUARANTINE_ROOT="$HOME/Music/Quarantine_Duplicates"
SCAN_RUN_ID=1
DUPLICATE_REPORT_ID=1
REVIEW_PLAN_ID=1
QUARANTINE_RUN_ID=1
```

## 1. Library QA

```bash
python -m app.main library-qa \
  --library-root "$LIBRARY_ROOT" \
  --quarantine-root "$QUARANTINE_ROOT" \
  --out reports
```

Expected report paths:

- `reports/library_qa/library_qa_summary.json`
- `reports/library_qa/artists.csv`
- `reports/library_qa/genres.csv`
- `reports/library_qa/file_health.csv`
- `reports/library_qa/quarantine_summary.csv`

Expected summary metrics:

- 627 organised FLAC files
- 52 quarantined duplicates
- 0 active duplicate groups
- 0 unresolved missing files

Operational behavior: generates read-only QA evidence for the active organized
library and quarantine state.

## 2. Metadata Audit

```bash
python -m app.main metadata-audit \
  --library-root "$LIBRARY_ROOT" \
  --out reports
```

Expected report paths:

- `reports/metadata_audit/metadata_summary.json`
- `reports/metadata_audit/missing_tags.csv`
- `reports/metadata_audit/malformed_tags.csv`
- `reports/metadata_audit/inconsistent_artists.csv`
- `reports/metadata_audit/inconsistent_titles.csv`

Expected summary metrics:

- 627 readable FLAC files
- 0 unreadable FLAC files

Operational behavior: reads FLAC metadata and reports quality issues without
writing tag changes.

## 3. Metadata Normalization Plan

```bash
python -m app.main metadata-plan \
  --library-root "$LIBRARY_ROOT" \
  --out reports
```

Expected report paths:

- `reports/metadata_plan/metadata_plan_summary.json`
- `reports/metadata_plan/tag_update_plan.csv`

Expected summary metrics:

- 627 readable FLAC files
- 2063 proposed metadata updates

Operational behavior: generates a reviewable tag update plan. It does not save
metadata updates to files.

## 4. Duplicate Report

```bash
python -m app.main duplicate-report \
  --scan-run-id "$SCAN_RUN_ID" \
  --library-root "$LIBRARY_ROOT" \
  --out reports
```

Expected report paths:

- `reports/duplicates_scan_1/duplicate_summary.json`
- `reports/duplicates_scan_1/exact_hash_duplicates.csv`
- `reports/duplicates_scan_1/same_artist_title_duplicates.csv`
- `reports/duplicates_scan_1/probable_variants.csv`

Expected summary metrics:

- 627 files checked
- 0 exact hash groups
- 0 same artist/title groups
- 0 probable variant title groups

Operational behavior: produces duplicate evidence only. It does not move or
delete files.

## 5. Duplicate Review Plan

```bash
python -m app.main duplicate-review \
  --duplicate-report-id "$DUPLICATE_REPORT_ID" \
  --out reports
```

Expected report paths:

- `reports/duplicate_review_scan_1/duplicate_review_summary.json`
- `reports/duplicate_review_scan_1/duplicate_review_plan.csv`

Operational behavior: creates a review plan from duplicate evidence. The plan is
used as the approval checkpoint before quarantine execution.

## 6. Quarantine Dry Run

```bash
python -m app.main quarantine-duplicates \
  --review-plan-id "$REVIEW_PLAN_ID" \
  --quarantine-root "$QUARANTINE_ROOT" \
  --dry-run
```

Expected operational behavior: evaluates the selected review plan and reports
what would be moved to quarantine without moving files.

## 7. Restore Dry Run

```bash
python -m app.main restore-quarantine \
  --quarantine-run-id "$QUARANTINE_RUN_ID" \
  --dry-run
```

Expected operational behavior: evaluates restore actions from recorded
quarantine ledger rows without moving files back into the library.

## UI Routes

Run the read-only report UI:

```bash
uvicorn app.main:app --reload
```

Expected routes:

- `/reports`
- `/reports/artists`
- `/reports/genres`
- `/reports/quarantine`
- `/reports/file-health`
- `/reports/duplicates`
- `/review`
- `/review/quarantine`
- `/review/conflicts`
- `/review/blocked`

## Screenshot Placeholders

- `tools/portfolio_demo/docs/screenshots/01_dashboard.png`
- `tools/portfolio_demo/docs/screenshots/02_library_browser.png`
- `tools/portfolio_demo/docs/screenshots/03_review_hub.png`
- `tools/portfolio_demo/docs/screenshots/04_metadata_review.png`
- `tools/portfolio_demo/docs/screenshots/05_player.png`

## Operational Evidence

The demonstration is evidence-driven. Reports are written as JSON and CSV files,
the UI reads generated report artifacts, duplicate remediation is staged through
review plans, and quarantine or restore actions can be dry-run before execution.
