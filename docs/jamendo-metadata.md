# Jamendo Metadata Acquisition

`fetch-jamendo-metadata` is a metadata-only acquisition command for Jamendo
track catalog records. It fetches JSON metadata, normalizes records into the
existing `ExternalTrackRecord` CSV contract, and leaves import and benchmarking
to the existing external metadata pipeline.

It does not download audio, request streams, write media files, mutate local
music files, touch the local music database, or write into the canonical graph.

## Client ID

Live Jamendo API access requires a client identifier. The command resolves it in
this order:

1. `--client-id`
2. `JAMENDO_CLIENT_ID`

When neither is available, it exits before writing outputs and prints:

```text
JAMENDO_CLIENT_ID is required for live Jamendo metadata acquisition
```

## Fetch Metadata

```bash
python -m app.main fetch-jamendo-metadata \
  --limit 1000 \
  --out reports
```

Optional arguments:

```bash
--page-size 100
--source jamendo
--client-id "$JAMENDO_CLIENT_ID"
--timeout 30
--dry-run
```

The command writes normalized metadata under the configured data root:

```bash
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/jamendo/raw_jamendo.csv
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/jamendo/raw_jamendo.jsonl
```

It also writes acquisition reports:

```bash
reports/jamendo_metadata/acquisition_summary.json
reports/jamendo_metadata/rejected_records.csv
reports/jamendo_metadata/sample_records.csv
```

During live paginated fetches, the command prints one progress line per fetched
page before the final summary:

```text
fetching_jamendo_metadata requested_limit=1000 page_size=100
jamendo_progress fetched=100 accepted=100 rejected=0 requested=1000
```

The summary always records:

```json
{
  "metadata_only": true,
  "audio_download_allowed": false
}
```

## Import

Use the existing external metadata importer after acquisition:

```bash
python -m app.main import-external-metadata \
  --source jamendo \
  --input "$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/jamendo/raw_jamendo.csv" \
  --out reports
```

## Benchmark

Then benchmark the imported metadata using the existing read-only validation
benchmark:

```bash
python -m app.main benchmark-validation \
  --source jamendo \
  --out reports
```

## Why This Source

Jamendo is useful as a second external validation source after MusicBrainz
because it contributes independent track, artist, album, duration, tag, and
release-date evidence from a music catalog. That makes it useful for
cross-source validation and cohort analysis while keeping acquisition strictly
limited to metadata.
