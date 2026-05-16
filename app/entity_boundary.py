"""Deterministic entity boundary classification before canonical graph insertion."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.filename_parser import parse_filename


REPORT_DIRNAME = "entity_boundaries"
SUMMARY_FILENAME = "entity_boundary_summary.json"
BOUNDARIES_FILENAME = "entity_boundaries.csv"
BLOCKED_FILENAME = "blocked_boundaries.csv"
QUARANTINED_FILENAME = "quarantined_boundaries.csv"
NEEDS_REVIEW_FILENAME = "needs_review_boundaries.csv"

BOUNDARY_FIELDS: tuple[str, ...] = (
    "candidate_value",
    "source_field",
    "proposed_boundary_type",
    "confidence_score",
    "boundary_status",
    "flags",
    "rationale",
)

BLOCKING_STATUSES = {"block", "quarantine", "needs_review"}

_OFFICIAL_RE = re.compile(r"\b(?:official\s+(?:audio|video|music\s+video)|music\s+video|visualizer)\b", re.I)
_LYRIC_RE = re.compile(r"\b(?:lyric|lyrics)\s+video\b", re.I)
_VERSION_RE = re.compile(
    r"\b(?:remaster(?:ed)?|anniversary|deluxe|radio\s+edit|single\s+edit|single\s+version|"
    r"clean|explicit|acoustic|live|edit)\b",
    re.I,
)
_UPLOADER_RE = re.compile(
    r"\b(?:mr[a-z0-9]+|channel|topic|uploads?|auto-generated|provided\s+to\s+youtube|youtube)\b",
    re.I,
)
_LABEL_RE = re.compile(r"\b(?:records?|recordings|label|entertainment|vevo|vault)\b", re.I)
_SOURCE_RE = re.compile(r"\b(?:projekt|project|pre\s*studio|studio|archive)\b", re.I)
_COLLAB_RE = re.compile(r"(?:,|&|\b(?:ft\.?|feat\.?|featuring)\b)", re.I)
_TRACK_NUMBER_RE = re.compile(r"^\s*\d+\.\s+\S+")
_BRACKET_ONLY_RE = re.compile(r"^\s*[\[(][^\])]+[\])]\s*$")
_TITLE_LIKE_RE = re.compile(r"^(?:\d+\.\s*)?[a-z0-9][a-z0-9'’]*(?:\s+[a-z0-9][a-z0-9'’]*){1,7}$", re.I)


@dataclass(frozen=True)
class BoundaryContext:
    candidate_value: str
    source_field: str
    file_path: str = ""
    folder_artist: str = ""
    filename_artist: str = ""
    filename_title: str = ""
    metadata_tags: dict[str, str] = field(default_factory=dict)
    repeated_role_evidence: int = 0


@dataclass(frozen=True)
class EntityBoundary:
    candidate_value: str
    source_field: str
    proposed_boundary_type: str
    confidence_score: float
    boundary_status: str
    flags: list[str]
    rationale: list[str]


@dataclass(frozen=True)
class EntityBoundaryResult:
    report_path: str
    total_candidates: int
    allowed_candidates: int
    blocked_candidates: int
    quarantined_candidates: int
    needs_review_candidates: int
    source_artifacts_blocked: int
    collaboration_strings_quarantined: int
    title_pollution_blocked: int
    release_annotations_quarantined: int


def classify_boundary(context: BoundaryContext) -> EntityBoundary:
    value = _clean(context.candidate_value)
    field = _clean(context.source_field).casefold()
    flags: list[str] = []
    rationale: list[str] = []
    boundary_type = _default_boundary_type(field)
    status = "allow"
    score = 0.72 if value else 0.1

    if not value:
        return _boundary(context, "ambiguous", 0.1, "needs_review", ["empty_candidate"], ["candidate value is empty"])

    value_norm = _norm(value)
    title_norms = {_norm(context.filename_title), _norm(context.metadata_tags.get("title", ""))}
    album_norm = _norm(context.metadata_tags.get("album", ""))
    folder_norm = _norm(Path(context.folder_artist).name)

    if field in {"artist", "album_artist", "filename_artist", "album"}:
        if _BRACKET_ONLY_RE.search(value):
            boundary_type = "release_annotation"
            status = "quarantine"
            score = 0.9
            flags.append("bracket_only_release_annotation")
            rationale.append("candidate is only a bracketed release annotation")
        elif _OFFICIAL_RE.search(value) or _LYRIC_RE.search(value):
            boundary_type = "release_annotation"
            status = "block"
            score = 0.93
            flags.append("official_or_lyric_video_marker")
            rationale.append("artist or album candidate contains official media marker")
        elif _VERSION_RE.search(value):
            boundary_type = "version_descriptor"
            status = "block"
            score = 0.9
            flags.append("version_or_edit_marker")
            rationale.append("artist or album candidate contains version, edit, or explicit marker")

    if field in {"artist", "album_artist", "filename_artist"} and status == "allow":
        if _COLLAB_RE.search(value):
            boundary_type = "collaboration_string"
            status = "quarantine"
            score = 0.88
            flags.append("collaboration_marker")
            rationale.append("artist candidate contains comma, ft, feat, or featuring marker")
        elif _UPLOADER_RE.search(value):
            boundary_type = "uploader_artifact"
            status = "block"
            score = 0.91
            flags.append("uploader_marker")
            rationale.append("artist candidate resembles uploader or platform channel residue")
        elif _LABEL_RE.search(value):
            boundary_type = "label_artifact"
            status = "block"
            score = 0.89
            flags.append("label_marker")
            rationale.append("artist candidate resembles label or record-source residue")
        elif value.isupper() and len(value) <= 6 and folder_norm and value_norm != folder_norm:
            boundary_type = "source_artifact"
            status = "block"
            score = 0.84
            flags.append("short_all_caps_source_marker")
            rationale.append("short all-caps artist candidate disagrees with folder artist")
        elif _SOURCE_RE.search(value):
            boundary_type = "source_artifact"
            status = "block"
            score = 0.88
            flags.append("source_marker")
            rationale.append("artist candidate resembles source archive or studio residue")
        elif value.casefold().endswith("band") and folder_norm and value_norm != folder_norm:
            boundary_type = "source_artifact"
            status = "block"
            score = 0.84
            flags.append("band_suffix_folder_disagreement")
            rationale.append("artist candidate ends in band and disagrees with folder artist")
        elif value_norm and value_norm in title_norms:
            boundary_type = "track_title_pollution"
            status = "block"
            score = 0.94
            flags.append("matches_title_context")
            rationale.append("artist candidate matches filename or tag title")
        elif _TRACK_NUMBER_RE.search(value):
            boundary_type = "track_title_pollution"
            status = "block"
            score = 0.9
            flags.append("track_number_title_shape")
            rationale.append("artist candidate has track-number title shape")
        elif value_norm and value_norm == album_norm and context.repeated_role_evidence < 2:
            boundary_type = "album_title_pollution"
            status = "block"
            score = 0.82
            flags.append("matches_album_context")
            rationale.append("artist candidate matches album title without enough artist role evidence")
        elif (
            _TITLE_LIKE_RE.search(value)
            and folder_norm
            and value_norm != folder_norm
            and context.repeated_role_evidence <= 1
        ):
            boundary_type = "track_title_pollution"
            status = "block"
            score = 0.76
            flags.append("title_like_artist_folder_disagreement")
            rationale.append("single artist candidate is title-like and disagrees with folder artist")

    if field == "album" and status == "allow":
        if _UPLOADER_RE.search(value) or _LABEL_RE.search(value) or _SOURCE_RE.search(value):
            boundary_type = "source_artifact"
            status = "block"
            score = 0.86
            flags.append("album_source_artifact_marker")
            rationale.append("album candidate resembles source, channel, or label residue")

    if status == "allow":
        rationale.append("candidate boundary is consistent with source field")
    return _boundary(context, boundary_type, score, status, flags, rationale)


def generate_entity_boundary_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> EntityBoundaryResult:
    report_dir = Path(out_dir).expanduser() / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    boundaries = collect_entity_boundaries(db_path=db_path)
    summary = entity_boundary_summary(boundaries)
    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_csv(report_dir / BOUNDARIES_FILENAME, BOUNDARY_FIELDS, (_serialize(item) for item in boundaries))
    _write_csv(
        report_dir / BLOCKED_FILENAME,
        BOUNDARY_FIELDS,
        (_serialize(item) for item in boundaries if item.boundary_status == "block"),
    )
    _write_csv(
        report_dir / QUARANTINED_FILENAME,
        BOUNDARY_FIELDS,
        (_serialize(item) for item in boundaries if item.boundary_status == "quarantine"),
    )
    _write_csv(
        report_dir / NEEDS_REVIEW_FILENAME,
        BOUNDARY_FIELDS,
        (_serialize(item) for item in boundaries if item.boundary_status == "needs_review"),
    )
    return EntityBoundaryResult(report_path=str(report_dir), **_summary_result(summary))


def collect_entity_boundaries(*, db_path: str | Path = db.DEFAULT_DB_PATH) -> list[EntityBoundary]:
    contexts = collect_boundary_contexts(db_path=db_path)
    return sorted(
        (classify_boundary(context) for context in contexts),
        key=lambda item: (item.boundary_status, item.source_field, item.candidate_value.casefold()),
    )


def collect_boundary_contexts(*, db_path: str | Path = db.DEFAULT_DB_PATH) -> list[BoundaryContext]:
    rows = _load_boundary_rows(db_path)
    role_counts = Counter(
        (_role_field(row["source_field"]), _norm(row["candidate_value"]))
        for row in rows
        if row["candidate_value"]
    )
    return [
        BoundaryContext(
            candidate_value=row["candidate_value"],
            source_field=row["source_field"],
            file_path=row["file_path"],
            folder_artist=row["folder_artist"],
            filename_artist=row["filename_artist"],
            filename_title=row["filename_title"],
            metadata_tags=row["metadata_tags"],
            repeated_role_evidence=role_counts[(_role_field(row["source_field"]), _norm(row["candidate_value"]))],
        )
        for row in rows
    ]


def entity_boundary_summary(boundaries: Iterable[EntityBoundary]) -> dict[str, int]:
    materialized = list(boundaries)
    statuses = Counter(item.boundary_status for item in materialized)
    types = Counter(item.proposed_boundary_type for item in materialized)
    return {
        "total_candidates": len(materialized),
        "allowed_candidates": statuses["allow"],
        "blocked_candidates": statuses["block"],
        "quarantined_candidates": statuses["quarantine"],
        "needs_review_candidates": statuses["needs_review"],
        "source_artifacts_blocked": sum(
            1
            for item in materialized
            if item.boundary_status == "block"
            and item.proposed_boundary_type in {"source_artifact", "uploader_artifact", "label_artifact"}
        ),
        "collaboration_strings_quarantined": sum(
            1
            for item in materialized
            if item.boundary_status == "quarantine" and item.proposed_boundary_type == "collaboration_string"
        ),
        "title_pollution_blocked": sum(
            1
            for item in materialized
            if item.boundary_status == "block"
            and item.proposed_boundary_type in {"track_title_pollution", "album_title_pollution"}
        ),
        "release_annotations_quarantined": sum(
            1
            for item in materialized
            if item.boundary_status == "quarantine" and item.proposed_boundary_type == "release_annotation"
        ),
    }


def _load_boundary_rows(db_path: str | Path) -> list[dict[str, Any]]:
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
        for source_field, value in (
            ("artist", row["probable_artist"] or row["tag_artist"]),
            ("album_artist", row["tag_album_artist"]),
            ("filename_artist", row["filename_artist"] or parsed.possible_artist),
            ("title", row["probable_title"] or row["tag_title"] or row["filename_title"] or parsed.possible_title),
            ("album", row["probable_album"] or row["tag_album"]),
        ):
            clean_value = _clean(value)
            if clean_value:
                candidates.append({**base, "source_field": source_field, "candidate_value": clean_value})
    return candidates


def _boundary(
    context: BoundaryContext,
    boundary_type: str,
    score: float,
    status: str,
    flags: list[str],
    rationale: list[str],
) -> EntityBoundary:
    return EntityBoundary(
        candidate_value=_clean(context.candidate_value),
        source_field=_clean(context.source_field),
        proposed_boundary_type=boundary_type,
        confidence_score=round(max(0.0, min(1.0, score)), 3),
        boundary_status=status,
        flags=sorted(dict.fromkeys(flags)),
        rationale=list(dict.fromkeys(rationale)),
    )


def _default_boundary_type(field: str) -> str:
    if field in {"artist", "album_artist", "filename_artist"}:
        return "canonical_artist_candidate"
    if field == "album":
        return "canonical_album_candidate"
    if field == "title":
        return "canonical_track_candidate"
    return "ambiguous"


def _role_field(field: str) -> str:
    if field in {"artist", "album_artist", "filename_artist"}:
        return "artist"
    if field == "album":
        return "album"
    if field == "title":
        return "track"
    return "ambiguous"


def _serialize(boundary: EntityBoundary) -> dict[str, Any]:
    payload = asdict(boundary)
    payload["flags"] = "|".join(boundary.flags)
    payload["rationale"] = " | ".join(boundary.rationale)
    return payload


def _summary_result(summary: dict[str, int]) -> dict[str, int]:
    return {
        field: int(summary.get(field, 0) or 0)
        for field in EntityBoundaryResult.__dataclass_fields__
        if field != "report_path"
    }


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    text = _clean(value).casefold()
    text = re.sub(r"[\W_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _write_json(path: Path, payload: dict[str, int]) -> None:
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
