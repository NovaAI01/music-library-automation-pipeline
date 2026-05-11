"""Read-only keep/remove recommendations for duplicate candidate groups."""

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


REVIEW_HEADERS: tuple[str, ...] = (
    "duplicate_group_key",
    "file_path",
    "decision",
    "reason",
)

_NUMERIC_SUFFIX_RE = re.compile(r"\(\s*\d+\s*\)(?=\.[^.]+$|$)")
_OFFICIAL_VIDEO_RE = re.compile(r"\bofficial\s+video\b", re.IGNORECASE)
_VISUALIZER_RE = re.compile(r"\bvisuali[sz]er\b", re.IGNORECASE)
_REMASTER_RE = re.compile(r"\bremaster(?:ed)?\b", re.IGNORECASE)
_BRACKET_SUFFIX_RE = re.compile(r"\[[^\]]+\](?=\s*(?:\.[^.]+)?$)")
_PAREN_SUFFIX_RE = re.compile(r"\([^)]*\)(?=\s*(?:\.[^.]+)?$)")


@dataclass(frozen=True)
class DuplicateReviewResult:
    plan_path: str
    total_groups: int
    total_files_reviewed: int
    keeper_count: int
    remove_candidate_count: int


@dataclass(frozen=True)
class DuplicateReviewItem:
    duplicate_group_key: str
    file_path: str
    decision: str
    reason: str


@dataclass(frozen=True)
class _Candidate:
    duplicate_group_key: str
    file_path: str
    file_size_bytes: int


