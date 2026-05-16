# External Data Root

Large runtime metadata artifacts should live outside the git repository. The
application uses a configurable data root for external metadata dumps, imported
external records, validation working data, caches, and future raw source dumps.

Set `MUSIC_INTELLIGENCE_DATA_ROOT` to place those files on an external SSD:

```bash
export MUSIC_INTELLIGENCE_DATA_ROOT="/media/$USER/MusicIntelSSD/music_intelligence_data"
```

If the variable is not set, the fallback is:

```text
data/
```

The fallback is convenient for small local fixtures, but large datasets should
use an external SSD path. Do not commit bulk metadata into the repository.

## Stored Layout

The data root is created automatically. Current and reserved subdirectories are:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/
  external_metadata/
    {source_name}/
      external_tracks.csv
      external_tracks.jsonl
  raw_dumps/
  cache/
  reports/
```

External metadata import writes normalized records under
`external_metadata/{source_name}/`. Source names are sanitized and path traversal
is rejected before paths are generated.

CLI report output is separate. Existing commands such as `--out reports` still
write report files to the path passed by `--out`; setting the data root does not
force report output onto the SSD.

## Example Workflow

```bash
export MUSIC_INTELLIGENCE_DATA_ROOT="/media/$USER/MusicIntelSSD/music_intelligence_data"

python -m app.main import-external-metadata \
  --source local_fixture \
  --input tests/fixtures/external_metadata_sample.csv \
  --out reports

python -m app.main validate-external-metadata \
  --source local_fixture \
  --out reports
```

## Do Not Commit

Do not commit:

- `data/`
- external metadata dumps
- imported `external_tracks.csv` or `external_tracks.jsonl` datasets
- generated validation reports from large runs
- caches or raw downloaded source payloads

Only commit code, tests, small fixtures under `tests/fixtures/`, and docs.
