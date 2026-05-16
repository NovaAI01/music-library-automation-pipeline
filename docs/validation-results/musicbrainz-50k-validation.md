# MusicBrainz 50k Validation Result

## Source

- Source: MusicBrainz full metadata dump
- Dump: `20260513-001936`
- Audio downloaded: no
- Local library mutated: no
- Canonical graph mutated: no
- External data root: `$MUSIC_INTELLIGENCE_DATA_ROOT`

## Conversion Result

| Metric | Value |
|---|---:|
| Input tracks seen | 50,000 |
| Accepted records | 49,773 |
| Rejected records | 227 |
| Rejection rate | 0.45% |
| Conversion duration | 54.79s |

## Ingestion Result

| Metric | Value |
|---|---:|
| Input records | 49,773 |
| Accepted records | 49,773 |
| Rejected records | 0 |
| Generated IDs | 0 |
| Missing artist | 0 |
| Missing album | 0 |
| Missing title | 0 |

## Benchmark Result

| Metric | Value |
|---|---:|
| Total records | 49,773 |
| Total cohorts | 5,622 |
| Total conflicts | 5,622 |
| Safe merge candidates | 350 |
| Blocked merges | 2,431 |
| Deferred conflicts | 2,841 |
| Duplicate external records | 12,065 |
| Source artifact candidates | 393 |
| Collaboration string candidates | 5,929 |
| Malformed records | 0 |
| Benchmark duration | 1.22s |

## Top Failure Cohorts

| Cohort | Count | % of dataset | Severity | Recommended action |
|---|---:|---:|---|---|
| collaboration_string | 5,929 | 11.91% | medium | Route through role-aware artist parsing proposals |
| source_artifact_candidate | 393 | 0.79% | high | Block from canonical promotion proposals until reviewed |
| remaster_version_noise | 350 | 0.70% | medium | Separate version descriptors from canonical titles |
| possible_album_as_artist | 319 | 0.64% | high | Investigate album-title-as-artist misclassification |
| album_title_punctuation_variant | 233 | 0.47% | medium | Review punctuation-insensitive album/title normalization |
| possible_track_as_artist | 191 | 0.38% | high | Investigate track-title-as-artist misclassification |
| explicit_clean_radio_edit_noise | 72 | 0.14% | medium | Treat as version metadata, not canonical title text |

## Interpretation

The pipeline successfully converted, ingested, and benchmarked a real 50k-record MusicBrainz metadata sample.

The dominant issue is not generic metadata dirtiness. The dominant issue is artist-credit and collaboration parsing.

Primary next engineering target:

`Artist Credit Parsing v1`

Artist Credit Parsing v1 analyzes this collaboration cohort and prepares
role-aware primary, featured, collaborator, and unresolved artist-credit
evidence for future canonical graph integration. It does not change canonical
entities, create aliases, merge artists, mutate local music data, or write
metadata tags in v1.

The second major issue is release-aware duplicate identity. The `duplicate_external_records` count likely reflects multiple releases, editions, countries, and reissues rather than simple duplicate tracks.

Do not treat those as removable duplicates without release-aware identity logic.
