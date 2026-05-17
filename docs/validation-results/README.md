# Validation Results

- [Cross-source validation summary](cross-source-validation-summary.md)
- [MusicBrainz 50k validation result](musicbrainz-50k-validation.md)
- [MusicBrainz 50k consolidated result](musicbrainz-50k-consolidated-result.md)
- [Jamendo 10k metadata validation result](jamendo-10k-validation.md)
- [Jamendo 1k metadata validation result](jamendo-1k-validation.md)
- [Jamendo 100 metadata validation smoke](jamendo-100-validation.md)

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

## Jamendo 100 Metadata Smoke

Jamendo 100 is the first successful metadata-only validation smoke for the
Jamendo metadata API as a second live metadata source. It is intentionally not
equal in scope to the MusicBrainz 50k validation result.

Boundary guarantees:

| Manifest field | Value |
|---|---|
| `metadata_only` | `true` |
| `audio_downloaded` | `false` |
| `local_library_mutated` | `false` |
| `canonical_graph_mutated` | `false` |

Verified smoke metrics:

| Stage | Metric | Value |
|---|---|---:|
| Acquisition | `fetched_records` | 100 |
| Acquisition | `accepted_records` | 100 |
| Acquisition | `rejected_records` | 0 |
| Import | `input_records` | 100 |
| Import | `accepted_records` | 100 |
| Import | `rejected_records` | 0 |
| Artist Credit Analysis | `parsed_records` | 100 |
| Artist Credit Analysis | `unresolved_count` | 0 |
| Release Identity Analysis | `total_identity_groups` | 100 |
| Integrated Benchmark | `total_records` | 100 |
| Integrated Benchmark | `total_conflicts` | 1 |

The raw payload redaction check passed for media, audio, and download URL
fields. This result confirms the Jamendo live metadata path at smoke scale only;
the later Jamendo 1k result records the next completed scale gate.

## Jamendo 1k Metadata Validation

Jamendo 1k is the first successful 1,000-record metadata-only validation for
Jamendo as the second live metadata source. It validates the same reporting path
as the Jamendo 100 smoke at a larger scale: acquisition, ingestion,
artist-credit analysis, release-identity analysis, and integrated benchmark
reporting.

Boundary guarantees:

| Manifest field | Value |
|---|---|
| `metadata_only` | `true` |
| `audio_downloaded` | `false` |
| `audio_download_allowed` | `false` |
| `local_library_mutated` | `false` |
| `canonical_graph_mutated` | `false` |
| `client_id_source` | `environment` |

Verified 1k metrics:

| Stage | Metric | Value |
|---|---|---:|
| Acquisition | `source` | Jamendo |
| Acquisition | `limit` | 1,000 |
| Acquisition | `fetched_records` | 1,000 |
| Acquisition | `accepted_records` | 1,000 |
| Acquisition | `rejected_records` | 0 |
| Acquisition | `duration_seconds` | 135.572386 |
| Ingestion | `input_records` | 1,000 |
| Ingestion | `accepted_records` | 1,000 |
| Ingestion | `rejected_records` | 0 |
| Ingestion | `missing_artist_count` | 0 |
| Ingestion | `missing_album_count` | 0 |
| Ingestion | `missing_title_count` | 0 |
| Artist Credit Analysis | `parsed_records` | 983 |
| Artist Credit Analysis | `solo_artist_count` | 962 |
| Artist Credit Analysis | `collaboration_count` | 21 |
| Artist Credit Analysis | `unresolved_count` | 17 |
| Release Identity Analysis | `total_identity_groups` | 1,000 |
| Release Identity Analysis | `single_record_identity_count` | 1,000 |
| Release Identity Analysis | `possible_true_duplicate_count` | 0 |
| Integrated Benchmark | `total_records` | 1,000 |
| Integrated Benchmark | `total_cohorts` | 15 |
| Integrated Benchmark | `total_conflicts` | 15 |
| Integrated Benchmark | `safe_merge_candidates` | 2 |
| Integrated Benchmark | `blocked_merges` | 9 |
| Integrated Benchmark | `deferred_conflicts` | 4 |
| Integrated Benchmark | `duplicate_external_records` | 0 |
| Integrated Benchmark | `source_artifact_candidates` | 0 |

