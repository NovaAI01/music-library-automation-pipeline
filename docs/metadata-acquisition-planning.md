# Metadata Acquisition Planning

Metadata acquisition is plan-first in v1. The planner writes auditable reports for
real external metadata sources, but it does not fetch live data, call APIs,
download audio, require credentials, import records, mutate the local library DB,
or write into the canonical graph.

The planning command is:

```bash
python -m app.main plan-metadata-acquisition --source musicbrainz --out reports
```

Supported sources are `musicbrainz`, `discogs`, `internet_archive`, `jamendo`,
and `youtube_metadata`.

## Why No Live Fetch Happens In v1

External music sources differ in licensing, terms, identity quality, data shape,
rate limits, and product boundaries. A planner-only layer keeps those decisions
reviewable before any ingestion work happens. It also prevents a metadata feature
from drifting into audio acquisition, marketplace, credential, scraping, or
canonical graph behavior.

The generated plan describes where manually acquired metadata dumps or exports
should be placed, what normalized local input file the existing importer expects,
and which existing benchmark command should be run after import.

## Recommended Source Order

1. `musicbrainz`: preferred first source. It is metadata-centric and marked low
   risk when used as a local metadata dump or prepared CSV.
2. `jamendo`: low-to-medium risk for metadata-only planning. Credentials are
   optional or future, not required in v1.
3. `discogs`: medium risk. Use dump metadata only; keep marketplace and purchase
   workflows out of scope.
4. `internet_archive`: medium risk. Metadata exports may reference downloadable
   files, so the no-file-download boundary must stay explicit.
5. `youtube_metadata`: high risk. Use metadata-only exports with skip-download
   style provenance and keep audio acquisition out of scope.

## SSD Data Root

Large datasets must stay out of the repository. Set
`MUSIC_INTELLIGENCE_DATA_ROOT` to an external SSD or another non-repo storage
location:

```bash
export MUSIC_INTELLIGENCE_DATA_ROOT="/media/$USER/MusicIntelSSD/music_intelligence_data"
```

The planner targets:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/raw_dumps/{source}/
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/{source}/
$MUSIC_INTELLIGENCE_DATA_ROOT/cache/{source}/
```

If the environment variable is absent, the existing fallback data root helper
uses `data/`.

## Manual Execution

Generate and inspect the plan first:

```bash
python -m app.main plan-metadata-acquisition --source musicbrainz --out reports
cat reports/metadata_acquisition/acquisition_plan.json
head -40 reports/metadata_acquisition/acquisition_steps.csv
cat reports/metadata_acquisition/source_risk_assessment.json
```

Then manually place metadata-only dumps or exports under the plan's
`raw_dump_target`. Preprocess them outside planner v1 into the plan's
`expected_normalized_input` file using the existing external metadata ingestion
schema.

Run only the generated import and benchmark commands after confirming the input
is metadata-only:

```bash
python -m app.main import-external-metadata \
  --source musicbrainz \
  --input "$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/musicbrainz/raw_musicbrainz.csv" \
  --out reports

python -m app.main benchmark-validation \
  --source musicbrainz \
  --out reports
```

Do not commit raw dumps, normalized large metadata files, cache directories, or
other large source artifacts. Commit only code, tests, docs, and small report
samples that are intentionally curated for documentation.
