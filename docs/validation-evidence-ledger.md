# Validation Evidence Ledger

This ledger records what each validation pass checks, what a passing signal
looks like, and what remains manual. It separates collection evidence from
execution evidence and does not claim CI, Docker, or smoke coverage unless that
workflow has actually run.

Operational command usage, troubleshooting, and cleanup guidance are documented
in the [operational runbook](operational-runbook.md).

## `python -m app.main run-public-fixture-validation`

Status in this Codex session: covered by focused pytest run.

What it checks:

- the public fictional CSV fixture can be imported as external metadata
- artist-credit analysis runs against the imported `local_fixture` records
- release-identity analysis runs against the same metadata-only records
- validation benchmarking uses the artist-credit and release-identity outputs
- the labeled run writes reports under
  `reports/runs/local_fixture/public_fixture/`

Why it passes / expected pass signal:

- command exits with status 0
- output ends with `reports/runs/local_fixture/public_fixture/` for the default
  report root
- the run manifest, ingestion summary, artist-credit summary, release-identity
  summary, and benchmark summary exist
- the manifest records `metadata_only=true`, `audio_downloaded=false`,
  `local_library_mutated=false`, and `canonical_graph_mutated=false`

What it proves:

- a clean metadata-only public fixture workflow can run end to end without
  external credentials or network access
- accepted and rejected rows, artist-credit cohorts, release-aware identity
  cohorts, and benchmark governance buckets are produced from public fixture
  metadata
- the workflow preserves the documented no-audio, no-private-library,
  no-local-media-mutation, and no-canonical-graph-mutation boundaries

What it does not prove:

- real-world source distribution coverage
- correctness for a private music library
- that any canonical merge, delete, tag write, or remediation action is safe
- live external service behavior
- Docker or GitHub Actions behavior

Boundary notes:

- the command calls the same local metadata-only functions as the documented
  four-command public fixture path
- it does not download audio, read private library paths, mutate media files, or
  mutate canonical graph state

## `python -m pytest --collect-only -q`

Status in this Codex session: run.

What it checks:

- pytest can import and collect the repository test suite
- tests under `tests/` and `tools/portfolio_demo/tests/` are visible to the
  configured pytest discovery
- parametrized cases expand into individual nodeids

Why it passes / expected pass signal:

- command exits with status 0
- output ends with `632 tests collected`

What it proves:

- the current test suite is discoverable
- the 632 count is a collection count derived from pytest nodeids

What it does not prove:

- test assertions pass
- Docker builds
- the smoke script runs
- GitHub Actions passes

Boundary notes:

- collection-only imports tests but does not execute test bodies
- no audio downloads, local media mutation, or canonical graph mutation are
  expected from collection-only

## `python -m app.main source-quality-report`

Status in this Codex session: covered by focused pytest run with synthetic
temporary report inputs.

What it checks:

- existing labeled validation run directories can be discovered under
  `reports/runs/<source>/<run_label>/`
- available ingestion, artist-credit, release-identity, benchmark, and manifest
  summary files are read into one source quality comparison
- missing optional summary files do not crash report generation
- source quality JSON and CSV outputs are written under `reports/source_quality/`
- manifest boundary fields are preserved in the per-source CSV rows

Why it passes / expected pass signal:

- command exits with status 0
- `reports/source_quality/source_quality_summary.json` exists
- `reports/source_quality/source_quality_by_source.csv` exists
- summary JSON records source run count, included sources, aggregate totals, and
  the output CSV path
- CSV contains one row per discovered source/run label

What it proves:

- existing validation evidence can be compared across available sources without
  rerunning source acquisition or validation
- missing optional source reports are tolerated as zero/blank fields rather than
  fatal errors
- source report inputs are treated as read-only

What it does not prove:

- the underlying source validations are correct or complete
- live source availability
- source quality for runs that have not been generated
- any canonical merge, tag write, audio download, or local library remediation
  is safe

Boundary notes:

- the command reads generated report summary JSON files only
- it does not read audio/media files
- it does not mutate source reports, local library files, or the canonical graph

## Internet Archive 100 live metadata validation

