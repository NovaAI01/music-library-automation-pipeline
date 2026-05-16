"""Read-only health reports for an organised music library."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.scanner import is_supported_audio_file


ARTIST_HEADERS: tuple[str, ...] = ("artist", "genre", "subgenre", "file_count")
GENRE_HEADERS: tuple[str, ...] = (
    "genre",
    "subgenre",
    "artist_count",
    "file_count",
)
QUARANTINE_HEADERS: tuple[str, ...] = ("extension", "file_count", "size_bytes")
FILE_HEALTH_HEADERS: tuple[str, ...] = ("path", "size_bytes", "extension", "status")


@dataclass(frozen=True)
class LibraryQAResult:
    report_path: str
    total_library_files: int
    total_quarantine_files: int
    genre_count: int
    subgenre_count: int
    artist_count: int
    album_count: int
    active_duplicate_group_count: int
    historical_duplicate_group_count: int
    quarantined_duplicate_file_count: int
    missing_file_count: int
    unresolved_missing_file_count: int


@dataclass(frozen=True)
class FileRecord:
    path: Path
    relative_path: str
    size_bytes: int
    extension: str
    status: str


def generate_library_qa_report(
    *,
    library_root: str | Path,
    quarantine_root: str | Path,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> LibraryQAResult:
    """Export a read-only QA snapshot for the library and quarantine trees."""

    library_root_path = Path(library_root).expanduser()
    quarantine_root_path = Path(quarantine_root).expanduser()
    report_dir = Path(out_dir).expanduser() / "library_qa"
    report_dir.mkdir(parents=True, exist_ok=True)

    library_files = _audio_file_records(
        library_root_path,
        root_label="library",
    )
    quarantine_files = _audio_file_records(
        quarantine_root_path,
        root_label="quarantine",
    )
    missing_files = _missing_placement_records(library_root_path, db_path)
    unresolved_missing_files = _unresolved_missing_records(
        missing_files,
        library_root=library_root_path,
        quarantine_root=quarantine_root_path,
        db_path=db_path,
    )

    artists = _artist_rows(library_files)
    genres = _genre_rows(library_files)
    quarantine_summary = _quarantine_rows(quarantine_files)
    active_duplicate_group_count = _active_duplicate_group_count(
        library_root_path,
        db_path,
    )
    historical_duplicate_group_count = _historical_duplicate_group_count(db_path)
    created_at = datetime.now(UTC).isoformat()

    summary = {
        "library_root": str(library_root_path),
        "quarantine_root": str(quarantine_root_path),
        "total_library_files": len(library_files),
        "total_quarantine_files": len(quarantine_files),
        "total_library_size_bytes": sum(record.size_bytes for record in library_files),
        "total_quarantine_size_bytes": sum(
            record.size_bytes for record in quarantine_files
        ),
        "genre_count": len({row["genre"] for row in genres}),
        "subgenre_count": len(
            {(row["genre"], row["subgenre"]) for row in genres if row["subgenre"]}
        ),
        "artist_count": len({row["artist"] for row in artists}),
        "album_count": len(_album_keys(library_files)),
        "active_duplicate_group_count": active_duplicate_group_count,
        "historical_duplicate_group_count": historical_duplicate_group_count,
        "quarantined_duplicate_file_count": len(quarantine_files),
        "missing_file_count": len(missing_files),
        "unresolved_missing_file_count": len(unresolved_missing_files),
        "created_at": created_at,
    }

    _write_json(report_dir / "library_qa_summary.json", summary)
    _write_csv(report_dir / "artists.csv", ARTIST_HEADERS, artists)
    _write_csv(report_dir / "genres.csv", GENRE_HEADERS, genres)
    _write_csv(
        report_dir / "quarantine_summary.csv",
        QUARANTINE_HEADERS,
        quarantine_summary,
    )
    _write_csv(
        report_dir / "file_health.csv",
        FILE_HEALTH_HEADERS,
        [_file_health_row(record) for record in [*library_files, *quarantine_files]]
        + [_file_health_row(record) for record in missing_files],
    )

    return LibraryQAResult(
        report_path=str(report_dir),
        total_library_files=summary["total_library_files"],
        total_quarantine_files=summary["total_quarantine_files"],
        genre_count=summary["genre_count"],
        subgenre_count=summary["subgenre_count"],
        artist_count=summary["artist_count"],
        album_count=summary["album_count"],
        active_duplicate_group_count=summary["active_duplicate_group_count"],
        historical_duplicate_group_count=summary["historical_duplicate_group_count"],
        quarantined_duplicate_file_count=summary["quarantined_duplicate_file_count"],
        missing_file_count=summary["missing_file_count"],
        unresolved_missing_file_count=summary["unresolved_missing_file_count"],
    )


def _audio_file_records(root: Path, *, root_label: str) -> list[FileRecord]:
    if not root.exists() or not root.is_dir():
        return []

    records: list[FileRecord] = []
    for path in _iter_visible_files(root):
        if not is_supported_audio_file(path):
            continue
        relative_path = path.relative_to(root).as_posix()
        records.append(
            FileRecord(
                path=path,
                relative_path=relative_path,
                size_bytes=path.stat().st_size,
                extension=path.suffix.lower(),
                status=f"{root_label}_present",
            )
        )
    return records


def _iter_visible_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def _artist_rows(records: Iterable[FileRecord]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for record in records:
        genre, subgenre, artist = _path_taxonomy(record.relative_path)
        if artist:
            counts[(artist, genre, subgenre)] += 1

    return [
        {
            "artist": artist,
            "genre": genre,
            "subgenre": subgenre,
            "file_count": count,
        }
        for (artist, genre, subgenre), count in sorted(counts.items())
    ]


def _genre_rows(records: Iterable[FileRecord]) -> list[dict[str, Any]]:
    file_counts: Counter[tuple[str, str]] = Counter()
    artists_by_genre: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        genre, subgenre, artist = _path_taxonomy(record.relative_path)
        if not genre:
            continue
        key = (genre, subgenre)
        file_counts[key] += 1
        if artist:
            artists_by_genre[key].add(artist)

    return [
        {
            "genre": genre,
            "subgenre": subgenre,
            "artist_count": len(artists_by_genre[(genre, subgenre)]),
            "file_count": file_counts[(genre, subgenre)],
        }
        for genre, subgenre in sorted(file_counts)
    ]


def _album_keys(records: Iterable[FileRecord]) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for record in records:
        genre, subgenre, artist, album = _path_album(record.relative_path)
        if artist and album:
            keys.add((genre, subgenre, artist, album))
    return keys


def _quarantine_rows(records: Iterable[FileRecord]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    for record in records:
        counts[record.extension] += 1
        sizes[record.extension] += record.size_bytes

    return [
        {
            "extension": extension,
            "file_count": counts[extension],
            "size_bytes": sizes[extension],
        }
        for extension in sorted(counts)
    ]


def _path_taxonomy(relative_path: str) -> tuple[str, str, str]:
    parts = Path(relative_path).parts
    genre = parts[0] if len(parts) >= 1 else ""
    subgenre = parts[1] if len(parts) >= 2 else ""
    artist = parts[2] if len(parts) >= 3 else ""
    return genre, subgenre, artist


def _path_album(relative_path: str) -> tuple[str, str, str, str]:
    parts = Path(relative_path).parts
    genre, subgenre, artist = _path_taxonomy(relative_path)
    album = parts[3] if len(parts) >= 5 else ""
    return genre, subgenre, artist, album


def _missing_placement_records(
    library_root: Path,
    db_path: str | Path,
) -> list[FileRecord]:
    database_path = Path(db_path).expanduser()
    if not database_path.exists():
        return []

    rows = _safe_query(
        database_path,
        """
        SELECT destination_path
        FROM placement_execution_files
        WHERE file_status IN ('copied', 'skipped_exists')
        ORDER BY destination_path
        """,
    )
    if rows is None:
        return []

    records: list[FileRecord] = []
    library_root_resolved = library_root.resolve(strict=False)
    seen: set[str] = set()
    for row in rows:
        destination = Path(row["destination_path"]).expanduser()
        if not destination.is_absolute():
            destination = library_root / destination
        try:
            destination.resolve(strict=False).relative_to(library_root_resolved)
        except ValueError:
            continue
        destination_key = str(destination)
        if destination.exists() or destination_key in seen:
            continue
        seen.add(destination_key)
        records.append(
            FileRecord(
                path=destination,
                relative_path=destination_key,
                size_bytes=0,
                extension=destination.suffix.lower(),
                status="missing_placement_file",
            )
        )
    return records


def _unresolved_missing_records(
    records: list[FileRecord],
    *,
    library_root: Path,
    quarantine_root: Path,
    db_path: str | Path,
) -> list[FileRecord]:
    quarantined_sources = _quarantined_source_paths(db_path)
    library_root_resolved = library_root.resolve(strict=False)
    quarantine_root_resolved = quarantine_root.resolve(strict=False)

    unresolved: list[FileRecord] = []
    for record in records:
        destination = record.path.expanduser()
        destination_resolved = destination.resolve(strict=False)
        if str(destination_resolved) in quarantined_sources:
            continue
        try:
            relative_path = destination_resolved.relative_to(library_root_resolved)
        except ValueError:
            unresolved.append(record)
            continue
        quarantine_path = quarantine_root_resolved / relative_path
        if quarantine_path.is_file():
            continue
        unresolved.append(record)
    return unresolved


def _quarantined_source_paths(db_path: str | Path) -> set[str]:
    database_path = Path(db_path).expanduser()
    if not database_path.exists():
        return set()

    rows = _safe_query(
        database_path,
        """
        SELECT source_path, quarantine_path
        FROM duplicate_quarantine_items
        WHERE item_status IN ('moved', 'skipped_exists')
        """,
    )
    if rows is None:
        return set()

    paths: set[str] = set()
    for row in rows:
        quarantine_path = Path(row["quarantine_path"]).expanduser()
        if quarantine_path.is_file():
            paths.add(str(Path(row["source_path"]).expanduser().resolve(strict=False)))
    return paths


def _active_duplicate_group_count(library_root: Path, db_path: str | Path) -> int:
    database_path = Path(db_path).expanduser()
    if not database_path.exists():
        return 0

    rows = _safe_query(
        database_path,
        """
        SELECT duplicate_group_key, file_path
        FROM duplicate_candidates
        ORDER BY duplicate_group_key, file_path
        """,
    )
    if rows is None:
        return 0

    library_root_resolved = library_root.resolve(strict=False)
    live_files_by_group: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        file_path = Path(row["file_path"]).expanduser()
        if not file_path.is_absolute():
            file_path = library_root / file_path
        if not file_path.is_file():
            continue
        try:
            resolved_file_path = file_path.resolve(strict=True)
            resolved_file_path.relative_to(library_root_resolved)
        except ValueError:
            continue
        live_files_by_group[row["duplicate_group_key"]].add(str(resolved_file_path))

    return sum(1 for paths in live_files_by_group.values() if len(paths) >= 2)


def _historical_duplicate_group_count(db_path: str | Path) -> int:
    database_path = Path(db_path).expanduser()
    if not database_path.exists():
        return 0

    rows = _safe_query(
        database_path,
        "SELECT COUNT(DISTINCT duplicate_group_key) AS group_count FROM duplicate_candidates",
    )
    if not rows:
        return 0
    return int(rows[0]["group_count"] or 0)


def _safe_query(database_path: Path, sql: str) -> list[sqlite3.Row] | None:
    try:
        with db.connect(database_path) as connection:
            return connection.execute(sql).fetchall()
    except sqlite3.Error:
        return None


def _file_health_row(record: FileRecord) -> dict[str, Any]:
    return {
        "path": str(record.path),
        "size_bytes": record.size_bytes,
        "extension": record.extension,
        "status": record.status,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file_handle:
        json.dump(payload, file_handle, indent=2, sort_keys=True)
        file_handle.write("\n")


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=list(headers))
        writer.writeheader()
        writer.writerows(rows)
