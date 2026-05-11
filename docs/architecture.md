# Architecture

Media Library Automation Pipeline is a local-first operational workflow for
media ingestion, auditing, duplicate remediation, metadata normalization
planning, and reporting. It uses deterministic rules, local filesystem state,
generated report files, and a local SQLite ledger. AI usage is positioned as
assisted analysis and workflow augmentation around the evidence the system
already produces, not as autonomous execution.

## Local-First Flow

```text
FLAC Files
  ->
Scanner
  ->
Metadata Parser
  ->
Identity Resolution
  ->
Classification
  ->
Placement Planning
  ->
Audit + Duplicate Reports
  ->
Duplicate Review Planning
  ->
Human Approval
  ->
Quarantine / Restore
  ->
Reports + UI
```

## Components

- Local filesystem ingestion: scans local media folders and records observed
  files without modifying the source tree.
- Metadata parsing: reads available tags and probe results so downstream steps
  can work from recorded evidence.
- Identity resolution: infers probable artist, title, album, year, and mix from
  tags, filenames, parent folders, and controlled local seed data.
- Classification: applies deterministic artist, genre, and subgenre rules to
  organize review and reporting output.
- Placement planning: creates reviewable destination paths before files are
  copied into the organized library.
- Duplicate detection: reports exact hash, same artist/title, and probable
  variant groups from organized files.
- Duplicate review planning: converts duplicate evidence into keep,
  remove-candidate, and manual-review rows.
- Quarantine execution: moves only approved remove-candidate rows into a
  quarantine folder and records the operation.
- Restore workflow: restores quarantined files from ledger records and supports
  dry-run review.
- Metadata audit: inspects FLAC tag quality without writing metadata changes.
- Metadata normalization planning: proposes tag updates for human review.
- Reporting UI: serves read-only FastAPI/Jinja2 report screens over generated
  report artifacts.

## Safety Boundaries

- Planning is separated from execution. Audit, duplicate, metadata, and
  placement commands produce evidence and plans before file-moving commands run.
- Quarantine is used instead of deletion. Duplicate remediation moves files into
  a recoverable quarantine location.
- Restore support is ledger-backed. Restore operations use recorded source and
  quarantine paths rather than guessing from the filesystem.
- Dry-run support is available for quarantine and restore workflows.
- Review checkpoints are explicit. Duplicate review plans and metadata update
  plans are intended for human review before any remediation.
- Outputs are deterministic. The workflow is based on local files, local rules,
  local database records, and generated report files.

## Operational Boundary

The repository does not implement a downloader, autonomous agent system,
distributed architecture, cloud workflow, or automatic metadata write engine.
AI-assisted work should be limited to interpreting reports, planning remediation,
supporting metadata normalization decisions, assisting duplicate resolution, and
augmenting the human review workflow.
