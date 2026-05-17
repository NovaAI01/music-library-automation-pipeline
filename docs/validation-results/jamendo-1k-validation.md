# Jamendo 1k Metadata Validation Result

## Source And Boundary

- Source: Jamendo metadata API
- Scale: 1,000 records
- Metadata only: true
- Audio downloaded: no
- Audio download allowed: false
- Media downloaded: no
- Local library mutated: no
- Canonical graph mutated: no
- Credentials: `JAMENDO_CLIENT_ID` required, stored outside the repository
- Client ID source: environment

This validation records the second live metadata source exercised through
acquisition, ingestion, artist-credit analysis, release-identity analysis, and
integrated benchmark reporting. It did not download audio, download media
assets, stream tracks, mutate local library state, write tags, or write to the
canonical graph.

This is 1k validation only. It should not be interpreted as full Jamendo source
generalization or as evidence for a 10k-scale run.

## Acquisition Result

| Metric | Value |
|---|---:|
| `source` | Jamendo |
| `limit` | 1,000 |
| `fetched_records` | 1,000 |
| `accepted_records` | 1,000 |
| `rejected_records` | 0 |
| `duration_seconds` | 135.572386 |
| `metadata_only` | `true` |
| `audio_download_allowed` | `false` |
| `client_id_source` | `environment` |

## Redaction Result

Raw payload JSON redacts media, audio, and download fields before
repository-safe documentation. The redaction check passed:

| Redaction check | Result |
|---|---|
| `audiodownload` | OK |
| `prod-1.storage.jamendo.com` | OK |
| `format=mp3` | OK |
| `mp31` | OK |
| `mp32` | OK |

## Ingestion Result

| Metric | Value |
|---|---:|
| `input_records` | 1,000 |
| `accepted_records` | 1,000 |
| `rejected_records` | 0 |
| `missing_artist_count` | 0 |
| `missing_album_count` | 0 |
| `missing_title_count` | 0 |

## Artist Credit Analysis

| Metric | Value |
|---|---:|
| `total_records` | 1,000 |
| `parsed_records` | 983 |
| `solo_artist_count` | 962 |
| `collaboration_count` | 21 |
| `featured_artist_count` | 0 |
| `unresolved_count` | 17 |
| `high_confidence_count` | 962 |
| `medium_confidence_count` | 21 |
| `low_confidence_count` | 17 |

Artist-credit analysis found mostly solo-artist evidence. The remaining
medium-confidence collaboration and low-confidence unresolved records stay
visible as review evidence and do not authorize canonical artist merges.

## Release Identity Analysis

| Metric | Value |
|---|---:|
| `total_records` | 1,000 |
| `total_identity_groups` | 1,000 |
| `single_record_identity_count` | 1,000 |
| `legitimate_release_appearance_count` | 0 |
| `possible_true_duplicate_count` | 0 |
| `ambiguous_identity_group_count` | 0 |

This run found no duplicate release-identity groups in the 1,000-record
Jamendo sample. Compared with the MusicBrainz 50k validation result, Jamendo's
1k release-identity distribution is much cleaner, with the observed issues
concentrated outside duplicate release identity.

## Integrated Benchmark Result

| Metric | Value |
|---|---:|
| `total_records` | 1,000 |
| `total_cohorts` | 15 |
| `total_conflicts` | 15 |
| `safe_merge_candidates` | 2 |
| `blocked_merges` | 9 |
| `deferred_conflicts` | 4 |
| `duplicate_external_records` | 0 |
| `source_artifact_candidates` | 0 |

## Top Cohorts

| Cohort | Count | Dataset % | Severity |
|---|---:|---:|---|
| `artist_credit_parsed_high_confidence` | 28 | 2.80% | low |
| `possible_album_as_artist` | 21 | 2.10% | high |
| `artist_credit_collaboration` | 21 | 2.10% | medium |
| `artist_credit_parsed_medium_confidence` | 21 | 2.10% | medium |
| `artist_credit_unresolved` | 17 | 1.70% | high |
| `possible_track_as_artist` | 13 | 1.30% | high |
| `album_title_punctuation_variant` | 13 | 1.30% | medium |

## Interpretation

Jamendo 1k validates a second live metadata source through the metadata-only
validation path: acquisition, ingestion, artist-credit analysis,
release-identity analysis, and integrated benchmark reporting.

Jamendo's observed 1k distribution is much cleaner than MusicBrainz for release
identity. The main Jamendo issues are artist, title, and album classification
and small artist-credit ambiguity, not duplicate release identity.

This remains 1k validation, not full source generalization. The next gate is a
Jamendo 10k run only after this result is documented.
