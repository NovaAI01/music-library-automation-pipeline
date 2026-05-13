"""Persistent review decision ledger for metadata suggestions."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app import db


DECISIONS: tuple[str, ...] = ("approved", "rejected", "deferred")
REVIEW_DECISION_HEADERS: tuple[str, ...] = (
    "decision_id",
    "suggestion_key",
    "file_path",
    "field",
    "current_value",
    "proposed_value",
    "suggestion_type",
    "confidence",
    "decision",
    "decision_reason",
    "source_evidence_json",
    "decided_at",
)


@dataclass(frozen=True)
class ReviewDecisionResult:
    decision_id: int
    suggestion_key: str
    decision: str
    decision_reason: str
    decided_at: str


@dataclass(frozen=True)
class ReviewDecisionImportResult:
    imported_count: int
    updated_count: int
    skipped_count: int


@dataclass(frozen=True)
class ReviewDecisionReportResult:
    report_path: str
    total_decisions: int
    approved_count: int
    rejected_count: int
    deferred_count: int


def suggestion_key_for(
    *,
    file_path: str,
    field: str,
    current_value: str,
    proposed_value: str,
    suggestion_type: str,
) -> str:
    """Return a stable key for a reviewable suggestion."""

    payload = {
        "file_path": file_path,
        "field": field,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "suggestion_type": suggestion_type,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def suggestion_key_from_row(row: dict[str, Any]) -> str:
    existing = str(row.get("suggestion_key", "") or "").strip()
    if existing:
        return existing
    return suggestion_key_for(
        file_path=str(row.get("file_path", "") or row.get("path", "")),
        field=str(row.get("field", "")),
        current_value=str(row.get("current_value", "")),
        proposed_value=str(row.get("proposed_value", "")),
        suggestion_type=str(row.get("suggestion_type", "")),
    )


def record_review_decision(
    *,
    suggestion_key: str,
    decision: str,
    reason: str,
    db_path: str | Path = db.DEFAULT_DB_PATH,
    suggestion: dict[str, Any] | None = None,
) -> ReviewDecisionResult:
    """Create or update one review decision without mutating audio metadata."""

    suggestion_key = suggestion_key.strip()
    if not suggestion_key:
        raise ValueError("suggestion_key is required")
    decision = _validate_decision(decision)
    suggestion_payload = _normalized_suggestion_payload(suggestion or {})
    decided_at = _utc_now()

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        existing = connection.execute(
            "SELECT * FROM review_decisions WHERE suggestion_key = ?",
            (suggestion_key,),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO review_decisions (
                    suggestion_key,
                    file_path,
                    field,
                    current_value,
                    proposed_value,
                    suggestion_type,
                    confidence,
                    decision,
                    decision_reason,
                    source_evidence_json,
                    decided_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    suggestion_key,
                    suggestion_payload["file_path"],
                    suggestion_payload["field"],
                    suggestion_payload["current_value"],
                    suggestion_payload["proposed_value"],
                    suggestion_payload["suggestion_type"],
                    suggestion_payload["confidence"],
                    decision,
                    reason,
                    suggestion_payload["source_evidence_json"],
                    decided_at,
                ),
            )
        else:
            merged = _merge_existing_payload(existing, suggestion_payload)
            connection.execute(
                """
                UPDATE review_decisions
                SET file_path = ?,
                    field = ?,
                    current_value = ?,
                    proposed_value = ?,
                    suggestion_type = ?,
                    confidence = ?,
                    decision = ?,
                    decision_reason = ?,
                    source_evidence_json = ?,
                    decided_at = ?
                WHERE suggestion_key = ?
                """,
                (
                    merged["file_path"],
                    merged["field"],
                    merged["current_value"],
                    merged["proposed_value"],
                    merged["suggestion_type"],
                    merged["confidence"],
                    decision,
                    reason,
                    merged["source_evidence_json"],
                    decided_at,
                    suggestion_key,
                ),
            )

        row = connection.execute(
            "SELECT * FROM review_decisions WHERE suggestion_key = ?",
            (suggestion_key,),
        ).fetchone()

    return ReviewDecisionResult(
        decision_id=int(row["decision_id"]),
        suggestion_key=str(row["suggestion_key"]),
        decision=str(row["decision"]),
        decision_reason=str(row["decision_reason"]),
        decided_at=str(row["decided_at"]),
    )


def import_review_decisions(
    *,
    suggestions_path: str | Path,
    decisions_path: str | Path,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> ReviewDecisionImportResult:
    suggestion_rows = _read_csv(Path(suggestions_path))
    suggestions_by_key = {suggestion_key_from_row(row): row for row in suggestion_rows}
    suggestions_by_visible = {
        _visible_suggestion_signature(row, include_type=True): row for row in suggestion_rows
    }
    suggestions_by_visible_without_type = {
        _visible_suggestion_signature(row, include_type=False): row for row in suggestion_rows
    }
    imported_count = 0
    updated_count = 0
    skipped_count = 0

    db.init_db(db_path)
    for row in _read_csv(Path(decisions_path)):
        resolved = _resolve_import_suggestion(
            row=row,
            suggestions_by_key=suggestions_by_key,
            suggestions_by_visible=suggestions_by_visible,
            suggestions_by_visible_without_type=suggestions_by_visible_without_type,
        )
        if resolved is None:
            skipped_count += 1
            continue
        suggestion_key, suggestion = resolved
        decision = str(row.get("decision", "")).strip()
        reason = str(row.get("decision_reason", "") or row.get("reason", ""))
        existed = _decision_exists(suggestion_key, db_path)
        try:
            record_review_decision(
                suggestion_key=suggestion_key,
                decision=decision,
                reason=reason,
                suggestion=suggestion,
                db_path=db_path,
            )
        except ValueError:
            skipped_count += 1
            continue
        if existed:
            updated_count += 1
        else:
            imported_count += 1

    return ReviewDecisionImportResult(
        imported_count=imported_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
    )


def generate_review_decision_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> ReviewDecisionReportResult:
    db.init_db(db_path)
    rows = list_review_decisions(db_path)
    report_dir = Path(out_dir).expanduser() / "review_decisions"
    report_dir.mkdir(parents=True, exist_ok=True)
    summary = review_decision_summary(rows)

    _write_json(report_dir / "review_decision_summary.json", summary)
    _write_csv(report_dir / "review_decisions.csv", REVIEW_DECISION_HEADERS, rows)

    return ReviewDecisionReportResult(report_path=str(report_dir), **summary)


def list_review_decisions(db_path: str | Path = db.DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM review_decisions
            ORDER BY decided_at DESC, decision_id DESC
            """
        ).fetchall()
    return [_row_dict(row) for row in rows]


