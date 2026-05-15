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
