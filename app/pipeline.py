"""Bridge intake batches into scan, identity, and classification stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app import db
from app.classifier import classify_scan_run
from app.identity_engine import identify_scan_run
from app.scanner import scan


PIPELINE_STATUSES: frozenset[str] = frozenset(
    {"completed", "partial", "failed", "blocked"}
)


@dataclass(frozen=True)
class IntakeBatch:
    id: int
    purchase_request_id: int
    source_path: str
    intake_root: str
    batch_status: str


@dataclass(frozen=True)
class PipelineResult:
    pipeline_run_id: int
    intake_batch_id: int
    scan_run_id: int | None
    scan_status: str | None
    identity_status: str | None
    classification_status: str | None
    pipeline_status: str
    error_message: str | None


def get_intake_batch(
    intake_batch_id: int, db_path: str | Path = db.DEFAULT_DB_PATH
) -> IntakeBatch | None:
    """Return an intake batch by id."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                id,
                purchase_request_id,
                source_path,
                intake_root,
                batch_status
            FROM intake_batches
            WHERE id = ?
            """,
            (intake_batch_id,),
        ).fetchone()

    if row is None:
        return None
    return IntakeBatch(
        id=int(row["id"]),
        purchase_request_id=int(row["purchase_request_id"]),
        source_path=row["source_path"],
        intake_root=row["intake_root"],
        batch_status=row["batch_status"],
    )


def should_block_duplicate_pipeline(
    intake_batch_id: int,
    *,
    rerun: bool = False,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> bool:
    """Return True when an existing run should block another pipeline run."""

    if rerun:
        return False

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM pipeline_runs
            WHERE intake_batch_id = ?
                AND pipeline_status IN ('completed', 'partial', 'blocked')
            LIMIT 1
            """,
            (intake_batch_id,),
        ).fetchone()
    return row is not None


def create_pipeline_run(
    intake_batch_id: int,
    *,
    pipeline_status: str = "partial",
    error_message: str | None = None,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> int:
    """Create a pipeline run ledger row."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        row_id = connection.execute(
            """
            INSERT INTO pipeline_runs (
                intake_batch_id,
                scan_run_id,
                pipeline_status,
                scan_status,
                identity_status,
                classification_status,
                created_at,
                completed_at,
                error_message
            )
            VALUES (?, NULL, ?, NULL, NULL, NULL, ?, NULL, ?)
            """,
            (intake_batch_id, pipeline_status, _now(), error_message),
        ).lastrowid
    return int(row_id)


def update_pipeline_stage_status(
    pipeline_run_id: int,
    *,
    scan_run_id: int | None = None,
    pipeline_status: str | None = None,
    scan_status: str | None = None,
    identity_status: str | None = None,
    classification_status: str | None = None,
    error_message: str | None = None,
    completed: bool = False,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> None:
    """Update pipeline stage statuses without embedding stage logic."""

    assignments: list[str] = []
    values: list[object] = []
    updates = {
        "scan_run_id": scan_run_id,
        "pipeline_status": pipeline_status,
        "scan_status": scan_status,
        "identity_status": identity_status,
        "classification_status": classification_status,
        "error_message": error_message,
    }
    for column, value in updates.items():
        if value is not None:
            assignments.append(f"{column} = ?")
            values.append(value)
    if completed:
        assignments.append("completed_at = ?")
        values.append(_now())
    if not assignments:
        return

    values.append(pipeline_run_id)
    with db.connect(db_path) as connection:
        connection.execute(
            f"""
            UPDATE pipeline_runs
            SET {", ".join(assignments)}
            WHERE id = ?
            """,
            values,
        )


def run_intake_pipeline(
    intake_batch_id: int,
    *,
    rerun: bool = False,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> PipelineResult:
    """Run scan, identity, and classification for an intake batch."""

    batch = get_intake_batch(intake_batch_id, db_path)
    if batch is None:
        pipeline_run_id = create_pipeline_run(
            intake_batch_id,
            pipeline_status="blocked",
            error_message="invalid_intake_batch",
            db_path=db_path,
        )
        update_pipeline_stage_status(
            pipeline_run_id,
            completed=True,
            db_path=db_path,
        )
        return _get_pipeline_result(pipeline_run_id, db_path)

    if should_block_duplicate_pipeline(intake_batch_id, rerun=rerun, db_path=db_path):
        pipeline_run_id = create_pipeline_run(
            intake_batch_id,
            pipeline_status="blocked",
            error_message="duplicate_pipeline_run",
            db_path=db_path,
        )
        update_pipeline_stage_status(
            pipeline_run_id,
            completed=True,
            db_path=db_path,
        )
        return _get_pipeline_result(pipeline_run_id, db_path)

    pipeline_run_id = create_pipeline_run(intake_batch_id, db_path=db_path)

    try:
        scan_result = scan(batch.intake_root, db_path)
        update_pipeline_stage_status(
            pipeline_run_id,
            scan_run_id=scan_result.scan_run_id,
            scan_status=scan_result.status,
            db_path=db_path,
        )
    except Exception as exc:
        update_pipeline_stage_status(
            pipeline_run_id,
            pipeline_status="failed",
            scan_status="failed",
            error_message=str(exc),
            completed=True,
            db_path=db_path,
        )
        return _get_pipeline_result(pipeline_run_id, db_path)

    if scan_result.status != "completed":
        update_pipeline_stage_status(
            pipeline_run_id,
            pipeline_status="failed",
            error_message=f"scan_status={scan_result.status}",
            completed=True,
            db_path=db_path,
        )
        return _get_pipeline_result(pipeline_run_id, db_path)

    try:
        identify_scan_run(scan_result.scan_run_id, db_path)
        update_pipeline_stage_status(
            pipeline_run_id,
            identity_status="completed",
            db_path=db_path,
        )
    except Exception as exc:
        update_pipeline_stage_status(
            pipeline_run_id,
            pipeline_status="failed",
            identity_status="failed",
            error_message=str(exc),
            completed=True,
            db_path=db_path,
        )
        return _get_pipeline_result(pipeline_run_id, db_path)

    try:
        classify_scan_run(scan_result.scan_run_id, db_path)
        update_pipeline_stage_status(
            pipeline_run_id,
            pipeline_status="completed",
            classification_status="completed",
            completed=True,
            db_path=db_path,
        )
    except Exception as exc:
        update_pipeline_stage_status(
            pipeline_run_id,
            pipeline_status="failed",
            classification_status="failed",
            error_message=str(exc),
            completed=True,
            db_path=db_path,
        )

    return _get_pipeline_result(pipeline_run_id, db_path)


def _get_pipeline_result(
    pipeline_run_id: int, db_path: str | Path
) -> PipelineResult:
    with db.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                id,
                intake_batch_id,
                scan_run_id,
                pipeline_status,
                scan_status,
                identity_status,
                classification_status,
                error_message
            FROM pipeline_runs
            WHERE id = ?
            """,
            (pipeline_run_id,),
        ).fetchone()

    return PipelineResult(
        pipeline_run_id=int(row["id"]),
        intake_batch_id=int(row["intake_batch_id"]),
        scan_run_id=int(row["scan_run_id"]) if row["scan_run_id"] else None,
        scan_status=row["scan_status"],
        identity_status=row["identity_status"],
        classification_status=row["classification_status"],
        pipeline_status=row["pipeline_status"],
        error_message=row["error_message"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
