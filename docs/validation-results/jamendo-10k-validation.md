# Jamendo 10k Metadata Validation Result

## Source And Boundary

- Source: Jamendo metadata API
- Scale: 10,000 requested records
- Metadata only: true
- Audio downloaded: no
- Audio download allowed: false
- Media downloaded: no
- Local library mutated: no
- Canonical graph mutated: no
- Credentials: `JAMENDO_CLIENT_ID` required, stored outside the repository
- Client ID source: environment

This validation records the strongest current Jamendo metadata-only result. It
exercises acquisition, ingestion, artist-credit analysis, release-identity
analysis, and integrated benchmark reporting against a second live metadata
source at useful scale.

It did not download audio, download media assets, stream tracks, mutate local
library state, write tags, or write to the canonical graph. It should not be
interpreted as proof for all Jamendo metadata, all catalog APIs, or source
families that remain unvalidated.

The acquisition summary is currently written to `reports/jamendo_metadata/` and
may be overwritten by future fetches. Downstream validation outputs for this
run are isolated under `reports/runs/jamendo/jamendo_10k/`.

## Acquisition Result

| Metric | Value |
|---|---:|
| `source` | Jamendo |
| `requested_limit` | 10,000 |
| `fetched_records` | 10,000 |
| `accepted_records` | 10,000 |
| `rejected_records` | 0 |
| `duration_seconds` | 1332.084767 |
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
| `download/track` | OK |

## Ingestion Result

| Metric | Value |
|---|---:|
| `input_records` | 10,000 |
| `accepted_records` | 10,000 |
| `rejected_records` | 0 |
| `generated_id_count` | 0 |
| `missing_artist_count` | 0 |
| `missing_album_count` | 0 |
| `missing_title_count` | 0 |

## Artist Credit Analysis

| Metric | Value |
|---|---:|
| `total_records` | 10,000 |
| `parsed_records` | 9,878 |
| `solo_artist_count` | 9,751 |
| `collaboration_count` | 127 |
| `featured_artist_count` | 0 |
| `unresolved_count` | 122 |
| `high_confidence_count` | 9,741 |
| `medium_confidence_count` | 137 |
| `low_confidence_count` | 122 |

Artist-credit analysis found mostly solo-artist evidence. Remaining
medium-confidence collaboration and low-confidence unresolved records stay
visible as review evidence and do not authorize canonical artist merges.

## Release Identity Analysis

| Metric | Value |
|---|---:|
| `total_records` | 10,000 |
| `total_identity_groups` | 9,945 |
| `single_record_identity_count` | 9,898 |
| `legitimate_release_appearance_count` | 0 |
| `possible_true_duplicate_count` | 3 |
| `ambiguous_identity_group_count` | 44 |
| `duplicate_external_records_explained` | 6 |
| `duplicate_external_records_unresolved` | 96 |

Jamendo 10k is cleaner than MusicBrainz for release identity in the validated
samples. The run found a small release-identity ambiguity surface rather than a
large duplicate-like release appearance pattern.

## Integrated Benchmark Result

| Metric | Value |
|---|---:|
| `total_records` | 10,000 |
| `total_cohorts` | 205 |
| `total_conflicts` | 205 |
| `safe_merge_candidates` | 107 |
| `blocked_merges` | 92 |
| `deferred_conflicts` | 6 |
| `duplicate_external_records` | 0 |
| `source_artifact_candidates` | 21 |
| `benchmark_duration_seconds` | 0.2595 |

## Top Cohorts

| Cohort | Count | Dataset % | Severity |
|---|---:|---:|---|
| `artist_credit_parsed_high_confidence` | 297 | 2.97% | low |
| `possible_album_as_artist` | 192 | 1.92% | high |
| `artist_credit_parsed_medium_confidence` | 137 | 1.37% | medium |
| `artist_credit_collaboration` | 127 | 1.27% | medium |
| `artist_credit_unresolved` | 122 | 1.22% | high |
| `release_identity_ambiguous` | 96 | 0.96% | high |
| `album_title_punctuation_variant` | 72 | 0.72% | medium |
| `remaster_version_noise` | 63 | 0.63% | medium |
| `possible_track_as_artist` | 30 | 0.30% | high |
| `source_artifact_candidate` | 21 | 0.21% | high |

## Interpretation

Jamendo 10k validates a second live metadata source through the metadata-only
validation path at useful scale: acquisition, ingestion, artist-credit analysis,
release-identity analysis, and integrated benchmark reporting.

Compared with MusicBrainz 50k, Jamendo 10k is cleaner for release identity in
the currently validated evidence. The main remaining Jamendo issues are
possible album/title-as-artist classification, artist-credit uncertainty, and a
small release-identity ambiguity surface.

This result does not prove all Jamendo metadata, all live catalog APIs, or all
source families. Discogs, Internet Archive, and YouTube metadata remain
unvalidated.
