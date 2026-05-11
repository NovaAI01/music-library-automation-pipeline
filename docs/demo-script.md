# Demo Script

## Introduction

This is the Media Library Automation Pipeline, a local-first operational
workflow for maintaining a FLAC media library. The system focuses on evidence:
it scans local files, records observations, generates reports, plans changes,
and keeps file-changing operations behind review checkpoints.

## Ingestion / Audit

The workflow starts with local filesystem ingestion. Files are scanned into a
SQLite observation ledger, then metadata audit commands inspect the organized
library without writing tag changes. The current audit evidence shows 627
readable FLAC files and report outputs for missing, malformed, and inconsistent
metadata.

## Duplicate Detection

Duplicate detection is handled as a read-only reporting stage. The duplicate
report checks organized files for exact hash groups, same artist/title groups,
and probable variants. Current generated evidence shows 627 files checked and 0
active duplicate groups.

## Review Planning

Duplicate review planning converts report evidence into keep, remove-candidate,
and manual-review rows. This creates a concrete approval checkpoint before any
file movement happens.

## Quarantine Workflow

Approved remove candidates can be moved into quarantine rather than deleted.
The quarantine command supports dry-run review, and the restore workflow can
recover files from recorded quarantine ledger entries.

## Metadata Normalization Planning

Metadata normalization is also staged. The system generates proposed tag updates
from existing metadata and organized library paths. The current plan contains
2063 proposed updates, but the workflow remains review-oriented and does not
automatically write tags.

## Reporting UI

The reporting UI provides read-only views for library QA, artists, genres,
quarantine state, duplicate reports, and manual review queues. It presents
generated evidence without mutating media files.

## Operational Safety Model

The safety model is straightforward: deterministic CLI execution, audit-first
outputs, dry-run support, quarantine instead of deletion, restore capability,
and human approval boundaries before remediation.

## Closing Summary

The result is an operational workflow system for media library maintenance:
local evidence collection, duplicate remediation planning, metadata
normalization support, reporting, and recoverable cleanup steps without
autonomous or destructive behavior.
