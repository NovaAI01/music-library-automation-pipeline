"""Copy planned placement files into an organised output root."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app import db


EXECUTION_STATUSES: frozenset[str] = frozenset(
    {"completed", "partial", "failed", "blocked"}
)
FILE_STATUSES: frozenset[str] = frozenset(
    {"copied", "skipped_not_planned", "skipped_exists", "failed"}
)


@dataclass(frozen=True)
class PlacementExecutionResult:
    execution_id: int
    output_root: str
    execution_status: str
    total_planned: int
    copied_count: int
    skipped_count: int
    failed_count: int


def execute_placement(
    scan_run_id: int,
    output_root: str | Path,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> PlacementExecutionResult:
    """Copy files for planned placement rows without mutating source files."""

    db.init_db(db_path)
    resolved_output_root = Path(output_root).expanduser().resolve()
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                source_path,
                planned_relative_path,
                placement_status
            FROM placement_plans
            WHERE scan_run_id = ?
            ORDER BY id
            """,
            (scan_run_id,),
        ).fetchall()

        total_planned = sum(
            1 for row in rows if row["placement_status"] == "planned"
        )
        created_at = _now()
        execution_id = int(
            connection.execute(
                """
                INSERT INTO placement_executions (
                    scan_run_id,
                    output_root,
                    execution_status,
                    total_planned,
                    copied_count,
                    skipped_count,
                    failed_count,
                    created_at
                )
                VALUES (?, ?, 'blocked', ?, 0, 0, 0, ?)
                """,
                (
                    scan_run_id,
                    str(resolved_output_root),
                    total_planned,
                    created_at,
                ),
            ).lastrowid
        )

        copied_count = 0
        skipped_count = 0
        failed_count = 0
        for row in rows:
            file_status, destination_path, reason = _execute_plan_row(
                row=row,
                output_root=resolved_output_root,
            )
            if file_status == "copied":
                copied_count += 1
            elif file_status in {"skipped_not_planned", "skipped_exists"}:
                skipped_count += 1
            else:
                failed_count += 1

            _insert_execution_file(
                connection=connection,
                execution_id=execution_id,
                placement_plan_id=row["id"],
                source_path=row["source_path"],
                destination_path=str(destination_path),
                file_status=file_status,
                reason=reason,
            )

        execution_status = _execution_status(
            total_planned=total_planned,
            copied_count=copied_count,
            failed_count=failed_count,
        )
        connection.execute(
            """
            UPDATE placement_executions
            SET execution_status = ?,
                copied_count = ?,
                skipped_count = ?,
                failed_count = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                execution_status,
                copied_count,
                skipped_count,
                failed_count,
                _now(),
                execution_id,
            ),
        )

    return PlacementExecutionResult(
        execution_id=execution_id,
        output_root=str(resolved_output_root),
        execution_status=execution_status,
        total_planned=total_planned,
        copied_count=copied_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )


def _execute_plan_row(
    *, row: Any, output_root: Path
) -> tuple[str, Path, str | None]:
    planned_relative_path = row["planned_relative_path"]
    destination_path = (
        output_root / planned_relative_path
        if planned_relative_path
        else output_root
    )

    if row["placement_status"] != "planned":
        return "skipped_not_planned", destination_path, "placement_not_planned"

    validated_destination = validate_destination_path(
        output_root=output_root,
        planned_relative_path=planned_relative_path,
    )
    if validated_destination is None:
        return "failed", destination_path, "invalid_planned_relative_path"

    if validated_destination.exists():
        return "skipped_exists", validated_destination, "destination_exists"

    try:
        _copy_without_overwrite(Path(row["source_path"]), validated_destination)
    except FileExistsError:
        return "skipped_exists", validated_destination, "destination_exists"
    except OSError as error:
        return "failed", validated_destination, str(error)

    return "copied", validated_destination, None


def validate_destination_path(
    *, output_root: Path, planned_relative_path: str | None
) -> Path | None:
    """Return a destination path only when it stays inside output_root."""

    if not planned_relative_path:
        return None

    pure_path = PurePosixPath(planned_relative_path)
    if pure_path.is_absolute() or any(part == ".." for part in pure_path.parts):
        return None

    destination = (output_root / Path(*pure_path.parts)).resolve()
    try:
        destination.relative_to(output_root)
    except ValueError:
        return None
    return destination


def _copy_without_overwrite(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    created_destination = False
    try:
        with source_path.open("rb") as source:
            descriptor = os.open(
                destination_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            )
            created_destination = True
            with os.fdopen(descriptor, "wb") as destination:
                shutil.copyfileobj(source, destination)
        shutil.copystat(source_path, destination_path)
    except Exception:
        if created_destination:
            destination_path.unlink(missing_ok=True)
        raise


def _insert_execution_file(
    *,
    connection: Any,
    execution_id: int,
    placement_plan_id: int,
    source_path: str,
    destination_path: str,
    file_status: str,
    reason: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO placement_execution_files (
            execution_id,
            placement_plan_id,
            source_path,
            destination_path,
            file_status,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            execution_id,
            placement_plan_id,
            source_path,
            destination_path,
            file_status,
            reason,
            _now(),
        ),
    )


def _execution_status(
    *, total_planned: int, copied_count: int, failed_count: int
) -> str:
    if total_planned == 0:
        return "blocked"
    if failed_count and copied_count:
        return "partial"
    if failed_count:
        return "failed"
    return "completed"


def _now() -> str:
    return datetime.now(UTC).isoformat()
