"""Deterministic governance for unresolved canonical graph conflicts.

The governance layer is review-only. It classifies unresolved canonical graph
conflicts into blocked, review, deferred, resolved, or safe-candidate buckets,
but it never merges entities, writes tags, or mutates media files.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.alias_equivalence import (
    deterministic_album_title_equivalence,
    deterministic_artist_alias_equivalence,
    has_artifact_marker,
    has_collaboration_marker,
    has_official_version_suffix,
)
from app.canonical_confidence import ScoredEntity, collect_scored_entities, score_canonical_entity
from app.canonical_entity_graph import CanonicalGraph, UnresolvedConflict, build_canonical_graph
from app.normalization_knowledge import derive_normalization_rules
from app.review_decisions import list_review_decisions


REPORT_DIRNAME = "conflict_governance"
SUMMARY_FILENAME = "conflict_summary.json"
CONFLICTS_FILENAME = "conflicts.csv"
BLOCKED_FILENAME = "blocked_merges.csv"
SAFE_FILENAME = "safe_merge_candidates.csv"
NEEDS_REVIEW_FILENAME = "needs_review.csv"
DEFERRED_FILENAME = "deferred.csv"

CONFLICT_TYPES = {
    "alias_collision",
    "role_collision",
    "duplicate_identity_conflict",
    "album_membership_conflict",
    "track_version_conflict",
    "promotion_conflict",
    "artifact_collision",
    "ambiguous_collaboration",
}
CONFLICT_STATUSES = {
    "unresolved",
    "needs_review",
    "blocked_merge",
    "safe_to_merge_candidate",
    "deferred",
    "resolved",
}
CONFLICT_FIELDS: tuple[str, ...] = (
    "conflict_id",
    "conflict_type",
    "source_entity",
    "target_entity",
    "entity_role",
    "conflict_status",
    "severity",
    "confidence_snapshot",
    "positive_evidence_json",
    "negative_evidence_json",
    "contradiction_reason",
    "recommended_action",
    "created_at",
)


@dataclass(frozen=True)
class GovernedConflict:
    conflict_id: str
    conflict_type: str
    source_entity: str
    target_entity: str
    entity_role: str
    conflict_status: str
    severity: str
    confidence_snapshot: str
    positive_evidence_json: str
    negative_evidence_json: str
    contradiction_reason: str
    recommended_action: str
    created_at: str


@dataclass(frozen=True)
class ConflictGovernanceReport:
    conflicts: list[GovernedConflict]
    summary: dict[str, Any]


@dataclass(frozen=True)
class ConflictGovernanceResult:
    report_path: str
    total_conflicts: int
    blocked_merges: int
    safe_merge_candidates: int
    needs_review: int
    deferred: int
    resolved: int
    high_severity: int
    medium_severity: int
    low_severity: int


def generate_conflict_governance_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> ConflictGovernanceResult:
    """Write review-only conflict governance reports."""

    reports_dir = Path(out_dir).expanduser()
    report_dir = reports_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    report = build_conflict_governance(reports_dir=reports_dir, db_path=db_path)
    _write_json(report_dir / SUMMARY_FILENAME, report.summary)
    _write_csv(report_dir / CONFLICTS_FILENAME, CONFLICT_FIELDS, (asdict(item) for item in report.conflicts))
    _write_csv(
        report_dir / BLOCKED_FILENAME,
        CONFLICT_FIELDS,
        (asdict(item) for item in report.conflicts if item.conflict_status == "blocked_merge"),
    )
    _write_csv(
        report_dir / SAFE_FILENAME,
        CONFLICT_FIELDS,
        (asdict(item) for item in report.conflicts if item.conflict_status == "safe_to_merge_candidate"),
    )
    _write_csv(
        report_dir / NEEDS_REVIEW_FILENAME,
        CONFLICT_FIELDS,
        (asdict(item) for item in report.conflicts if item.conflict_status == "needs_review"),
    )
    _write_csv(
        report_dir / DEFERRED_FILENAME,
        CONFLICT_FIELDS,
        (asdict(item) for item in report.conflicts if item.conflict_status == "deferred"),
    )
    return ConflictGovernanceResult(report_path=str(report_dir), **_summary_result(report.summary))


def build_conflict_governance(
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
    graph: CanonicalGraph | None = None,
) -> ConflictGovernanceReport:
    graph = graph or build_canonical_graph(reports_dir=reports_dir, db_path=db_path)
    scored = _scored_lookup(db_path)
    approvals = _approved_alias_pairs(db_path)
    conflicts = [
        govern_unresolved_conflict(conflict, scored=scored, approved_alias_pairs=approvals)
        for conflict in graph.unresolved_conflicts
    ]
    conflicts = sorted(conflicts, key=lambda item: (item.conflict_status, item.severity, item.conflict_id))
    return ConflictGovernanceReport(conflicts=conflicts, summary=conflict_summary(conflicts))


def govern_unresolved_conflict(
    conflict: UnresolvedConflict,
    *,
    scored: dict[tuple[str, str], ScoredEntity] | None = None,
    approved_alias_pairs: set[tuple[str, str]] | None = None,
) -> GovernedConflict:
    variants = _variants(conflict.variants)
    source = variants[0] if variants else conflict.entity_key
    target = variants[1] if len(variants) > 1 else conflict.entity_key
    entity_role = _entity_role(conflict.entity_type)
    scored_entity = (scored or {}).get((_entity_type(entity_role), _norm(source))) or (scored or {}).get((_entity_type(entity_role), _norm(target)))
    if scored_entity is None:
        scored_entity = score_canonical_entity(
            entity_type=_entity_type(entity_role),
            entity_key=conflict.entity_key,
            entity_value=source or target,
            evidence_count=conflict.evidence_count,
            conflict_count=conflict.conflict_count,
            average_reliability=0.58,
            role_agreement=entity_role in {"artist", "album", "track"},
        )
    return evaluate_conflict(
        conflict_id=conflict.conflict_id,
        conflict_type=_conflict_type(conflict, scored_entity, variants),
        source_entity=source,
        target_entity=target,
        entity_role=entity_role,
        evidence_count=conflict.evidence_count,
        conflict_count=conflict.conflict_count,
        rationale=conflict.rationale,
        confidence_snapshot=_confidence_snapshot(scored_entity),
        positive_evidence_json=scored_entity.positive_evidence_json,
        negative_evidence_json=scored_entity.negative_evidence_json,
        lifecycle_state=_lifecycle_from_snapshot(scored_entity),
        approved_alias=_has_approved_alias(source, target, approved_alias_pairs or set()),
        created_at=conflict.created_at,
    )


def evaluate_conflict(
    *,
    conflict_id: str | None = None,
    conflict_type: str,
    source_entity: str,
    target_entity: str,
    entity_role: str,
    evidence_count: int = 1,
    conflict_count: int = 1,
    rationale: str = "",
    confidence_snapshot: dict[str, Any] | str | None = None,
    positive_evidence_json: str = "[]",
    negative_evidence_json: str = "[]",
    lifecycle_state: str = "candidate",
    approved_alias: bool = False,
    normalization_knowledge: bool = False,
    created_at: str | None = None,
) -> GovernedConflict:
    """Classify one conflict using deterministic merge vetoes."""

    conflict_type = conflict_type if conflict_type in CONFLICT_TYPES else "duplicate_identity_conflict"
    source_norm = _norm(source_entity)
    target_norm = _norm(target_entity)
    snapshot = _coerce_snapshot(confidence_snapshot)
    positive = _read_json_list(positive_evidence_json)
    negative = _read_json_list(negative_evidence_json)
    positive_types = _evidence_types(positive)
    negative_types = _evidence_types(negative)
    raw_positive = float(snapshot.get("raw_positive_score", 0.0) or 0.0)
    raw_negative = float(snapshot.get("raw_negative_score", 0.0) or 0.0)
    confidence = float(snapshot.get("normalized_confidence", 0.0) or 0.0)
    confidence_tier = str(snapshot.get("confidence_tier", "") or "")
    confidence_gap = abs(raw_positive - raw_negative)
    artifact_dominates = _artifact_dominates(negative)
    role_conflict = conflict_type == "role_collision" or "conflicting_role_pattern" in negative_types
    blocked_alias_marker_text = f"{source_entity} {target_entity}"
    version_suffix_conflict = conflict_type == "alias_collision" and has_official_version_suffix(blocked_alias_marker_text)
    artifact_marker_conflict = conflict_type == "alias_collision" and has_artifact_marker(blocked_alias_marker_text)
    collaboration_conflict = (
        conflict_type == "ambiguous_collaboration"
        or _collaboration_single_artist_conflict(source_entity, target_entity)
        or (conflict_type == "alias_collision" and has_collaboration_marker(blocked_alias_marker_text))
    )
    lifecycle_blocked = lifecycle_state in {"conflicted", "blocked", "deprecated"}
    low_negative = raw_negative <= 0.34 and not artifact_dominates and conflict_count <= 1
    same_role = entity_role in {"artist", "album", "track", "version"} and not role_conflict
    strong_alias = source_norm == target_norm or conflict_type == "alias_collision" or "approved_normalization_rule" in positive_types
    approved_review = approved_alias or normalization_knowledge or "approved_normalization_rule" in positive_types
    merge_ready_lifecycle = lifecycle_state in {"probationary", "canonical"}
    deterministic_alias = deterministic_artist_alias_equivalence(
        conflict_type=conflict_type,
        entity_role=entity_role,
        source_entity=source_entity,
        target_entity=target_entity,
        positive_evidence_types=positive_types,
        negative_evidence_types=negative_types,
        confidence_tier=confidence_tier,
        lifecycle_state=lifecycle_state,
        artifact_dominates=artifact_dominates,
    )
    deterministic_album_title = deterministic_album_title_equivalence(
        conflict_type=conflict_type,
        entity_role=entity_role,
        source_entity=source_entity,
        target_entity=target_entity,
        positive_evidence_types=positive_types,
        negative_evidence_types=negative_types,
        confidence_tier=confidence_tier,
        lifecycle_state=lifecycle_state,
        artifact_dominates=artifact_dominates,
    )

    vetoes: list[str] = []
    if role_conflict and not approved_review:
        vetoes.append("roles conflict and no approved review decision exists")
    if artifact_dominates:
        vetoes.append("dominant artifact evidence blocks merge")
    if artifact_marker_conflict:
        vetoes.append("uploader/channel/label artifact marker blocks merge")
    if version_suffix_conflict:
        vetoes.append("official/version suffix blocks merge")
    if collaboration_conflict:
        vetoes.append("collaboration string conflicts with single artist identity")
    if lifecycle_blocked:
        vetoes.append(f"lifecycle state is {lifecycle_state}")
    if (
        confidence_gap < 0.16
        and not approved_review
        and not deterministic_alias.safe_to_merge_candidate
        and not deterministic_album_title.safe_to_merge_candidate
    ):
        vetoes.append("confidence gap is too small to determine canonical winner")

    if vetoes:
        status = "blocked_merge"
        severity = "high" if artifact_dominates or role_conflict or lifecycle_blocked else "medium"
        action = "do not merge; keep entities separate until human review resolves the contradiction"
        reason = " | ".join(vetoes)
    elif deterministic_alias.safe_to_merge_candidate:
        status = "safe_to_merge_candidate"
        severity = "low"
        action = "safe alias candidate; merge only through reviewed canonical alias workflow"
        reason = deterministic_alias.reason
    elif deterministic_album_title.safe_to_merge_candidate:
        status = "safe_to_merge_candidate"
        severity = "low"
        action = "safe album title candidate; merge only through reviewed canonical album workflow"
        reason = deterministic_album_title.reason
    elif same_role and strong_alias and low_negative and approved_review and merge_ready_lifecycle:
        status = "safe_to_merge_candidate"
        severity = "low"
        action = "eligible for human-approved merge workflow; no automatic merge is executed"
        reason = "same role, strong alias evidence, low negative evidence, approved review or knowledge, and lifecycle allows promotion"
    elif confidence < 0.42 or evidence_count <= 1:
        status = "deferred"
        severity = "low"
        action = "defer merge decision until more local evidence is observed"
        reason = "sparse or low-confidence evidence is not enough for a canonical decision"
    else:
        status = "needs_review"
        severity = "medium"
        action = "queue for human review with evidence and lifecycle snapshots"
        reason = rationale or "unresolved conflict needs human adjudication"

    return GovernedConflict(
        conflict_id=conflict_id or _stable_id("governed_conflict", f"{conflict_type}:{source_entity}:{target_entity}:{entity_role}"),
        conflict_type=conflict_type,
        source_entity=source_entity,
        target_entity=target_entity,
        entity_role=entity_role,
        conflict_status=status,
        severity=severity,
        confidence_snapshot=json.dumps(snapshot, sort_keys=True),
        positive_evidence_json=_json_dump(positive_evidence_json),
        negative_evidence_json=_json_dump(negative_evidence_json),
        contradiction_reason=reason,
        recommended_action=action,
        created_at=created_at or datetime.now(UTC).isoformat(),
    )


def conflict_summary(conflicts: Iterable[GovernedConflict]) -> dict[str, Any]:
    materialized = list(conflicts)
    statuses = Counter(item.conflict_status for item in materialized)
    severities = Counter(item.severity for item in materialized)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "total_conflicts": len(materialized),
        "blocked_merges": statuses["blocked_merge"],
        "safe_merge_candidates": statuses["safe_to_merge_candidate"],
        "needs_review": statuses["needs_review"],
        "deferred": statuses["deferred"],
        "resolved": statuses["resolved"],
        "high_severity": severities["high"],
        "medium_severity": severities["medium"],
        "low_severity": severities["low"],
    }


def read_conflict_governance_report(
    reports_dir: str | Path = "reports",
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[str]]:
    report_dir = Path(reports_dir).expanduser() / REPORT_DIRNAME
    summary, missing_summary = _read_json(report_dir / SUMMARY_FILENAME)
    conflicts, missing_conflicts = _read_csv(report_dir / CONFLICTS_FILENAME)
    blocked, missing_blocked = _read_csv(report_dir / BLOCKED_FILENAME)
    safe, missing_safe = _read_csv(report_dir / SAFE_FILENAME)
    needs_review, missing_needs_review = _read_csv(report_dir / NEEDS_REVIEW_FILENAME)
    return (
        summary,
        conflicts,
        blocked,
        safe,
        needs_review,
        [item for item in (missing_summary, missing_conflicts, missing_blocked, missing_safe, missing_needs_review) if item],
    )


def governance_summary_from_reports(reports_dir: str | Path = "reports") -> dict[str, int]:
    summary, _ = _read_json(Path(reports_dir).expanduser() / REPORT_DIRNAME / SUMMARY_FILENAME)
    return {
        "governed_conflicts": int(summary.get("total_conflicts", 0) or 0),
        "blocked_merges": int(summary.get("blocked_merges", 0) or 0),
        "safe_merge_candidates": int(summary.get("safe_merge_candidates", 0) or 0),
        "needs_review_conflicts": int(summary.get("needs_review", 0) or 0),
    }


def _summary_result(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "total_conflicts": int(summary.get("total_conflicts", 0) or 0),
        "blocked_merges": int(summary.get("blocked_merges", 0) or 0),
        "safe_merge_candidates": int(summary.get("safe_merge_candidates", 0) or 0),
        "needs_review": int(summary.get("needs_review", 0) or 0),
        "deferred": int(summary.get("deferred", 0) or 0),
        "resolved": int(summary.get("resolved", 0) or 0),
        "high_severity": int(summary.get("high_severity", 0) or 0),
        "medium_severity": int(summary.get("medium_severity", 0) or 0),
        "low_severity": int(summary.get("low_severity", 0) or 0),
    }


def _scored_lookup(db_path: str | Path) -> dict[tuple[str, str], ScoredEntity]:
    return {(item.entity_type, item.entity_key): item for item in collect_scored_entities(db_path=db_path)}


def _approved_alias_pairs(db_path: str | Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in list_review_decisions(db_path):
        if row.get("decision") != "approved" or row.get("field") not in {"artist", "album_artist"}:
            continue
        current = _norm(row.get("current_value"))
        proposed = _norm(row.get("proposed_value"))
        if current and proposed:
            pairs.add((current, proposed))
            pairs.add((proposed, current))
    for rule in derive_normalization_rules(db_path=db_path):
        if getattr(rule, "rule_type", "") != "artist_alias" or getattr(rule, "confidence", "") == "rejected_pattern":
            continue
        source = _norm(getattr(rule, "source_value", ""))
        target = _norm(getattr(rule, "target_value", ""))
        if source and target:
            pairs.add((source, target))
            pairs.add((target, source))
    return pairs


def _conflict_type(conflict: UnresolvedConflict, scored: ScoredEntity, variants: list[str]) -> str:
    text = f"{conflict.entity_type} {conflict.rationale} {conflict.variants}".casefold()
    negative_types = _evidence_types(_read_json_list(scored.negative_evidence_json))
    if _artifact_dominates(_read_json_list(scored.negative_evidence_json)):
        return "artifact_collision"
    if "role" in text or conflict.entity_type == "ambiguous" or "conflicting_role_pattern" in negative_types:
        return "role_collision"
    if _collaboration_single_artist_conflict(*(variants[:2] if len(variants) >= 2 else (conflict.variants, ""))):
        return "ambiguous_collaboration"
    if "album" in conflict.entity_type or "album" in text:
        return "album_membership_conflict"
    if "version" in text or "remaster" in text or "live" in text:
        return "track_version_conflict"
    if "promotion" in text or "classification blocked" in text:
        return "promotion_conflict"
    if _case_alias_only(variants):
        return "alias_collision"
    return "duplicate_identity_conflict"


def _entity_role(entity_type: str) -> str:
    return entity_type if entity_type in {"artist", "album", "track", "version", "ambiguous"} else "ambiguous"


def _entity_type(role: str) -> str:
    return role if role in {"artist", "album", "track"} else "artist"


def _confidence_snapshot(scored: ScoredEntity) -> dict[str, Any]:
    return {
        "confidence_tier": scored.confidence_tier,
        "normalized_confidence": scored.normalized_confidence,
        "raw_positive_score": scored.raw_positive_score,
        "raw_negative_score": scored.raw_negative_score,
        "rationale": scored.rationale,
    }


def _lifecycle_from_snapshot(scored: ScoredEntity) -> str:
    if scored.confidence_tier == "blocked":
        return "blocked"
    if scored.raw_positive_score >= 0.55 and scored.raw_negative_score >= 0.55:
        return "conflicted"
    if scored.normalized_confidence >= 0.74:
        return "canonical"
    if scored.normalized_confidence >= 0.55:
        return "probationary"
    return "candidate"


def _has_approved_alias(source: str, target: str, pairs: set[tuple[str, str]]) -> bool:
    return (_norm(source), _norm(target)) in pairs


def _artifact_dominates(negative: list[dict[str, Any]]) -> bool:
    artifact_score = 0.0
    other_score = 0.0
    for item in negative:
        score = float(item.get("calibrated_score", item.get("weighted_score", 0.0)) or 0.0)
        if item.get("evidence_family") == "artifact" or item.get("evidence_type") in {"uploader_signature", "source_artifact_pattern"}:
            artifact_score += score
        else:
            other_score += score
    return artifact_score >= 0.38 and artifact_score >= other_score


def _collaboration_single_artist_conflict(source: str, target: str) -> bool:
    source_collab = _looks_collaboration(source)
    target_collab = _looks_collaboration(target)
    return source_collab != target_collab and bool(source.strip() and target.strip())


def _looks_collaboration(value: str) -> bool:
    return bool(re.search(r"(?:\b(?:feat\.?|ft\.?|with|x|vs\.?|and)\b|&)", value, re.I))


def _case_alias_only(variants: list[str]) -> bool:
    normalized = {_norm(item) for item in variants if item}
    display = {item for item in variants if item}
    return len(normalized) == 1 and len(display) > 1


def _variants(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def _evidence_types(items: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("evidence_type", "")) for item in items if item.get("evidence_type")}


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


def _read_json_list(value: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _json_dump(value: str) -> str:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        payload = []
    return json.dumps(payload if isinstance(payload, list) else [], sort_keys=True)


def _norm(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    text = re.sub(r"[\W_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stable_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{key}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, str(path)
    try:
        with path.open(encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return {}, str(path)
    return payload if isinstance(payload, dict) else {}, None


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.exists():
        return [], str(path)
    try:
        with path.open(newline="", encoding="utf-8") as file_handle:
            return list(csv.DictReader(file_handle)), None
    except OSError:
        return [], str(path)


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
