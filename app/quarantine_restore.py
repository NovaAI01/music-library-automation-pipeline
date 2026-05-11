"""Restore quarantined duplicate files to their original library paths."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db


RESTORE_STATUSES: frozenset[str] = frozenset({"completed", "partial", "failed"})
ITEM_STATUSES: frozenset[str] = frozenset(
    {
        "restored",
        "skipped_missing_quarantine_file",
        "skipped_restore_target_exists",
        "failed",
    }
)


@dataclass(frozen=True)
class QuarantineRestoreResult:
    restore_run_id: int
    quarantine_run_id: int
    restore_status: str
    total_restore_candidates: int
    restored_count: int
    skipped_count: int
    failed_count: int
    dry_run: bool


def restore_quarantine(
    *,
    quarantine_run_id: int,
    dry_run: bool = False,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> QuarantineRestoreResult:
    """Restore files recorded in duplicate_quarantine_items for one run."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        quarantine_run = _load_quarantine_run(connection, quarantine_run_id)
        if quarantine_run is None:
            raise ValueError(f"duplicate quarantine run not found: {quarantine_run_id}")

        rows = _load_quarantine_items(connection, quarantine_run_id)
        total_restore_candidates = len(rows)
        restore_run_id = int(
            connection.execute(
                """
                INSERT INTO quarantine_restore_runs (
                    quarantine_run_id,
                    restore_status,
                    total_restore_candidates,
                    restored_count,
                    skipped_count,
                    failed_count,
                    dry_run,
                    created_at
                )
                VALUES (?, 'completed', ?, 0, 0, 0, ?, ?)
                """,
                (
                    quarantine_run_id,
                    total_restore_candidates,
                    int(dry_run),
                    _now(),
                ),
            ).lastrowid
        )

        if dry_run:
            restore_status = "completed"
            restored_count = 0
            skipped_count = 0
            failed_count = 0
        else:
            restored_count = 0
            skipped_count = 0
            failed_count = 0
            library_root = _library_root(quarantine_run)
            for row in rows:
                item_status, reason = _restore_row(row=row, library_root=library_root)
                if item_status == "restored":
                    restored_count += 1
                elif item_status in {
                    "skipped_missing_quarantine_file",
                    "skipped_restore_target_exists",
                }:
                    skipped_count += 1
                else:
                    failed_count += 1
                _insert_restore_item(
                    connection=connection,
                    restore_run_id=restore_run_id,
                    quarantine_item_id=row["id"],
                    quarantine_path=row["quarantine_path"],
                    restore_path=row["source_path"],
                    item_status=item_status,
                    reason=reason,
                )
            restore_status = _restore_status(
                restored_count=restored_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
            )

        connection.execute(
            """
            UPDATE quarantine_restore_runs
            SET restore_status = ?,
                restored_count = ?,
                skipped_count = ?,
                failed_count = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                restore_status,
                restored_count,
                skipped_count,
                failed_count,
                _now(),
                restore_run_id,
            ),
        )

    return QuarantineRestoreResult(
        restore_run_id=restore_run_id,
        quarantine_run_id=quarantine_run_id,
        restore_status=restore_status,
        total_restore_candidates=total_restore_candidates,
        restored_count=restored_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        dry_run=dry_run,
    )


def _load_quarantine_run(connection: Any, quarantine_run_id: int) -> Any | None:
    return connection.execute(
        """
        SELECT
            duplicate_quarantine_runs.id,
            duplicate_reports.library_root
        FROM duplicate_quarantine_runs
        LEFT JOIN duplicate_review_plans
            ON duplicate_review_plans.id = duplicate_quarantine_runs.review_plan_id
        LEFT JOIN duplicate_reports
            ON duplicate_reports.id = duplicate_review_plans.duplicate_report_id
        WHERE duplicate_quarantine_runs.id = ?
        """,
        (quarantine_run_id,),
    ).fetchone()


def _load_quarantine_items(connection: Any, quarantine_run_id: int) -> list[Any]:
    return connection.execute(
        """
        SELECT id, source_path, quarantine_path
        FROM duplicate_quarantine_items
        WHERE quarantine_run_id = ?
        ORDER BY id
        """,
        (quarantine_run_id,),
    ).fetchall()


def _restore_row(*, row: Any, library_root: Path | None) -> tuple[str, str | None]:
    quarantine_path = Path(row["quarantine_path"]).expanduser()
    restore_path = Path(row["source_path"]).expanduser()

    if library_root is not None and not _path_is_inside(
        restore_path.resolve(strict=False), library_root
    ):
        return "failed", "restore_path_outside_library_root"
    if not quarantine_path.is_file():
        return "skipped_missing_quarantine_file", "quarantine_file_missing"
    if restore_path.exists():
        return "skipped_restore_target_exists", "restore_target_exists"

    try:
        restore_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(quarantine_path), str(restore_path))
    except FileExistsError:
        return "skipped_restore_target_exists", "restore_target_exists"
    except OSError as error:
        return "failed", str(error)

    return "restored", None


def _library_root(quarantine_run: Any) -> Path | None:
    library_root = quarantine_run["library_root"]
    if library_root is None:
        return None
    return Path(library_root).expanduser().resolve(strict=False)


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _insert_restore_item(
    *,
    connection: Any,
    restore_run_id: int,
    quarantine_item_id: int,
    quarantine_path: str,
    restore_path: str,
    item_status: str,
    reason: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO quarantine_restore_items (
            restore_run_id,
            quarantine_item_id,
            quarantine_path,
            restore_path,
            item_status,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            restore_run_id,
            quarantine_item_id,
            quarantine_path,
            restore_path,
            item_status,
            reason,
            _now(),
        ),
    )


def _restore_status(
    *, restored_count: int, skipped_count: int, failed_count: int
) -> str:
    if failed_count:
        if restored_count or skipped_count:
            return "partial"
        return "failed"
    return "completed"


def _now() -> str:
    return datetime.now(UTC).isoformat()
