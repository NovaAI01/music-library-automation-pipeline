# Music Library Intelligence Platform

## What it is

Music Library Intelligence Platform is a local-first metadata intelligence
system for understanding, normalizing, and safely reviewing user-owned or
legally sourced music libraries.

The platform organizes evidence around Artists -> Albums -> Tracks without
cloud accounts, AI/LLM enrichment, audio/media acquisition, or destructive
automation. It observes local files, records an evidence ledger, normalizes
metadata evidence, detects duplicate-like records, scores confidence, proposes
review-only remediation plans, keeps audit logs, and routes uncertain decisions
through human review boundaries. Metadata-only external validation remains
separate from the local canonical graph.

It is a metadata intelligence and remediation governance platform, not a
playback-first app, AI wrapper, downloader, automatic tag writer, or unattended
cleanup tool. Optional metadata-only acquisition commands exist for supported
sources, but they do not acquire audio or media, do not enrich the canonical
graph remotely, and do not mutate local library state.

## Problem

Personal music libraries accumulate inconsistent tags, duplicate files, partial
album folders, collaboration naming variants, remasters, compilations, and years
of uncertain manual cleanup history. Directly changing a large library is risky:
the wrong operation can overwrite curated files, remove the wrong copy, or leave
no audit trail.

This project separates observation, planning, review, execution boundaries,
quarantine, restore, and validation evidence so a reviewer can inspect the
reasoning before any local file operation is approved.

## What it does

- Builds a local ingestion and evidence ledger from file observations and
  metadata-only external records.
- Plans metadata normalization from deterministic local evidence without writing
  tags.
- Parses artist credits into primary, featured, collaboration, ambiguous, and
  unresolved evidence.
- Performs release-aware duplicate analysis so repeated release appearances are
  not treated as removable duplicates by default.
- Scores confidence for canonical entities, evidence reliability, album
  cohesion, and review candidates.
- Applies conflict governance to separate safe merge candidates, blocked merges,
  and deferred review items without executing merges.
- Provides review and audit workflows for duplicate, metadata, canonical graph,
  reliability, and conflict evidence.
- Benchmarks validation runs across public fixtures and metadata-only source
  samples.

## What it does not do

- It does not download, acquire, stream, or fingerprint audio as part of
  validation.
- It does not use AI, LLMs, embeddings, or remote enrichment to infer metadata.
- It does not automatically write tags, delete files, merge canonical entities,
  or remediate conflicts.
- It does not claim that every source is validated or that all metadata
  distributions generalize from the current evidence.
- It does not validate Discogs yet.
- It does not treat Internet Archive live validation as public evidence yet.
- It intentionally defers YouTube metadata validation until product-identity risk
  is reviewed.

## Validation evidence

| Evidence | What it proves | What it does not prove |
|---|---|---|
| Public fixture: 65 rows | A clean clone can run the metadata-only fixture workflow with fictional CSV records, accepted/rejected rows, artist-credit analysis, release-identity analysis, benchmark cohorts, and manifest boundaries. See [docs/public-fixture-validation.md](docs/public-fixture-validation.md). | It does not prove real-world source distribution coverage or local library remediation quality. |
| MusicBrainz 50k | A large canonical metadata sample can be converted and ingested as metadata-only evidence: 50,000 rows seen, 49,773 accepted after conversion, 0 ingestion rejects, and duplicate-like records explained through release identity analysis. See [MusicBrainz 50k result](docs/validation-results/musicbrainz-50k-consolidated-result.md). | It does not prove all MusicBrainz rows are correct, that all duplicates are solved, or that any merge/delete action is safe. |
| Jamendo 10k | A second live catalog metadata source can run through acquisition, ingestion, artist-credit analysis, release-identity analysis, and benchmarking with 10,000 fetched and 10,000 accepted records. See [Jamendo 10k result](docs/validation-results/jamendo-10k-validation.md). | It does not prove all Jamendo metadata, all catalog APIs, Discogs, Internet Archive live validation, or YouTube metadata behavior. |
| 594 tests | The deterministic pipeline has focused regression coverage across scanning, identity, classification, planning, reporting, duplicate review, quarantine, restore, metadata audit/planning, validation, and UI behavior. | It does not replace source-specific validation, full end-to-end review on a private library, or a fresh full-suite run by the reviewer. |

Validation boundaries documented in the public evidence include
`metadata_only=true`, `audio_downloaded=false`,
`local_library_mutated=false`, and `canonical_graph_mutated=false` where those
manifest fields apply. Public validation summaries are committed under
[docs/validation-results/](docs/validation-results/); generated `reports/`
artifacts are local runtime outputs and are ignored by git.

## Quick start

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the focused project test suite in your terminal:

```bash
python -m pytest -q
```

Build and run the local Docker runtime:

```bash
docker build -t music-library-intelligence:local .
docker run --rm -p 8000:8000 music-library-intelligence:local
```

Or use Docker Compose:

```bash
docker compose up --build
```

The container runs the existing FastAPI app with Uvicorn on port `8000` and binds local `reports/` and `data/` directories when using Compose. No secrets, external services, audio downloads, or media mutation are required.

