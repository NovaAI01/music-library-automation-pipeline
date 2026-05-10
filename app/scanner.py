"""Read-only local music folder scanner for the observation ledger."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app import db
from app.artist_seeds import classify_by_artist
from app.audio_probe import AudioProbeResult, probe_audio
from app.filename_parser import parse_filename


SUPPORTED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".webm"}
)


@dataclass(frozen=True)
class ScanResult:
    scan_run_id: int
    total_files_seen: int
    audio_files_seen: int
    files_failed: int
    status: str


def sha256_file(path: str | Path) -> str:
    """Return a stable SHA-256 digest for a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_supported_audio_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def scan(source: str | Path, db_path: str | Path = db.DEFAULT_DB_PATH) -> ScanResult:
    """Observe supported audio files under source and record evidence in SQLite."""

    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")
    if not source_path.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_path}")

    visible_files = _iter_visible_files(source_path)
    db.init_db(db_path)
    started_at = _now()

    with db.connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO scan_runs (
                source_path,
                started_at,
                status,
                total_files_seen,
                audio_files_seen,
                files_failed
            )
            VALUES (?, ?, ?, 0, 0, 0)
            """,
            (str(source_path), started_at, "running"),
        )
        scan_run_id = int(cursor.lastrowid)

        total_files_seen = 0
        audio_files_seen = 0
        files_failed = 0

        ledger_path = Path(db_path).expanduser().resolve()
        for path in visible_files:
            if path.resolve() == ledger_path:
                continue

            total_files_seen += 1
            if not is_supported_audio_file(path):
                continue

            audio_files_seen += 1
            try:
                observed_file_id = _insert_observed_file(
                    connection, scan_run_id, source_path, path
                )
                probe = probe_audio(path)
                if probe.probe_status != "ok":
                    files_failed += 1
                _insert_audio_observation(connection, observed_file_id, probe)
                _insert_tag_observation(connection, observed_file_id, probe)
                _insert_filename_observation(connection, observed_file_id, path)
            except OSError:
                files_failed += 1

        status = "completed"
        connection.execute(
            """
            UPDATE scan_runs
            SET
                completed_at = ?,
                status = ?,
                total_files_seen = ?,
                audio_files_seen = ?,
                files_failed = ?
            WHERE id = ?
            """,
            (
                _now(),
                status,
                total_files_seen,
                audio_files_seen,
                files_failed,
                scan_run_id,
            ),
        )

    return ScanResult(
        scan_run_id=scan_run_id,
        total_files_seen=total_files_seen,
        audio_files_seen=audio_files_seen,
        files_failed=files_failed,
        status=status,
    )


def _iter_visible_files(source_path: Path) -> list[Path]:
    files: list[Path] = []
    for path in source_path.rglob("*"):
        relative_parts = path.relative_to(source_path).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def _insert_observed_file(
    connection, scan_run_id: int, source_path: Path, path: Path
) -> int:
    relative_path = path.relative_to(source_path)
    cursor = connection.execute(
        """
        INSERT INTO observed_files (
            scan_run_id,
            source_path,
            relative_path,
            parent_folder,
            filename,
            extension,
            file_size_bytes,
            sha256,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_run_id,
            str(source_path),
            relative_path.as_posix(),
            relative_path.parent.as_posix() if str(relative_path.parent) != "." else "",
            path.name,
            path.suffix.lower(),
            path.stat().st_size,
            sha256_file(path),
            _now(),
        ),
    )
    return int(cursor.lastrowid)


def _insert_audio_observation(
    connection, observed_file_id: int, probe: AudioProbeResult
) -> None:
    connection.execute(
        """
        INSERT INTO audio_observations (
            observed_file_id,
            duration_seconds,
            sample_rate,
            channels,
            bitrate,
            codec,
            container,
            probe_status,
            probe_error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observed_file_id,
            probe.duration_seconds,
            probe.sample_rate,
            probe.channels,
            probe.bitrate,
            probe.codec,
            probe.container,
            probe.probe_status,
            probe.probe_error,
        ),
    )


def _insert_tag_observation(
    connection, observed_file_id: int, probe: AudioProbeResult
) -> None:
    artist = probe.tags.get("artist")
    if artist:
        classify_by_artist(artist)

    connection.execute(
        """
        INSERT INTO tag_observations (
            observed_file_id,
            title,
            artist,
            album,
            album_artist,
            genre,
            date,
            track_number,
            disc_number,
            composer,
            comment,
            tag_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observed_file_id,
            probe.tags.get("title"),
            artist,
            probe.tags.get("album"),
            probe.tags.get("album_artist"),
            probe.tags.get("genre"),
            probe.tags.get("date"),
            probe.tags.get("track_number"),
            probe.tags.get("disc_number"),
            probe.tags.get("composer"),
            probe.tags.get("comment"),
            probe.tag_status,
        ),
    )


def _insert_filename_observation(connection, observed_file_id: int, path: Path) -> None:
    observation = parse_filename(path.name)
    if observation.possible_artist:
        classify_by_artist(observation.possible_artist)

    connection.execute(
        """
        INSERT INTO filename_observations (
            observed_file_id,
            cleaned_filename,
            possible_artist,
            possible_title,
            possible_mix,
            possible_track_number,
            filename_pattern,
            parser_confidence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observed_file_id,
            observation.cleaned_filename,
            observation.possible_artist,
            observation.possible_title,
            observation.possible_mix,
            observation.possible_track_number,
            observation.filename_pattern,
            observation.parser_confidence,
        ),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
