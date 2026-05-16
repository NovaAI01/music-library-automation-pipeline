# MusicBrainz Dump Conversion v1

The MusicBrainz dump converter is a metadata-only bridge from locally extracted
MusicBrainz dump tables into the existing `ExternalTrackRecord` CSV input
contract. It does not download audio, call MusicBrainz APIs, scrape websites,
write tags, mutate the local music library, or write into the canonical graph.

## Inputs

The converter expects already extracted MusicBrainz dump tables under a local
dump directory, for example:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/raw_dumps/musicbrainz/20260513-001936/extracted/mbdump/
  artist
  artist_credit
  artist_credit_name
  recording
  release
  release_group
  medium
  track
```

MusicBrainz dump files are tab-delimited and headerless. v1 reads the table
positions used by the MusicBrainz core dump schema and only maps fields needed
for external metadata validation.

Large dump files stay outside the repository under
`MUSIC_INTELLIGENCE_DATA_ROOT`. Do not commit raw dump data, generated large CSVs,
caches, or large validation reports.

## Output

The command writes:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/musicbrainz/raw_musicbrainz.csv
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/musicbrainz/raw_musicbrainz_rejected.csv
reports/musicbrainz_conversion/conversion_summary.json
```

`raw_musicbrainz.csv` uses the input fields accepted by
`import-external-metadata`:

```text
source_record_id,artist,album,title,track_number,release_year,label,duration_seconds,genre,source_url,raw_payload_json
```

`raw_musicbrainz_rejected.csv` captures rows missing required converter fields:
artist, album, or title. It includes `source_record_id`, `rejection_reason`, and
`raw_payload_json` for traceability.

## First Run

Use `--limit` for controlled validation before processing more rows:

```bash
python -m app.main convert-musicbrainz-dump \
  --dump-dir "$MUSIC_INTELLIGENCE_DATA_ROOT/raw_dumps/musicbrainz/20260513-001936/extracted/mbdump" \
  --out "$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/musicbrainz/raw_musicbrainz.csv" \
  --limit 10000
```

The bounded strategy is:

1. Read `track` rows up to `--limit`.
2. Collect needed recording, medium, and artist credit IDs.
3. Read `medium` only for needed medium IDs.
4. Read `release` only for needed release IDs.
5. Read `recording` only for needed recording IDs.
6. Read `artist_credit_name` only for needed artist credit IDs.
7. Read `artist` only for needed artist IDs.

This avoids loading the full `track` table into memory during limit-based
validation runs.

## Downstream Validation

After conversion, import and benchmark the metadata-only records:

```bash
python -m app.main import-external-metadata \
  --source musicbrainz \
  --input "$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/musicbrainz/raw_musicbrainz.csv" \
  --out reports

python -m app.main benchmark-validation \
  --source musicbrainz \
  --out reports
```

These downstream commands remain read-only with respect to audio files and the
canonical graph.
