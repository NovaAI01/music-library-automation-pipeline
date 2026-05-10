"""Deterministic placement planning for classified tracks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from app import db


PLACEMENT_STATUSES: frozenset[str] = frozenset(
    {
        "planned",
        "needs_review",
        "blocked_unknown_identity",
        "blocked_unknown_classification",
        "conflict",
    }
)


@dataclass(frozen=True)
class PlacementPlan:
    observed_file_id: int
    scan_run_id: int
    source_path: str
    planned_relative_path: str | None
    planned_artist: str | None
    planned_title: str | None
    planned_primary_genre: str | None
    planned_subgenre: str | None
    placement_confidence: float
    placement_status: str
    reason: dict[str, Any]


@dataclass(frozen=True)
class PlacementSummary:
    total: int
    planned: int
    needs_review: int
    blocked_unknown_identity: int
    blocked_unknown_classification: int
    conflict: int


def sanitize_path_component(value: str | None) -> str:
    """Return a safe single path component with traversal stripped."""

    if value is None:
        return "_Unknown"

    cleaned = value.replace("\\", "/")
    cleaned = cleaned.replace("..", "")
    cleaned = cleaned.replace("/", " ")
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "_Unknown"


def build_planned_relative_path(
    *,
    primary_genre: str,
    subgenre: str | None,
    artist: str,
    title: str,
    extension: str,
) -> str:
    """Build the v1 relative placement path."""

    safe_primary = sanitize_path_component(primary_genre)
    safe_subgenre = sanitize_path_component(subgenre or "_Unsorted")
    safe_artist = sanitize_path_component(artist)
    safe_title = sanitize_path_component(title)
    safe_extension = _sanitize_extension(extension)
    filename = f"{safe_artist} - {safe_title}{safe_extension}"
    relative = PurePosixPath(safe_primary, safe_subgenre, safe_artist, filename)
    return relative.as_posix()


def detect_planned_path_collision(
    planned_relative_path: str, existing_paths: set[str]
) -> str:
    """Append numeric suffixes when a planned path already exists."""

    if planned_relative_path not in existing_paths:
        return planned_relative_path

    path = PurePosixPath(planned_relative_path)
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    for index in range(2, 10000):
        candidate = path.with_name(f"{stem} ({index}){suffix}").as_posix()
        if candidate not in existing_paths:
            return candidate

    raise ValueError(f"Could not resolve planned path collision: {planned_relative_path}")


def calculate_placement_confidence(
    *,
    identity_confidence: float | None,
    classification_confidence: float | None,
    placement_status: str,
) -> float:
    """Return deterministic placement confidence."""

    if placement_status in {
        "blocked_unknown_identity",
        "blocked_unknown_classification",
        "conflict",
    }:
        return 0.0
    if placement_status == "needs_review":
        return min(identity_confidence or 0.0, classification_confidence or 0.0, 0.5)
    if placement_status == "planned":
        return min(identity_confidence or 0.0, classification_confidence or 0.0)
    raise ValueError(f"Unknown placement_status: {placement_status}")


def create_placement_plan(
    *,
    observed_file_id: int,
    scan_run_id: int,
    source_path: str,
    extension: str,
    identity_status: str | None,
    identity_confidence: float | None,
    probable_artist: str | None,
    probable_title: str | None,
    classification_status: str | None,
    classification_confidence: float | None,
    primary_genre: str | None,
    subgenre: str | None,
    existing_paths: set[str] | None = None,
) -> PlacementPlan:
    """Create one deterministic placement plan from joined ledger evidence."""

    existing_paths = existing_paths if existing_paths is not None else set()
    reasons: list[str] = []

    if identity_status == "conflicting":
        status = "conflict"
        reasons.append("identity_conflicting")
    elif identity_status == "unknown" or not probable_artist or not probable_title:
        status = "blocked_unknown_identity"
        reasons.append("identity_unknown")
    elif classification_status == "unknown" or not primary_genre:
        status = "blocked_unknown_classification"
        reasons.append("classification_unknown")
    elif classification_status == "uncertain":
        status = "needs_review"
        reasons.append("classification_uncertain")
    else:
        status = "planned"

    planned_relative_path = None
    planned_subgenre = subgenre or "_Unsorted" if primary_genre else None
    if status in {"planned", "needs_review"}:
        planned_relative_path = build_planned_relative_path(
            primary_genre=primary_genre or "_Unknown",
            subgenre=subgenre,
            artist=probable_artist or "_Unknown",
            title=probable_title or "_Unknown",
            extension=extension,
        )
        planned_relative_path = detect_planned_path_collision(
            planned_relative_path, existing_paths
        )
        existing_paths.add(planned_relative_path)

    confidence = calculate_placement_confidence(
        identity_confidence=identity_confidence,
        classification_confidence=classification_confidence,
        placement_status=status,
    )
    reason = {
        "identity_status": identity_status,
        "classification_status": classification_status,
        "reasons": reasons,
    }
    return PlacementPlan(
        observed_file_id=observed_file_id,
        scan_run_id=scan_run_id,
        source_path=source_path,
        planned_relative_path=planned_relative_path,
        planned_artist=probable_artist,
        planned_title=probable_title,
        planned_primary_genre=primary_genre,
        planned_subgenre=planned_subgenre,
        placement_confidence=confidence,
        placement_status=status,
        reason=reason,
    )


def plan_scan_run_placements(
    scan_run_id: int, db_path: str = db.DEFAULT_DB_PATH
) -> PlacementSummary:
    """Create placement plans for all observed files in a scan run."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                observed_files.id AS observed_file_id,
                observed_files.scan_run_id,
                observed_files.source_path,
                observed_files.relative_path,
                observed_files.extension,
                track_identity.probable_artist,
                track_identity.probable_title,
                track_identity.identity_confidence,
                track_identity.identity_status,
                classification_results.primary_genre,
                classification_results.subgenre,
                classification_results.classification_confidence,
                classification_results.classification_status
            FROM observed_files
            LEFT JOIN track_identity
                ON track_identity.observed_file_id = observed_files.id
            LEFT JOIN classification_results
                ON classification_results.observed_file_id = observed_files.id
            WHERE observed_files.scan_run_id = ?
            ORDER BY observed_files.id
            """,
            (scan_run_id,),
        ).fetchall()

        observed_file_ids = [row["observed_file_id"] for row in rows]
        if observed_file_ids:
            placeholders = ",".join("?" for _ in observed_file_ids)
            connection.execute(
                f"""
                DELETE FROM placement_plans
                WHERE scan_run_id = ?
                    AND observed_file_id IN ({placeholders})
                """,
                [scan_run_id, *observed_file_ids],
            )

        counts = {
            "planned": 0,
            "needs_review": 0,
            "blocked_unknown_identity": 0,
            "blocked_unknown_classification": 0,
            "conflict": 0,
        }
        existing_paths: set[str] = set()
        for row in rows:
            source_path = _source_file_path(row["source_path"], row["relative_path"])
            plan = create_placement_plan(
                observed_file_id=row["observed_file_id"],
                scan_run_id=row["scan_run_id"],
                source_path=source_path,
                extension=row["extension"],
                identity_status=row["identity_status"],
                identity_confidence=row["identity_confidence"],
                probable_artist=row["probable_artist"],
                probable_title=row["probable_title"],
                classification_status=row["classification_status"],
                classification_confidence=row["classification_confidence"],
                primary_genre=row["primary_genre"],
                subgenre=row["subgenre"],
                existing_paths=existing_paths,
            )
            _insert_placement_plan(connection, plan)
            counts[plan.placement_status] += 1

    return PlacementSummary(
        total=len(rows),
        planned=counts["planned"],
        needs_review=counts["needs_review"],
        blocked_unknown_identity=counts["blocked_unknown_identity"],
        blocked_unknown_classification=counts["blocked_unknown_classification"],
        conflict=counts["conflict"],
    )


def _insert_placement_plan(connection, plan: PlacementPlan) -> None:
    connection.execute(
        """
        INSERT INTO placement_plans (
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
            reason_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan.observed_file_id,
            plan.scan_run_id,
            plan.source_path,
            plan.planned_relative_path,
            plan.planned_artist,
            plan.planned_title,
            plan.planned_primary_genre,
            plan.planned_subgenre,
            plan.placement_confidence,
            plan.placement_status,
            json.dumps(plan.reason, sort_keys=True),
            datetime.now(UTC).isoformat(),
        ),
    )


def _source_file_path(source_path: str, relative_path: str) -> str:
    return str(PurePosixPath(source_path) / relative_path)


def _sanitize_extension(extension: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9.]", "", extension.strip())
    if not cleaned:
        return ""
    if not cleaned.startswith("."):
        cleaned = f".{cleaned}"
    return cleaned.lower()
