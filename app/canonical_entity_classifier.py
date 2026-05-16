"""Deterministic canonical entity candidate classification.

This module is observational. It classifies candidate strings before the
canonical graph promotes them, but it never writes tags or mutates media files.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.album_cohesion import read_album_cohesion_report
from app.canonical_confidence import score_canonical_entity
from app.entity_roles import aggregate_entity_roles, best_role_record, role_records_by_value
from app.filename_parser import parse_filename
from app.normalization_knowledge import derive_normalization_rules
from app.review_decisions import list_review_decisions


REPORT_DIRNAME = "canonical_entity_classification"
SUMMARY_FILENAME = "entity_classification_summary.json"
CLASSIFICATIONS_FILENAME = "entity_classifications.csv"
BLOCKED_FILENAME = "blocked_entity_candidates.csv"
AMBIGUOUS_FILENAME = "ambiguous_entity_candidates.csv"

CLASSIFICATION_HEADERS: tuple[str, ...] = (
    "candidate_value",
    "field_name",
    "file_path",
    "proposed_entity_type",
    "confidence_score",
    "confidence_tier",
    "flags",
    "rationale",
)

BLOCKING_TYPES = {
    "version_descriptor",
    "source_or_label_artifact",
    "uploader_channel_artifact",
    "track_title_misclassified_as_artist",
    "album_title_misclassified_as_artist",
}
AMBIGUOUS_TYPE = "unknown_or_ambiguous"

_OFFICIAL_OR_VERSION_RE = re.compile(
    r"\b(?:official\s+(?:audio|video|music\s+video|visualizer)|explicit|clean|lyrics?|"
    r"remaster(?:ed)?|anniversary|deluxe|radio edit|single version|live)\b",
    re.I,
)
_SOURCE_ARTIFACT_RE = re.compile(
    r"\b(?:records?|recordings|vault|channel|official|vevo|topic|projekt|project|"
    r"pre\s*studio|studio|uploads?|archive|label|entertainment)\b",
    re.I,
)
_UPLOADER_STYLE_RE = re.compile(
    r"\b(?:mr[a-z0-9]+|.+['’]s\s+.+channel|.+\s+channel|.+\s+topic)\b",
    re.I,
)
_PLATFORM_RE = re.compile(r"\b(?:youtube|soundcloud|bandcamp|auto-generated|provided to youtube)\b", re.I)
_TRACK_PHRASE_RE = re.compile(r"^(?:\d+\.\s*)?[a-z0-9][a-z0-9'’]*(?:\s+[a-z0-9][a-z0-9'’]*){1,6}$", re.I)
_TRACK_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+\.\s+\S+")
_COLLABORATION_ARTIST_RE = re.compile(r"(?:\s&\s|,\s|\s(?:feat\.?|ft\.?|featuring)\s)", re.I)


@dataclass(frozen=True)
class CandidateContext:
    candidate_value: str
    field_name: str
    file_path: str = ""
    folder_artist: str = ""
    filename_artist: str = ""
    filename_title: str = ""
    metadata_tags: dict[str, str] = field(default_factory=dict)
    evidence_reliability_flags: list[str] = field(default_factory=list)
    album_cohesion_context: dict[str, Any] = field(default_factory=dict)
    normalization_knowledge_support: bool = False
    approved_review_support: bool = False
    rejected_review_conflict: bool = False
    value_artist_count: int = 0
    value_album_count: int = 0
    value_title_count: int = 0
    other_title_count: int = 0
    artist_folder_conflict_count: int = 0
    total_artist_count: int = 0
    low_reliability_conflicts: int = 0
    role_evidence_count: int = 0
    role_status: str = ""
    active_roles: list[str] = field(default_factory=list)
    role_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EntityClassification:
    candidate_value: str
    field_name: str
    file_path: str
    proposed_entity_type: str
    confidence_score: float
    confidence_tier: str
    flags: list[str]
    rationale: list[str]


@dataclass(frozen=True)
class CanonicalEntityClassificationResult:
    report_path: str
    total_candidates: int
    canonical_artist_candidates: int
    canonical_album_candidates: int
    canonical_track_candidates: int
    blocked_candidates: int
    ambiguous_candidates: int
    source_artifacts: int
    misclassified_track_titles: int


def classify_candidate(context: CandidateContext) -> EntityClassification:
    value = _clean(context.candidate_value)
    field_name = _clean(context.field_name).casefold()
    flags: list[str] = []
    rationale: list[str] = []
    proposed = _default_entity_type(field_name)
    score = 0.56 if value else 0.12

    value_norm = _norm(value)
    filename_title_norm = _norm(context.filename_title)
    filename_artist_norm = _norm(context.filename_artist)
    folder_artist_norm = _norm(Path(context.folder_artist).name)
    tag_title_norm = _norm(context.metadata_tags.get("title", ""))
    tag_album_norm = _norm(context.metadata_tags.get("album", ""))
    active_roles = set(context.active_roles)
    supported_current_role = context.role_status in {"candidate", "probationary", "canonical"} and context.role_evidence_count > 0
    strong_current_role = context.role_status in {"probationary", "canonical"} or context.role_evidence_count >= 2
    weighted = _weighted_support(context, field_name, value)

    if not value:
        proposed = AMBIGUOUS_TYPE
        flags.append("empty_candidate")
        rationale.append("candidate value is empty")
        return _classification(context, proposed, 0.08, flags, rationale)

    if context.approved_review_support:
        score += 0.20
        flags.append("approved_review_support")
        rationale.append("approved review decision supports this value")
    if context.normalization_knowledge_support:
        score += 0.18
        flags.append("normalization_knowledge_support")
        rationale.append("normalization knowledge supports this value")
    if context.rejected_review_conflict:
        score -= 0.20
        flags.append("rejected_review_conflict")
        rationale.append("review history rejects this value or pattern")
    if "multi_role_entity" in context.role_flags:
        flags.append("multi_role_entity")
        rationale.append("role context preserves this value separately across roles")
    if supported_current_role:
        score += min(0.12, 0.04 + context.role_evidence_count * 0.02)
        flags.append("role_context_support")
        rationale.append(f"role context supports {context.field_name} evidence independently")

    if field_name in {"artist", "album_artist", "filename_artist"}:
        if value_norm and value_norm == folder_artist_norm:
            score += 0.20
            flags.append("folder_artist_match")
            rationale.append("candidate matches folder artist context")
        if context.value_artist_count >= 2:
            score += min(0.18, 0.06 + context.value_artist_count * 0.025)
            flags.append("repeated_artist_metadata")
            rationale.append("candidate appears repeatedly as artist metadata")
        if context.low_reliability_conflicts == 0:
            score += 0.04
            flags.append("low_reliability_conflict_rate")
            rationale.append("low reliability conflict rate observed")

        if value_norm and value_norm in {filename_title_norm, tag_title_norm}:
            proposed = "track_title_misclassified_as_artist"
            score = max(score, 0.91)
            flags.append("matches_title_context")
            rationale.append("artist candidate matches filename or tag title")
        elif context.other_title_count and not (strong_current_role or "artist" in active_roles):
            proposed = "track_title_misclassified_as_artist"
            score = max(score, 0.82)
            flags.append("appears_as_title_elsewhere")
            rationale.append("candidate appears as a title in other records")
        elif _TRACK_NUMBER_PREFIX_RE.search(value):
            proposed = "track_title_misclassified_as_artist"
            score = max(score, 0.88)
            flags.append("track_number_title_shape")
            rationale.append("candidate has track-number title shape")
        elif _OFFICIAL_OR_VERSION_RE.search(value) and (
            filename_title_norm == value_norm or tag_title_norm == value_norm or _TRACK_PHRASE_RE.search(_strip_version(value))
        ):
            proposed = "track_title_misclassified_as_artist"
            score = max(score, 0.86)
            flags.append("version_suffix_on_artist_candidate")
            rationale.append("artist candidate contains track/version suffix wording")
        elif _is_source_artifact(value, context) and not _positive_evidence_dominates(weighted):
            proposed = _artifact_type(value)
            score = max(score, 0.88)
            flags.append("source_or_uploader_signature")
            rationale.append("dominant weighted negative evidence resembles source, label, channel, or uploader residue")
        elif _is_source_artifact(value, context):
            flags.append("weak_artifact_signal_overridden")
            rationale.append("weighted canonical evidence overrides weak artifact signal")
        elif _COLLABORATION_ARTIST_RE.search(value) and not (strong_current_role or context.approved_review_support):
            proposed = AMBIGUOUS_TYPE
            score = min(score, 0.49)
            flags.append("collaboration_artist_collision")
            rationale.append("compound artist candidate needs explicit evidence before canonical promotion")
        elif value_norm and value_norm == tag_album_norm and not (strong_current_role or "artist" in active_roles):
            proposed = "album_title_misclassified_as_artist"
            score = max(score, 0.78)
            flags.append("matches_album_context")
            rationale.append("artist candidate matches album title context")
        elif context.value_album_count and "album" in active_roles:
            flags.append("cross_role_album_collision")
            rationale.append("same value also has album role evidence; artist role remains separate")
        elif (
            context.value_artist_count <= 1
            and folder_artist_norm
            and value_norm != folder_artist_norm
            and not _compatible(value, context.folder_artist)
            and not (context.approved_review_support or context.normalization_knowledge_support)
        ):
            proposed = AMBIGUOUS_TYPE
            score = min(score, 0.48)
            flags.append("single_artist_folder_disagreement")
            rationale.append("single artist occurrence disagrees with folder artist context")

    elif field_name == "album":
        if context.value_album_count >= 2:
            score += min(0.16, 0.06 + context.value_album_count * 0.02)
            flags.append("repeated_album_metadata")
            rationale.append("candidate appears repeatedly as album metadata")
        if _OFFICIAL_OR_VERSION_RE.search(value):
            proposed = "version_descriptor"
            score = max(score, 0.76)
            flags.append("version_descriptor_terms")
            rationale.append("album candidate is dominated by version descriptor wording")
        elif _is_source_artifact(value, context) and not (strong_current_role or "album" in active_roles or _positive_evidence_dominates(weighted)):
            proposed = "source_or_label_artifact"
            score = max(score, 0.84)
            flags.append("source_or_label_signature")
            rationale.append("dominant weighted negative evidence resembles source or label residue")
        elif _is_source_artifact(value, context):
            flags.append("weak_source_artifact_collision")
            rationale.append("album role evidence overrides weak source-artifact suspicion")
        if context.value_artist_count and "artist" in active_roles:
            flags.append("cross_role_artist_collision")
            rationale.append("same value also has artist role evidence; album role remains separate")

    elif field_name == "title":
        if context.value_title_count >= 1:
            score += min(0.14, 0.05 + context.value_title_count * 0.02)
            flags.append("title_metadata_support")
            rationale.append("candidate appears as title metadata")
        if _OFFICIAL_OR_VERSION_RE.search(value):
            proposed = "canonical_track"
            flags.append("version_suffix_on_track")
            rationale.append("title contains version wording but remains track evidence")

    if proposed == _default_entity_type(field_name) and not rationale:
        rationale.append("candidate is consistent with its source field")
    if proposed == _default_entity_type(field_name):
        score = max(score, weighted.normalized_confidence)
        flags.append("weighted_confidence")
        rationale.append("weighted positive and negative evidence supports canonical role")

    if proposed == AMBIGUOUS_TYPE:
        score = min(score, 0.49)
    return _classification(context, proposed, score, flags, rationale)


def generate_canonical_entity_classification_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> CanonicalEntityClassificationResult:
    reports_dir = Path(out_dir).expanduser()
    report_dir = reports_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    classifications = collect_entity_classifications(reports_dir=reports_dir, db_path=db_path)
    summary = classification_summary(classifications)
    summary["created_at"] = datetime.now(UTC).isoformat()
    summary["report_file"] = str(report_dir / CLASSIFICATIONS_FILENAME)

    blocked = [item for item in classifications if item.proposed_entity_type in BLOCKING_TYPES]
    ambiguous = [item for item in classifications if item.proposed_entity_type == AMBIGUOUS_TYPE]
    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_csv(report_dir / CLASSIFICATIONS_FILENAME, CLASSIFICATION_HEADERS, (_csv_row(item) for item in classifications))
    _write_csv(report_dir / BLOCKED_FILENAME, CLASSIFICATION_HEADERS, (_csv_row(item) for item in blocked))
    _write_csv(report_dir / AMBIGUOUS_FILENAME, CLASSIFICATION_HEADERS, (_csv_row(item) for item in ambiguous))
    return CanonicalEntityClassificationResult(report_path=str(report_dir), **_summary_ints(summary))


def collect_entity_classifications(
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[EntityClassification]:
    rows = _load_candidate_rows(db_path)
    contexts = build_candidate_contexts(
        rows,
        reports_dir=reports_dir,
        db_path=db_path,
    )
    return sorted(
        (classify_candidate(context) for context in contexts),
        key=lambda item: (item.proposed_entity_type, item.field_name, item.candidate_value.casefold(), item.file_path),
    )


def build_candidate_contexts(
    rows: Iterable[dict[str, Any]],
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[CandidateContext]:
    materialized = [_normalize_row(row) for row in rows]
    role_records = aggregate_entity_roles(materialized)
    roles_by_value = role_records_by_value(role_records)
    artist_counts = Counter(_norm(row["value"]) for row in materialized if row["field_name"] in {"artist", "album_artist", "filename_artist"} and row["value"])
    album_counts = Counter(_norm(row["value"]) for row in materialized if row["field_name"] == "album" and row["value"])
    title_counts = Counter(_norm(row["value"]) for row in materialized if row["field_name"] == "title" and row["value"])
    approvals, rejections = _decision_support(db_path)
    knowledge = _normalization_support(db_path)
    album_context = _album_context(reports_dir)
    contexts: list[CandidateContext] = []
    for row in materialized:
        value_norm = _norm(row["value"])
        field_name = row["field_name"]
        role = _role_for_field(field_name)
        role_record = best_role_record(role_records, value_norm, role)
        value_role_records = roles_by_value.get(value_norm, [])
        folder_conflict = 0
        if field_name in {"artist", "album_artist", "filename_artist"} and row["folder_artist"]:
            folder_conflict = 0 if _compatible(row["value"], row["folder_artist"]) else 1
        contexts.append(
            CandidateContext(
                candidate_value=row["value"],
                field_name=field_name,
                file_path=row["file_path"],
                folder_artist=row["folder_artist"],
                filename_artist=row["filename_artist"],
                filename_title=row["filename_title"],
                metadata_tags=row["metadata_tags"],
                evidence_reliability_flags=row["evidence_reliability_flags"],
                album_cohesion_context=album_context.get((_norm(row["metadata_tags"].get("artist", "")), _norm(row["metadata_tags"].get("album", ""))), {}),
                normalization_knowledge_support=(field_name, value_norm) in knowledge,
                approved_review_support=(field_name, value_norm) in approvals,
                rejected_review_conflict=(field_name, value_norm) in rejections,
                value_artist_count=artist_counts[value_norm],
                value_album_count=album_counts[value_norm],
                value_title_count=title_counts[value_norm],
                other_title_count=title_counts[value_norm] if field_name in {"artist", "album_artist", "filename_artist"} else 0,
                artist_folder_conflict_count=folder_conflict,
                total_artist_count=sum(artist_counts.values()),
                low_reliability_conflicts=sum(1 for flag in row["evidence_reliability_flags"] if "conflict" in flag),
                role_evidence_count=role_record.evidence_count if role_record else 0,
                role_status=role_record.role_status if role_record else "",
                active_roles=sorted(
                    record.entity_role
                    for record in value_role_records
                    if record.role_status in {"candidate", "probationary", "canonical", "conflicted"}
                ),
                role_flags=sorted({flag for record in value_role_records for flag in record.flags}),
            )
        )
    return contexts


def classification_summary(classifications: Iterable[EntityClassification]) -> dict[str, int]:
    materialized = list(classifications)
    counts = Counter(item.proposed_entity_type for item in materialized)
    return {
        "total_candidates": len(materialized),
        "canonical_artist_candidates": counts["canonical_artist"],
        "canonical_album_candidates": counts["canonical_album"],
        "canonical_track_candidates": counts["canonical_track"],
        "blocked_candidates": sum(counts[item] for item in BLOCKING_TYPES),
        "ambiguous_candidates": counts[AMBIGUOUS_TYPE],
        "source_artifacts": counts["source_or_label_artifact"] + counts["uploader_channel_artifact"],
        "misclassified_track_titles": counts["track_title_misclassified_as_artist"],
    }


def read_entity_classification_report(
    reports_dir: str | Path = "reports",
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    report_dir = Path(reports_dir).expanduser() / REPORT_DIRNAME
    summary, missing_summary = _read_json_with_missing(report_dir / SUMMARY_FILENAME)
    classifications, missing_classifications = _read_csv(report_dir / CLASSIFICATIONS_FILENAME)
    blocked, missing_blocked = _read_csv(report_dir / BLOCKED_FILENAME)
    ambiguous, missing_ambiguous = _read_csv(report_dir / AMBIGUOUS_FILENAME)
    return (
        summary,
        [_normalize_classification_record(row) for row in classifications],
        [_normalize_classification_record(row) for row in blocked],
        [_normalize_classification_record(row) for row in ambiguous],
        [label for label in (missing_summary, missing_classifications, missing_blocked, missing_ambiguous) if label],
    )


def blocked_or_ambiguous(classification: EntityClassification) -> bool:
    return classification.proposed_entity_type in BLOCKING_TYPES or classification.proposed_entity_type == AMBIGUOUS_TYPE


def _load_candidate_rows(db_path: str | Path) -> list[dict[str, Any]]:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                observed_files.source_path,
                observed_files.relative_path,
                observed_files.parent_folder,
                observed_files.filename,
                tag_observations.artist AS tag_artist,
                tag_observations.album_artist AS tag_album_artist,
                tag_observations.title AS tag_title,
                tag_observations.album AS tag_album,
                filename_observations.possible_artist AS filename_artist,
                filename_observations.possible_title AS filename_title,
                track_identity.probable_artist,
                track_identity.probable_title,
                track_identity.probable_album
            FROM observed_files
            LEFT JOIN tag_observations
                ON tag_observations.observed_file_id = observed_files.id
            LEFT JOIN filename_observations
                ON filename_observations.observed_file_id = observed_files.id
            LEFT JOIN track_identity
                ON track_identity.observed_file_id = observed_files.id
            ORDER BY observed_files.id
            """
        ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        parsed = parse_filename(str(row["filename"] or ""))
        file_path = str(row["source_path"] or row["relative_path"] or row["filename"])
        metadata_tags = {
            "artist": _clean(row["tag_artist"]) or _clean(row["probable_artist"]),
            "album_artist": _clean(row["tag_album_artist"]),
            "title": _clean(row["tag_title"]) or _clean(row["probable_title"]),
            "album": _clean(row["tag_album"]) or _clean(row["probable_album"]),
        }
        base = {
            "file_path": file_path,
            "folder_artist": str(row["parent_folder"] or ""),
            "filename_artist": _clean(row["filename_artist"]) or parsed.possible_artist or "",
            "filename_title": _clean(row["filename_title"]) or parsed.possible_title or "",
            "metadata_tags": metadata_tags,
            "evidence_reliability_flags": [],
        }
        for field_name, value in (
            ("artist", row["probable_artist"] or row["tag_artist"]),
            ("album_artist", row["tag_album_artist"]),
            ("filename_artist", row["filename_artist"] or parsed.possible_artist),
            ("title", row["probable_title"] or row["tag_title"] or row["filename_title"] or parsed.possible_title),
            ("album", row["probable_album"] or row["tag_album"]),
        ):
            clean_value = _clean(value)
            if clean_value:
                candidates.append({**base, "field_name": field_name, "value": clean_value})
    return candidates


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    tags = row.get("metadata_tags", {})
    flags = row.get("evidence_reliability_flags", [])
    return {
        "value": _clean(row.get("value") or row.get("candidate_value")),
        "field_name": _clean(row.get("field_name") or row.get("field")),
        "file_path": _clean(row.get("file_path")),
        "folder_artist": _clean(row.get("folder_artist")),
        "filename_artist": _clean(row.get("filename_artist")),
        "filename_title": _clean(row.get("filename_title")),
        "metadata_tags": {str(key): _clean(value) for key, value in tags.items()} if isinstance(tags, dict) else {},
        "evidence_reliability_flags": [str(item) for item in flags] if isinstance(flags, list) else [],
    }


