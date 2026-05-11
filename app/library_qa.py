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
    duplicate_group_count: int
    missing_file_count: int


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

    artists = _artist_rows(library_files)
    genres = _genre_rows(library_files)
    quarantine_summary = _quarantine_rows(quarantine_files)
    duplicate_group_count = _duplicate_group_count(db_path)
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
        "duplicate_group_count": duplicate_group_count,
        "missing_file_count": len(missing_files),
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
        duplicate_group_count=duplicate_group_count,
        missing_file_count=summary["missing_file_count"],
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


def _duplicate_group_count(db_path: str | Path) -> int:
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
