# Architecture

Music Library Intelligence Platform is a local-first architecture for
user-owned or legally sourced music libraries. It records local evidence,
normalizes metadata, detects duplicates, scores confidence, proposes
reviewable remediation, and preserves audit history before any controlled file
operation runs.

v1 has no network or AI behavior. External metadata ingestion and validation
are metadata-only workflows over local CSV/JSONL fixtures; they do not mutate
the local canonical graph.

## Local-First Flow

```text
Local audio files
  ->
Scanner
  ->
SQLite observation ledger
  ->
Identity + classification
  ->
Placement and metadata plans
  ->
Duplicate, QA, reliability, and canonical reports
  ->
Conflict governance and confidence scoring
  ->
Human review
  ->
Optional controlled execution, quarantine, or restore
  ->
Audit logs and read-only UI
```

## Core Components

- Local filesystem ingestion scans media folders and records observations
  without modifying source files.
- Metadata parsing reads available tags and probe results so downstream steps
  work from persisted evidence.
- Identity resolution infers probable artist, title, album, year, and mix from
  tags, filenames, parent folders, and controlled local seed data.
- Classification applies deterministic artist, genre, and subgenre rules.
- Placement planning creates reviewable destination paths before copy
  execution.
- Duplicate detection reports exact hash, same artist/title, and probable
  variant groups.
- Metadata audit and normalization planning produce review-only tag evidence.
- Metadata suggestions turn audit and plan rows into evidence-based
  remediation proposals with deterministic confidence and rationale.
- Evidence reliability and canonical confidence reports score local evidence
  before it is used for graph or review decisions.
- Canonical entity graph generation persists artist, album, track, version,
  and relationship hypotheses without auto-merging unresolved conflicts.
- Conflict governance classifies unresolved graph conflicts into blocked,
  safe-to-review, deferred, or needs-review buckets without changing graph
  behavior.
- Review decision and normalization knowledge ledgers preserve human decisions
  for future deterministic scoring.
- Quarantine and restore provide ledger-backed duplicate remediation and
  recovery when explicitly executed.
- FastAPI/Jinja2 UI serves read-only dashboards, library browsing, review
  queues, and local playback over generated reports.

## Product Boundaries

- Not a downloader.
- Not a substitute for streaming services.
- Not an AI wrapper.
- Not an automatic tag writer.
- No network or AI behavior in v1.
- No autonomous mutation of media tags, files, or canonical graph state.
- External metadata validation stays separate from local graph mutation.

## Safety Boundaries

- Planning is separated from execution. Audit, duplicate, metadata, canonical,
  and placement commands produce evidence and plans before file-moving commands
  run.
- Quarantine is used instead of deletion for duplicate remediation.
- Restore support is ledger-backed and uses recorded paths.
- Dry-run support is available for quarantine and restore workflows.
- Human review checkpoints are explicit for duplicate, metadata, conflict, and
  canonical-confidence workflows.
- Outputs are deterministic and based on local files, local rules, SQLite
  records, and generated report artifacts.

## Current Consolidation Boundary

The CLI entry point (`app/main.py`) and the unified UI route module
(`app/library_app_ui.py`) remain intact to avoid churn across existing commands
and FastAPI routes. Portfolio-only screenshot and demo generation code lives in
`tools/portfolio_demo/` and is exposed through existing compatibility commands.
