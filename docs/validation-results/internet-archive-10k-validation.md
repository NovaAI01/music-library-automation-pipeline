# Internet Archive 10k Metadata Validation

## Source And Boundary

- Source: Internet Archive advanced search metadata
- Query: `collection:opensource_audio`
- Scale: 10,000 records
- Metadata only: true
- Audio downloaded: no
- Audio download allowed: false
- Local library mutated: no
- Canonical graph mutated: no
- Run label: `internet_archive_10k`
- Evidence source: manual user-terminal run outside CI

This result records user-terminal evidence for a metadata-only Internet Archive
validation run. It did not download audio, stream tracks, mutate local library
state, write tags, or write to the canonical graph.

This supersedes the Internet Archive 1,000-record validation as the stronger
current Internet Archive evidence gate for the selected query, while preserving
the same metadata-only and no-mutation boundaries.

## Command Sequence

Acquisition:

```bash
python -m app.main fetch-internet-archive-metadata \
  --query "collection:opensource_audio" \
  --limit 10000 \
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
  --run-label internet_archive_10k

python -m app.main analyze-artist-credits \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_10k

python -m app.main analyze-release-identity \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_10k

python -m app.main benchmark-validation \
  --source internet_archive \
  --out reports \
  --run-label internet_archive_10k

python -m app.main source-quality-report
```

## Acquisition Result

| Metric | Value |
|---|---:|
| `fetched_records` | 10,000 |
| `accepted_records` | 10,000 |
| `rejected_records` | 0 |
| `metadata_only` | `true` |
| `audio_download_allowed` | `false` |
| `duration_seconds` | 89.881497 |

Output files:

```text
/media/jack/MUSIC_INTEL/MusicIntelligenceData/external_metadata/internet_archive/raw_internet_archive.csv
/media/jack/MUSIC_INTEL/MusicIntelligenceData/external_metadata/internet_archive/raw_internet_archive.jsonl
```

## Import Result

| Metric | Value |
|---|---:|
| `input_records` | 10,000 |
| `accepted_records` | 10,000 |
| `rejected_records` | 0 |
| `generated_id_count` | 0 |
| `missing_artist_count` | 8,008 |
| `missing_album_count` | 0 |
| `missing_title_count` | 0 |

## Artist Credit Result

| Metric | Value |
|---|---:|
| `total_records` | 10,000 |
| `parsed_records` | 1,925 |
| `unresolved_count` | 8,075 |
| `collaboration_count` | 43 |
| `featured_artist_count` | 2 |
| `high_confidence_count` | 1,878 |
| `medium_confidence_count` | 48 |
| `low_confidence_count` | 8,074 |
| `top_pattern` | `unknown_or_ambiguous` |

## Release Identity Result

| Metric | Value |
|---|---:|
| `total_records` | 10,000 |
| `total_identity_groups` | 7,429 |
| `possible_true_duplicate_count` | 1,977 |
| `ambiguous_identity_group_count` | 23 |
| `duplicate_external_records_explained` | 4,457 |
| `duplicate_external_records_unresolved` | 114 |
| `legitimate_release_appearance_count` | 0 |
| `edition_or_reissue_cluster_count` | 0 |
| `compilation_or_multi_release_appearance_count` | 0 |

## Benchmark Result

| Metric | Value |
|---|---:|
| `total_records` | 10,000 |
| `total_cohorts` | 134 |
| `total_conflicts` | 134 |
| `safe_merge_candidates` | 25 |
| `blocked_merges` | 100 |
| `deferred_conflicts` | 9 |
| `source_artifact_candidates` | 38 |
| `artist_credit_analysis_used` | `true` |
| `release_identity_analysis_used` | `true` |

## Source Quality Report Inclusion

The source quality report included 8 source runs and an
`internet_archive_10k` row with this CSV evidence:

```text
internet_archive,internet_archive_10k,10000,10000,0,8008,0,0,1925,8075,7429,1977,4457,38,134,134,25,100,9,true,false,false,false
```

## Top Cohorts

| Cohort | Count | Dataset % | Severity |
|---|---:|---:|---|
| `artist_credit_unresolved` | 8,074 | 80.74% | high |
| `missing_artist` | 8,008 | 80.08% | low |
| `release_identity_possible_true_duplicate` | 4,457 | 44.57% | high |
| `artist_credit_parsed_high_confidence` | 139 | 1.39% | low |
| `release_identity_ambiguous` | 114 | 1.14% | high |
| `artist_credit_parsed_medium_confidence` | 47 | 0.47% | medium |
| `artist_credit_collaboration` | 43 | 0.43% | medium |
| `source_artifact_candidate` | 38 | 0.38% | high |
| `remaster_version_noise` | 24 | 0.24% | medium |
| `album_title_punctuation_variant` | 15 | 0.15% | medium |

## Boundary Guarantees

| Boundary | Value |
|---|---|
| `metadata_only` | `true` |
| `audio_downloaded` | `false` |
| `local_library_mutated` | `false` |
| `canonical_graph_mutated` | `false` |

## Key Findings

Internet Archive 10k validates a larger live metadata-only sample for the
selected query. The run fetched 10,000 records, accepted 10,000, rejected 0,
and completed acquisition, import, artist-credit analysis, release-identity
analysis, benchmark reporting, and source-quality report inclusion.

The result also confirms weak artist completeness for this query. Import
reported 8,008 records missing artist evidence, artist-credit analysis left
8,075 records unresolved, release-identity analysis found 1,977 possible true
duplicate groups, and benchmarking surfaced 38 source artifact candidates.

## Fault Visibility

The validation did not hide weak source evidence. It surfaced unresolved artist
credits, missing artists, possible true duplicate groups, source artifact
candidates, release-identity ambiguity, remaster/version noise, punctuation
variants, and collaboration cohorts as benchmark evidence for review.

## What This Proves

- The Internet Archive metadata-only acquisition path can fetch and normalize a
  10,000-record live sample for `collection:opensource_audio`.
- The imported Internet Archive sample can run through ingestion,
  artist-credit analysis, release-identity analysis, integrated benchmark
  reporting, and source-quality report inclusion.
- The benchmark uses artist-credit and release-identity analysis to surface
  fault evidence instead of treating all accepted records as clean.
- The run preserved the metadata-only, no-audio, no-local-library-mutation, and
  no-canonical-graph-mutation boundaries.
- The 10k run is stronger Internet Archive evidence than the historical
  100-record and 1,000-record runs for this query.

## What This Does Not Prove

- It does not prove CI runs Internet Archive live validation.
- It does not prove all Internet Archive metadata distributions.
- It does not prove broader Internet Archive behavior beyond this query and
  10,000-record sample.
- It does not prove stronger artist completeness for other Internet Archive
  queries.
- It does not authorize canonical merges, tag writes, media downloads, or local
  library remediation.
- It does not prove Discogs, YouTube metadata, or all live catalog API behavior.
