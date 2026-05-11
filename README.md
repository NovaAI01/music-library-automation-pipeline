# Media Library Automation Pipeline

A local, SQLite-backed automation pipeline for observing, organizing, auditing,
and safely maintaining a FLAC-based media library.

This project is positioned around library operations: intake control, identity
resolution, deterministic classification, placement planning, duplicate review,
quarantine, restore, metadata audit, and report UI surfaces.

## Problem Statement

Large personal media libraries often accumulate inconsistent filenames,
partial tags, repeated files, stale placement records, and unclear review
state. Manual cleanup is risky because a single mistaken move, overwrite, or
metadata rewrite can damage a curated collection.

This system solves that operational problem by separating observation,
planning, execution, reporting, and restore into auditable stages. Most stages
are read-only. Mutating stages are narrow, ledger-backed, and designed to avoid
overwriting or deleting files.

## Current Library Snapshot

Generated reports in this repository currently show:

- 627 clean library files, all represented as readable FLAC files
- 0 active duplicate groups in the live organized library
- 52 quarantined duplicate files
- 627 readable files in the metadata audit
- 2,063 proposed metadata updates in the metadata normalization plan
- 222 passing pytest tests in the documented project baseline
- Latest local verification on 2026-05-11: 232 passed

Evidence sources:

- `reports/library_qa/library_qa_summary.json`
- `reports/duplicates_scan_1/duplicate_summary.json`
- `reports/metadata_audit/metadata_summary.json`
- `reports/metadata_plan/metadata_plan_summary.json`

## What The System Does

The pipeline creates a durable observation ledger for local audio files and
generates reviewable outputs before any file-changing operation is available.

Core responsibilities:

- Scan local folders and record file observations, hashes, metadata, and probe
  results in SQLite.
- Resolve probable track identity from tags, filenames, parent folders, and a
  controlled artist seed list.
- Classify identified tracks with deterministic artist-seed and genre metadata
  rules.
- Plan organized placement paths without touching files.
- Copy planned files into an organized output root when explicitly executed.
- Export review reports for placement, blocked items, conflicts, duplicates,
  library QA, and metadata quality.
- Generate duplicate review plans and move selected duplicate candidates into
  quarantine.
- Restore quarantined files from ledger records.
- Provide read-only FastAPI/Jinja2 views over generated reports.
- Build read-only metadata audit and metadata normalization plans for FLAC
  libraries.

The system does not claim AI-driven recognition, audio fingerprinting,
automatic metadata writing, or automatic destructive cleanup. Identity and
classification are deterministic and evidence-based.

## Architecture Flow

```text
Local files
  |
  v
Scanner
  - observes supported audio files
  - records hashes, paths, metadata, probe status
  |
  v
SQLite observation ledger
  |
  +--> Identity engine
  |      - probable artist/title/album/year/mix
  |      - preserves conflicts and unknowns
  |
  +--> Classification engine
  |      - artist seed rules first
  |      - embedded genre metadata second
  |
  v
Placement planner
  - creates reviewable relative paths
  - writes plans only
  |
  +--> Review reports
  |      - JSON/CSV summaries
  |      - conflicts and blocked items
  |
  v
Placement executor
  - copies planned files to an organized root
  - never overwrites existing destinations
  |
  v
Duplicate reports and review plans
  - exact hash, same artist/title, probable variants
  - keep/remove/manual-review recommendations
  |
  v
Quarantine and restore
  - move selected remove candidates to quarantine
  - restore from recorded original paths
  |
  v
Library QA, metadata audit, metadata plan, report UI
```

## Current Capabilities

### Observation Ledger

- Initializes and uses a local SQLite database.
- Scans supported audio extensions: `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`,
  `.ogg`, `.aiff`, and `.webm`.
- Uses `ffprobe` when available and records probe failures instead of stopping
  the run.
- Supports alternate database paths with `--db`.

### Identity And Classification

- Resolves probable artist, title, album, year, and mix from observed tags,
  filenames, folders, and artist seed matches.
