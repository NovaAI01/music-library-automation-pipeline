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

Initial validation benchmarking treated collaboration syntax as one raw
`collaboration_string` cohort. Artist Credit Validation Integration v1 now
feeds the parser output back into benchmark reporting when
`reports/artist_credit_analysis/` exists for the same source, so explained
credits are separated from unresolved artist-credit failures. Release Identity
Validation Integration v1 also feeds release-aware identity analysis into the
benchmark when `reports/release_identity_analysis/` exists for the same source,
so duplicate-looking rows are separated into legitimate release appearances,
possible true duplicates, edition/reissue clusters, compilation or
multi-release appearances, and unresolved identity evidence.

| Metric | Value |
|---|---:|
| Total records | 49,773 |
| Total cohorts | 1,212 |
| Total conflicts | 1,212 |
| Safe merge candidates | 350 |
| Blocked merges | 851 |
| Deferred conflicts | 11 |
| Duplicate external records | 0 |
| Source artifact candidates | 393 |
| Collaboration string candidates | 0 |
| Malformed records | 0 |
| Benchmark duration | 2.50s |

## Artist Credit Benchmark Integration

MusicBrainz 50k artist-credit analysis after calibration:

| Metric | Value |
|---|---:|
| Total records | 49,773 |
| Parsed records | 49,407 |
| Solo artist count | 46,971 |
| Collaboration count | 2,009 |
| Featured artist count | 427 |
| Unresolved count | 366 |
| High confidence count | 47,151 |
| Medium confidence count | 2,266 |
| Low confidence count | 356 |

When this report is present, `benchmark-validation` records
`artist_credit_analysis_used=true`, removes the raw `collaboration_string`
aggregate from benchmark failure counts, and emits artist-credit cohorts for
high-confidence parsed credits, medium-confidence parsed collaborations,
featured artists, ambiguous group names, and unresolved artist credits.

This is reporting integration only. It does not mutate MusicBrainz-derived
external metadata, local music files, media tags, canonical graph state, or
artist merge behavior.

## Top Failure Cohorts

| Cohort | Count | % of dataset | Severity | Recommended action |
|---|---:|---:|---|---|
| release_identity_legitimate_appearance | 12,075 | 24.26% | low | Treat as release-aware duplicate evidence; do not remove or merge automatically. |
| artist_credit_parsed_high_confidence | 4,690 | 9.42% | low | Treat as parser-explained artist credit evidence; do not merge automatically. |
| artist_credit_parsed_medium_confidence | 2,256 | 4.53% | medium | Review parsed collaboration evidence before graph integration. |
| artist_credit_collaboration | 2,009 | 4.04% | medium | Review as collaboration role evidence before graph integration. |
| release_identity_compilation_or_multi_release | 1,355 | 2.72% | medium | Preserve compilation or multi-release context before duplicate interpretation. |
| artist_credit_featured | 427 | 0.86% | medium | Review as featured-artist role evidence before graph integration. |
| artist_credit_ambiguous_group | 412 | 0.83% | medium | Review as possible group-name ambiguity before splitting artists. |
| source_artifact_candidate | 393 | 0.79% | high | Block from canonical promotion proposals until reviewed |
| artist_credit_unresolved | 356 | 0.72% | high | Keep blocked from canonical artist promotion until parser or human review resolves it. |
| remaster_version_noise | 350 | 0.70% | medium | Separate version descriptors from canonical titles |

## Interpretation

The pipeline successfully converted, ingested, and benchmarked a real 50k-record MusicBrainz metadata sample.

The dominant issue is no longer one raw collaboration-string bucket. Artist
Credit Parsing v1 explains most collaboration-like strings and leaves a smaller
unresolved artist-credit cohort visible for review.

Release Identity Validation Integration v1 also removes the raw
`duplicate_external_record` benchmark bucket when matching release identity
analysis exists. The dominant duplicate-like evidence is now explained as
legitimate release appearances, while possible true duplicate candidates remain
visible as high-severity review evidence.

Primary next engineering target:

`Artist Credit Parsing v1`

Artist Credit Parsing v1 analyzes this collaboration cohort and prepares
role-aware primary, featured, collaborator, and unresolved artist-credit
evidence for future canonical graph integration. It does not change canonical
entities, create aliases, merge artists, mutate local music data, or write
metadata tags in v1.

## Artist Credit Parser Calibration v1

The 50k artist-credit analysis showed false collaboration risk around
canonical group names that contain collaboration-like separators. Examples
include orchestra, band, company, and named group suffixes such as `Jimmy
Dorsey & His Orchestra`, `Siouxsie and the Banshees`, `Martin & Company`, and
`Nick Cave and the Bad Seeds`.

Calibration v1 keeps explicit `feat`, `ft`, `featuring`, `with`, `vs`, and `x`
collaboration parsing, but protects deterministic group-name boundaries before
generic `&`, comma, or `and` splitting. Protected rows are analysis evidence
only; this does not change canonical graph behavior, create aliases, merge
artists, mutate local files, or write metadata tags.

The second major issue is release-aware duplicate identity. The `duplicate_external_records` count likely reflects multiple releases, editions, countries, and reissues rather than simple duplicate tracks.

Do not treat those as removable duplicates without release-aware identity logic.

Release-Aware Identity Analysis v1 adds that intermediate reporting step:

```bash
python -m app.main analyze-release-identity --source musicbrainz --out reports
```

It distinguishes likely true duplicate rows from the same recording appearing
across legitimate releases, editions, reissues, compilations, soundtracks, and
ambiguous weak-identity clusters. This is required before interpreting
`duplicate_external_records` as a duplicate-remediation target, and it remains
reporting-only: no files, tags, external metadata inputs, duplicate quarantine
state, or canonical graph behavior are changed.

MusicBrainz 50k release-aware identity analysis:

| Metric | Value |
|---|---:|
| Total records | 49,773 |
| Total identity groups | 40,709 |
| Single-record identity groups | 36,061 |
| Legitimate release appearances | 4,277 |
| Edition or reissue clusters | 42 |
| Compilation or multi-release appearances | 321 |
| Possible true duplicate groups | 8 |
| Ambiguous identity groups | 0 |
| Duplicate-like records explained | 13,712 |
| Duplicate-like records unresolved | 0 |

When this report is present, `benchmark-validation` records
`release_identity_analysis_used=true`, removes the raw
`duplicate_external_record` aggregate from benchmark failure counts, and emits
release identity cohorts for legitimate release appearances, edition/reissue
clusters, compilation or multi-release appearances, possible true duplicates,
ambiguous identity groups, and unresolved duplicate-like records.
