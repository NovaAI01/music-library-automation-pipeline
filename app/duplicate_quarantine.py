"""Move duplicate remove candidates into a quarantine folder."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any

from app import db


RUN_STATUSES: frozenset[str] = frozenset({"completed", "partial", "failed"})
ITEM_STATUSES: frozenset[str] = frozenset(
    {"moved", "skipped_missing", "skipped_exists", "failed"}
)


@dataclass(frozen=True)
class DuplicateQuarantineResult:
    quarantine_run_id: int
    review_plan_id: int
    quarantine_root: str
    run_status: str
    total_remove_candidates: int
    moved_count: int
    skipped_count: int
    failed_count: int
    dry_run: bool


def quarantine_duplicates(
    *,
    review_plan_id: int,
    quarantine_root: str | Path,
    dry_run: bool = False,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> DuplicateQuarantineResult:
    """Move only remove_candidate rows from a duplicate review plan."""

    db.init_db(db_path)
    resolved_quarantine_root = Path(quarantine_root).expanduser().resolve()
    if not dry_run:
        resolved_quarantine_root.mkdir(parents=True, exist_ok=True)

    with db.connect(db_path) as connection:
        plan = _load_review_plan(connection, review_plan_id)
        if plan is None:
            raise ValueError(f"duplicate review plan not found: {review_plan_id}")

        rows = _load_remove_candidates(connection, review_plan_id)
        total_remove_candidates = len(rows)
        created_at = _now()
        quarantine_run_id = int(
            connection.execute(
                """
                INSERT INTO duplicate_quarantine_runs (
                    review_plan_id,
                    quarantine_root,
                    run_status,
                    total_remove_candidates,
                    moved_count,
                    skipped_count,
                    failed_count,
                    created_at
                )
                VALUES (?, ?, 'completed', ?, 0, 0, 0, ?)
                """,
                (
                    review_plan_id,
                    str(resolved_quarantine_root),
                    total_remove_candidates,
                    created_at,
                ),
            ).lastrowid
        )

        if dry_run:
            run_status = "completed"
            moved_count = 0
            skipped_count = 0
            failed_count = 0
        else:
            moved_count = 0
            skipped_count = 0
            failed_count = 0
            library_root = Path(plan["library_root"]).expanduser().resolve()
            for row in rows:
                item_status, quarantine_path, reason = _quarantine_row(
                    row=row,
                    library_root=library_root,
                    quarantine_root=resolved_quarantine_root,
                )
                if item_status == "moved":
                    moved_count += 1
                elif item_status in {"skipped_missing", "skipped_exists"}:
                    skipped_count += 1
                else:
                    failed_count += 1
                _insert_quarantine_item(
                    connection=connection,
                    quarantine_run_id=quarantine_run_id,
                    source_path=row["file_path"],
                    quarantine_path=str(quarantine_path),
                    item_status=item_status,
                    reason=reason,
                )
            run_status = _run_status(
                total_remove_candidates=total_remove_candidates,
                moved_count=moved_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
            )

        connection.execute(
            """
            UPDATE duplicate_quarantine_runs
            SET run_status = ?,
                moved_count = ?,
                skipped_count = ?,
                failed_count = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                run_status,
                moved_count,
                skipped_count,
                failed_count,
                _now(),
                quarantine_run_id,
            ),
        )

    return DuplicateQuarantineResult(
        quarantine_run_id=quarantine_run_id,
        review_plan_id=review_plan_id,
        quarantine_root=str(resolved_quarantine_root),
        run_status=run_status,
        total_remove_candidates=total_remove_candidates,
        moved_count=moved_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        dry_run=dry_run,
    )


def _load_review_plan(connection: Any, review_plan_id: int) -> Any | None:
    return connection.execute(
        """
        SELECT
            duplicate_review_plans.id,
            duplicate_reports.library_root
        FROM duplicate_review_plans
        INNER JOIN duplicate_reports
            ON duplicate_reports.id = duplicate_review_plans.duplicate_report_id
        WHERE duplicate_review_plans.id = ?
        """,
        (review_plan_id,),
    ).fetchone()


def _load_remove_candidates(connection: Any, review_plan_id: int) -> list[Any]:
    return connection.execute(
        """
        SELECT id, file_path
        FROM duplicate_review_items
        WHERE review_plan_id = ?
          AND decision = 'remove_candidate'
        ORDER BY id
        """,
        (review_plan_id,),
    ).fetchall()


def _quarantine_row(
    *, row: Any, library_root: Path, quarantine_root: Path
) -> tuple[str, Path, str | None]:
    source_path = Path(row["file_path"]).expanduser()
    quarantine_path = quarantine_destination_path(
        source_path=source_path,
        library_root=library_root,
        quarantine_root=quarantine_root,
    )
    if quarantine_path is None:
        fallback = quarantine_root / source_path.name
        return "failed", fallback, "invalid_quarantine_path"

    if not source_path.exists():
        return "skipped_missing", quarantine_path, "source_missing"
    if quarantine_path.exists():
        return "skipped_exists", quarantine_path, "quarantine_destination_exists"

    try:
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(quarantine_path))
    except FileExistsError:
        return "skipped_exists", quarantine_path, "quarantine_destination_exists"
    except OSError as error:
        return "failed", quarantine_path, str(error)

    return "moved", quarantine_path, None


def quarantine_destination_path(
    *, source_path: Path, library_root: Path, quarantine_root: Path
) -> Path | None:
    """Build a destination path only when it stays inside quarantine_root."""

    try:
        relative_path = source_path.resolve().relative_to(library_root)
    except ValueError:
        relative_path = PurePath(source_path.name)

    if relative_path.is_absolute() or any(part == ".." for part in relative_path.parts):
        return None

    destination = (quarantine_root / Path(*relative_path.parts)).resolve()
    try:
        destination.relative_to(quarantine_root)
    except ValueError:
        return None
    return destination


def _insert_quarantine_item(
    *,
    connection: Any,
    quarantine_run_id: int,
    source_path: str,
    quarantine_path: str,
    item_status: str,
    reason: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO duplicate_quarantine_items (
            quarantine_run_id,
            source_path,
            quarantine_path,
            item_status,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            quarantine_run_id,
            source_path,
            quarantine_path,
            item_status,
            reason,
            _now(),
        ),
    )


def _run_status(
    *,
    total_remove_candidates: int,
    moved_count: int,
    skipped_count: int,
    failed_count: int,
) -> str:
    if failed_count:
        if moved_count or skipped_count:
            return "partial"
        return "failed"
    return "completed"


def _now() -> str:
    return datetime.now(UTC).isoformat()
