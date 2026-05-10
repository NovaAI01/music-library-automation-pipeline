"""Read-only review report exports for placement plans."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db


PLACEMENT_REVIEW_HEADERS: tuple[str, ...] = (
    "observed_file_id",
    "source_path",
    "planned_relative_path",
    "planned_artist",
    "planned_title",
    "planned_primary_genre",
    "planned_subgenre",
    "placement_confidence",
    "placement_status",
)

BLOCKED_HEADERS: tuple[str, ...] = (
    "observed_file_id",
    "source_path",
    "placement_status",
    "reason_json",
)

CONFLICT_HEADERS: tuple[str, ...] = (
    "observed_file_id",
    "source_path",
    "planned_artist",
    "planned_title",
    "reason_json",
)


@dataclass(frozen=True)
class ReviewReportResult:
    report_path: str
    total_plans: int
    planned_count: int
    needs_review_count: int
    blocked_unknown_identity_count: int
    blocked_unknown_classification_count: int
    conflict_count: int

    @property
    def blocked_count(self) -> int:
        return (
            self.blocked_unknown_identity_count
            + self.blocked_unknown_classification_count
        )


def generate_review_report(
    *,
    scan_run_id: int,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> ReviewReportResult:
    """Export deterministic review files for placement plans."""

    db.init_db(db_path)
    rows = _load_placement_rows(scan_run_id, db_path)
    counts = _count_statuses(rows)
    report_dir = Path(out_dir).expanduser() / f"scan_{scan_run_id}"

    if report_dir.exists():
        shutil.rmtree(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "scan_run_id": scan_run_id,
        "total_plans": len(rows),
        "planned_count": counts["planned"],
        "needs_review_count": counts["needs_review"],
        "blocked_unknown_identity_count": counts["blocked_unknown_identity"],
        "blocked_unknown_classification_count": counts[
            "blocked_unknown_classification"
        ],
        "conflict_count": counts["conflict"],
    }
    _write_json(report_dir / "placement_summary.json", summary)
    _write_csv(
        report_dir / "placement_review.csv",
        PLACEMENT_REVIEW_HEADERS,
        [_placement_review_row(row) for row in rows],
    )
    _write_csv(
        report_dir / "blocked_items.csv",
        BLOCKED_HEADERS,
        [_blocked_row(row) for row in rows if _is_blocked(row)],
    )
    _write_csv(
        report_dir / "conflicts.csv",
        CONFLICT_HEADERS,
        [_conflict_row(row) for row in rows if row["placement_status"] == "conflict"],
    )

    result = ReviewReportResult(
        report_path=str(report_dir),
        total_plans=len(rows),
        planned_count=counts["planned"],
        needs_review_count=counts["needs_review"],
        blocked_unknown_identity_count=counts["blocked_unknown_identity"],
        blocked_unknown_classification_count=counts["blocked_unknown_classification"],
        conflict_count=counts["conflict"],
    )
    _record_review_report(scan_run_id, result, db_path)
    return result


def _load_placement_rows(scan_run_id: int, db_path: str | Path) -> list[Any]:
    with db.connect(db_path) as connection:
        return connection.execute(
            """
            SELECT
                id,
                observed_file_id,
                scan_run_id,
                source_path,
                planned_relative_path,
                planned_artist,
                planned_title,
                planned_primary_genre,
                planned_subgenre,
                placement_confidence,
                placement_status,
                reason_json
            FROM placement_plans
            WHERE scan_run_id = ?
            ORDER BY id
            """,
            (scan_run_id,),
        ).fetchall()


def _count_statuses(rows: list[Any]) -> dict[str, int]:
    counts = {
        "planned": 0,
        "needs_review": 0,
        "blocked_unknown_identity": 0,
        "blocked_unknown_classification": 0,
        "conflict": 0,
    }
    for row in rows:
        if row["placement_status"] in counts:
            counts[row["placement_status"]] += 1
    return counts


def _placement_review_row(row) -> dict[str, Any]:
    return {
        "observed_file_id": row["observed_file_id"],
        "source_path": row["source_path"],
        "planned_relative_path": row["planned_relative_path"] or "",
        "planned_artist": row["planned_artist"] or "",
        "planned_title": row["planned_title"] or "",
        "planned_primary_genre": row["planned_primary_genre"] or "",
        "planned_subgenre": row["planned_subgenre"] or "",
        "placement_confidence": row["placement_confidence"],
        "placement_status": row["placement_status"],
    }


def _blocked_row(row) -> dict[str, Any]:
    return {
        "observed_file_id": row["observed_file_id"],
        "source_path": row["source_path"],
        "placement_status": row["placement_status"],
        "reason_json": row["reason_json"],
    }


def _conflict_row(row) -> dict[str, Any]:
    return {
        "observed_file_id": row["observed_file_id"],
        "source_path": row["source_path"],
        "planned_artist": row["planned_artist"] or "",
        "planned_title": row["planned_title"] or "",
        "reason_json": row["reason_json"],
    }


def _is_blocked(row) -> bool:
    return row["placement_status"] in {
        "blocked_unknown_identity",
        "blocked_unknown_classification",
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


def _record_review_report(
    scan_run_id: int,
    result: ReviewReportResult,
    db_path: str | Path,
) -> None:
    with db.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO review_reports (
                scan_run_id,
                report_path,
                total_plans,
                planned_count,
                needs_review_count,
                blocked_count,
                conflict_count,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_run_id,
                result.report_path,
                result.total_plans,
                result.planned_count,
                result.needs_review_count,
                result.blocked_count,
                result.conflict_count,
                datetime.now(UTC).isoformat(),
            ),
        )
