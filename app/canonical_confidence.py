"""Weighted confidence scoring for canonical entity evidence.

The confidence engine is deterministic and observational. It balances positive
and negative evidence into explainable confidence scores, but it never mutates
media files or writes metadata.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.entity_roles import aggregate_entity_roles
from app.filename_parser import parse_filename


REPORT_DIRNAME = "canonical_confidence"
SUMMARY_FILENAME = "confidence_summary.json"
SCORED_FILENAME = "scored_entities.csv"
HIGH_FILENAME = "high_confidence_entities.csv"
BLOCKED_FILENAME = "blocked_entities.csv"
BREAKDOWNS_FILENAME = "confidence_breakdowns.json"

EVIDENCE_WEIGHTS: dict[str, float] = {
    "repeated_artist_metadata": 0.35,
    "repeated_album_metadata": 0.32,
    "repeated_track_metadata": 0.30,
    "folder_agreement": 0.25,
    "canonical_graph_reinforcement": 0.22,
    "approved_normalization_rule": 0.34,
    "repeated_album_cohesion": 0.28,
    "stable_temporal_presence": 0.20,
    "canonical_role_agreement": 0.26,
    "uploader_signature": 0.42,
    "source_artifact_pattern": 0.38,
    "isolated_occurrence": 0.20,
    "conflicting_role_pattern": 0.32,
    "conflicting_graph_relationship": 0.34,
    "title_like_structure_in_artist_field": 0.30,
    "excessive_symbol_noise": 0.18,
    "all_caps_anomaly": 0.16,
    "weak_album_cohesion": 0.22,
}

POSITIVE_EVIDENCE = {
    "repeated_artist_metadata",
    "repeated_album_metadata",
    "repeated_track_metadata",
    "folder_agreement",
    "canonical_graph_reinforcement",
    "approved_normalization_rule",
    "repeated_album_cohesion",
    "stable_temporal_presence",
    "canonical_role_agreement",
}
NEGATIVE_EVIDENCE = set(EVIDENCE_WEIGHTS) - POSITIVE_EVIDENCE

CONFIDENCE_HEADERS: tuple[str, ...] = (
    "entity_type",
    "entity_key",
    "entity_value",
    "positive_evidence_json",
    "negative_evidence_json",
    "weighted_score_breakdown_json",
    "raw_positive_score",
    "raw_negative_score",
    "normalized_confidence",
    "confidence_tier",
    "rationale",
)

_SOURCE_ARTIFACT_RE = re.compile(
    r"\b(?:records?|recordings|vault|official|vevo|projekt|project|"
    r"pre\s*studio|studio|uploads?|archive|label|entertainment)\b",
    re.I,
)
_UPLOADER_RE = re.compile(r"\b(?:channel|topic|provided to youtube|auto-generated|youtube|soundcloud|bandcamp)\b", re.I)
_TITLE_LIKE_RE = re.compile(r"^(?:\d+\.\s*)?[a-z0-9][a-z0-9'’]*(?:\s+[a-z0-9][a-z0-9'’]*){1,6}$", re.I)


@dataclass(frozen=True)
class WeightedEvidence:
    evidence_type: str
    weight: float
    count: int = 1
    rationale: str = ""

    @property
    def weighted_score(self) -> float:
        return round(self.weight * max(1, self.count), 3)


@dataclass(frozen=True)
class ScoredEntity:
    entity_type: str
    entity_key: str
    entity_value: str
    positive_evidence_json: str
    negative_evidence_json: str
    weighted_score_breakdown_json: str
    raw_positive_score: float
    raw_negative_score: float
    normalized_confidence: float
    confidence_tier: str
    rationale: str


@dataclass(frozen=True)
class CanonicalConfidenceResult:
    report_path: str
    total_scored_entities: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    blocked_confidence_count: int
    average_confidence: float
    average_positive_score: float
    average_negative_score: float


def score_weighted_evidence(
    *,
    entity_type: str,
    entity_key: str,
    entity_value: str,
    positive: Iterable[str | WeightedEvidence] = (),
    negative: Iterable[str | WeightedEvidence] = (),
) -> ScoredEntity:
    positives = [_coerce_evidence(item) for item in positive]
    negatives = [_coerce_evidence(item) for item in negative]
    raw_positive = round(sum(item.weighted_score for item in positives), 3)
    raw_negative = round(sum(item.weighted_score for item in negatives), 3)
    normalized = normalize_confidence(raw_positive - raw_negative)
    tier = confidence_tier(normalized, raw_positive_score=raw_positive, raw_negative_score=raw_negative)
    breakdown = {
        "formula": "normalized(raw_positive_score - raw_negative_score)",
        "raw_delta": round(raw_positive - raw_negative, 3),
        "positive_total": raw_positive,
        "negative_total": raw_negative,
        "positive": [_evidence_payload(item) for item in positives],
        "negative": [_evidence_payload(item) for item in negatives],
    }
    rationale_parts = []
    if positives:
        rationale_parts.append("positive evidence: " + ", ".join(item.evidence_type for item in positives[:4]))
    if negatives:
        rationale_parts.append("negative evidence: " + ", ".join(item.evidence_type for item in negatives[:4]))
    if not rationale_parts:
        rationale_parts.append("limited weighted evidence")
    return ScoredEntity(
        entity_type=entity_type,
        entity_key=entity_key,
        entity_value=entity_value,
        positive_evidence_json=json.dumps([_evidence_payload(item) for item in positives], sort_keys=True),
        negative_evidence_json=json.dumps([_evidence_payload(item) for item in negatives], sort_keys=True),
        weighted_score_breakdown_json=json.dumps(breakdown, sort_keys=True),
        raw_positive_score=raw_positive,
        raw_negative_score=raw_negative,
        normalized_confidence=normalized,
        confidence_tier=tier,
        rationale=" | ".join(rationale_parts),
    )


def score_canonical_entity(
    *,
    entity_type: str,
    entity_key: str,
    entity_value: str,
    evidence_count: int,
    conflict_count: int = 0,
    average_reliability: float = 0.5,
    approvals: int = 0,
    first_seen: str = "",
    last_seen: str = "",
    folder_agreement: bool = False,
    role_agreement: bool = False,
    album_cohesion_count: int = 0,
    graph_reinforcement: bool = False,
    weak_album_cohesion: bool = False,
    artifact_flags: Iterable[str] = (),
    title_like_artist: bool = False,
) -> ScoredEntity:
    positive: list[WeightedEvidence] = []
    negative: list[WeightedEvidence] = []
    if entity_type == "artist" and evidence_count >= 2:
        positive.append(_evidence("repeated_artist_metadata", count=min(evidence_count - 1, 4), rationale="artist value repeats across observations"))
    elif entity_type == "album" and evidence_count >= 2:
        positive.append(_evidence("repeated_album_metadata", count=min(evidence_count - 1, 4), rationale="album value repeats across observations"))
    elif entity_type == "track" and evidence_count >= 2:
        positive.append(_evidence("repeated_track_metadata", count=min(evidence_count - 1, 4), rationale="track value repeats across observations"))
    if folder_agreement:
        positive.append(_evidence("folder_agreement", rationale="entity agrees with folder context"))
    if graph_reinforcement:
        positive.append(_evidence("canonical_graph_reinforcement", rationale="entity is reinforced by graph relationships"))
    if approvals:
        positive.append(_evidence("approved_normalization_rule", count=min(approvals, 3), rationale="approved review or normalization evidence exists"))
    if album_cohesion_count:
        positive.append(_evidence("repeated_album_cohesion", count=min(album_cohesion_count, 3), rationale="album cohesion repeatedly supports this entity"))
    if _stable_temporal(first_seen, last_seen):
        positive.append(_evidence("stable_temporal_presence", rationale="entity appears across a stable time span"))
    if role_agreement:
        positive.append(_evidence("canonical_role_agreement", rationale="entity role model supports this role"))
    if evidence_count <= 1:
        negative.append(_evidence("isolated_occurrence", rationale="entity has sparse evidence"))
    if conflict_count:
        negative.append(_evidence("conflicting_graph_relationship", count=min(conflict_count, 3), rationale="graph evidence has unresolved conflicts"))
    for flag in sorted(set(artifact_flags)):
        if flag == "uploader_signature":
            negative.append(_evidence("uploader_signature", rationale="uploader or platform signature detected"))
        elif flag == "source_artifact_pattern":
            negative.append(_evidence("source_artifact_pattern", rationale="source or label artifact wording detected"))
        elif flag == "conflicting_role_pattern":
            negative.append(_evidence("conflicting_role_pattern", rationale="role evidence conflicts with context"))
        elif flag == "excessive_symbol_noise":
            negative.append(_evidence("excessive_symbol_noise", rationale="value contains excessive symbol noise"))
        elif flag == "all_caps_anomaly":
            negative.append(_evidence("all_caps_anomaly", rationale="value is an all-caps anomaly"))
    if title_like_artist:
        negative.append(_evidence("title_like_structure_in_artist_field", rationale="artist field has title-like structure"))
    if weak_album_cohesion:
        negative.append(_evidence("weak_album_cohesion", rationale="album cohesion is weak"))
    if average_reliability >= 0.72:
        positive.append(_evidence("canonical_graph_reinforcement", rationale="high average reliability reinforces entity"))
    elif average_reliability < 0.42:
        negative.append(_evidence("conflicting_graph_relationship", rationale="low average reliability weakens entity"))
    return score_weighted_evidence(
        entity_type=entity_type,
        entity_key=entity_key,
        entity_value=entity_value,
        positive=positive,
        negative=negative,
    )


def normalize_confidence(raw_confidence: float) -> float:
    # Logistic normalization keeps unbounded weighted totals stable in 0.0..1.0.
    return round(1.0 / (1.0 + math.exp(-2.0 * raw_confidence)), 3)


def confidence_tier(normalized_confidence: float, *, raw_positive_score: float = 0.0, raw_negative_score: float = 0.0) -> str:
    if raw_negative_score > raw_positive_score + 0.34 and normalized_confidence < 0.36:
        return "blocked"
    if normalized_confidence >= 0.74:
        return "high"
    if normalized_confidence >= 0.55:
        return "medium"
    return "low"


def generate_canonical_confidence_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> CanonicalConfidenceResult:
    reports_dir = Path(out_dir).expanduser()
    report_dir = reports_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    scored = collect_scored_entities(db_path=db_path)
    summary = confidence_summary(scored)
    summary["created_at"] = datetime.now().astimezone().isoformat()
    summary["report_file"] = str(report_dir / SCORED_FILENAME)
    high = [item for item in scored if item.confidence_tier == "high"]
    blocked = [item for item in scored if item.confidence_tier == "blocked"]
    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_csv(report_dir / SCORED_FILENAME, CONFIDENCE_HEADERS, (_csv_row(item) for item in scored))
    _write_csv(report_dir / HIGH_FILENAME, CONFIDENCE_HEADERS, (_csv_row(item) for item in high))
    _write_csv(report_dir / BLOCKED_FILENAME, CONFIDENCE_HEADERS, (_csv_row(item) for item in blocked))
    _write_json(report_dir / BREAKDOWNS_FILENAME, {"entities": [_breakdown_payload(item) for item in scored]})
    return CanonicalConfidenceResult(report_path=str(report_dir), **_summary_result(summary))


def collect_scored_entities(*, db_path: str | Path = db.DEFAULT_DB_PATH) -> list[ScoredEntity]:
    rows = _load_rows(db_path)
    role_records = aggregate_entity_roles(rows)
    role_status = {(record.normalized_value, record.entity_role): record for record in role_records}
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        role = _entity_type_for_field(str(row.get("field_name", "")))
        value = _clean(row.get("value"))
        if value and role in {"artist", "album", "track"}:
            grouped[(role, _norm(value))].append(row)
    scored: list[ScoredEntity] = []
    for (entity_type, normalized), values in sorted(grouped.items()):
        names = [_clean(row.get("value")) for row in values]
        first_seen = min(str(row.get("observed_at", "")) for row in values)
        last_seen = max(str(row.get("observed_at", "")) for row in values)
        role_record = role_status.get((normalized, entity_type))
        artifact_flags = _artifact_flags(names)
        if role_record and role_record.role_status == "conflicted":
            artifact_flags.append("conflicting_role_pattern")
        scored.append(
            score_canonical_entity(
                entity_type=entity_type,
                entity_key=normalized,
                entity_value=_best_value(names),
                evidence_count=len(values),
                conflict_count=1 if role_record and role_record.role_status == "conflicted" else 0,
                average_reliability=0.66,
                first_seen=first_seen,
                last_seen=last_seen,
                folder_agreement=_folder_agreement(values),
                role_agreement=bool(role_record and role_record.role_status in {"probationary", "canonical"}),
                weak_album_cohesion=entity_type == "album" and len(values) == 1,
                artifact_flags=artifact_flags,
                title_like_artist=entity_type == "artist" and _title_like(_best_value(names)),
            )
        )
    return scored


def confidence_summary(scored: Iterable[ScoredEntity]) -> dict[str, Any]:
    materialized = list(scored)
    tiers = Counter(item.confidence_tier for item in materialized)
    total = len(materialized)
    return {
        "total_scored_entities": total,
        "high_confidence_count": tiers["high"],
        "medium_confidence_count": tiers["medium"],
        "low_confidence_count": tiers["low"],
        "blocked_confidence_count": tiers["blocked"],
        "average_confidence": round(sum(item.normalized_confidence for item in materialized) / total, 3) if total else 0.0,
        "average_positive_score": round(sum(item.raw_positive_score for item in materialized) / total, 3) if total else 0.0,
        "average_negative_score": round(sum(item.raw_negative_score for item in materialized) / total, 3) if total else 0.0,
    }


def _coerce_evidence(item: str | WeightedEvidence) -> WeightedEvidence:
    if isinstance(item, WeightedEvidence):
        return item
    return _evidence(str(item))


def _evidence(evidence_type: str, *, count: int = 1, rationale: str = "") -> WeightedEvidence:
    return WeightedEvidence(
        evidence_type=evidence_type,
        weight=EVIDENCE_WEIGHTS[evidence_type],
        count=count,
        rationale=rationale,
    )


def _evidence_payload(item: WeightedEvidence) -> dict[str, Any]:
    return {
        "evidence_type": item.evidence_type,
        "weight": item.weight,
        "count": item.count,
        "weighted_score": item.weighted_score,
        "rationale": item.rationale,
    }


def _stable_temporal(first_seen: str, last_seen: str) -> bool:
    first = _parse_datetime(first_seen)
    last = _parse_datetime(last_seen)
    if first is None or last is None:
        return False
    return (last - first).days >= 30


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_rows(db_path: str | Path) -> list[dict[str, Any]]:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                observed_files.source_path,
                observed_files.relative_path,
                observed_files.parent_folder,
                observed_files.filename,
                observed_files.created_at,
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
            "observed_at": str(row["created_at"] or ""),
        }
        for field_name, value in (
            ("artist", row["probable_artist"] or row["tag_artist"]),
            ("album", row["probable_album"] or row["tag_album"]),
            ("title", row["probable_title"] or row["tag_title"] or row["filename_title"] or parsed.possible_title),
        ):
            clean_value = _clean(value)
            if clean_value:
                candidates.append({**base, "field_name": field_name, "value": clean_value})
    return candidates


def _entity_type_for_field(field_name: str) -> str:
    if field_name in {"artist", "album_artist", "filename_artist"}:
        return "artist"
    if field_name == "album":
        return "album"
    if field_name == "title":
        return "track"
    return "ambiguous"


def _folder_agreement(values: list[dict[str, Any]]) -> bool:
    for row in values:
        value = _norm(row.get("value"))
        folder = _norm(Path(_clean(row.get("folder_artist"))).name)
        if value and folder and (value in folder or folder in value):
            return True
    return False


def _artifact_flags(values: Iterable[str]) -> list[str]:
    flags: list[str] = []
    for value in values:
        text = _clean(value)
        if _UPLOADER_RE.search(text):
            flags.append("uploader_signature")
        if _SOURCE_ARTIFACT_RE.search(text):
            flags.append("source_artifact_pattern")
        if text.isupper() and len(re.sub(r"[^A-Z0-9]", "", text)) > 3:
            flags.append("all_caps_anomaly")
        if len(re.findall(r"[^A-Za-z0-9\s]", text)) >= 4:
            flags.append("excessive_symbol_noise")
    return flags


def _title_like(value: str) -> bool:
    return bool(_TITLE_LIKE_RE.search(value))


def _best_value(values: Iterable[str]) -> str:
    clean_values = [_clean(value) for value in values if _clean(value)]
    if not clean_values:
        return ""
    counts = Counter(clean_values)
    return sorted(counts, key=lambda value: (-counts[value], value.casefold()))[0]


def _summary_result(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_scored_entities": int(summary["total_scored_entities"]),
        "high_confidence_count": int(summary["high_confidence_count"]),
        "medium_confidence_count": int(summary["medium_confidence_count"]),
        "low_confidence_count": int(summary["low_confidence_count"]),
        "blocked_confidence_count": int(summary["blocked_confidence_count"]),
        "average_confidence": float(summary["average_confidence"]),
        "average_positive_score": float(summary["average_positive_score"]),
        "average_negative_score": float(summary["average_negative_score"]),
    }


def _csv_row(item: ScoredEntity) -> dict[str, Any]:
    return asdict(item)


def _breakdown_payload(item: ScoredEntity) -> dict[str, Any]:
    return {
        "entity_type": item.entity_type,
        "entity_key": item.entity_key,
        "entity_value": item.entity_value,
        "confidence_tier": item.confidence_tier,
        "normalized_confidence": item.normalized_confidence,
        "breakdown": json.loads(item.weighted_score_breakdown_json),
        "rationale": item.rationale,
    }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).casefold())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in headers})
