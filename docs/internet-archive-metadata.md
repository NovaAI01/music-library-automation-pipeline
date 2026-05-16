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
