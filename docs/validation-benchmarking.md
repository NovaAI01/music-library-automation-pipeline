# Validation Benchmarking

Validation benchmarking is a v1 stabilization workflow for measuring how the
existing metadata validation architecture behaves against larger local evidence
sets. It does not add intelligence systems, change governance decisions, or
write into the canonical graph.

## Purpose

The benchmark command reads one source dataset from:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/{source}/external_tracks.csv
```

If `MUSIC_INTELLIGENCE_DATA_ROOT` is not set, the fallback is `data/`.

It reuses the existing external metadata cohort analyzer, then writes summary,
distribution, ranking, and timing reports under:

```text
reports/validation_benchmark/
```

The goal is operational measurement: record volume, cohort distribution,
severity mix, benchmark timing, and benchmark-level governance posture.

If matching artist-credit parser reports already exist under
`reports/artist_credit_analysis/`, the benchmark also reads:

```text
reports/artist_credit_analysis/artist_credit_summary.json
reports/artist_credit_analysis/parsed_artist_credits.csv
```

The artist-credit summary must match the benchmark source name. When it does,
the benchmark replaces the raw `collaboration_string` aggregate with
artist-credit cohorts that separate explained parser output from unresolved
artist credits.

If matching release identity analysis reports already exist under
`reports/release_identity_analysis/`, the benchmark also reads:

```text
reports/release_identity_analysis/release_identity_summary.json
reports/release_identity_analysis/identity_groups.csv
```

The release identity summary must match the benchmark source name. When it
does, the benchmark replaces the raw `duplicate_external_record` aggregate with
release-aware cohorts that separate legitimate release appearances from
possible true duplicates and unresolved identity clusters.

## Why Scale Validation Matters

Small fixtures prove that individual rules behave correctly. Larger evidence
sets show whether the architecture remains stable when repeated source
artifacts, duplicate external records, collaboration strings, malformed fields,
and sparse records appear together. The benchmark makes those distributions
visible before feature growth continues.

This helps answer practical stabilization questions:

- Which cohort types dominate the dataset?
- How many validation cohorts are high, medium, or low severity?
- Which cohorts would be blocked, deferred, or only safe-to-review at the
  benchmark layer?
- How long does loading, cohort analysis, governance analysis, and report
  generation take?
- How many collaboration-like artist credits are parser-explained, and how
  many remain unresolved?
- How many duplicate-looking records are legitimate release appearances, and
  how many remain possible true duplicates or unresolved?

## Artist Credit Integration

Artist Credit Parsing v1 feeds validation benchmarking only as reporting
evidence. It does not mutate canonical graph behavior, auto-merge artists,
write tags, or change source metadata.

When the parser report is present, benchmark cohorts include:

- `artist_credit_parsed_high_confidence`
- `artist_credit_parsed_medium_confidence`
- `artist_credit_unresolved`
- `artist_credit_featured`
- `artist_credit_collaboration`
- `artist_credit_ambiguous_group`

High-confidence parsed artist credits are low severity because the parser can
explain the collaboration-like syntax. Medium-confidence collaborations,
featured-artist roles, and ambiguous group-name boundaries remain medium
severity review evidence. Low-confidence unresolved artist credits remain high
severity because they are not safe canonical artist evidence.

If no matching artist-credit analysis report exists, benchmark output preserves
the legacy raw `collaboration_string` cohort.

## Release Identity Integration

Release-Aware Identity Analysis v1 feeds validation benchmarking only as
reporting evidence. It does not mutate canonical graph behavior, auto-merge
tracks, delete duplicates, change duplicate quarantine behavior, write tags, or
change source metadata.

When the release identity report is present, benchmark cohorts include:

- `release_identity_legitimate_appearance`
- `release_identity_possible_true_duplicate`
- `release_identity_edition_or_reissue`
- `release_identity_compilation_or_multi_release`
- `release_identity_ambiguous`
- `release_identity_unresolved_duplicate_like`

Legitimate release appearances are low severity because MusicBrainz recording
and release evidence explains the duplicate-looking rows. Edition/reissue and
compilation/multi-release clusters remain medium severity because release
context must be preserved before future remediation. Possible true duplicates,
ambiguous groups, and unresolved duplicate-like records remain high severity.

If no matching release identity analysis report exists, benchmark output
preserves the legacy raw `duplicate_external_record` cohort. Duplicate-looking
external records are not removable duplicates by default.

## No Mutation Boundary

`benchmark-validation` is read-only. It does not mutate source datasets, local
music libraries, media tags, the local music database, canonical graph tables,
or governance reports. It only reads the local `external_tracks.csv` file for
the selected source and writes benchmark artifacts under the requested reports
directory.

The command does not perform network ingestion, call AI APIs, download music,
or enrich metadata from remote services.

## No Autonomous Refinement

Benchmark governance distribution is measurement only. It classifies validation
cohorts into reporting buckets such as `safe_to_merge_candidate`,
`blocked_merge`, `deferred`, `resolved`, and `none`, but it does not update the
canonical graph or conflict governance engine.

Any remediation, graph promotion, merge, tag update, or dataset cleanup remains
outside this phase and requires explicit future review boundaries.

## Architecture Stabilization Before Feature Growth

This phase is intentionally conservative. It validates whether the current
architecture can explain larger metadata evidence sets before adding more
features. The benchmark should be used to compare output stability, cohort mix,
and timing across fixture sizes and source types while preserving v1 product
scope.

Run:

```bash
python -m app.main benchmark-validation --source local_fixture --out reports
```

Expected outputs:

```text
reports/validation_benchmark/benchmark_summary.json
reports/validation_benchmark/cohort_distribution.csv
reports/validation_benchmark/severity_distribution.csv
reports/validation_benchmark/governance_distribution.csv
reports/validation_benchmark/top_failure_cohorts.csv
reports/validation_benchmark/benchmark_timing.json
```
