"""Deterministic track identity resolution from observed evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db
from app.artist_seeds import match_seed_artist, normalize_artist_name


IDENTITY_STATUSES: frozenset[str] = frozenset(
    {"identified", "partial", "unknown", "conflicting"}
)

REQUIRED_EVIDENCE_FIELDS: tuple[str, ...] = (
    "selected_artist_source",
    "selected_title_source",
    "tag_artist",
    "tag_title",
    "filename_artist",
    "filename_title",
    "parent_folder",
    "artist_seed_matched",
    "conflict_reasons",
)

CONTAMINATED_TAG_ARTIST_TERMS: tuple[str, ...] = (
    "records",
    "music",
    "official",
    "channel",
    "vevo",
    "topic",
    "label",
    "entertainment",
)

YOUTUBE_TITLE_SUFFIXES: tuple[str, ...] = (
    "Official Audio",
    "Official Music Video",
    "Official Video",
    "Official Visualizer",
    "Performance Music Video",
    "HD Remaster",
    "4K",
    "EXPLICIT",
)


@dataclass(frozen=True)
class IdentityResolution:
    observed_file_id: int | None
    probable_artist: str | None
    probable_title: str | None
    probable_album: str | None
    probable_year: str | None
    probable_mix: str | None
    identity_confidence: float
    identity_status: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class IdentifySummary:
    total: int
    identified: int
    partial: int
    conflicting: int
    unknown: int


def resolve_identity(
    *,
    observed_file_id: int | None = None,
    tag_artist: str | None = None,
    tag_title: str | None = None,
    tag_album: str | None = None,
    tag_date: str | None = None,
    filename_artist: str | None = None,
    filename_title: str | None = None,
    filename_mix: str | None = None,
    parent_folder: str | None = None,
) -> IdentityResolution:
    """Resolve probable track identity without guessing missing data."""

    tag_artist = _clean(tag_artist)
    tag_title = _clean(tag_title)
    tag_album = _clean(tag_album)
    tag_date = _clean(tag_date)
    filename_artist = _clean(filename_artist)
    filename_title = _clean(filename_title)
    filename_mix = _clean(filename_mix)
    parent_folder = _clean(parent_folder)

    tag_artist_seed = match_seed_artist(tag_artist) if tag_artist else None
    filename_artist_seed = match_seed_artist(filename_artist) if filename_artist else None
    normalized_tag_artist = tag_artist_seed.artist if tag_artist_seed else tag_artist
    normalized_filename_artist = (
        filename_artist_seed.artist if filename_artist_seed else filename_artist
    )
    parent_artist = _parent_folder_artist(parent_folder)
    tag_artist_deprioritized = _is_contaminated_tag_artist(
        tag_artist=tag_artist,
        tag_artist_seed_matched=tag_artist_seed is not None,
        filename_artist_seed_matched=filename_artist_seed is not None,
    )
    deprioritized_reason = (
        "uploader_or_label_metadata" if tag_artist_deprioritized else None
    )

    conflict_reasons = _detect_conflicts(
        tag_artist=None if tag_artist_deprioritized else normalized_tag_artist,
        tag_title=None if tag_artist_deprioritized else _clean_title(tag_title),
        filename_artist=normalized_filename_artist,
        filename_title=_clean_title(filename_title),
    )

    selected_artist_source = None
    selected_title_source = None

    if tag_artist_deprioritized and normalized_filename_artist:
        probable_artist = normalized_filename_artist
        selected_artist_source = "filename"
    elif normalized_tag_artist:
        probable_artist = normalized_tag_artist
        selected_artist_source = "tag"
    elif normalized_filename_artist:
        probable_artist = normalized_filename_artist
        selected_artist_source = "filename"
    elif parent_artist:
        probable_artist = parent_artist
        selected_artist_source = "parent_folder"
    else:
        probable_artist = None

    cleaned_tag_title = _clean_title(tag_title, probable_artist=probable_artist)
    cleaned_filename_title = _clean_title(
        filename_title, probable_artist=probable_artist
    )

    if tag_artist_deprioritized and cleaned_filename_title:
        probable_title = cleaned_filename_title
        selected_title_source = "filename"
    elif cleaned_tag_title:
        probable_title = cleaned_tag_title
        selected_title_source = "tag"
    elif cleaned_filename_title:
        probable_title = cleaned_filename_title
        selected_title_source = "filename"
    else:
        probable_title = None

    if conflict_reasons:
        identity_status = "conflicting"
    elif probable_artist and probable_title:
        identity_status = "identified"
    elif probable_artist or probable_title:
        identity_status = "partial"
    else:
        identity_status = "unknown"

    artist_seed = (
        match_seed_artist(probable_artist) if probable_artist is not None else None
    )
    artist_seed_matched = artist_seed.artist if artist_seed else None

    evidence = build_identity_evidence(
        selected_artist_source=selected_artist_source,
        selected_title_source=selected_title_source,
        tag_artist=tag_artist,
        tag_title=tag_title,
        filename_artist=filename_artist,
        filename_title=filename_title,
        parent_folder=parent_folder,
        artist_seed_matched=artist_seed_matched,
        conflict_reasons=conflict_reasons,
        tag_artist_deprioritized=tag_artist_deprioritized,
        deprioritized_reason=deprioritized_reason,
    )

    confidence = calculate_identity_confidence(
        identity_status=identity_status,
        selected_artist_source=selected_artist_source,
        selected_title_source=selected_title_source,
        tag_artist=tag_artist,
        tag_title=tag_title,
        filename_artist=filename_artist,
        filename_title=filename_title,
        artist_seed_matched=artist_seed_matched,
    )

    return IdentityResolution(
        observed_file_id=observed_file_id,
        probable_artist=probable_artist,
        probable_title=probable_title,
        probable_album=tag_album,
        probable_year=_extract_year(tag_date),
        probable_mix=filename_mix,
        identity_confidence=confidence,
        identity_status=identity_status,
        evidence=evidence,
    )


def calculate_identity_confidence(
    *,
    identity_status: str,
    selected_artist_source: str | None = None,
    selected_title_source: str | None = None,
    tag_artist: str | None = None,
    tag_title: str | None = None,
    filename_artist: str | None = None,
    filename_title: str | None = None,
    artist_seed_matched: str | None = None,
) -> float:
    """Return deterministic confidence for the resolved identity state."""

    if identity_status == "conflicting":
        return 0.40
    if identity_status == "unknown":
        return 0.10
    if identity_status == "partial":
        return 0.60
    if (
        identity_status == "identified"
        and tag_artist
        and tag_title
        and selected_artist_source == "tag"
        and selected_title_source == "tag"
    ):
        return 0.95
    if (
        identity_status == "identified"
        and filename_artist
        and filename_title
        and artist_seed_matched
        and selected_artist_source == "filename"
        and selected_title_source == "filename"
    ):
        return 0.85
    if identity_status == "identified" and filename_artist and filename_title:
        return 0.75
    if identity_status == "identified":
        return 0.75

    raise ValueError(f"Unknown identity_status: {identity_status}")


def build_identity_evidence(
    *,
    selected_artist_source: str | None,
    selected_title_source: str | None,
    tag_artist: str | None,
    tag_title: str | None,
    filename_artist: str | None,
    filename_title: str | None,
    parent_folder: str | None,
    artist_seed_matched: str | None,
    conflict_reasons: list[str],
    tag_artist_deprioritized: bool = False,
    deprioritized_reason: str | None = None,
) -> dict[str, Any]:
    """Build the required evidence JSON payload."""

    evidence = {
        "selected_artist_source": selected_artist_source,
        "selected_title_source": selected_title_source,
        "tag_artist": tag_artist,
        "tag_title": tag_title,
        "filename_artist": filename_artist,
        "filename_title": filename_title,
        "parent_folder": parent_folder,
        "artist_seed_matched": artist_seed_matched,
        "conflict_reasons": list(conflict_reasons),
    }
    if tag_artist_deprioritized:
        evidence["tag_artist_deprioritized"] = True
        evidence["deprioritized_reason"] = deprioritized_reason
    return evidence


def identify_scan_run(
    scan_run_id: int, db_path: str | Path = db.DEFAULT_DB_PATH
) -> IdentifySummary:
    """Resolve and persist identity rows for all observed files in a scan run."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                observed_files.id AS observed_file_id,
                observed_files.parent_folder,
                tag_observations.artist AS tag_artist,
                tag_observations.title AS tag_title,
                tag_observations.album AS tag_album,
                tag_observations.date AS tag_date,
                filename_observations.possible_artist AS filename_artist,
                filename_observations.possible_title AS filename_title,
                filename_observations.possible_mix AS filename_mix
            FROM observed_files
            LEFT JOIN tag_observations
                ON tag_observations.observed_file_id = observed_files.id
            LEFT JOIN filename_observations
                ON filename_observations.observed_file_id = observed_files.id
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
                DELETE FROM track_identity
                WHERE observed_file_id IN ({placeholders})
                """,
                observed_file_ids,
            )

        counts = {"identified": 0, "partial": 0, "conflicting": 0, "unknown": 0}
        for row in rows:
            resolution = resolve_identity(
                observed_file_id=row["observed_file_id"],
                tag_artist=row["tag_artist"],
                tag_title=row["tag_title"],
                tag_album=row["tag_album"],
                tag_date=row["tag_date"],
                filename_artist=row["filename_artist"],
                filename_title=row["filename_title"],
                filename_mix=row["filename_mix"],
                parent_folder=row["parent_folder"],
            )
            _insert_identity(connection, resolution)
            counts[resolution.identity_status] += 1

    return IdentifySummary(
        total=len(rows),
        identified=counts["identified"],
        partial=counts["partial"],
        conflicting=counts["conflicting"],
        unknown=counts["unknown"],
    )


def _insert_identity(connection, resolution: IdentityResolution) -> None:
    connection.execute(
        """
        INSERT INTO track_identity (
            observed_file_id,
            probable_artist,
            probable_title,
            probable_album,
            probable_year,
            probable_mix,
            identity_confidence,
            identity_status,
            evidence_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolution.observed_file_id,
            resolution.probable_artist,
            resolution.probable_title,
            resolution.probable_album,
            resolution.probable_year,
            resolution.probable_mix,
            resolution.identity_confidence,
            resolution.identity_status,
            json.dumps(resolution.evidence, sort_keys=True),
            datetime.now(UTC).isoformat(),
        ),
    )


