# Cross-Source Validation Summary v1

## Executive Summary

The platform is now validated against one public fixture workflow, one large
canonical metadata source, one live catalog API source at useful scale, and one
Internet Archive live metadata source at smoke/early scale.

The validated evidence is metadata-only. It proves that the external metadata
contract, artist-credit analysis, release-identity analysis, and integrated
benchmark reporting can run across more than one source distribution without
downloading audio, mutating a local library, or mutating the canonical graph.

This summary consolidates existing evidence only. It does not claim full
generalization or prove behavior for sources and scale gates that remain blocked
or deferred.

## Source Coverage Matrix

| Source | Scale | Acquisition method | Validation status | Primary evidence | Current limitation |
|---|---:|---|---|---|---|
| Public fixture | 65 input records | Clean-clone reproducible local CSV fixture | Verified reviewer workflow | 60 accepted, 5 rejected, 29 benchmark cohorts, 9 safe merge candidates, 8 blocked merges, 12 deferred conflicts | Fictional fixture proves reproducibility and reviewer path, not real-world distribution coverage |
| MusicBrainz | 50,000 tracks seen | Local MusicBrainz dump conversion | Verified large canonical metadata source | 49,773 accepted after conversion, 227 rejected, 49,773 imported, 49,407 artist credits parsed, 13,712 duplicate-like records explained by release identity analysis, 1,212 benchmark cohorts/conflicts | Validates a large MusicBrainz sample, not every MusicBrainz row or all external catalogs |
| Jamendo 100 | 100 fetched records | Live Jamendo metadata API | Verified smoke for live catalog API path | 100 accepted, 0 rejected, benchmark completed, media/audio URLs redacted from raw payload JSON | Smoke-scale only; superseded by Jamendo 1k and Jamendo 10k as stronger Jamendo evidence gates |
| Jamendo 1k | 1,000 fetched records | Live Jamendo metadata API | Verified 1k live catalog API validation | 1,000 accepted, 0 rejected, 983 artist credits parsed, 1,000 single-record release identity groups, 15 benchmark cohorts/conflicts, 2 safe merge candidates, 9 blocked merges, 4 deferred conflicts | 1k validation only; superseded by Jamendo 10k as the strongest current Jamendo evidence gate |
| Jamendo 10k | 10,000 fetched records | Live Jamendo metadata API | Verified 10k live catalog API validation | 10,000 accepted, 0 rejected, 9,878 artist credits parsed, 9,945 release identity groups, 205 benchmark cohorts/conflicts, 107 safe merge candidates, 92 blocked merges, 6 deferred conflicts | Validates Jamendo at useful scale, not all Jamendo metadata or all live catalog APIs |
| Internet Archive | 1,000 fetched records | Live Internet Archive metadata search | Validated smoke/early-scale | 1,000 accepted, 0 rejected, 228 artist credits parsed, 772 unresolved artist credits, 763 missing artists, 906 release identity groups, 89 possible true duplicate groups, 5 source artifact candidates, 23 benchmark cohorts/conflicts | Early-scale only; high missing artist and unresolved artist-credit rate for `collection:opensource_audio`; does not generalize beyond this 1,000-record sample |
| Discogs | Not validated | Metadata acquisition planner exists | Blocked | Planner identifies dump-based metadata-only path | Earlier dump discovery failed; requires known dump URL before converter validation |
| YouTube metadata | Not validated | Metadata-only planning only | Intentionally deferred | High-risk source is modeled in planning and boundary classifiers | Deferred due product-identity risk; requires explicit identity-risk review first |

## Comparative Findings

MusicBrainz exercises the hardest observed release and identity complexity. In
the 50k run, 13,712 duplicate-like external records were explained by
release-aware identity analysis. The integrated benchmark then reported
`duplicate_external_records=0`, with remaining evidence expressed as structured
cohorts rather than a raw duplicate bucket. MusicBrainz also exercises
artist-credit complexity: 49,407 of 49,773 records were parsed, including
collaboration, featured-artist, ambiguous, and unresolved credit evidence.

