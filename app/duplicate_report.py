"""Read-only duplicate detection reports for organised library placements."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db


DUPLICATE_HEADERS: tuple[str, ...] = (
    "duplicate_group_key",
    "duplicate_type",
    "artist",
    "normalized_title",
    "file_path",
    "file_size_bytes",
    "sha256",
    "reason",
)

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^a-z0-9]+")
_VIDEO_ID_BRACKETS_RE = re.compile(r"\[[A-Za-z0-9_-]{6,}\]")
_NUMERIC_SUFFIX_RE = re.compile(r"\(\s*\d+\s*\)\s*$")
_VARIANT_TERMS_RE = re.compile(
    r"\b("
    r"official\s+audio|official\s+video|low\s+gain\s+mix|"
    r"visualizer|remastered|remaster|explicit|hd|4k"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DuplicateReportResult:
    report_path: str
    total_files_checked: int
    exact_hash_groups: int
    same_artist_title_groups: int
    variant_title_groups: int


@dataclass(frozen=True)
class DuplicateCandidate:
    duplicate_group_key: str
    duplicate_type: str
    artist: str
    normalized_title: str
    file_path: str
    file_size_bytes: int
    sha256: str
    reason: str


def generate_duplicate_report(
    *,
    scan_run_id: int,
    library_root: str | Path,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> DuplicateReportResult:
    """Export duplicate candidate reports without modifying library files."""

    db.init_db(db_path)
    library_root_path = Path(library_root).expanduser()
    rows = _live_library_rows(
        _load_destination_rows(scan_run_id, db_path),
        library_root_path,
    )
    report_dir = Path(out_dir).expanduser() / f"duplicates_scan_{scan_run_id}"
    report_dir.mkdir(parents=True, exist_ok=True)

    exact_hash_candidates = _exact_hash_candidates(rows)
    same_artist_title_candidates = _same_artist_title_candidates(rows)
    variant_candidates = _variant_title_candidates(rows)

    summary = {
        "scan_run_id": scan_run_id,
        "library_root": str(library_root_path),
        "report_path": str(report_dir),
        "total_files_checked": len(rows),
        "exact_hash_groups": _group_count(exact_hash_candidates),
        "same_artist_title_groups": _group_count(same_artist_title_candidates),
        "variant_title_groups": _group_count(variant_candidates),
    }
    _write_json(report_dir / "duplicate_summary.json", summary)
    _write_csv(report_dir / "exact_hash_duplicates.csv", exact_hash_candidates)
    _write_csv(
        report_dir / "same_artist_title_duplicates.csv",
        same_artist_title_candidates,
    )
    _write_csv(report_dir / "probable_variants.csv", variant_candidates)

    result = DuplicateReportResult(
        report_path=str(report_dir),
        total_files_checked=len(rows),
        exact_hash_groups=summary["exact_hash_groups"],
        same_artist_title_groups=summary["same_artist_title_groups"],
        variant_title_groups=summary["variant_title_groups"],
    )
    _record_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=summary["library_root"],
        result=result,
        candidates=[
            *exact_hash_candidates,
            *same_artist_title_candidates,
            *variant_candidates,
        ],
        db_path=db_path,
    )
    return result


def normalize_title(title: str | None) -> str:
    """Normalize titles for exact planned-title comparison."""

    value = (title or "").casefold()
    value = _PUNCTUATION_RE.sub(" ", value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def normalize_variant_title(title: str | None) -> str:
    """Normalize titles after removing common release and upload variants."""

    value = title or ""
    value = _VIDEO_ID_BRACKETS_RE.sub(" ", value)
    previous = None
    while previous != value:
        previous = value
        value = _NUMERIC_SUFFIX_RE.sub(" ", value)
    value = _VARIANT_TERMS_RE.sub(" ", value)
    return normalize_title(value)


def _load_destination_rows(scan_run_id: int, db_path: str | Path) -> list[Any]:
    with db.connect(db_path) as connection:
        return connection.execute(
            """
            SELECT
                placement_execution_files.destination_path,
                placement_execution_files.file_status,
                placement_plans.planned_artist,
                placement_plans.planned_title,
                track_identity.probable_artist,
                track_identity.probable_title,
                observed_files.file_size_bytes,
                observed_files.sha256
            FROM placement_execution_files
            INNER JOIN placement_executions
                ON placement_executions.id = placement_execution_files.execution_id
            INNER JOIN placement_plans
                ON placement_plans.id =
                    placement_execution_files.placement_plan_id
            INNER JOIN observed_files
                ON observed_files.id = placement_plans.observed_file_id
            LEFT JOIN track_identity
                ON track_identity.observed_file_id = observed_files.id
            WHERE placement_executions.scan_run_id = ?
                AND placement_execution_files.file_status IN (
                    'copied',
                    'skipped_exists'
                )
            ORDER BY placement_execution_files.destination_path
            """,
            (scan_run_id,),
        ).fetchall()


def _live_library_rows(rows: list[Any], library_root: Path) -> list[Any]:
    root = library_root.resolve(strict=False)
    live_rows: list[Any] = []
    for row in rows:
        destination_path = Path(row["destination_path"]).expanduser()
        if not destination_path.is_absolute():
            destination_path = library_root / destination_path
        if not destination_path.is_file():
            continue
        try:
            destination_path.resolve(strict=True).relative_to(root)
        except ValueError:
            continue
        live_rows.append(row)
    return live_rows


def _exact_hash_candidates(rows: list[Any]) -> list[DuplicateCandidate]:
    grouped = _group_rows(rows, lambda row: row["sha256"])
    candidates: list[DuplicateCandidate] = []
    for sha256, group_rows in grouped.items():
        if not sha256 or len(group_rows) < 2:
            continue
        candidates.extend(
            _candidate_from_row(
                row=row,
                duplicate_group_key=f"exact_hash:{sha256}",
                duplicate_type="exact_hash",
                normalized_title=normalize_title(row["planned_title"]),
                reason="same_sha256",
            )
            for row in group_rows
        )
    return candidates


def _same_artist_title_candidates(rows: list[Any]) -> list[DuplicateCandidate]:
    grouped = _group_rows(
        rows,
        lambda row: (
            _normalize_artist(row["planned_artist"]),
            normalize_title(row["planned_title"]),
        ),
    )
    candidates: list[DuplicateCandidate] = []
    for (artist, title), group_rows in grouped.items():
        if not artist or not title or len(group_rows) < 2:
            continue
        candidates.extend(
            _candidate_from_row(
                row=row,
                duplicate_group_key=f"same_artist_title:{artist}:{title}",
                duplicate_type="same_artist_title",
                normalized_title=title,
                reason="same_planned_artist_and_normalized_title",
            )
            for row in group_rows
        )
    return candidates


def _variant_title_candidates(rows: list[Any]) -> list[DuplicateCandidate]:
    grouped = _group_rows(
        rows,
        lambda row: (
            _normalize_artist(row["planned_artist"]),
            normalize_variant_title(row["planned_title"]),
        ),
    )
    candidates: list[DuplicateCandidate] = []
    for (artist, title), group_rows in grouped.items():
        if not artist or not title or len(group_rows) < 2:
            continue
        distinct_titles = {normalize_title(row["planned_title"]) for row in group_rows}
        if len(distinct_titles) < 2:
            continue
        candidates.extend(
            _candidate_from_row(
                row=row,
                duplicate_group_key=f"probable_variant:{artist}:{title}",
                duplicate_type="probable_variant",
                normalized_title=title,
                reason="titles_match_after_variant_terms_removed",
            )
            for row in group_rows
        )
    return candidates


def _group_rows(rows: list[Any], key_func) -> dict[Any, list[Any]]:
    grouped: dict[Any, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[key_func(row)].append(row)
    return grouped


def _candidate_from_row(
    *,
    row: Any,
    duplicate_group_key: str,
    duplicate_type: str,
    normalized_title: str,
    reason: str,
) -> DuplicateCandidate:
    return DuplicateCandidate(
        duplicate_group_key=duplicate_group_key,
        duplicate_type=duplicate_type,
        artist=row["planned_artist"] or "",
        normalized_title=normalized_title,
        file_path=row["destination_path"],
        file_size_bytes=row["file_size_bytes"],
        sha256=row["sha256"],
        reason=reason,
    )


def _normalize_artist(artist: str | None) -> str:
    return normalize_title(artist)


def _group_count(candidates: list[DuplicateCandidate]) -> int:
    return len({candidate.duplicate_group_key for candidate in candidates})


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file_handle:
        json.dump(payload, file_handle, indent=2, sort_keys=True)
        file_handle.write("\n")


def _write_csv(path: Path, candidates: list[DuplicateCandidate]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=list(DUPLICATE_HEADERS))
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "duplicate_group_key": candidate.duplicate_group_key,
                    "duplicate_type": candidate.duplicate_type,
                    "artist": candidate.artist,
                    "normalized_title": candidate.normalized_title,
                    "file_path": candidate.file_path,
                    "file_size_bytes": candidate.file_size_bytes,
                    "sha256": candidate.sha256,
                    "reason": candidate.reason,
                }
            )


def _record_duplicate_report(
    *,
    scan_run_id: int,
    library_root: str,
    result: DuplicateReportResult,
    candidates: list[DuplicateCandidate],
    db_path: str | Path,
) -> None:
    created_at = datetime.now(UTC).isoformat()
    with db.connect(db_path) as connection:
        report_id = connection.execute(
            """
            INSERT INTO duplicate_reports (
                scan_run_id,
                library_root,
                report_path,
                total_files_checked,
                exact_hash_groups,
                same_artist_title_groups,
                variant_title_groups,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_run_id,
                library_root,
                result.report_path,
                result.total_files_checked,
                result.exact_hash_groups,
                result.same_artist_title_groups,
                result.variant_title_groups,
                created_at,
            ),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO duplicate_candidates (
                report_id,
                duplicate_group_key,
                duplicate_type,
                artist,
                normalized_title,
                file_path,
                file_size_bytes,
                sha256,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    report_id,
                    candidate.duplicate_group_key,
                    candidate.duplicate_type,
                    candidate.artist,
                    candidate.normalized_title,
                    candidate.file_path,
                    candidate.file_size_bytes,
                    candidate.sha256,
                    candidate.reason,
                    created_at,
                )
                for candidate in candidates
            ],
        )
