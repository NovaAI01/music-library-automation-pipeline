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