- Deprioritizes tag artists that look like uploader, channel, or label metadata
  when stronger filename or folder seed evidence exists.
- Preserves conflicting, partial, and unknown identities for review.
- Classifies with deterministic rules from controlled artist seeds and embedded
  genre metadata.

### Intake And Placement

- Records purchase/intake gateway state for baseline artists using manually
  supplied metadata and proof paths.
- Copies unlocked local files into a controlled intake area.
- Plans deterministic organized paths shaped around genre, subgenre, artist,
  and filename evidence.
- Executes placement by copying planned files into a destination root.

### Reports And UI

- Placement review reports under `reports/scan_<SCAN_RUN_ID>/`.
- Duplicate reports under `reports/duplicates_scan_<SCAN_RUN_ID>/`.
- Duplicate review plans under
  `reports/duplicate_review_scan_<SCAN_RUN_ID>/`.
- Library QA reports under `reports/library_qa/`.
- Metadata audit reports under `reports/metadata_audit/`.
- Metadata normalization plans under `reports/metadata_plan/`.
- Read-only FastAPI routes for report and manual review screens.

### Duplicate Handling

- Exports duplicate candidates without modifying the library.
- Separates active live-library duplicate groups from historical duplicate
  records.
- Moves only `remove_candidate` rows from a duplicate review plan into
  quarantine.
- Supports dry-run quarantine and restore.

### Metadata Review

- Audits FLAC tags with `mutagen`.
- Checks for missing tags, malformed track numbers, trailing whitespace,
  duplicate whitespace, separator inconsistencies, probable source suffixes,
  capitalization inconsistencies, and artist/title variant groups.
- Generates a review plan for tag updates inferred from organized library paths.
- Does not write metadata tags.

## CLI Examples

Initialize the ledger:

```bash
python -m app.main init-db
```

Scan a local media folder:

```bash
python -m app.main scan --source ~/Music/Library_Intake
python -m app.main summary --scan-run-id 1
```

Resolve identity and classification:

```bash
python -m app.main identify --scan-run-id 1
python -m app.main classify --scan-run-id 1
```

Plan, review, and execute placement:

```bash
python -m app.main plan-placement --scan-run-id 1
python -m app.main review-report --scan-run-id 1 --out reports
python -m app.main execute-placement --scan-run-id 1 --dest ~/Music/Organised_Library
```

Generate duplicate reports and review plans:

```bash
python -m app.main duplicate-report \
  --scan-run-id 1 \
  --library-root ~/Music/Organised_Library \
  --out reports

python -m app.main duplicate-review --duplicate-report-id 1 --out reports
```

Quarantine duplicate remove candidates:

```bash
python -m app.main quarantine-duplicates \
  --review-plan-id 1 \
  --quarantine-root ~/Music/Quarantine_Duplicates \
  --dry-run

python -m app.main quarantine-duplicates \
  --review-plan-id 1 \
  --quarantine-root ~/Music/Quarantine_Duplicates
```

Restore a quarantine run:

```bash
python -m app.main restore-quarantine --quarantine-run-id 1 --dry-run
python -m app.main restore-quarantine --quarantine-run-id 1
```

Generate QA and metadata reports:

```bash
python -m app.main library-qa \
  --library-root ~/Music/Organised_Library \
  --quarantine-root ~/Music/Quarantine_Duplicates \
  --out reports

python -m app.main metadata-audit \
  --library-root ~/Music/Organised_Library \
  --out reports

python -m app.main metadata-plan \
  --library-root ~/Music/Organised_Library \
  --out reports
```

Run the report UI:

```bash
uvicorn app.main:app --reload
```

Available UI routes:

```text
/reports
/reports/artists
/reports/genres
/reports/quarantine
/reports/file-health
/reports/duplicates
/review
/review/quarantine
/review/conflicts
/review/blocked
```

Set `MUSIC_LIBRARY_REPORTS_DIR` before starting the server to read reports from
a directory other than `reports`.

Use a separate SQLite database:

```bash
python -m app.main --db /tmp/media_library.sqlite3 scan --source ~/Music/Library_Intake
```

