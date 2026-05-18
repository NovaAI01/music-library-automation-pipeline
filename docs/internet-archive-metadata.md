# Internet Archive Metadata Acquisition

`fetch-internet-archive-metadata` is a metadata-only acquisition command for
public Internet Archive search records. It uses the Internet Archive advanced
search JSON endpoint and writes normalized `ExternalTrackRecord` input files.

It does not download audio, media files, item file lists, streams, or item
payloads. It does not mutate local music files, the local music database, or the
canonical graph.

## Fetch Metadata

```bash
python -m app.main fetch-internet-archive-metadata \
  --query "collection:audio" \
  --limit 10000 \
  --out reports
```

Optional arguments:

```bash
--page-size 100
--source internet_archive
--timeout 30
--dry-run
```

The command writes acquisition outputs under the configured data root:

```bash
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/internet_archive/raw_internet_archive.csv
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/internet_archive/raw_internet_archive.jsonl
```

It also writes reports:

```bash
reports/internet_archive_metadata/acquisition_summary.json
reports/internet_archive_metadata/rejected_records.csv
reports/internet_archive_metadata/sample_records.csv
```

The summary always records:

```json
{
  "metadata_only": true,
  "audio_download_allowed": false
}
```

## Artist Mapping Guardrails

The current Internet Archive mapping treats `creator` as the only approved
source-level artist field. When `creator` is present, list-valued creator
metadata is normalized into the importer `artist` field. When `creator` is
missing, `artist` remains blank even if other metadata fields are present.

The following fields are intentionally not used as artist fallbacks:

- `collection`: source grouping or category evidence. It may help describe the
  archive location or album-like grouping, but it is not artist identity.
- `subject`: tag, topic, or genre-like evidence. It may describe content, but
  it is too broad to promote into artist identity.
- `title`: display title evidence only. Title-like strings such as
  `Artist - Track` are not parsed into source-level artist mapping.
- uploader-like fields such as `uploader`, `uploader_email`, or contributor
  metadata: source-account or submission evidence. These fields must not
  populate artist unless a future evidence review separately approves that
  behavior.

These guardrails preserve the metadata-only boundary. They do not authorize
audio downloads, local file mutation, local database mutation, canonical graph
mutation, or speculative enrichment from weak Internet Archive fields.

## Import

Use the existing external metadata importer after acquisition:

```bash
python -m app.main import-external-metadata \
  --source internet_archive \
  --input "$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/internet_archive/raw_internet_archive.csv" \
  --out reports
```

## Benchmark

Then benchmark the imported metadata using the existing read-only validation
benchmark:

```bash
python -m app.main benchmark-validation \
  --source internet_archive \
  --out reports
```

## Why This Source

Internet Archive metadata is useful validation input because public archive
records are messy: creators may be missing or list-valued, collections often
stand in for albums, dates may be inconsistent, and subject fields can carry
genre-like information. That makes it a good stress test for normalization,
cohort reporting, and rejection handling without introducing media download
behavior.
