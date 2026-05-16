# Validation Results

- [MusicBrainz 50k validation result](musicbrainz-50k-validation.md)
- [MusicBrainz 50k consolidated result](musicbrainz-50k-consolidated-result.md)

The public repository commits summarized validation result documents here. Full
generated run artifacts are local report outputs under ignored `reports/`
paths and are not expected to be present in a public checkout.

Isolated local report runs use ignored generated paths such as `reports/runs/musicbrainz/musicbrainz_50k/`.

Each labeled local run contains command-specific report directories plus
`run_manifest.json`. This prevents later smoke tests or fixture runs from
overwriting benchmark evidence under legacy paths such as
`reports/validation_benchmark/`.

The current verified MusicBrainz 50k metrics were produced from the ignored local isolated run `reports/runs/musicbrainz/musicbrainz_50k/`.

Its manifest records:

| Manifest field | Value |
|---|---|
| `metadata_only` | `true` |
| `audio_downloaded` | `false` |
| `local_library_mutated` | `false` |
| `canonical_graph_mutated` | `false` |

Current isolated run metrics:

| Stage | Metric | Value |
|---|---|---:|
| Conversion | `input_tracks_seen` | 50,000 |
| Conversion | `accepted_records` | 49,773 |
| Conversion | `rejected_records` | 227 |
| Conversion | `duration_seconds` | 82.84 |
| Ingestion | `input_records` | 49,773 |
| Ingestion | `accepted_records` | 49,773 |
| Ingestion | `rejected_records` | 0 |
| Artist Credit Analysis | `total_records` | 49,773 |
| Artist Credit Analysis | `parsed_records` | 49,407 |
| Artist Credit Analysis | `collaboration_count` | 2,009 |
| Artist Credit Analysis | `featured_artist_count` | 427 |
| Artist Credit Analysis | `unresolved_count` | 366 |
| Artist Credit Analysis | `high_confidence_count` | 47,151 |
| Artist Credit Analysis | `medium_confidence_count` | 2,266 |
| Artist Credit Analysis | `low_confidence_count` | 356 |
| Release Identity Analysis | `total_identity_groups` | 40,709 |
| Release Identity Analysis | `legitimate_release_appearance_count` | 4,277 |
| Release Identity Analysis | `possible_true_duplicate_count` | 8 |
| Release Identity Analysis | `duplicate_external_records_explained` | 13,712 |
| Release Identity Analysis | `duplicate_external_records_unresolved` | 0 |
| Integrated Benchmark | `total_records` | 49,773 |
| Integrated Benchmark | `total_cohorts` | 1,212 |
| Integrated Benchmark | `total_conflicts` | 1,212 |
| Integrated Benchmark | `safe_merge_candidates` | 350 |
| Integrated Benchmark | `blocked_merges` | 851 |
| Integrated Benchmark | `deferred_conflicts` | 11 |
| Integrated Benchmark | `collaboration_string_candidates` | 0 |
| Integrated Benchmark | `duplicate_external_records` | 0 |
| Integrated Benchmark | `benchmark_duration_seconds` | 2.45 |
