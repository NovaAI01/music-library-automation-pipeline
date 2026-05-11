# Music Library Normalization System

This project builds a local, SQLite-backed observation ledger for music-library
normalization. The scanner is read-only: it does not modify, move, rename, or
delete source files.

## Artist Seeds

`app/artist_seeds.py` contains the controlled artist seed library used for
artist-first classification when metadata or filename evidence identifies a
seed artist.

## Observation Ledger

Initialize the SQLite schema:

```bash
python -m app.main init-db
```

Scan a local music folder:

```bash
python -m app.main scan --source /path/to/music
```

Show a scan summary:

```bash
python -m app.main summary --scan-run-id 1
```

Resolve probable track identity for a scan run:

```bash
python -m app.main identify --scan-run-id 1
```

Classify identified tracks for a scan run:

```bash
python -m app.main classify --scan-run-id 1
```

Create and manage purchase gateway records:

```bash
python -m app.main purchase-request --artist "Deftones" --title "Change"
python -m app.main purchase-option-add --request-id 1 --provider "Bandcamp" --url "https://example.com" --type digital_download --price 1.29 --currency GBP --scope "private DJ use"
python -m app.main purchase-proof-add --option-id 1 --proof ~/Receipts/deftones-change.pdf --status user_declared
python -m app.main purchase-unlock --request-id 1
python -m app.main purchase-report
```

Copy unlocked local purchases into the controlled intake area:

```bash
python -m app.main intake --purchase-request-id 1 --source ~/Downloads/PurchasedMusic --dest ~/Music/Library_Intake
```

Run scan, identity, and classification for an intake batch:

```bash
python -m app.main pipeline-run --intake-batch-id 1
python -m app.main pipeline-run --intake-batch-id 1 --rerun
```

Plan output placement for a scan run:

```bash
python -m app.main plan-placement --scan-run-id 1
```

Generate review reports from placement plans:

```bash
python -m app.main review-report --scan-run-id 1 --out reports
```

Use `--db PATH` before the subcommand to select a different SQLite database:

```bash
python -m app.main --db /tmp/music.sqlite3 scan --source /path/to/music
```

Supported audio extensions are `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`,
`.ogg`, `.aiff`, and `.webm`.

Audio probing uses `ffprobe` when available. If probing fails, the scan records
the failure in SQLite and continues.

## Track Identity Engine

`app/identity_engine.py` resolves probable artist, title, album, year, and mix
from observed tags, filename evidence, parent folder names, and artist seed
matches. It records identity evidence only in the `track_identity` table and
does not classify genres, organize folders, move files, convert audio, or
generate playlists.

When filename artist evidence matches a controlled artist seed, the identity
engine deprioritizes embedded tag artists that look like uploader, channel, or
label metadata instead of treating them as stronger artist evidence. These
deprioritized uploader or label tags do not force a conflicting identity when
the filename artist is a seed match; the row remains identified with filename
artist and title evidence. Parent-folder seed artist matches provide the same
support when filename artist evidence is missing. Seed artists embedded in title
text are also used when they appear as an artist prefix, artist suffix, first
artist in a collaboration or feature prefix, or whitespace-separated artist
prefix, such as `Static-X - Push It`, `3 Libras - A Perfect Circle`,
`Loathe & Teenage Wrist - Is It Really You`, and `Spiritbox   Holy Roller`.
Conflicts are preserved when separate primary artist evidence contains two
different controlled seed artists. Common YouTube title suffixes and source
markers such as `[Official Video]`, `(Official Audio)`, `(Official Audio
Stream)`, `(HD)`, `[Full Dynamic Range Edition]`, `| Warner Vault`,
`[KvknOXGPzCQ]`, and `[EXPLICIT]` are removed from probable titles, and
repeated filename artist prefixes such as `Deftones - Be Quiet And Drive`,
`Deftones – Risk`, and `Deftones — Tempest` are trimmed when they match the
resolved artist.

## Classification Engine

`app/classifier.py` classifies identified tracks from artist seed matches first
and embedded genre metadata second. It records deterministic classification
evidence in `classification_results` and does not organize folders, deduplicate,
move files, convert audio, or expand the artist seed list.

## Artist Purchase Gateway

`app/purchase_gateway.py` records purchase requests, manually supplied purchase
URLs, user proof metadata, and intake unlock decisions for artists already in
the baseline seed list. It does not download files, automate checkout, store
payment credentials, bypass DRM, scrape protected audio, or ingest purchased
files automatically.

## Local File Intake

`app/intake.py` copies legally obtained local files into a controlled intake
area only when the purchase request has an `intake_unlocks` row. It preserves
relative folder structure, skips unsupported files, records duplicate SHA-256
files inside a batch, and never overwrites an existing destination file.

## Intake Pipeline Bridge

`app/pipeline.py` bridges an intake batch into the existing scan, identity, and
classification stages. It records stage status in `pipeline_runs`, blocks
duplicate runs unless `--rerun` is passed, and does not organize folders, move
source files, convert audio, generate playlists, or download music.

## Placement Planner

`app/placement_planner.py` creates deterministic relative placement plans from
identity and classification evidence using `Primary Genre/Subgenre/Artist` and
`Artist - Title.ext`. It writes only `placement_plans` rows and does not copy,
move, convert, delete, or mutate music files.

## Review Reports

`app/review_report.py` exports placement plans into stable JSON and CSV files
under `reports/scan_<SCAN_RUN_ID>/` for review before any execution step exists.
It records generated report metadata in `review_reports` and does not modify
music files or placement plans.