Status in this Codex session: superseded by Internet Archive 1k as stronger
evidence. This historical smoke evidence was documented from user-terminal
evidence produced outside CI. The live command was not run in Codex.

What it checks:

- Internet Archive metadata-only acquisition for `collection:opensource_audio`
  at 100-record smoke scale
- import of the acquired `internet_archive` CSV as external metadata
- artist-credit analysis against the imported records
- release-identity analysis against the same metadata-only records
- integrated benchmark reporting under run label `internet_archive_100`

Why it passes / expected pass signal:

- acquisition reports `fetched_records=100`, `accepted_records=100`, and
  `rejected_records=0`
- import reports `input_records=100`, `accepted_records=100`, and
  `rejected_records=0`
- benchmark reports `total_records=100`, `total_cohorts=5`,
  `total_conflicts=5`, `safe_merge_candidates=0`, `blocked_merges=3`, and
  `deferred_conflicts=2`
- artist-credit and release-identity analysis are both used by the benchmark
- manifest boundaries record `metadata_only=true`, `audio_downloaded=false`,
  `local_library_mutated=false`, and `canonical_graph_mutated=false`

What it proves:

- the previous Internet Archive live retry blocker is resolved at smoke scale
- a live Internet Archive metadata search can produce 100 accepted
  metadata-only records without rejects
- the Internet Archive sample can run through import, artist-credit analysis,
  release-identity analysis, and benchmark reporting
- the selected query broadens real source coverage while exposing weak artist
  completeness: 87 records missing artist evidence and 89 unresolved artist
  credits

What it does not prove:

- that CI runs Internet Archive live validation
- all Internet Archive metadata distributions work
- larger Internet Archive paging stability
- stronger artist completeness for other Internet Archive queries
- any canonical merge, tag write, audio download, or local library remediation
  is safe

Boundary notes:

- acquisition was metadata-only with `audio_download_allowed=false`
- no audio was downloaded
- the local library was not mutated
- the canonical graph was not mutated
- manual evidence was produced outside CI and should not be described as a CI
  validation gate

## Internet Archive 1k live metadata validation

Status in this Codex session: superseded by Internet Archive 10k as stronger
evidence. This historical early-scale evidence was documented from
user-terminal evidence produced outside CI. The live command was not run in
Codex, and CI does not run Internet Archive live validation.

What it checks:

- Internet Archive metadata-only acquisition for `collection:opensource_audio`
  at 1,000-record smoke/early scale
- import of the acquired `internet_archive` CSV as external metadata
- artist-credit analysis against the imported records
- release-identity analysis against the same metadata-only records
- integrated benchmark reporting under run label `internet_archive_1k`

Why it passes / expected pass signal:

- acquisition reports `fetched_records=1000`, `accepted_records=1000`, and
  `rejected_records=0`
- import reports `input_records=1000`, `accepted_records=1000`, and
  `rejected_records=0`
- artist-credit analysis reports `parsed_records=228` and
  `unresolved_count=772`
- release-identity analysis reports `total_identity_groups=906`,
  `possible_true_duplicate_count=89`, and
  `duplicate_external_records_unresolved=6`
- benchmark reports `total_records=1000`, `total_cohorts=23`,
  `total_conflicts=23`, `safe_merge_candidates=1`, `blocked_merges=15`,
  `deferred_conflicts=7`, and `source_artifact_candidates=5`
- artist-credit and release-identity analysis are both used by the benchmark
- manifest boundaries record `metadata_only=true`, `audio_downloaded=false`,
  `local_library_mutated=false`, and `canonical_graph_mutated=false`

What it proves:

- the Internet Archive live metadata path can fetch and normalize a
  1,000-record sample without rejects for the selected query
- the Internet Archive sample can run through import, artist-credit analysis,
  release-identity analysis, and benchmark reporting
- the benchmark exposes weak artist completeness and fault evidence, including
  763 missing artists, 772 unresolved artist credits, 89 possible true
  duplicate groups, and 5 source artifact candidates
- the selected query broadens real source coverage while preserving
  metadata-only and no-mutation boundaries

What it does not prove:

- that CI runs Internet Archive live validation
- all Internet Archive metadata distributions work
- broader Internet Archive behavior beyond this 1,000-record sample and query
- stronger artist completeness for other Internet Archive queries
- any canonical merge, tag write, audio download, or local library remediation
  is safe

Boundary notes:

- acquisition was metadata-only with `audio_download_allowed=false`
- no audio was downloaded
- the local library was not mutated
- the canonical graph was not mutated
- manual evidence was produced outside CI and should not be described as a CI
  validation gate

## Internet Archive 10k live metadata validation

Status in this Codex session: documented from user-terminal evidence produced
outside CI. The live command was not run in Codex, and CI does not run
Internet Archive live validation.

What it checks:

- Internet Archive metadata-only acquisition for `collection:opensource_audio`
  at 10,000-record scale
- import of the acquired `internet_archive` CSV as external metadata
- artist-credit analysis against the imported records
- release-identity analysis against the same metadata-only records
- integrated benchmark reporting under run label `internet_archive_10k`
- source quality report inclusion for the `internet_archive_10k` row

Why it passes / expected pass signal:

- acquisition reports `fetched_records=10000`, `accepted_records=10000`, and
  `rejected_records=0`
- import reports `input_records=10000`, `accepted_records=10000`, and
  `rejected_records=0`
- artist-credit analysis reports `parsed_records=1925` and
  `unresolved_count=8075`
- release-identity analysis reports `total_identity_groups=7429`,
  `possible_true_duplicate_count=1977`, and
  `duplicate_external_records_unresolved=114`
- benchmark reports `total_records=10000`, `total_cohorts=134`,
  `total_conflicts=134`, `safe_merge_candidates=25`,
  `blocked_merges=100`, `deferred_conflicts=9`, and
  `source_artifact_candidates=38`
- artist-credit and release-identity analysis are both used by the benchmark
- source quality report includes
  `internet_archive,internet_archive_10k,10000,10000,0,8008,0,0,1925,8075,7429,1977,4457,38,134,134,25,100,9,true,false,false,false`
- manifest boundaries record `metadata_only=true`, `audio_downloaded=false`,
  `local_library_mutated=false`, and `canonical_graph_mutated=false`

What it proves:

- the Internet Archive live metadata path can fetch and normalize a
  10,000-record sample without rejects for the selected query
- the Internet Archive sample can run through import, artist-credit analysis,
  release-identity analysis, benchmark reporting, and source-quality report
  inclusion
- the benchmark exposes weak artist completeness and fault evidence, including
  8,008 missing artists, 8,075 unresolved artist credits, 1,977 possible true
  duplicate groups, and 38 source artifact candidates
- the selected query broadens real source coverage while preserving
  metadata-only and no-mutation boundaries

What it does not prove:

- that CI runs Internet Archive live validation
- all Internet Archive metadata distributions work
- broader Internet Archive behavior beyond this 10,000-record sample and query
- stronger artist completeness for other Internet Archive queries
- any canonical merge, tag write, audio download, or local library remediation
  is safe

Boundary notes:

- acquisition was metadata-only with `audio_download_allowed=false`
- no audio was downloaded
- the local library was not mutated
- the canonical graph was not mutated
- manual evidence was produced outside CI and should not be described as a CI
  validation gate

## `python -m pytest -q`

Status in this Codex session: manual verification required before commit.

What it checks:

- all collected test bodies execute
- assertions across scanner, intake, identity, classification, placement,
  duplicate review, quarantine, restore, metadata, validation, canonical graph,
  UI, and portfolio demo tooling pass

Why it passes / expected pass signal:

- command exits with status 0
- terminal reports all collected tests passing, currently expected as 632 tests

What it proves:

- the regression suite passes in the user terminal environment
- the assertions described in the [test coverage map](test-coverage-map.md)
  hold for the current branch

What it does not prove:

- exhaustive correctness for all music libraries or sources
- Docker image build/runtime behavior
- live external service availability
- approved remediation execution on private data

Boundary notes:

- the suite uses temporary fixtures and mocked network paths where documented
- public validation paths preserve metadata-only, no audio downloads, no local
  media mutation, and no canonical graph mutation boundaries

## `docker build -t music-library-intelligence:local .`