def _detect_conflicts(
    *,
    tag_artist: str | None,
    tag_title: str | None,
    filename_artist: str | None,
    filename_title: str | None,
) -> list[str]:
    reasons: list[str] = []
    if tag_artist and filename_artist:
        if normalize_artist_name(tag_artist) != normalize_artist_name(filename_artist):
            reasons.append("tag_artist_conflicts_with_filename_artist")
    if tag_title and filename_title:
        if _normalize_title(tag_title) != _normalize_title(filename_title):
            reasons.append("tag_title_conflicts_with_filename_title")
    return reasons


def _normalize_artist_with_seed(value: str | None) -> str | None:
    if value is None:
        return None
    seed = match_seed_artist(value)
    return seed.artist if seed else value


def _is_contaminated_tag_artist(
    *,
    tag_artist: str | None,
    tag_artist_seed_matched: bool,
    filename_artist_seed_matched: bool,
) -> bool:
    if not tag_artist or tag_artist_seed_matched or not filename_artist_seed_matched:
        return False

    normalized_tag_artist = tag_artist.lower()
    if any(term in normalized_tag_artist for term in CONTAMINATED_TAG_ARTIST_TERMS):
        return True
    return True


def _parent_folder_artist(parent_folder: str | None) -> str | None:
    if parent_folder is None:
        return None

    candidates = [part for part in re.split(r"[\\/]", parent_folder) if part]
    for candidate in reversed(candidates):
        seed = match_seed_artist(candidate)
        if seed:
            return seed.artist
    return None