Jamendo is cleaner in the validated samples. The Jamendo 10k run produced
9,945 release identity groups for 10,000 records, with 9,898 single-record
identities, 3 possible true duplicate groups, 44 ambiguous identity groups,
6 duplicate external records explained, and 96 duplicate external records
unresolved. Its remaining benchmark evidence is concentrated in possible
album/title-as-artist classification, artist-credit uncertainty, and small
release-identity ambiguity rather than the larger release-appearance pattern
seen in MusicBrainz.

The public fixture is the clean-clone reviewer proof. It validates that a public
checkout can run the metadata-only workflow and produce accepted/rejected
records, merge candidates, blocked merges, deferred conflicts, artist-credit
analysis, release-identity analysis, and benchmark output. It does not prove a
real-world metadata distribution.

Internet Archive 1k broadens real source coverage with a larger metadata-only
live search sample. The run fetched 1,000 records, accepted 1,000, rejected 0,
and completed import, artist-credit analysis, release-identity analysis, and
benchmarking. It also confirms the selected query has weak artist completeness:
763 records were missing artist evidence and 772 artist credits remained
unresolved. Release-identity analysis found 89 possible true duplicate groups,
and benchmarking surfaced 5 source artifact candidates. These findings are
limited to the validated `collection:opensource_audio` sample and should not be
treated as broader Internet Archive distribution claims.

## Boundary Guarantees

- External validation is metadata-only.
- No audio was downloaded.
- No local library was mutated.
- No canonical graph was mutated.
- Credential/config files are ignored, including `.config/`.
- Jamendo media, audio, and download URLs were redacted from raw payload JSON in
  the committed validation evidence.

Verified manifest boundaries include `metadata_only=true`,
`audio_downloaded=false`, `local_library_mutated=false`, and
`canonical_graph_mutated=false` for the public fixture and MusicBrainz runs.
Jamendo validation also records `metadata_only=true`,
`audio_download_allowed=false`, and `client_id_source=environment`.
Internet Archive 1k records `metadata_only=true`,
`audio_download_allowed=false`, `audio_downloaded=false`,
`local_library_mutated=false`, and `canonical_graph_mutated=false`.

## What This Proves

- A clean-clone reviewer can run the public fixture workflow without private
  data, credentials, audio, media downloads, or canonical graph mutation.
- The external metadata contract works across more than one source: the public
  fixture, MusicBrainz, Jamendo, and Internet Archive.
- The integrated benchmark can ingest multiple source distributions and produce
  explainable cohorts rather than a single undifferentiated failure bucket.
- Artist-credit analysis and release-identity analysis produce explainable
  cohorts for both complex canonical metadata and cleaner catalog API metadata.
- Duplicate-like external records can be interpreted with release identity
  context before any merge or remediation claim is made.
- Jamendo 10k validates a second live metadata source at useful scale, with
  10,000 fetched records, 10,000 accepted records, and 0 rejected records.
- Internet Archive 1k validates the live metadata acquisition path at
  smoke/early scale, with 1,000 fetched records, 1,000 accepted records, and 0
  rejected records.

## What This Does Not Prove

- Not all planned sources have been validated.
- There is no Discogs converter validation proof yet.
- Internet Archive evidence is early-scale only and does not prove broader
  Internet Archive metadata distributions.
- There is no YouTube metadata validation proof yet.
- The Jamendo 10k result does not prove all Jamendo metadata or all live catalog
  API distributions.
- There is no broad commercial user validation yet.
- There is no acoustic fingerprinting, waveform matching, or audio identity
  claim.
- There is no claim that all external metadata distributions generalize from
  these runs.

## Next Evidence Gates

1. Discogs known dump URL plus 1k/10k converter validation.
2. Internet Archive 10k metadata-only validation after the 1k result.
3. Optional YouTube metadata-only validation after product-identity risk review.
4. Local audio fixture only if legally safe synthetic files are used.
