"""Copy-only local file intake gated by purchase unlocks."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app import db


SUPPORTED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".webm"}
)
BATCH_STATUSES: frozenset[str] = frozenset(
    {"completed", "partial", "blocked", "failed"}
)
FILE_STATUSES: frozenset[str] = frozenset(
    {"copied", "skipped_unsupported", "duplicate", "failed"}
)


@dataclass(frozen=True)
class IntakeBatchResult:
    intake_batch_id: int
    batch_status: str
    total_files_seen: int
    audio_files_copied: int
    skipped_files: int
    duplicate_files: int


def is_supported_audio_file(path: str | Path) -> bool:
    """Return whether a path has a supported audio extension."""

    return Path(path).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def calculate_sha256(path: str | Path) -> str:
    """Calculate a stable SHA-256 digest without modifying the source file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_intake_destination(
    original_path: str | Path,
    source_root: str | Path,
    intake_root: str | Path,
) -> Path:
    """Build the destination path while preserving relative structure."""

    original = Path(original_path).expanduser().resolve()
    source = Path(source_root).expanduser().resolve()
    intake = Path(intake_root).expanduser()
    return intake / original.relative_to(source)


def unique_destination_path(path: str | Path) -> Path:
    """Return a non-existing path by appending a deterministic numeric suffix."""

    candidate = Path(path)
    if not candidate.exists():
        return candidate

    for index in range(1, 10000):
        next_candidate = candidate.with_name(
            f"{candidate.stem} ({index}){candidate.suffix}"
        )
        if not next_candidate.exists():
            return next_candidate

    raise ValueError(f"Could not create unique destination path: {candidate}")


def intake_requires_unlock(
    purchase_request_id: int, db_path: str | Path = db.DEFAULT_DB_PATH
) -> bool:
    """Return True when no intake unlock exists for the purchase request."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM intake_unlocks
            WHERE purchase_request_id = ?
            LIMIT 1
            """,
            (purchase_request_id,),
        ).fetchone()
    return row is None


def run_intake(
    *,
    purchase_request_id: int,
    source_path: str | Path,
    intake_root: str | Path,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> IntakeBatchResult:
    """Copy supported local audio files into intake after purchase unlock."""

    source = Path(source_path).expanduser().resolve()
    intake = Path(intake_root).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source path does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source}")

    db.init_db(db_path)
    if intake_requires_unlock(purchase_request_id, db_path):
        return _create_blocked_batch(
            purchase_request_id=purchase_request_id,
            source_path=source,
            intake_root=intake,
            db_path=db_path,
        )

    files = _iter_visible_files(source)
    intake.mkdir(parents=True, exist_ok=True)
    seen_hashes: set[str] = set()
    total_files_seen = 0
    audio_files_copied = 0
    skipped_files = 0
    duplicate_files = 0
    failed_files = 0

    with db.connect(db_path) as connection:
        batch_id = _insert_batch(
            connection=connection,
            purchase_request_id=purchase_request_id,
            source_path=source,
            intake_root=intake,
            batch_status="partial",
        )

        for path in files:
            total_files_seen += 1
            extension = path.suffix.lower()
            file_size = path.stat().st_size

            if not is_supported_audio_file(path):
                skipped_files += 1
                _insert_file(
                    connection=connection,
                    batch_id=batch_id,
                    original_path=path,
                    intake_path=None,
                    sha256=None,
                    extension=extension,
                    file_size_bytes=file_size,
                    file_status="skipped_unsupported",
                    reason="unsupported_extension",
                )
                continue

            try:
                sha256 = calculate_sha256(path)
                if sha256 in seen_hashes:
                    duplicate_files += 1
                    _insert_file(
                        connection=connection,
                        batch_id=batch_id,
                        original_path=path,
                        intake_path=None,
                        sha256=sha256,
                        extension=extension,
                        file_size_bytes=file_size,
                        file_status="duplicate",
                        reason="duplicate_sha256_in_batch",
                    )
                    continue

                seen_hashes.add(sha256)
                destination = unique_destination_path(
                    build_intake_destination(path, source, intake)
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                audio_files_copied += 1
                _insert_file(
                    connection=connection,
                    batch_id=batch_id,
                    original_path=path,
                    intake_path=destination,
                    sha256=sha256,
                    extension=extension,
                    file_size_bytes=file_size,
                    file_status="copied",
                    reason=None,
                )
            except OSError as exc:
                failed_files += 1
                _insert_file(
                    connection=connection,
                    batch_id=batch_id,
                    original_path=path,
                    intake_path=None,
                    sha256=None,
                    extension=extension,
                    file_size_bytes=file_size,
                    file_status="failed",
                    reason=str(exc),
                )

        batch_status = "failed" if failed_files and not audio_files_copied else "partial"
        if failed_files == 0:
            batch_status = "completed"

        connection.execute(
            """
            UPDATE intake_batches
            SET
                batch_status = ?,
                total_files_seen = ?,
                audio_files_copied = ?,
                skipped_files = ?,
                duplicate_files = ?
            WHERE id = ?
            """,
            (
                batch_status,
                total_files_seen,
                audio_files_copied,
                skipped_files,
                duplicate_files,
                batch_id,
            ),
        )

    return IntakeBatchResult(
        intake_batch_id=batch_id,
        batch_status=batch_status,
        total_files_seen=total_files_seen,
        audio_files_copied=audio_files_copied,
        skipped_files=skipped_files,
        duplicate_files=duplicate_files,
    )


def _create_blocked_batch(
    *,
    purchase_request_id: int,
    source_path: Path,
    intake_root: Path,
    db_path: str | Path,
) -> IntakeBatchResult:
    with db.connect(db_path) as connection:
        batch_id = _insert_batch(
            connection=connection,
            purchase_request_id=purchase_request_id,
            source_path=source_path,
            intake_root=intake_root,
            batch_status="blocked",
        )

    return IntakeBatchResult(
        intake_batch_id=batch_id,
        batch_status="blocked",
        total_files_seen=0,
        audio_files_copied=0,
        skipped_files=0,
        duplicate_files=0,
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


def _insert_batch(
    *,
    connection,
    purchase_request_id: int,
    source_path: Path,
    intake_root: Path,
    batch_status: str,
) -> int:
    row_id = connection.execute(
        """
        INSERT INTO intake_batches (
            purchase_request_id,
            source_path,
            intake_root,
            batch_status,
            total_files_seen,
            audio_files_copied,
            skipped_files,
            duplicate_files,
            created_at
        )
        VALUES (?, ?, ?, ?, 0, 0, 0, 0, ?)
        """,
        (
            purchase_request_id,
            str(source_path),
            str(intake_root),
            batch_status,
            _now(),
        ),
    ).lastrowid
    return int(row_id)


def _insert_file(
    *,
    connection,
    batch_id: int,
    original_path: Path,
    intake_path: Path | None,
    sha256: str | None,
    extension: str,
    file_size_bytes: int,
    file_status: str,
    reason: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO intake_files (
            intake_batch_id,
            original_path,
            intake_path,
            sha256,
            extension,
            file_size_bytes,
            file_status,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            str(original_path),
            str(intake_path) if intake_path is not None else None,
            sha256,
            extension,
            file_size_bytes,
            file_status,
            reason,
            _now(),
        ),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