def generate_duplicate_review_plan(
    *,
    duplicate_report_id: int,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> DuplicateReviewResult:
    """Create a duplicate review plan without mutating any audio files."""

    db.init_db(db_path)
    report = _load_duplicate_report(duplicate_report_id, db_path)
    if report is None:
        raise ValueError(f"duplicate report not found: {duplicate_report_id}")

    candidates = _load_candidates(duplicate_report_id, db_path)
    groups = _group_candidates(candidates)
    report_dir = (
        Path(out_dir).expanduser()
        / f"duplicate_review_scan_{report['scan_run_id']}"
    )
    report_dir.mkdir(parents=True, exist_ok=True)

    items: list[DuplicateReviewItem] = []
    for group_key in sorted(groups):
        items.extend(_review_group(group_key, groups[group_key]))

    summary = {
        "duplicate_report_id": duplicate_report_id,
        "scan_run_id": report["scan_run_id"],
        "plan_path": str(report_dir),
        "total_groups": len(groups),
        "total_files_reviewed": len(items),
        "keeper_count": _decision_count(items, "keep_candidate"),
        "remove_candidate_count": _decision_count(items, "remove_candidate"),
        "manual_review_count": _decision_count(items, "manual_review"),
    }
    _write_json(report_dir / "duplicate_review_summary.json", summary)
    _write_csv(report_dir / "duplicate_review_plan.csv", items)

    result = DuplicateReviewResult(
        plan_path=str(report_dir),
        total_groups=summary["total_groups"],
        total_files_reviewed=summary["total_files_reviewed"],
        keeper_count=summary["keeper_count"],
        remove_candidate_count=summary["remove_candidate_count"],
    )
    _record_review_plan(
        duplicate_report_id=duplicate_report_id,
        scan_run_id=report["scan_run_id"],
        result=result,
        items=items,
        db_path=db_path,
    )
    return result


def _load_duplicate_report(
    duplicate_report_id: int, db_path: str | Path
) -> Any | None:
    with db.connect(db_path) as connection:
        return connection.execute(
            """
            SELECT id, scan_run_id
            FROM duplicate_reports
            WHERE id = ?
            """,
            (duplicate_report_id,),
        ).fetchone()


def _load_candidates(
    duplicate_report_id: int, db_path: str | Path
) -> list[_Candidate]:
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT duplicate_group_key, file_path, file_size_bytes
            FROM duplicate_candidates
            WHERE report_id = ?
            ORDER BY duplicate_group_key, file_path
            """,
            (duplicate_report_id,),
        ).fetchall()
    return [
        _Candidate(
            duplicate_group_key=row["duplicate_group_key"],
            file_path=row["file_path"],
            file_size_bytes=row["file_size_bytes"],
        )
        for row in rows
    ]


def _group_candidates(
    candidates: list[_Candidate],
) -> dict[str, list[_Candidate]]:
    groups: dict[str, list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate.duplicate_group_key].append(candidate)
    return dict(groups)


def _review_group(
    group_key: str, candidates: list[_Candidate]
) -> list[DuplicateReviewItem]:
    ranked = sorted(
        candidates, key=lambda candidate: _ranking_key(candidate, candidates)
    )
    if len(candidates) > 3 and not _has_clear_keeper(ranked, candidates):
        return [
            DuplicateReviewItem(
                duplicate_group_key=group_key,
                file_path=candidate.file_path,
                decision="manual_review",
                reason="group_has_more_than_3_files_without_clear_keeper",
            )
            for candidate in sorted(
                candidates, key=lambda candidate: candidate.file_path
            )
        ]

    keeper = ranked[0]
    return [
        DuplicateReviewItem(
            duplicate_group_key=group_key,
            file_path=candidate.file_path,
            decision=(
                "keep_candidate"
                if candidate.file_path == keeper.file_path
                else "remove_candidate"
            ),
            reason=(
                "best_ranked_by_suffix_size_cleanliness_path"
                if candidate.file_path == keeper.file_path
                else f"lower_ranked_than_keeper:{keeper.file_path}"
            ),
        )
        for candidate in sorted(candidates, key=lambda candidate: candidate.file_path)
    ]


def _ranking_key(
    candidate: _Candidate, group_candidates: list[_Candidate]
) -> tuple[int, int, int, str]:
    all_remasters = all(_has_remaster(item.file_path) for item in group_candidates)
    return (
        1 if _has_numeric_suffix(candidate.file_path) else 0,
        -candidate.file_size_bytes,
        _cleanliness_penalty(candidate.file_path, all_remasters=all_remasters),
        candidate.file_path,
    )


def _has_clear_keeper(
    ranked: list[_Candidate], group_candidates: list[_Candidate]
) -> bool:
    if len(ranked) < 2:
        return True
    best = ranked[0]
    second = ranked[1]
    return _ranking_key(best, group_candidates)[:3] != _ranking_key(
        second, group_candidates
    )[:3]


def _has_numeric_suffix(path: str) -> bool:
    return bool(_NUMERIC_SUFFIX_RE.search(Path(path).name))


def _has_remaster(path: str) -> bool:
    return bool(_REMASTER_RE.search(Path(path).name))


def _cleanliness_penalty(path: str, *, all_remasters: bool) -> int:
    filename = Path(path).name
    penalty = 0
    penalty += len(_NUMERIC_SUFFIX_RE.findall(filename))
    penalty += len(_BRACKET_SUFFIX_RE.findall(filename))
    penalty += len(_PAREN_SUFFIX_RE.findall(filename))
    if _OFFICIAL_VIDEO_RE.search(filename):
        penalty += 1
    if _VISUALIZER_RE.search(filename):
        penalty += 1
    if not all_remasters and _REMASTER_RE.search(filename):
        penalty += 1
    return penalty


def _decision_count(items: list[DuplicateReviewItem], decision: str) -> int:
    return sum(1 for item in items if item.decision == decision)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file_handle:
        json.dump(payload, file_handle, indent=2, sort_keys=True)
        file_handle.write("\n")


def _write_csv(path: Path, items: list[DuplicateReviewItem]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=list(REVIEW_HEADERS))
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "duplicate_group_key": item.duplicate_group_key,
                    "file_path": item.file_path,
                    "decision": item.decision,
                    "reason": item.reason,
                }
            )


def _record_review_plan(
    *,
    duplicate_report_id: int,
    scan_run_id: int,
    result: DuplicateReviewResult,
    items: list[DuplicateReviewItem],
    db_path: str | Path,
) -> None:
    created_at = datetime.now(UTC).isoformat()
    with db.connect(db_path) as connection:
        review_plan_id = connection.execute(
            """
            INSERT INTO duplicate_review_plans (
                duplicate_report_id,
                scan_run_id,
                plan_path,
                total_groups,
                total_files_reviewed,
                keeper_count,
                remove_candidate_count,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                duplicate_report_id,
                scan_run_id,
                result.plan_path,
                result.total_groups,
                result.total_files_reviewed,
                result.keeper_count,
                result.remove_candidate_count,
                created_at,
            ),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO duplicate_review_items (
                review_plan_id,
                duplicate_group_key,
                file_path,
                decision,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    review_plan_id,
                    item.duplicate_group_key,
                    item.file_path,
                    item.decision,
                    item.reason,
                    created_at,
                )
                for item in items
            ],
        )
