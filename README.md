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

Use `--db PATH` before the subcommand to select a different SQLite database:

```bash
python -m app.main --db /tmp/music.sqlite3 scan --source /path/to/music
```

Supported audio extensions are `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`,
`.ogg`, `.aiff`, and `.webm`.

Audio probing uses `ffprobe` when available. If probing fails, the scan records
the failure in SQLite and continues.