The raw payload redaction check passed for `audiodownload`,
`prod-1.storage.jamendo.com`, `format=mp3`, `mp31`, and `mp32`.

Jamendo 1k shows a much cleaner release-identity distribution than MusicBrainz:
1,000 records produced 1,000 single-record identity groups, with no legitimate
release appearances, possible true duplicates, or ambiguous identity groups in
the sample. The observed Jamendo issues are mainly artist, title, and album
classification plus small artist-credit ambiguity. This remains 1k validation
only and is superseded by the Jamendo 10k result as the strongest current
Jamendo validation evidence.

## Jamendo 10k Metadata Validation

Jamendo 10k is the strongest current Jamendo metadata-only validation result.
It validates a second live metadata source at useful scale while preserving the
same no-audio and no-canonical-mutation boundaries as earlier Jamendo runs.

Boundary guarantees:

| Manifest field | Value |
|---|---|
| `metadata_only` | `true` |
| `audio_download_allowed` | `false` |
| `local_library_mutated` | `false` |
| `canonical_graph_mutated` | `false` |
| `client_id_source` | `environment` |

Verified 10k metrics:

| Stage | Metric | Value |
|---|---|---:|
| Acquisition | `source` | Jamendo |
| Acquisition | `requested_limit` | 10,000 |
| Acquisition | `fetched_records` | 10,000 |
| Acquisition | `accepted_records` | 10,000 |
| Acquisition | `rejected_records` | 0 |
| Acquisition | `duration_seconds` | 1332.084767 |
| Ingestion | `input_records` | 10,000 |
| Ingestion | `accepted_records` | 10,000 |
| Ingestion | `rejected_records` | 0 |
| Ingestion | `generated_id_count` | 0 |
| Ingestion | `missing_artist_count` | 0 |
| Ingestion | `missing_album_count` | 0 |
| Ingestion | `missing_title_count` | 0 |
| Artist Credit Analysis | `parsed_records` | 9,878 |
| Artist Credit Analysis | `solo_artist_count` | 9,751 |
| Artist Credit Analysis | `collaboration_count` | 127 |
| Artist Credit Analysis | `unresolved_count` | 122 |
| Release Identity Analysis | `total_identity_groups` | 9,945 |
| Release Identity Analysis | `single_record_identity_count` | 9,898 |
| Release Identity Analysis | `possible_true_duplicate_count` | 3 |
| Release Identity Analysis | `ambiguous_identity_group_count` | 44 |
| Release Identity Analysis | `duplicate_external_records_explained` | 6 |
| Release Identity Analysis | `duplicate_external_records_unresolved` | 96 |
| Integrated Benchmark | `total_records` | 10,000 |
| Integrated Benchmark | `total_cohorts` | 205 |
| Integrated Benchmark | `total_conflicts` | 205 |
| Integrated Benchmark | `safe_merge_candidates` | 107 |
| Integrated Benchmark | `blocked_merges` | 92 |
| Integrated Benchmark | `deferred_conflicts` | 6 |
| Integrated Benchmark | `duplicate_external_records` | 0 |
| Integrated Benchmark | `source_artifact_candidates` | 21 |
| Integrated Benchmark | `benchmark_duration_seconds` | 0.2595 |

The raw payload redaction check passed for `audiodownload`,
`prod-1.storage.jamendo.com`, `format=mp3`, `mp31`, `mp32`, and
`download/track`.

Jamendo 10k is cleaner than MusicBrainz for release identity in the currently
validated evidence. Its main remaining issues are possible
album/title-as-artist classification, artist-credit uncertainty, and small
release-identity ambiguity. This does not prove all Jamendo metadata or all
source families; Discogs, Internet Archive, and YouTube metadata remain
unvalidated.

The acquisition summary is currently written to `reports/jamendo_metadata/` and
may be overwritten by future fetches. Downstream validation outputs are isolated
under `reports/runs/jamendo/jamendo_10k/`.