Status in this Codex session: manual verification required before commit.

What it checks:

- the Docker build context is sufficient after `.dockerignore` filtering
- the Dockerfile can install dependencies and package the local FastAPI runtime

Why it passes / expected pass signal:

- Docker exits with status 0
- image `music-library-intelligence:local` is created locally

What it proves:

- the runtime image can be built on the verifying machine
- ignored local files such as caches, credentials, SQLite DBs, reports, and data
  are not required in the build context

What it does not prove:

- the container starts successfully
- `/health` responds
- Compose works
- CI verifies Docker

Boundary notes:

- no audio downloads or external metadata service calls are expected from image
  build
- Docker was not run in this Codex session

## `./scripts/smoke_container.sh`

Status in this Codex session: manual verification required before commit.

What it checks:

- local image build and container startup through the smoke script
- Docker health state becomes `healthy`
- `/health` responds from the running container
- temporary container cleanup happens on exit

Why it passes / expected pass signal:

- script exits with status 0
- output shows the image/container evidence and a successful health response

What it proves:

- the local container runtime can start and expose the health endpoint on the
  verifying machine

What it does not prove:

- full application correctness
- Compose behavior
- GitHub Actions behavior
- private library workflows

Boundary notes:

- the smoke script is runtime verification, not a metadata validation pass
- no audio downloads, local media mutation, or canonical graph mutation are
  expected
- the script was not run in this Codex session

## GitHub Actions CI on `pull_request`

Status in this Codex session: manual verification required before commit.

What it checks:

- the configured GitHub Actions workflow for pull requests
- dependency installation
- pytest suite execution with `python -m pytest -q`
- public fixture validation with
  `python -m app.main run-public-fixture-validation`
- generated public fixture reports under
  `reports/runs/local_fixture/public_fixture/`
- the public fixture manifest records metadata-only/no-audio/no-local-mutation/
  no-canonical-graph-mutation boundaries
- Docker image build through `scripts/smoke_container.sh`
- container boot
- Docker health status
- `/health` response
- temporary container cleanup

Why it passes / expected pass signal:

- the pull request check run completes successfully in GitHub Actions

What it proves:

- the pull request passes dependency installation, the pytest suite, the
  public fixture validation command, and the container smoke checks currently
  configured in CI
- the public fixture reports can be generated in GitHub Actions from local
  metadata-only fixture data

What it does not prove:

- local private-library workflows
- private library validation
- validation of all external metadata sources
- live source validation
- live external service availability

Boundary notes:

- the public fixture validation step is metadata-only and local
- CI does not download audio, mutate local media, perform unattended
  remediation, or mutate the canonical graph
- CI verifies the container runtime only through `scripts/smoke_container.sh`
- GitHub Actions was not queried or run in this Codex session

## GitHub Actions CI on `master` push

Status in this Codex session: manual verification required before commit.

What it checks:

- the configured GitHub Actions workflow when changes reach `master`
- dependency installation
- pytest suite execution with `python -m pytest -q`
- public fixture validation with
  `python -m app.main run-public-fixture-validation`
- generated public fixture reports under
  `reports/runs/local_fixture/public_fixture/`
- the public fixture manifest records metadata-only/no-audio/no-local-mutation/
  no-canonical-graph-mutation boundaries
- Docker image build through `scripts/smoke_container.sh`
- container boot
- Docker health status
- `/health` response
- temporary container cleanup

Why it passes / expected pass signal:

- the `master` push workflow completes successfully in GitHub Actions

What it proves:

- the default branch passes dependency installation, the pytest suite, the
  public fixture validation command, and the container smoke checks currently
  configured in CI after merge or push
- the public fixture reports can be generated in GitHub Actions from local
  metadata-only fixture data

What it does not prove:

- private library validation
- private library remediation correctness
- validation of all external metadata sources
- live external API behavior
- live external service availability

Boundary notes:

- this is post-merge/push evidence, not a substitute for local focused
  verification before commit
- the public fixture validation step is metadata-only and local
- CI does not download audio, mutate local media, perform unattended
  remediation, or mutate the canonical graph
- this Codex session did not run or inspect a GitHub Actions execution
