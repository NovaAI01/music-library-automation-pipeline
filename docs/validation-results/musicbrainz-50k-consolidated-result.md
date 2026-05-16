# MusicBrainz 50k Consolidated Validation Result

## Executive Summary

The MusicBrainz 50k validation run shows that the system can convert noisy
external metadata into explainable operational cohorts without mutating the
local music library or canonical graph.

The run converted 50,000 MusicBrainz metadata rows into 49,773 accepted
external records, ingested all accepted records with no missing artist, album,
or title fields, and then used specialist reporting to replace raw validation
noise with structured artist-credit and release-identity cohorts.

Before specialist analysis, collaboration strings were raw failure noise, and
`duplicate_external_records` looked like 12,065 duplicate-like records. After
specialist analysis, collaboration strings became structured artist-credit
cohorts, duplicate-looking records became release-aware identity cohorts, and
the integrated benchmark reported `duplicate_external_records=0` because
release identity analysis explained the duplicate-like evidence.

This is evidence consolidation only. It does not add remediation behavior and
does not prove that every metadata problem is solved.

## Dataset Boundary

- Source: MusicBrainz full metadata dump sample.
- Scope: metadata only.
- Input tracks seen: 50,000.
- Audio downloaded: no.
- Local library mutation: no.
- Metadata tag writes: no.
- Canonical graph mutation during external validation: no.
- Automatic remediation: no.
- Downloader behavior: none.
- AI/API behavior: none.

The validation treated MusicBrainz as an external metadata corpus. It did not
download audio, modify local music files, write tags, mutate canonical graph
state, or execute cleanup decisions.

## Conversion Result

| Metric | Value |
|---|---:|
| `input_tracks_seen` | 50,000 |
| `accepted_records` | 49,773 |
| `rejected_records` | 227 |
| `conversion_duration_seconds` | 54.79 |

The conversion stage accepted 99.55% of the sampled MusicBrainz rows and
rejected 227 records before ingestion. These metrics are taken from the
committed 50k validation result because the current generated
`reports/musicbrainz_conversion/conversion_summary.json` in the worktree
contains a small pytest fixture result rather than the 50k run summary.

## Ingestion Result

| Metric | Value |
|---|---:|
| `input_records` | 49,773 |
| `accepted_records` | 49,773 |
| `rejected_records` | 0 |
| `missing_artist` | 0 |
| `missing_album` | 0 |
| `missing_title` | 0 |

The ingestion stage accepted every converted external metadata record. The
absence of missing artist, album, and title fields matters because downstream
analysis could classify evidence instead of spending the benchmark on basic
schema failures.

## Artist Credit Analysis

| Metric | Value |
|---|---:|
| `parsed_records` | 49,407 |
| `solo_artist_count` | 46,971 |
| `collaboration_count` | 2,009 |
| `featured_artist_count` | 427 |
| `unresolved_count` | 366 |
| `high_confidence_count` | 47,151 |
| `medium_confidence_count` | 2,266 |
| `low_confidence_count` | 356 |

Artist-credit analysis converted raw collaboration-like strings into explicit
cohorts: high-confidence parsed credits, medium-confidence parsed credits,
collaborations, featured-artist cases, and unresolved artist credits. The
remaining unresolved records stay visible as review evidence rather than being
promoted into automatic artist merges.

## Release Identity Analysis

| Metric | Value |
|---|---:|
| `total_identity_groups` | 40,709 |
| `single_record_identity_count` | 36,061 |
| `legitimate_release_appearance_count` | 4,277 |
| `possible_true_duplicate_count` | 8 |
| `edition_or_reissue_cluster_count` | 42 |
| `compilation_or_multi_release_appearance_count` | 321 |
| `ambiguous_identity_group_count` | 0 |
| `duplicate_external_records_explained` | 13,712 |
| `duplicate_external_records_unresolved` | 0 |

Release identity analysis showed that duplicate-looking external metadata was
mostly release-context evidence: the same recording appearing across legitimate
releases, editions, reissues, compilations, or multiple release contexts. It
did not authorize deletion, merging, canonical graph changes, or tag writes.

## Benchmark Intelligence Before/After

Before specialist analysis:

- Collaboration strings were raw failure noise.
- Duplicate-looking external metadata appeared as a broad duplicate bucket.
- `duplicate_external_records` looked like 12,065 duplicate-like records.

After specialist analysis:

- `artist_credit_analysis_used=true`.
- `release_identity_analysis_used=true`.
- Collaboration strings became structured artist-credit cohorts.
- Duplicate-looking records became release-aware identity cohorts.
- `duplicate_external_records=0` in the integrated benchmark because release
  identity analysis explained them.

Integrated benchmark summary:

| Metric | Value |
|---|---:|
| `artist_credit_analysis_used` | true |
| `release_identity_analysis_used` | true |
| `duplicate_external_records` | 0 |
| `total_cohorts` | 1,212 |
| `total_conflicts` | 1,212 |

## Remaining Dominant Cohorts

| Cohort | Count | Dataset % | Severity |
|---|---:|---:|---|
| `release_identity_legitimate_appearance` | 12,075 | 24.26% | low |
| `artist_credit_parsed_high_confidence` | 4,690 | 9.42% | low |
| `artist_credit_parsed_medium_confidence` | 2,256 | 4.53% | medium |
| `artist_credit_collaboration` | 2,009 | 4.04% | medium |
| `release_identity_compilation_or_multi_release` | 1,355 | 2.72% | medium |
| `release_identity_possible_true_duplicate` | 169 | 0.34% | high |
| `release_identity_edition_or_reissue` | 113 | 0.23% | medium |

The dominant remaining cohorts are not a single unresolved failure mode. They
separate low-severity release appearances, parsed artist-credit evidence,
medium-severity collaboration or compilation contexts, and a much smaller
high-severity possible-true-duplicate cohort.

## What This Proves

- The pipeline can process a 50,000-row external metadata validation sample.
- Conversion and ingestion preserve a large usable external metadata corpus:
  49,773 accepted records after conversion and 0 rejected records during
  ingestion.
- Specialist analysis can turn raw failure buckets into explainable operational
  cohorts.
- Release-aware identity analysis can explain duplicate-looking external
  records without treating them as automatic deletion or merge candidates.
- Artist-credit analysis can distinguish solo, collaboration, featured, and
  unresolved credit evidence before any canonical graph integration.
- The validation workflow preserves review boundaries: reporting occurs without
  mutating local files, metadata tags, canonical graph state, or downloader
  behavior.

## What This Does Not Prove

- It does not prove all MusicBrainz metadata is correct.
- It does not prove all collaboration credits are resolved.
- It does not prove all possible duplicates are safe to merge or delete.
- It does not validate audio identity, fingerprints, or waveform similarity.
- It does not prove local library remediation quality.
- It does not add source adapters, AI/API behavior, download behavior, automatic
  remediation, canonical graph mutation, or metadata tag writing.

## Next Evidence Step

The next evidence step is targeted review of the remaining high-severity and
medium-severity cohorts, especially `release_identity_possible_true_duplicate`,
unresolved artist credits, source artifact candidates, and collaboration cases
that require human or graph-aware review before any operational remediation
proposal.
