"""Audit deterministic alias equivalence decisions against governance output."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.alias_equivalence import (
    deterministic_artist_alias_equivalence,
    has_artifact_marker,
    has_collaboration_marker,
    has_official_version_suffix,
    normalized_alnum_casefold,
)
from app.conflict_governance import GovernedConflict, build_conflict_governance


REPORT_DIRNAME = "alias_equivalence_audit"
SUMMARY_FILENAME = "alias_equivalence_summary.json"
AUDIT_FILENAME = "alias_equivalence_audit.csv"
PREVENTED_FILENAME = "prevented_escalations.csv"
MISSED_FILENAME = "missed_safe_aliases.csv"
REMAINING_FILENAME = "remaining_escalations.csv"

AUDIT_FIELDS: tuple[str, ...] = (
    "conflict_id",
    "conflict_type",
    "source_entity",
    "target_entity",
    "entity_role",
    "normalized_source",
    "normalized_target",
    "equivalence_category",
    "equivalence_matched",
    "equivalence_reason",
    "pre_governance_status",
    "post_governance_status",
    "escalation_reason",
    "prevented_escalation",
    "created_at",
)


@dataclass(frozen=True)
class AliasEquivalenceAuditRecord:
    conflict_id: str
    conflict_type: str
    source_entity: str
    target_entity: str
    entity_role: str
    normalized_source: str
    normalized_target: str
    equivalence_category: str
    equivalence_matched: bool
    equivalence_reason: str
    pre_governance_status: str
    post_governance_status: str
    escalation_reason: str
    prevented_escalation: bool
    created_at: str


@dataclass(frozen=True)
class AliasEquivalenceAuditReport:
    audit_records: list[AliasEquivalenceAuditRecord]
    summary: dict[str, Any]


@dataclass(frozen=True)
class AliasEquivalenceAuditResult:
    report_path: str
    total_audited_conflicts: int
    equivalence_matches: int
    prevented_escalations: int
    missed_safe_aliases: int
    remaining_escalations: int
    casing_only_matches: int
    punctuation_only_matches: int
    whitespace_only_matches: int
    suffix_noise_rejections: int
    collaboration_rejections: int
    source_artifact_rejections: int
    role_collision_rejections: int


def generate_alias_equivalence_audit_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> AliasEquivalenceAuditResult:
    reports_dir = Path(out_dir).expanduser()
    report_dir = reports_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)

    report = build_alias_equivalence_audit(reports_dir=reports_dir, db_path=db_path)
    _write_json(report_dir / SUMMARY_FILENAME, report.summary)
    _write_csv(report_dir / AUDIT_FILENAME, AUDIT_FIELDS, (asdict(item) for item in report.audit_records))
    _write_csv(
        report_dir / PREVENTED_FILENAME,
        AUDIT_FIELDS,
        (asdict(item) for item in report.audit_records if item.prevented_escalation),
    )
    _write_csv(
        report_dir / MISSED_FILENAME,
        AUDIT_FIELDS,
        (asdict(item) for item in report.audit_records if _is_missed_safe_alias(item)),
    )
    _write_csv(
        report_dir / REMAINING_FILENAME,
        AUDIT_FIELDS,
        (
            asdict(item)
            for item in report.audit_records
            if item.post_governance_status in {"needs_review", "blocked_merge"}
        ),
    )
    return AliasEquivalenceAuditResult(report_path=str(report_dir), **_summary_result(report.summary))


def build_alias_equivalence_audit(
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
    governed_conflicts: Iterable[GovernedConflict] | None = None,
) -> AliasEquivalenceAuditReport:
    if governed_conflicts is None:
        governance = build_conflict_governance(reports_dir=reports_dir, db_path=db_path)
        governed_conflicts = governance.conflicts
    records = [audit_governed_conflict(conflict) for conflict in governed_conflicts]
    return AliasEquivalenceAuditReport(audit_records=records, summary=alias_equivalence_summary(records))


def audit_governed_conflict(conflict: GovernedConflict) -> AliasEquivalenceAuditRecord:
    snapshot = _coerce_snapshot(conflict.confidence_snapshot)
    positive_types = _evidence_types(_read_json_list(conflict.positive_evidence_json))
    negative_types = _evidence_types(_read_json_list(conflict.negative_evidence_json))
    category = classify_equivalence_category(
        conflict_type=conflict.conflict_type,
        entity_role=conflict.entity_role,
        source_entity=conflict.source_entity,
        target_entity=conflict.target_entity,
    )
    decision = deterministic_artist_alias_equivalence(
        conflict_type=conflict.conflict_type,
        entity_role=conflict.entity_role,
        source_entity=conflict.source_entity,
        target_entity=conflict.target_entity,
        positive_evidence_types=positive_types,
        negative_evidence_types=negative_types,
        confidence_tier=str(snapshot.get("confidence_tier", "") or ""),
        lifecycle_state=_lifecycle_from_snapshot(snapshot),
        artifact_dominates=_artifact_dominates(_read_json_list(conflict.negative_evidence_json)),
    )
    pre_status = "safe_alias_candidate" if decision.safe_to_merge_candidate else "would_escalate"
    prevented = decision.safe_to_merge_candidate and conflict.conflict_status == "safe_to_merge_candidate"
    escalation_reason = "" if prevented else conflict.contradiction_reason or decision.reason
    return AliasEquivalenceAuditRecord(
        conflict_id=conflict.conflict_id,
        conflict_type=conflict.conflict_type,
        source_entity=conflict.source_entity,
        target_entity=conflict.target_entity,
        entity_role=conflict.entity_role,
        normalized_source=normalized_alnum_casefold(conflict.source_entity),
        normalized_target=normalized_alnum_casefold(conflict.target_entity),
        equivalence_category=category,
        equivalence_matched=decision.safe_to_merge_candidate,
        equivalence_reason=decision.reason,
        pre_governance_status=pre_status,
        post_governance_status=conflict.conflict_status,
        escalation_reason=escalation_reason,
        prevented_escalation=prevented,
        created_at=datetime.now(UTC).isoformat(),
    )


def classify_equivalence_category(
    *,
    conflict_type: str,
    entity_role: str,
    source_entity: str,
    target_entity: str,
) -> str:
    joined = f"{source_entity} {target_entity}"
    if conflict_type == "role_collision" or entity_role == "ambiguous":
        return "role_collision"
    if conflict_type != "alias_collision":
        return "not_alias_collision"
    if has_collaboration_marker(joined):
        return "collaboration_or_feature"
    if has_artifact_marker(joined):
        return "source_artifact"
    if has_official_version_suffix(joined):
        return "suffix_noise"
    if normalized_alnum_casefold(source_entity) != normalized_alnum_casefold(target_entity):
        return "semantic_difference"

    source = str(source_entity or "")
    target = str(target_entity or "")
    if source.casefold() == target.casefold() and " " not in source and " " not in target:
        return "casing_only"
    if _strip_whitespace(source) == _strip_whitespace(target) and source.casefold() == target.casefold():
        return "whitespace_only"
    if _has_punctuation(source + target) and (
        _strip_punctuation(source).casefold() == _strip_punctuation(target).casefold()
    ):
        return "punctuation_only"
    return "casing_punctuation_spacing"


def alias_equivalence_summary(records: Iterable[AliasEquivalenceAuditRecord]) -> dict[str, Any]:
    materialized = list(records)
    categories = Counter(item.equivalence_category for item in materialized)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "total_audited_conflicts": len(materialized),
        "equivalence_matches": sum(1 for item in materialized if item.equivalence_matched),
        "prevented_escalations": sum(1 for item in materialized if item.prevented_escalation),
        "missed_safe_aliases": sum(1 for item in materialized if _is_missed_safe_alias(item)),
        "remaining_escalations": sum(
            1 for item in materialized if item.post_governance_status in {"needs_review", "blocked_merge"}
        ),
        "casing_only_matches": sum(
            1 for item in materialized if item.equivalence_matched and item.equivalence_category == "casing_only"
        ),
        "punctuation_only_matches": sum(
            1 for item in materialized if item.equivalence_matched and item.equivalence_category == "punctuation_only"
        ),
        "whitespace_only_matches": sum(
            1 for item in materialized if item.equivalence_matched and item.equivalence_category == "whitespace_only"
        ),
        "suffix_noise_rejections": categories["suffix_noise"],
        "collaboration_rejections": categories["collaboration_or_feature"],
        "source_artifact_rejections": categories["source_artifact"],
        "role_collision_rejections": categories["role_collision"],
    }


def _is_missed_safe_alias(record: AliasEquivalenceAuditRecord) -> bool:
    return (
        record.conflict_type == "alias_collision"
        and record.entity_role == "artist"
        and record.normalized_source == record.normalized_target
        and record.equivalence_category not in {"suffix_noise", "collaboration_or_feature", "source_artifact"}
        and record.equivalence_matched
        and record.post_governance_status in {"needs_review", "blocked_merge"}
    )


def _summary_result(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "total_audited_conflicts": int(summary.get("total_audited_conflicts", 0) or 0),
        "equivalence_matches": int(summary.get("equivalence_matches", 0) or 0),
        "prevented_escalations": int(summary.get("prevented_escalations", 0) or 0),
        "missed_safe_aliases": int(summary.get("missed_safe_aliases", 0) or 0),
        "remaining_escalations": int(summary.get("remaining_escalations", 0) or 0),
        "casing_only_matches": int(summary.get("casing_only_matches", 0) or 0),
        "punctuation_only_matches": int(summary.get("punctuation_only_matches", 0) or 0),
        "whitespace_only_matches": int(summary.get("whitespace_only_matches", 0) or 0),
        "suffix_noise_rejections": int(summary.get("suffix_noise_rejections", 0) or 0),
        "collaboration_rejections": int(summary.get("collaboration_rejections", 0) or 0),
        "source_artifact_rejections": int(summary.get("source_artifact_rejections", 0) or 0),
        "role_collision_rejections": int(summary.get("role_collision_rejections", 0) or 0),
    }


def _lifecycle_from_snapshot(snapshot: dict[str, Any]) -> str:
    confidence_tier = str(snapshot.get("confidence_tier", "") or "")
    raw_positive = float(snapshot.get("raw_positive_score", 0.0) or 0.0)
    raw_negative = float(snapshot.get("raw_negative_score", 0.0) or 0.0)
    normalized = float(snapshot.get("normalized_confidence", 0.0) or 0.0)
    if confidence_tier == "blocked":
        return "blocked"
    if raw_positive >= 0.55 and raw_negative >= 0.55:
        return "conflicted"
    if normalized >= 0.74:
        return "canonical"
    if normalized >= 0.55:
        return "probationary"
    return "candidate"


def _artifact_dominates(negative: list[dict[str, Any]]) -> bool:
    artifact_score = 0.0
    other_score = 0.0
    for item in negative:
        score = float(item.get("calibrated_score", item.get("weighted_score", 0.0)) or 0.0)
        if item.get("evidence_family") == "artifact" or item.get("evidence_type") in {
            "uploader_signature",
            "source_artifact_pattern",
        }:
            artifact_score += score
        else:
            other_score += score
    return artifact_score >= 0.38 and artifact_score >= other_score


def _read_json_list(value: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _coerce_snapshot(value: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _evidence_types(items: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("evidence_type", "")) for item in items if item.get("evidence_type")}


def _strip_whitespace(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _strip_punctuation(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char.isspace())


def _has_punctuation(value: str) -> bool:
    return any(not char.isalnum() and not char.isspace() for char in value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, sort_keys=True)
        file_handle.write("\n")


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialized:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
