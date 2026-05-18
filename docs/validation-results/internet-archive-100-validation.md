# Internet Archive 100 Metadata Validation Smoke

## Source And Boundary

- Source: Internet Archive advanced search metadata
- Query: `collection:opensource_audio`
- Scale: 100 records
- Metadata only: true
- Audio downloaded: no
- Audio download allowed: false
- Local library mutated: no
- Canonical graph mutated: no
- Run label: `internet_archive_100`
- Evidence source: manual user-terminal run outside CI

This smoke result records user-terminal evidence for a metadata-only Internet
Archive validation run. It did not download audio, stream tracks, mutate local
library state, write tags, or write to the canonical graph.

This resolves the previous "blocked pending live retry" status at smoke scale
only. It does not prove broad Internet Archive behavior beyond this 100-record
sample and query.

Supersession note: this remains historical smoke evidence, but it has been
superseded by the Internet Archive 1k metadata-only validation as stronger
evidence for the same query and boundary guarantees.

## Command Sequence

Acquisition:

```bash
python -m app.main fetch-internet-archive-metadata \
  --query "collection:opensource_audio" \
  --limit 100 \
  --out reports \
  --source internet_archive \
  --page-size 100 \
  --timeout 30
```

Downstream validation sequence for the recorded run label:

```bash
python -m app.main import-external-metadata \
  --source internet_archive \
  --input /media/jack/MUSIC_INTEL/MusicIntelligenceData/external_metadata/internet_archive/raw_internet_archive.csv \
  --out reports \
  --run-label internet_archive_100

python -m app.main analyze-artist-credits \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_100

python -m app.main analyze-release-identity \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_100

python -m app.main benchmark-validation \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_100
```

## Acquisition Result

| Metric | Value |
|---|---:|
| `fetched_records` | 100 |
| `accepted_records` | 100 |
| `rejected_records` | 0 |
| `metadata_only` | `true` |
| `audio_download_allowed` | `false` |

Output files:

```text
/media/jack/MUSIC_INTEL/MusicIntelligenceData/external_metadata/internet_archive/raw_internet_archive.csv
/media/jack/MUSIC_INTEL/MusicIntelligenceData/external_metadata/internet_archive/raw_internet_archive.jsonl
```

## Import Result

| Metric | Value |
|---|---:|
| `input_records` | 100 |
| `accepted_records` | 100 |
| `rejected_records` | 0 |
| `missing_artist_count` | 87 |
| `missing_album_count` | 0 |
| `missing_title_count` | 0 |

## Artist Credit And Release Identity Result

| Metric | Value |
|---|---:|
| `parsed_records` | 11 |
| `unresolved_count` | 89 |
| `total_identity_groups` | 100 |
| `possible_true_duplicate_count` | 0 |

## Benchmark Result

| Metric | Value |
|---|---:|
| `total_records` | 100 |
| `total_cohorts` | 5 |
| `total_conflicts` | 5 |
| `safe_merge_candidates` | 0 |
| `blocked_merges` | 3 |
| `deferred_conflicts` | 2 |
| `artist_credit_analysis_used` | `true` |
| `release_identity_analysis_used` | `true` |

## Top Cohorts

| Cohort | Count | Dataset % | Severity |
|---|---:|---:|---|
| `artist_credit_unresolved` | 89 | 89.00% | high |
| `missing_artist` | 87 | 87.00% | low |
| `possible_track_as_artist` | 1 | 1.00% | high |
| `possible_track_as_artist` | 1 | 1.00% | high |
| `artist_credit_parsed_high_confidence` | 1 | 1.00% | low |

## Boundary Guarantees

| Boundary | Value |
|---|---|
| `metadata_only` | `true` |
| `audio_downloaded` | `false` |
| `local_library_mutated` | `false` |
| `canonical_graph_mutated` | `false` |

## Key Finding

The Internet Archive sample broadens real source coverage but has weak artist
completeness for this query. The 100 fetched records were all accepted, but 87
records were missing artist evidence and 89 artist credits remained unresolved.

## Mapping Audit Note

The missing artist count is mostly true absence of `creator` in this 100-record
sample, not an ignored safe structured artist field. `creator` is already
mapped to artist when present. Rows without `creator` did not expose another
approved source-level artist field: `collection` is source/category evidence,
`subject` is tag/topic evidence, title parsing is not source-level artist
mapping, and uploader-like fields are not approved artist identity evidence.

No fallback artist mapping was added because using those weaker fields would
pollute identity evidence and make missing artist metrics look better without
making the records safer.

## What This Proves

- The Internet Archive metadata-only acquisition path can fetch and normalize a
  100-record live sample for `collection:opensource_audio`.
- The imported Internet Archive sample can run through ingestion,
  artist-credit analysis, release-identity analysis, and integrated benchmark
  reporting.
- The run preserved the metadata-only, no-audio, no-local-library-mutation, and
  no-canonical-graph-mutation boundaries.
- The previous Internet Archive live retry blocker is resolved for smoke-scale
  evidence.

## What This Does Not Prove

- It does not prove CI runs Internet Archive live validation.
- It does not prove all Internet Archive metadata distributions.
- It does not prove larger Internet Archive paging stability.
- It does not prove stronger artist completeness for other Internet Archive
  queries.
- It does not authorize canonical merges, tag writes, media downloads, or local
  library remediation.
- It does not prove Discogs, YouTube metadata, or all live catalog API behavior.
