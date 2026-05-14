"""Role-aware canonical entity evidence aggregation.

The entity role model is observational. It separates a raw entity value from
the role and context where that value appears, but it never writes tags or
mutates media files.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.filename_parser import parse_filename


REPORT_DIRNAME = "entity_roles"
SUMMARY_FILENAME = "entity_role_summary.json"
ROLES_FILENAME = "entity_roles.csv"
MULTI_ROLE_FILENAME = "multi_role_entities.csv"
CONFLICTED_FILENAME = "conflicted_roles.csv"
BLOCKED_COLLISIONS_FILENAME = "blocked_role_collisions.csv"

SUPPORTED_ROLES = {
    "artist",
    "album",
    "track",
    "version",
    "source_artifact",
    "uploader_artifact",
    "label_artifact",
    "ambiguous",
}
SUPPORTED_STATUSES = {"candidate", "probationary", "canonical", "conflicted", "blocked"}

ROLE_HEADERS: tuple[str, ...] = (
    "entity_value",
    "normalized_value",
    "entity_role",
    "source_field",
    "file_path",
    "evidence_count",
    "confidence_score",
    "confidence_tier",
    "role_status",
    "rationale",
    "flags",
)
MULTI_ROLE_HEADERS: tuple[str, ...] = (
    "normalized_value",
    "entity_value",
    "active_roles",
    "role_count",
    "evidence_count",
    "flags",
    "rationale",
)

_SOURCE_ARTIFACT_RE = re.compile(
    r"\b(?:records?|recordings|vault|official|vevo|projekt|project|"
    r"pre\s*studio|studio|uploads?|archive|label|entertainment)\b",
    re.I,
)
_UPLOADER_STYLE_RE = re.compile(r"\b(?:mr[a-z0-9]+|.+['’]s\s+.+channel|.+\s+channel|.+\s+topic|channel|topic)\b", re.I)
_PLATFORM_RE = re.compile(r"\b(?:youtube|soundcloud|bandcamp|auto-generated|provided to youtube)\b", re.I)
_LABEL_TOKEN_RE = re.compile(r"\b(?:records?|recordings|label|entertainment)\b", re.I)
_VERSION_RE = re.compile(r"\b(?:remaster(?:ed)?|anniversary|deluxe|radio edit|single version|live|explicit|clean)\b", re.I)


@dataclass(frozen=True)
class EntityRoleRecord:
    entity_value: str
    normalized_value: str
    entity_role: str
    source_field: str
    file_path: str
    evidence_count: int
    confidence_score: float
    confidence_tier: str
    role_status: str
    rationale: list[str]
    flags: list[str]


@dataclass(frozen=True)
class EntityRoleReportResult:
    report_path: str
    total_role_records: int
    multi_role_entities: int
    conflicted_roles: int
    canonical_role_agreements: int
    blocked_role_collisions: int


def generate_entity_role_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> EntityRoleReportResult:
    reports_dir = Path(out_dir).expanduser()
    report_dir = reports_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    records = collect_entity_roles(db_path=db_path)
    summary = entity_role_summary(records)
    summary["created_at"] = datetime.now(UTC).isoformat()
    summary["report_file"] = str(report_dir / ROLES_FILENAME)
    multi_role = multi_role_entities(records)
    conflicted = [record for record in records if record.role_status == "conflicted"]
    blocked_collisions = blocked_role_collisions(records)

    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_csv(report_dir / ROLES_FILENAME, ROLE_HEADERS, (_csv_role(record) for record in records))
    _write_csv(report_dir / MULTI_ROLE_FILENAME, MULTI_ROLE_HEADERS, multi_role)
    _write_csv(report_dir / CONFLICTED_FILENAME, ROLE_HEADERS, (_csv_role(record) for record in conflicted))
    _write_csv(report_dir / BLOCKED_COLLISIONS_FILENAME, ROLE_HEADERS, (_csv_role(record) for record in blocked_collisions))
    return EntityRoleReportResult(report_path=str(report_dir), **_summary_ints(summary))


def collect_entity_roles(*, db_path: str | Path = db.DEFAULT_DB_PATH) -> list[EntityRoleRecord]:
    return aggregate_entity_roles(_load_role_rows(db_path))


def aggregate_entity_roles(rows: Iterable[dict[str, Any]]) -> list[EntityRoleRecord]:
    observations = [_normalize_row(row) for row in rows]
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        value = _clean(row.get("value"))
        normalized = _norm(value)
        if not normalized:
            continue
        grouped[(normalized, _field_role_for(row))].append(row)
        artifact_role = _artifact_role_for(value)
        if artifact_role:
            grouped[(normalized, artifact_role)].append(row)

    roles_by_value: defaultdict[str, set[str]] = defaultdict(set)
    for normalized, role in grouped:
        roles_by_value[normalized].add(role)

    records: list[EntityRoleRecord] = []
    for (normalized, role), values in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        records.append(_record(normalized, role, values, roles_by_value[normalized]))
    return records


def entity_role_summary(records: Iterable[EntityRoleRecord]) -> dict[str, int]:
    materialized = list(records)
    return {
        "total_role_records": len(materialized),
        "multi_role_entities": len(multi_role_entities(materialized)),
        "conflicted_roles": sum(1 for record in materialized if record.role_status == "conflicted"),
        "canonical_role_agreements": sum(1 for record in materialized if record.role_status == "canonical"),
        "blocked_role_collisions": len(blocked_role_collisions(materialized)),
    }


def role_records_by_value(records: Iterable[EntityRoleRecord]) -> dict[str, list[EntityRoleRecord]]:
    grouped: defaultdict[str, list[EntityRoleRecord]] = defaultdict(list)
    for record in records:
        grouped[record.normalized_value].append(record)
    return dict(grouped)


def best_role_record(records: Iterable[EntityRoleRecord], normalized_value: str, role: str) -> EntityRoleRecord | None:
    matches = [record for record in records if record.normalized_value == normalized_value and record.entity_role == role]
    if not matches:
        return None
    return max(matches, key=lambda record: (record.confidence_score, record.evidence_count))


def multi_role_entities(records: Iterable[EntityRoleRecord]) -> list[dict[str, Any]]:
    grouped = role_records_by_value(records)
    rows: list[dict[str, Any]] = []
    for normalized, role_records in sorted(grouped.items()):
        active = [record for record in role_records if record.role_status in {"candidate", "probationary", "canonical", "conflicted"}]
        roles = sorted({record.entity_role for record in active})
        if len(roles) < 2:
            continue
        rows.append(
            {
                "normalized_value": normalized,
                "entity_value": _best_value([record.entity_value for record in active]),
                "active_roles": "|".join(roles),
                "role_count": len(roles),
                "evidence_count": sum(record.evidence_count for record in active),
                "flags": json.dumps(["multi_role_entity"], sort_keys=True),
                "rationale": "value has separate role evidence and is not globally collapsed",
            }
        )
    return rows


def blocked_role_collisions(records: Iterable[EntityRoleRecord]) -> list[EntityRoleRecord]:
    grouped = role_records_by_value(records)
    collisions: list[EntityRoleRecord] = []
    for role_records in grouped.values():
        has_active = any(record.role_status in {"candidate", "probationary", "canonical"} for record in role_records)
        if not has_active:
            continue
        collisions.extend(record for record in role_records if record.role_status == "blocked")
    return sorted(collisions, key=lambda record: (record.normalized_value, record.entity_role))


def read_entity_role_report(
    reports_dir: str | Path = "reports",
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    report_dir = Path(reports_dir).expanduser() / REPORT_DIRNAME
    summary, missing_summary = _read_json(report_dir / SUMMARY_FILENAME)
    records, missing_records = _read_csv(report_dir / ROLES_FILENAME)
    multi_role, missing_multi = _read_csv(report_dir / MULTI_ROLE_FILENAME)
    conflicted, missing_conflicted = _read_csv(report_dir / CONFLICTED_FILENAME)
    blocked, missing_blocked = _read_csv(report_dir / BLOCKED_COLLISIONS_FILENAME)
    return (
        summary,
        [_normalize_report_row(row) for row in records],
        [_normalize_report_row(row) for row in multi_role],
        [_normalize_report_row(row) for row in conflicted],
        [_normalize_report_row(row) for row in blocked],
        [label for label in (missing_summary, missing_records, missing_multi, missing_conflicted, missing_blocked) if label],
    )


def _record(normalized: str, role: str, rows: list[dict[str, Any]], roles_for_value: set[str]) -> EntityRoleRecord:
    values = [_clean(row.get("value")) for row in rows]
    fields = sorted({_clean(row.get("field_name")) for row in rows if _clean(row.get("field_name"))})
    paths = sorted({_clean(row.get("file_path")) for row in rows if _clean(row.get("file_path"))})
    evidence_count = len(rows)
    flags: list[str] = []
    rationale: list[str] = [f"{evidence_count} observation(s) support {role} role"]
    if len(roles_for_value) > 1:
        flags.append("multi_role_entity")
        rationale.append("same normalized value appears in separate roles")
    contradictions = sum(1 for row in rows if _direct_context_conflict(row, role))
    if contradictions:
        flags.append("context_contradiction")
        rationale.append("role evidence directly contradicts file title or folder context")
    if role in {"source_artifact", "uploader_artifact", "label_artifact"}:
        flags.append("artifact_role")
        rationale.append("artifact wording dominates this role evidence")
    if role == "version":
        flags.append("version_role")
        rationale.append("version descriptor wording dominates this value")

    score = _score(evidence_count, contradictions, role)
    status = _status(score, contradictions, role)
    if role == "ambiguous":
        status = "conflicted" if contradictions else "candidate"
    return EntityRoleRecord(
        entity_value=_best_value(values),
        normalized_value=normalized,
        entity_role=role if role in SUPPORTED_ROLES else "ambiguous",
        source_field="|".join(fields),
        file_path="|".join(paths[:5]),
        evidence_count=evidence_count,
        confidence_score=round(score, 3),
        confidence_tier=_tier(score),
        role_status=status if status in SUPPORTED_STATUSES else "candidate",
        rationale=list(dict.fromkeys(rationale)),
        flags=sorted(dict.fromkeys(flags)),
    )


def _field_role_for(row: dict[str, Any]) -> str:
    value = _clean(row.get("value"))
    field = _clean(row.get("field_name")).casefold()
    if field in {"artist", "album_artist", "filename_artist"}:
        return "artist"
    if field == "album":
        return "version" if _VERSION_RE.search(value) else "album"
    if field in {"title", "filename_title"}:
        return "track"
    return "ambiguous"


def _artifact_role_for(value: str) -> str:
    if _is_uploader_artifact(value):
        return "uploader_artifact"
    if _is_label_artifact(value):
        return "label_artifact"
    if _is_source_artifact(value):
        return "source_artifact"
    return ""


def _direct_context_conflict(row: dict[str, Any], role: str) -> bool:
    value_norm = _norm(row.get("value"))
    if not value_norm:
        return False
    if role == "artist":
        title_norms = {_norm(row.get("filename_title")), _norm(row.get("metadata_tags", {}).get("title", ""))}
        folder_norm = _norm(Path(_clean(row.get("folder_artist"))).name)
        return value_norm in title_norms and (not folder_norm or value_norm != folder_norm)
    if role == "album":
        title_norms = {_norm(row.get("filename_title")), _norm(row.get("metadata_tags", {}).get("title", ""))}
        return value_norm in title_norms
    return False


def _score(evidence_count: int, contradictions: int, role: str) -> float:
    score = 0.48 + min(0.32, evidence_count * 0.08)
    if evidence_count >= 3:
        score += 0.08
    if role in {"source_artifact", "uploader_artifact", "label_artifact", "version"}:
        score += 0.14
    if contradictions:
        score -= min(0.35, contradictions * 0.18)
    return max(0.05, min(0.98, score))


def _status(score: float, contradictions: int, role: str) -> str:
    if role in {"source_artifact", "uploader_artifact", "label_artifact"} and score >= 0.68:
        return "blocked"
    if contradictions:
        return "conflicted"
    if score >= 0.78:
        return "canonical"
    if score >= 0.62:
        return "probationary"
    return "candidate"


def _load_role_rows(db_path: str | Path) -> list[dict[str, Any]]:
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
    return {
        "value": _clean(row.get("value") or row.get("candidate_value")),
        "field_name": _clean(row.get("field_name") or row.get("field")),
        "file_path": _clean(row.get("file_path")),
        "folder_artist": _clean(row.get("folder_artist")),
        "filename_artist": _clean(row.get("filename_artist")),
        "filename_title": _clean(row.get("filename_title")),
        "metadata_tags": {str(key): _clean(value) for key, value in tags.items()} if isinstance(tags, dict) else {},
    }


def _is_uploader_artifact(value: str) -> bool:
    return bool(_UPLOADER_STYLE_RE.search(value) or _PLATFORM_RE.search(value))


def _is_label_artifact(value: str) -> bool:
    return bool(_LABEL_TOKEN_RE.search(value))


def _is_source_artifact(value: str) -> bool:
    text = _clean(value)
    if _SOURCE_ARTIFACT_RE.search(text):
        return True
    if text.isupper() and 2 <= len(re.sub(r"[^A-Z0-9]", "", text)) <= 8:
        return True
    if text.casefold().endswith("band"):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9_]{8,14}", text) and any(char.islower() for char in text) and any(char.isupper() for char in text))


def _csv_role(record: EntityRoleRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["rationale"] = " | ".join(record.rationale)
    payload["flags"] = json.dumps(record.flags, sort_keys=True)
    return payload


def _normalize_report_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key in ("confidence_score",):
        if key in normalized:
            normalized[key] = float(normalized.get(key, 0.0) or 0.0)
    for key in ("evidence_count", "role_count"):
        if key in normalized:
            normalized[key] = int(normalized.get(key, 0) or 0)
    for key in ("rationale", "flags"):
        value = normalized.get(key, [])
        if key == "flags" and isinstance(value, str):
            try:
                normalized[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        if isinstance(value, str):
            normalized[key] = [part.strip() for part in re.split(r"\s*\|\s*", value) if part.strip()]
    return normalized


def _summary_ints(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "total_role_records": int(summary["total_role_records"]),
        "multi_role_entities": int(summary["multi_role_entities"]),
        "conflicted_roles": int(summary["conflicted_roles"]),
        "canonical_role_agreements": int(summary["canonical_role_agreements"]),
        "blocked_role_collisions": int(summary["blocked_role_collisions"]),
    }


def _best_value(values: Iterable[str]) -> str:
    clean_values = [_clean(value) for value in values if _clean(value)]
    if not clean_values:
        return ""
    counts = Counter(clean_values)
    return sorted(counts, key=lambda value: (-counts[value], value.casefold()))[0]


def _tier(score: float) -> str:
    if score >= 0.74:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).casefold())


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
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
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in headers})