## UI Screenshots

Screenshot placeholders are intentionally kept as documentation targets. The UI
reads generated report files and does not generate reports or mutate library
state.

![Reports dashboard placeholder](docs/screenshots/reports-dashboard.png)

![Duplicate report placeholder](docs/screenshots/duplicates.png)

![Manual review quarantine placeholder](docs/screenshots/manual-review-quarantine.png)

![File health placeholder](docs/screenshots/file-health.png)

## Example Outputs

Library QA snapshot:

```text
report_path=reports/library_qa
total_library_files=627
total_quarantine_files=52
genre_count=9
subgenre_count=22
artist_count=49
active_duplicate_group_count=0
historical_duplicate_group_count=46
quarantined_duplicate_file_count=52
missing_file_count=52
unresolved_missing_file_count=0
```

Duplicate report snapshot:

```text
report_path=reports/duplicates_scan_1
total_files_checked=627
exact_hash_groups=0
same_artist_title_groups=0
probable_variant_groups=0
```

Metadata audit snapshot:

```text
report_path=reports/metadata_audit
total_flac_files=627
readable_flac_files=627
unreadable_flac_files=0
missing_tag_count=1715
malformed_tag_count=682
inconsistent_artist_group_count=4
inconsistent_title_group_count=0
```

Metadata normalization plan snapshot:

```text
report_path=reports/metadata_plan
total_flac_files=627
readable_flac_files=627
unreadable_flac_files=0
proposed_update_count=2063
```

## Safety Model

The pipeline is designed around staged, inspectable operations:

- Scanning, identity resolution, classification, placement planning, duplicate
  reporting, duplicate review planning, library QA, metadata audit, metadata
  planning, and UI views are read-only with respect to media files.
- Placement execution copies files only from planned rows and never overwrites
  an existing destination.
- Duplicate quarantine moves only rows marked `remove_candidate` in a stored
  duplicate review plan.
- Quarantine and restore support dry-run mode.
- Restore skips missing quarantine files and existing restore targets.
- Path validation rejects absolute or traversing planned paths during
  placement execution.
- Metadata audit and metadata plans do not save tags or mutate audio.
- The UI reads generated reports only and does not execute cleanup actions.

## Audit And Restore Model

State-changing operations write ledger rows before and after execution so the
system can explain what happened:

- `placement_executions` and `placement_execution_files` record placement
  execution runs and per-file outcomes.
- `duplicate_reports` and `duplicate_candidates` preserve duplicate detection
  evidence.
- `duplicate_review_plans` and `duplicate_review_items` preserve keep/remove
  recommendations.
- `duplicate_quarantine_runs` and `duplicate_quarantine_items` record
  quarantine decisions, source paths, quarantine paths, and outcomes.
- `quarantine_restore_runs` and `quarantine_restore_items` record restore
  attempts and outcomes.

Restore is intentionally based on recorded quarantine items, not filesystem
guesswork. When the original library root is known, restore validates the
library boundary and avoids overwriting existing files.

## Testing Status

The repository has focused tests for scanner behavior, identity resolution,
classification, intake, placement planning/execution, reports, duplicate
review, quarantine, restore, metadata audit, metadata planning, report UI, and
manual review UI.

Documented baseline:

```text
pytest: 222 passed
```

Latest local verification:

```text
232 passed in 6.89s
```

Run tests:

```bash
python -m pytest
```

## Roadmap

Planned work should preserve the same safety posture: observe first, plan
second, mutate only through explicit and auditable commands.

- Add screenshot assets for the report and manual review UI placeholders.
- Expand report fixtures so documentation examples can be regenerated from a
  scripted demo dataset.
- Add explicit CLI documentation for each command's output contract.
- Add optional export bundles for sharing QA snapshots without exposing local
  absolute paths.
- Add review workflow affordances for metadata plan approval while keeping tag
  writing separate from audit and plan generation.
- Add more edge-case tests around malformed media files, interrupted
  quarantine runs, and restore boundary validation.
