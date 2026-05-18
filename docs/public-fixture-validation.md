# Public Fixture Validation

This workflow proves the metadata intelligence report path with a public,
reproducible fixture. The fixture is fictional metadata only. It does not include
audio, download audio, fetch live network data, require API credentials, read
private library paths, write tags, mutate music files, or alter the canonical
graph.

## Fixture

Input:

```text
examples/fixture_library/external_metadata_fixture.csv
```

The CSV uses the existing `ExternalTrackRecord` local input columns and includes
clean records, casing aliases, punctuation variants, duplicate-like release
appearances, possible true duplicates, collaboration strings, featured artists,
ambiguous group names, remaster/version/edit noise, source/uploader artifacts,
and malformed rows that are rejected during import.

## One-command path

Run from the repository root:

```bash
python -m app.main run-public-fixture-validation
```

The command runs the same metadata-only workflow end to end and prints the final
output directory:

```text
reports/runs/local_fixture/public_fixture/
```

To write reports somewhere else while preserving the same run layout:

```bash
python -m app.main run-public-fixture-validation --out /tmp/public-fixture-reports
```

## Manual four-command path

The equivalent manual path is:

```bash
python -m app.main import-external-metadata \
  --source local_fixture \
  --input examples/fixture_library/external_metadata_fixture.csv \
  --out reports \
  --run-label public_fixture

python -m app.main analyze-artist-credits \
  --source local_fixture \
  --out reports \
  --run-label public_fixture

python -m app.main analyze-release-identity \
  --source local_fixture \
  --out reports \
  --run-label public_fixture

python -m app.main benchmark-validation \
  --source local_fixture \
  --out reports \
  --run-label public_fixture
```

Generated outputs are local ignored files under:

```text
reports/runs/local_fixture/public_fixture/
```

## Expected Outputs

Inspect the run manifest and summaries:

```bash
cat reports/runs/local_fixture/public_fixture/run_manifest.json
cat reports/runs/local_fixture/public_fixture/external_metadata_ingestion/ingestion_summary.json
cat reports/runs/local_fixture/public_fixture/artist_credit_analysis/artist_credit_summary.json
cat reports/runs/local_fixture/public_fixture/release_identity_analysis/release_identity_summary.json
cat reports/runs/local_fixture/public_fixture/validation_benchmark/benchmark_summary.json
head -40 reports/runs/local_fixture/public_fixture/validation_benchmark/top_failure_cohorts.csv
```

Expected categories are documented in:

```text
examples/fixture_library/expected_summary.md
```

The run should show accepted and rejected import rows, artist-credit analysis
usage, release-identity analysis usage, safe merge candidates, deferred
duplicate/version/collaboration cohorts, blocked unresolved/source-artifact
cohorts, and a manifest with `metadata_only=true`.
