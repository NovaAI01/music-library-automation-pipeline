# Internet Archive 1k Metadata Validation

## Source And Boundary

- Source: Internet Archive advanced search metadata
- Query: `collection:opensource_audio`
- Scale: 1,000 records
- Metadata only: true
- Audio downloaded: no
- Audio download allowed: false
- Local library mutated: no
- Canonical graph mutated: no
- Run label: `internet_archive_1k`
- Evidence source: manual user-terminal run outside CI

This result records user-terminal evidence for a metadata-only Internet Archive
validation run. It did not download audio, stream tracks, mutate local library
state, write tags, or write to the canonical graph.

This supersedes the Internet Archive 100-record smoke result as the stronger
current Internet Archive evidence gate, while preserving the same metadata-only
and no-mutation boundaries.

## Command Sequence

Acquisition:

```bash
python -m app.main fetch-internet-archive-metadata \
  --query "collection:opensource_audio" \
  --limit 1000 \
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
  --run-label internet_archive_1k

python -m app.main analyze-artist-credits \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_1k

python -m app.main analyze-release-identity \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_1k

python -m app.main benchmark-validation \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_1k
```

## Acquisition Result

| Metric | Value |
|---|---:|
| `fetched_records` | 1,000 |
| `accepted_records` | 1,000 |
| `rejected_records` | 0 |
| `metadata_only` | `true` |
| `audio_download_allowed` | `false` |
| `duration_seconds` | 7.990053 |

Output files:

```text
/media/jack/MUSIC_INTEL/MusicIntelligenceData/external_metadata/internet_archive/raw_internet_archive.csv
/media/jack/MUSIC_INTEL/MusicIntelligenceData/external_metadata/internet_archive/raw_internet_archive.jsonl
```

## Import Result

| Metric | Value |
|---|---:|
| `input_records` | 1,000 |
| `accepted_records` | 1,000 |
| `rejected_records` | 0 |
| `generated_id_count` | 0 |
| `missing_artist_count` | 763 |
| `missing_album_count` | 0 |
| `missing_title_count` | 0 |

## Artist Credit Result

| Metric | Value |
|---|---:|
| `total_records` | 1,000 |
| `parsed_records` | 228 |
| `unresolved_count` | 772 |
| `collaboration_count` | 15 |
| `featured_artist_count` | 0 |
| `high_confidence_count` | 211 |
| `medium_confidence_count` | 17 |
| `low_confidence_count` | 772 |
| `top_pattern` | `unknown_or_ambiguous` |

## Release Identity Result

| Metric | Value |
|---|---:|
| `total_records` | 1,000 |
| `total_identity_groups` | 906 |
| `single_record_identity_count` | 815 |
| `possible_true_duplicate_count` | 89 |
| `ambiguous_identity_group_count` | 2 |
| `duplicate_external_records_explained` | 179 |
| `duplicate_external_records_unresolved` | 6 |
| `legitimate_release_appearance_count` | 0 |
| `edition_or_reissue_cluster_count` | 0 |
| `compilation_or_multi_release_appearance_count` | 0 |

## Benchmark Result

| Metric | Value |
|---|---:|
| `total_records` | 1,000 |
| `total_cohorts` | 23 |
| `total_conflicts` | 23 |
| `safe_merge_candidates` | 1 |
| `blocked_merges` | 15 |
| `deferred_conflicts` | 7 |
| `source_artifact_candidates` | 5 |
| `artist_credit_analysis_used` | `true` |
| `release_identity_analysis_used` | `true` |

## Top Cohorts

| Cohort | Count | Dataset % | Severity |
|---|---:|---:|---|
| `artist_credit_unresolved` | 772 | 77.20% | high |
| `missing_artist` | 763 | 76.30% | low |
| `release_identity_possible_true_duplicate` | 179 | 17.90% | high |
| `artist_credit_parsed_high_confidence` | 19 | 1.90% | low |
| `artist_credit_parsed_medium_confidence` | 17 | 1.70% | medium |
| `artist_credit_collaboration` | 15 | 1.50% | medium |
| `release_identity_ambiguous` | 6 | 0.60% | high |
| `source_artifact_candidate` | 5 | 0.50% | high |
| `possible_track_as_artist` | multiple small cohorts | n/a | high |
| `artist_credit_ambiguous_group` | 2 | 0.20% | medium |
| `casing_alias_candidate` | 2 | 0.20% | low |

## Boundary Guarantees

| Boundary | Value |
|---|---|
| `metadata_only` | `true` |
| `audio_downloaded` | `false` |
| `local_library_mutated` | `false` |
| `canonical_graph_mutated` | `false` |

## Key Finding

Internet Archive 1k validates a larger live metadata-only sample but confirms
weak artist completeness for this query. The run fetched 1,000 records,
accepted 1,000, rejected 0, and completed acquisition, import, artist-credit
analysis, release-identity analysis, and benchmark reporting. It also found
763 records missing artist evidence and 772 unresolved artist credits.

## Fault Visibility

The validation did not hide weak source evidence. It surfaced unresolved artist
credits, missing artists, possible true duplicates, source artifact candidates,
release-identity ambiguity, and possible track-as-artist cohorts as benchmark
evidence for review.

## What This Proves

- The Internet Archive metadata-only acquisition path can fetch and normalize a
  1,000-record live sample for `collection:opensource_audio`.
- The imported Internet Archive sample can run through ingestion,
  artist-credit analysis, release-identity analysis, and integrated benchmark
  reporting.
- The benchmark uses artist-credit and release-identity analysis to surface
  fault evidence instead of treating all accepted records as clean.
- The run preserved the metadata-only, no-audio, no-local-library-mutation, and
  no-canonical-graph-mutation boundaries.
- The 1k run is stronger evidence than the historical 100-record smoke result
  for this query.

## What This Does Not Prove

- It does not prove CI runs Internet Archive live validation.
- It does not prove all Internet Archive metadata distributions.
- It does not prove larger Internet Archive behavior beyond this query and
  1,000-record sample.
- It does not prove stronger artist completeness for other Internet Archive
  queries.
- It does not authorize canonical merges, tag writes, media downloads, or local
  library remediation.
- It does not prove Discogs, YouTube metadata, or all live catalog API behavior.
