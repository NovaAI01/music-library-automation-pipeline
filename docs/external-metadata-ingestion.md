# External Metadata Ingestion Contract v1

This contract defines a metadata-only ingestion boundary for external source
records. It exists to support large-scale validation reports without downloading,
streaming, scraping, storing, or mutating audio files.

External metadata is kept outside the local music library and outside the
canonical graph in v1.

```text
external metadata
  -> cohort validation
  -> canonical comparison
  -> optional reviewed import
```

## Supported Sources

The v1 source names are:

- `musicbrainz`
- `discogs`
- `jamendo`
- `internet_archive`
- `youtube_metadata`
- `local_fixture`

Source adapters are deterministic placeholders only. Live fetching raises
`NotImplementedError`; no API credentials or network calls are configured.

## Record Contract

Each normalized record is an `ExternalTrackRecord` with these fields:

- `source_name`
- `source_record_id`
- `artist`
- `album`
- `title`
- `track_number`
- `release_year`
- `label`
- `duration_seconds`
- `genre`
- `source_url`
- `raw_payload_json`
- `ingested_at`

Required provenance fields are always preserved for accepted records:
`source_name`, `source_record_id`, `raw_payload_json`, and `ingested_at`.

## Validation Rules

Required input:

- `source_name`
- `source_record_id`, unless it can be generated deterministically
- at least one of `artist`, `title`, or `album`

Normalization:

- leading and trailing whitespace is stripped
- empty strings are normalized to `""`
- `duration_seconds` must be an integer or empty/null
- `release_year` must be integer-like or empty/null
- `raw_payload_json` must be valid JSON and defaults to `{}`

When `source_record_id` is missing, the importer generates a stable ID from:

```text
source_name + artist + album + title + track_number
```

## Local Ingestion

CSV and JSONL are supported. CSV accepts:

- `artist`
- `album`
- `title`
- `track_number`
- `release_year`
- `label`
- `duration_seconds`
- `genre`
- `source_url`
- `raw_payload_json`
- `source_record_id`

JSONL accepts one JSON object per line with the same field names. If
`raw_payload_json` is not provided, the full line object is preserved as the raw
payload.

Run:

```bash
python -m app.main import-external-metadata \
  --source local_fixture \
  --input tests/fixtures/external_metadata_sample.csv \
  --out reports
```

Storage outputs:

```text
data/external_metadata/{source_name}/external_tracks.csv
data/external_metadata/{source_name}/external_tracks.jsonl
```

Report outputs:

```text
reports/external_metadata_ingestion/ingestion_summary.json
reports/external_metadata_ingestion/external_tracks_sample.csv
reports/external_metadata_ingestion/rejected_records.csv
```

The importer does not write to the local library database, does not feed the
canonical graph, and does not require audio file paths.