def _decision_support(db_path: str | Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    approvals: set[tuple[str, str]] = set()
    rejections: set[tuple[str, str]] = set()
    for row in list_review_decisions(db_path):
        field_name = str(row.get("field", ""))
        for key in ("proposed_value", "current_value"):
            signature = (field_name, _norm(str(row.get(key, ""))))
            if not signature[1]:
                continue
            if row.get("decision") == "approved":
                approvals.add(signature)
            elif row.get("decision") == "rejected":
                rejections.add(signature)
    return approvals, rejections


def _normalization_support(db_path: str | Path) -> set[tuple[str, str]]:
    support: set[tuple[str, str]] = set()
    for rule in derive_normalization_rules(db_path=db_path):
        if getattr(rule, "confidence", "") == "rejected_pattern":
            continue
        rule_type = getattr(rule, "rule_type", "")
        target = _norm(getattr(rule, "target_value", ""))
        if not target:
            continue
        if rule_type == "artist_alias":
            support.add(("artist", target))
            support.add(("album_artist", target))
            support.add(("filename_artist", target))
        elif rule_type == "title_cleanup":
            support.add(("title", target))
        elif rule_type == "album_artist_default":
            support.add(("album_artist", target))
    return support


def _album_context(reports_dir: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    _, groups, _, _, _ = read_album_cohesion_report(reports_dir)
    context: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        key = (_norm(group.get("artist", "")), _norm(group.get("album", "")))
        context[key] = group
    return context


def _classification(
    context: CandidateContext,
    proposed: str,
    score: float,
    flags: list[str],
    rationale: list[str],
) -> EntityClassification:
    score = round(max(0.0, min(1.0, score)), 3)
    return EntityClassification(
        candidate_value=_clean(context.candidate_value),
        field_name=_clean(context.field_name),
        file_path=_clean(context.file_path),
        proposed_entity_type=proposed,
        confidence_score=score,
        confidence_tier=_tier(score),
        flags=sorted(dict.fromkeys(flags)),
        rationale=list(dict.fromkeys(rationale)) or ["limited classification evidence"],
    )


def _default_entity_type(field_name: str) -> str:
    if field_name in {"artist", "album_artist", "filename_artist"}:
        return "canonical_artist"
    if field_name == "album":
        return "canonical_album"
    if field_name == "title":
        return "canonical_track"
    return AMBIGUOUS_TYPE


def _role_for_field(field_name: str) -> str:
    if field_name in {"artist", "album_artist", "filename_artist"}:
        return "artist"
    if field_name == "album":
        return "album"
    if field_name == "title":
        return "track"
    return "ambiguous"


def _weighted_support(context: CandidateContext, field_name: str, value: str) -> Any:
    role = _role_for_field(field_name)
    artifact_flags: list[str] = []
    if _is_source_artifact(value, context):
        artifact_flags.append("uploader_signature" if _artifact_type(value) == "uploader_channel_artifact" else "source_artifact_pattern")
    if "multi_role_entity" in context.role_flags and role not in set(context.active_roles):
        artifact_flags.append("conflicting_role_pattern")
    return score_canonical_entity(
        entity_type=role if role in {"artist", "album", "track"} else "artist",
        entity_key=_norm(value),
        entity_value=value,
        evidence_count=max(context.role_evidence_count, context.value_artist_count if role == "artist" else context.value_album_count if role == "album" else context.value_title_count),
        conflict_count=1 if context.rejected_review_conflict else 0,
        average_reliability=0.68 if context.low_reliability_conflicts == 0 else 0.45,
        approvals=1 if context.approved_review_support or context.normalization_knowledge_support else 0,
        folder_agreement=bool(_norm(value) and _norm(value) == _norm(Path(context.folder_artist).name)),
        role_agreement=context.role_status in {"probationary", "canonical"},
        artifact_flags=artifact_flags,
        title_like_artist=role == "artist" and bool(_TRACK_PHRASE_RE.search(_strip_version(value))),
    )


def _positive_evidence_dominates(weighted: Any) -> bool:
    return weighted.raw_positive_score >= weighted.raw_negative_score + 0.25 and weighted.normalized_confidence >= 0.62


def _is_source_artifact(value: str, context: CandidateContext) -> bool:
    text = _clean(value)
    value_norm = _norm(text)
    folder_norm = _norm(Path(context.folder_artist).name)
    if _SOURCE_ARTIFACT_RE.search(text) or _UPLOADER_STYLE_RE.search(text) or _PLATFORM_RE.search(text):
        return True
    if (
        text.isupper()
        and 2 <= len(re.sub(r"[^A-Z0-9]", "", text)) <= 8
        and not _compatible(text, context.folder_artist)
    ):
        return True
    if text.casefold().endswith("band") and folder_norm and value_norm != folder_norm:
        return True
    if re.fullmatch(r"[A-Za-z0-9_]{8,14}", text) and any(char.islower() for char in text) and any(char.isupper() for char in text):
        return True
    return False


def _artifact_type(value: str) -> str:
    if _UPLOADER_STYLE_RE.search(value) or "channel" in value.casefold() or "topic" in value.casefold():
        return "uploader_channel_artifact"
    return "source_or_label_artifact"


def _strip_version(value: str) -> str:
    return re.sub(r"\s*[\[(].*?[\])]\s*", " ", _OFFICIAL_OR_VERSION_RE.sub(" ", value)).strip()


def _compatible(value: str, other: str) -> bool:
    left = _norm(value)
    right = _norm(Path(other).name)
    return not left or not right or left in right or right in left


def _tier(score: float) -> str:
    if score >= 0.74:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _csv_row(classification: EntityClassification) -> dict[str, Any]:
    payload = asdict(classification)
    payload["flags"] = json.dumps(classification.flags, sort_keys=True)
    payload["rationale"] = " | ".join(classification.rationale)
    return payload


def _normalize_classification_record(row: dict[str, Any]) -> dict[str, Any]:
    flags = row.get("flags", [])
    if isinstance(flags, str):
        try:
            parsed_flags = json.loads(flags)
        except json.JSONDecodeError:
            parsed_flags = [part.strip() for part in flags.split("|") if part.strip()]
    else:
        parsed_flags = flags
    rationale = row.get("rationale", [])
    if isinstance(rationale, str):
        parsed_rationale = [part.strip() for part in rationale.split("|") if part.strip()]
    else:
        parsed_rationale = rationale
    return {
        **row,
        "confidence_score": float(row.get("confidence_score", 0.0) or 0.0),
        "confidence_tier": str(row.get("confidence_tier", "low") or "low"),
        "flags": [str(item) for item in parsed_flags] if isinstance(parsed_flags, list) else [str(parsed_flags)],
        "rationale": [str(item) for item in parsed_rationale] if isinstance(parsed_rationale, list) else [str(parsed_rationale)],
    }


def _summary_ints(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "total_candidates": int(summary["total_candidates"]),
        "canonical_artist_candidates": int(summary["canonical_artist_candidates"]),
        "canonical_album_candidates": int(summary["canonical_album_candidates"]),
        "canonical_track_candidates": int(summary["canonical_track_candidates"]),
        "blocked_candidates": int(summary["blocked_candidates"]),
        "ambiguous_candidates": int(summary["ambiguous_candidates"]),
        "source_artifacts": int(summary["source_artifacts"]),
        "misclassified_track_titles": int(summary["misclassified_track_titles"]),
    }


def _read_json_with_missing(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, str(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, str(path)
    return (payload if isinstance(payload, dict) else {}), ""


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], str(path)
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle)), ""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).casefold())