def decisions_by_key(db_path: str | Path = db.DEFAULT_DB_PATH) -> dict[str, dict[str, Any]]:
    return {row["suggestion_key"]: row for row in list_review_decisions(db_path)}


def review_decision_summary(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(row["decision"] for row in rows)
    total = sum(counts.values())
    return {
        "total_decisions": total,
        "approved_count": counts["approved"],
        "rejected_count": counts["rejected"],
        "deferred_count": counts["deferred"],
    }


def attach_decisions_to_suggestions(
    suggestions: list[dict[str, Any]],
    decision_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for suggestion in suggestions:
        suggestion_key = suggestion_key_from_row(suggestion)
        decision = decision_lookup.get(suggestion_key)
        enriched.append(
            {
                **suggestion,
                "suggestion_key": suggestion_key,
                "decision": decision["decision"] if decision else "",
                "decision_reason": decision["decision_reason"] if decision else "",
                "decided_at": decision["decided_at"] if decision else "",
            }
        )
    return enriched


def approved_artist_casing_rules(
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    return [
        _rule(row)
        for row in list_review_decisions(db_path)
        if row["decision"] == "approved" and row["suggestion_type"] == "artist_casing"
    ]


def approved_title_cleanup_rules(
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    return [
        _rule(row)
        for row in list_review_decisions(db_path)
        if row["decision"] == "approved"
        and row["suggestion_type"] in {"title_cleanup", "junk_suffix_removal", "separator_cleanup", "duplicate_whitespace_cleanup"}
        and row["field"] == "title"
    ]


def approved_album_artist_rules(
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    return [
        _rule(row)
        for row in list_review_decisions(db_path)
        if row["decision"] == "approved" and row["field"] == "album_artist"
    ]


def rejected_patterns(
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    return [_rule(row) for row in list_review_decisions(db_path) if row["decision"] == "rejected"]


def _rule(row: dict[str, Any]) -> dict[str, str]:
    return {
        "field": str(row["field"]),
        "current_value": str(row["current_value"]),
        "proposed_value": str(row["proposed_value"]),
        "suggestion_type": str(row["suggestion_type"]),
        "decision_reason": str(row["decision_reason"]),
    }


def _validate_decision(decision: str) -> str:
    normalized = decision.strip().lower()
    if normalized not in DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(DECISIONS)}")
    return normalized


def _normalized_suggestion_payload(suggestion: dict[str, Any]) -> dict[str, str]:
    return {
        "file_path": str(suggestion.get("file_path", "") or suggestion.get("path", "")),
        "field": str(suggestion.get("field", "")),
        "current_value": str(suggestion.get("current_value", "")),
        "proposed_value": str(suggestion.get("proposed_value", "")),
        "suggestion_type": str(suggestion.get("suggestion_type", "")),
        "confidence": str(suggestion.get("confidence", "")),
        "source_evidence_json": _source_evidence_json(suggestion),
    }


def _merge_existing_payload(existing: Any, incoming: dict[str, str]) -> dict[str, str]:
    return {
        key: incoming[key] if incoming[key] not in ("", "[]") else str(existing[key])
        for key in (
            "file_path",
            "field",
            "current_value",
            "proposed_value",
            "suggestion_type",
            "confidence",
            "source_evidence_json",
        )
    }


def _source_evidence_json(suggestion: dict[str, Any]) -> str:
    evidence = suggestion.get("source_evidence_json", suggestion.get("source_evidence", []))
    if isinstance(evidence, str):
        try:
            parsed = json.loads(evidence)
            evidence = parsed if isinstance(parsed, list) else [evidence]
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(evidence)
                evidence = parsed if isinstance(parsed, list) else [evidence]
            except (SyntaxError, ValueError):
                evidence = [evidence] if evidence else []
    elif not isinstance(evidence, list):
        evidence = []
    return json.dumps([str(item) for item in evidence], sort_keys=True)


def _decision_exists(suggestion_key: str, db_path: str | Path) -> bool:
    with db.connect(db_path) as connection:
        return (
            connection.execute(
                "SELECT 1 FROM review_decisions WHERE suggestion_key = ?",
                (suggestion_key,),
            ).fetchone()
            is not None
        )


def _resolve_import_suggestion(
    *,
    row: dict[str, Any],
    suggestions_by_key: dict[str, dict[str, Any]],
    suggestions_by_visible: dict[tuple[str, ...], dict[str, Any]],
    suggestions_by_visible_without_type: dict[tuple[str, ...], dict[str, Any]],
) -> tuple[str, dict[str, Any]] | None:
    suggestion_key = suggestion_key_from_row(row)
    suggestion = suggestions_by_key.get(suggestion_key)
    if suggestion is None:
        if str(row.get("suggestion_type", "")).strip():
            suggestion = suggestions_by_visible.get(
                _visible_suggestion_signature(row, include_type=True)
            )
        else:
            suggestion = suggestions_by_visible_without_type.get(
                _visible_suggestion_signature(row, include_type=False)
            )
    if suggestion is None:
        return None
    return suggestion_key_from_row(suggestion), suggestion


def _visible_suggestion_signature(
    row: dict[str, Any],
    *,
    include_type: bool,
) -> tuple[str, ...]:
    fields = ("file_path", "field", "current_value", "proposed_value")
    signature = tuple(str(row.get(field, "") or "").strip() for field in fields)
    if include_type:
        return signature + (str(row.get("suggestion_type", "") or "").strip(),)
    return signature


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in REVIEW_DECISION_HEADERS}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, headers: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