Run the public validation path from
[docs/public-fixture-validation.md](docs/public-fixture-validation.md). It is a
metadata-only fixture workflow: no audio, no private data, no external API
credentials, no media downloads, no local library mutation, and no canonical
graph mutation.

Generated reports and local data are ignored by git. Large metadata dumps and
working data should live outside the repository by setting
`MUSIC_INTELLIGENCE_DATA_ROOT`; see
[docs/external-data-root.md](docs/external-data-root.md).

## Public fixture workflow

The public fixture is the reviewer-friendly validation path:
[docs/public-fixture-validation.md](docs/public-fixture-validation.md).

It runs four metadata-only commands against
`examples/fixture_library/external_metadata_fixture.csv`:

- import external metadata
- analyze artist credits
- analyze release identity
- benchmark validation

Expected evidence includes accepted and rejected import rows, artist-credit
analysis usage, release-identity analysis usage, safe merge candidates, deferred
duplicate/version/collaboration cohorts, blocked unresolved/source-artifact
cohorts, and a manifest with metadata-only safety boundaries.

## Architecture summary

```text
Local files and metadata-only source records
  -> scanner / external ingestion
  -> SQLite observation and evidence ledger
  -> identity, classification, artist-credit, release-identity, and reliability analysis
  -> placement, metadata, duplicate, conflict, and benchmark reports
  -> human review and audit ledgers
  -> optional narrow execution paths with dry-run, quarantine, and restore safeguards
  -> local FastAPI/Jinja2 review UI over generated reports
```

Most commands inspect data and write reports or ledger records. Commands that
can affect files are intentionally narrow, support review or dry-run boundaries
where appropriate, and preserve recovery information. Detailed architecture is
in [docs/architecture.md](docs/architecture.md) and
[docs/operational-workflow.md](docs/operational-workflow.md).

## Documentation map

Core workflow:

- [Architecture](docs/architecture.md)
- [Operational workflow](docs/operational-workflow.md)
- [Metadata suggestion workflow](docs/metadata-suggestion-workflow.md)
- [External metadata ingestion](docs/external-metadata-ingestion.md)
- [Validation benchmarking](docs/validation-benchmarking.md)
- [Public fixture validation](docs/public-fixture-validation.md)

Analysis and governance:

- [Artist-credit parsing](docs/artist-credit-parsing.md)
- [Release identity analysis](docs/release-identity-analysis.md)
- [Conflict governance](docs/conflict-governance.md)
- [Evidence reliability](docs/evidence-reliability.md)
- [Canonical confidence](docs/canonical-confidence.md)
- [Canonical entity graph](docs/canonical-entity-graph.md)
- [Entity boundaries](docs/entity-boundaries.md)
- [Entity roles](docs/entity-roles.md)
- [Normalization knowledge](docs/normalization-knowledge.md)

Source and validation evidence:

- [Cross-source validation summary](docs/validation-results/cross-source-validation-summary.md)
- [MusicBrainz conversion](docs/musicbrainz-conversion.md)
- [MusicBrainz 50k result](docs/validation-results/musicbrainz-50k-consolidated-result.md)
- [Jamendo metadata](docs/jamendo-metadata.md)
- [Jamendo 10k result](docs/validation-results/jamendo-10k-validation.md)
- [Internet Archive metadata](docs/internet-archive-metadata.md)
- [Large-scale evidence validation](docs/large-scale-evidence-validation.md)
- [Validation results directory](docs/validation-results/)
- [Sample outputs](docs/sample-outputs/)

Portfolio review:

- [Project brief](docs/portfolio/project-brief.md)
- [Interview brief](docs/portfolio/interview-brief.md)
- [CV bullets](docs/portfolio/cv-bullets.md)

Commercial notes:

- [Catalog audit offer](docs/commercial/catalog-audit-offer.md)
- [Outreach messages](docs/commercial/outreach-messages.md)

## Repository structure

```text
app/
  main.py                 CLI entry point and local UI app
  scanner.py              Local media observation
  identity_engine.py      Deterministic identity resolution
  external_metadata.py    Metadata-only external ingestion contract
  artist_credit_parser.py Artist-credit analysis
  release_identity_analysis.py
                           Release-aware duplicate-like evidence analysis
  validation_benchmark.py Validation cohort reporting
  conflict_governance.py  Review-only conflict classification
  duplicate_*.py          Duplicate reporting, review, quarantine, restore
  metadata_*.py           Metadata audit, planning, suggestions, review UI
  canonical_*.py          Canonical entity reports and confidence scoring
  library_app_ui.py       Local review UI routes

tests/
  test_*.py               Focused pytest coverage for pipeline behavior

docs/
  validation-results/     Committed summarized validation evidence
  sample-outputs/         Sanitized report excerpts
  portfolio/              Public review and interview summaries

examples/
  fixture_library/        Public metadata-only validation fixture
```

Ignored runtime outputs include generated `reports/`, local data roots, demo
exports, SQLite databases, caches, credentials, and large metadata dumps.

## License

MIT License. See [LICENSE](LICENSE).