def _extract_year(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", value)
    return match.group(1) if match else None


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _clean_title(value: str | None, *, probable_artist: str | None = None) -> str | None:
    if value is None:
        return None

    cleaned = value
    cleaned = _remove_duplicate_artist_prefix(cleaned, probable_artist=probable_artist)
    suffix_pattern = "|".join(re.escape(suffix) for suffix in YOUTUBE_TITLE_SUFFIXES)
    bracketed_suffix = re.compile(
        rf"\s*(?:\((?:{suffix_pattern})\)|\[(?:{suffix_pattern})\])\s*$",
        re.IGNORECASE,
    )
    bare_suffix = re.compile(rf"\s*[-–—:]?\s*(?:{suffix_pattern})\s*$", re.IGNORECASE)
    video_id_suffix = re.compile(r"\s*\[[A-Za-z0-9_-]{11}\]\s*$")
    while True:
        next_cleaned = bracketed_suffix.sub("", cleaned).strip()
        next_cleaned = bare_suffix.sub("", next_cleaned).strip()
        next_cleaned = video_id_suffix.sub("", next_cleaned).strip()
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    return _clean(cleaned)


def _remove_duplicate_artist_prefix(
    value: str, *, probable_artist: str | None
) -> str:
    if probable_artist is None:
        return value

    match = re.match(r"^\s*(?P<prefix>.+?)\s+-\s+(?P<title>.+)$", value)
    if not match:
        return value
    if normalize_artist_name(match.group("prefix")) != normalize_artist_name(
        probable_artist
    ):
        return value
    return match.group("title")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None
