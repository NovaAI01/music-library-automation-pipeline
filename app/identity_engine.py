"""Deterministic track identity resolution from observed evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db
from app.album_organization import UNKNOWN_ALBUM, infer_album
from app.artist_seeds import list_seed_artists, match_seed_artist, normalize_artist_name


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
    "Official Audio Stream",
    "Official Music Video",
    "Official Video",
    "Official Visual",
    "Official Visualizer",
    "Performance Music Video",
    "Low Gain Mix",
    "Studio Version, from X-Rated",
    "HD Remaster",
    "Audio",
    "4K",
    "HD",
    "EXPLICIT",
)

TITLE_REMOVAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\s*\[Full Dynamic Range Edition\]\s*", re.IGNORECASE),
    re.compile(r"\s*\[4K,\s*60FPS\]\s*", re.IGNORECASE),
    re.compile(r"\s*\|\s*Warner Vault\s*$", re.IGNORECASE),
)

FULL_WIDTH_PUNCTUATION = str.maketrans(
    {
        "：": ":",
        "＞": ">",
        "＂": '"',
        "？": "?",
    }
)

TITLE_ARTIST_SEPARATORS = re.compile(r"\s+[-–—]\s+|:\s+")
ALBUM_ARTIST_SEPARATOR = re.compile(r"\s*[-–—|｜]\s*")
FULL_ALBUM_DECORATION = re.compile(
    r"\s*(?:(?:\[|\()\s*full album(?: stream)?\s*(?:\]|\))|full album(?: stream)?)\s*$",
    re.IGNORECASE,
)

PARENT_ARTIST_ALIASES: dict[str, str] = {
    normalize_artist_name("CrossfadeMusicTV"): "Crossfade",
    normalize_artist_name("System Of A Down"): "System of a Down",
    normalize_artist_name("NOTHING MORE"): "Nothing More",
    normalize_artist_name("Fit For a King"): "Fit for a King",
}

KNOWN_LABEL_UPLOADER_NAMES: tuple[str, ...] = (
    "Better Noise Music",
    "Warner Records Vault",
    "SharpTone Records",
    "Solid State Records",
    "Pale Chord Music",
    "riserecords",
    "SUMERIAN",
)

KNOWN_LABEL_UPLOADER_KEYS: frozenset[str] = frozenset(
    normalize_artist_name(name) for name in KNOWN_LABEL_UPLOADER_NAMES
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


@dataclass(frozen=True)
class TitleArtistEvidence:
    artist: str
    title: str
    source: str


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
    filename_track_number: str | None = None,
    parent_folder: str | None = None,
) -> IdentityResolution:
    """Resolve probable track identity without guessing missing data."""

    raw_tag_title = tag_title
    raw_filename_title = filename_title

    tag_artist = _clean(tag_artist)
    tag_title = _clean(tag_title)
    tag_album = _clean(tag_album)
    tag_date = _clean(tag_date)
    filename_artist = _clean(filename_artist)
    filename_title = _clean(filename_title)
    filename_mix = _clean(filename_mix)
    filename_track_number = _clean(filename_track_number)
    parent_folder = _clean(parent_folder)

    tag_artist_seed = match_seed_artist(tag_artist) if tag_artist else None
    filename_artist_seed = match_seed_artist(filename_artist) if filename_artist else None
    normalized_tag_artist = tag_artist_seed.artist if tag_artist_seed else tag_artist
    normalized_filename_artist = (
        filename_artist_seed.artist if filename_artist_seed else filename_artist
    )
    parent_artist = _parent_folder_artist(parent_folder)
    parent_artist_seed_matched = parent_artist is not None
    title_artist_evidence = _title_artist_evidence(
        filename_title=raw_filename_title,
        tag_title=raw_tag_title,
    )
    chapter_album_context = _has_chapter_album_context(
        filename_artist=normalized_filename_artist,
        filename_title=filename_title,
        filename_track_number=filename_track_number,
        parent_folder=parent_folder,
    )
    chapter_tag_title_album_context = _chapter_tag_title_matches_parent_album(
        tag_title=tag_title,
        parent_folder=parent_folder,
    ) if chapter_album_context else False
    tag_artist_deprioritized = _is_contaminated_tag_artist(
        tag_artist=tag_artist,
        tag_artist_seed_matched=tag_artist_seed is not None,
        seed_artist_available=(
            filename_artist_seed is not None or parent_artist_seed_matched
            or title_artist_evidence is not None
        ),
        chapter_album_context=chapter_album_context,
        chapter_tag_title_album_context=chapter_tag_title_album_context,
    )
    deprioritized_reason = (
        "chapter_album_metadata"
        if tag_artist_deprioritized and chapter_tag_title_album_context
        else "uploader_or_label_metadata"
        if tag_artist_deprioritized
        else None
    )

    selected_artist_source = None
    selected_title_source = None

    if tag_artist_deprioritized and normalized_filename_artist:
        probable_artist = normalized_filename_artist
        selected_artist_source = "filename"
    elif tag_artist_deprioritized and title_artist_evidence:
        probable_artist = title_artist_evidence.artist
        selected_artist_source = title_artist_evidence.source
    elif tag_artist_deprioritized and parent_artist:
        probable_artist = parent_artist
        selected_artist_source = "parent_folder"
    elif tag_artist_deprioritized:
        probable_artist = None
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

    if title_artist_evidence and probable_artist == title_artist_evidence.artist:
        if chapter_album_context and cleaned_filename_title:
            probable_title = cleaned_filename_title
            selected_title_source = "filename"
        else:
            probable_title = title_artist_evidence.title
            selected_title_source = title_artist_evidence.source
    elif tag_artist_deprioritized and cleaned_filename_title:
        probable_title = cleaned_filename_title
        selected_title_source = "filename"
    elif chapter_tag_title_album_context and cleaned_filename_title:
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

    conflict_reasons = _detect_conflicts(
        tag_artist=None if tag_artist_deprioritized else normalized_tag_artist,
        tag_title=(
            None
            if chapter_tag_title_album_context
            or _has_seed_artist_support(
                probable_artist=probable_artist,
                filename_artist=normalized_filename_artist,
                parent_artist=parent_artist,
                title_artist=title_artist_evidence.artist
                if title_artist_evidence
                else None,
            )
            else _clean_title(tag_title, probable_artist=probable_artist)
        ),
        filename_artist=normalized_filename_artist,
        filename_title=cleaned_filename_title,
        title_artist=title_artist_evidence.artist if title_artist_evidence else None,
    )

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
        tag_title_deprioritized=chapter_tag_title_album_context,
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
    probable_album = _resolve_probable_album(
        tag_album=tag_album,
        parent_folder=parent_folder,
        probable_artist=probable_artist,
        probable_title=probable_title,
        chapter_album_context=chapter_album_context,
    )

    return IdentityResolution(
        observed_file_id=observed_file_id,
        probable_artist=probable_artist,
        probable_title=probable_title,
        probable_album=probable_album,
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
    if (
        identity_status == "identified"
        and artist_seed_matched
        and selected_artist_source in {"filename_title", "tag_title"}
        and selected_title_source == selected_artist_source
    ):
        return 0.85
    if (
        identity_status == "identified"
        and artist_seed_matched
        and selected_artist_source == "filename"
        and selected_title_source == "filename_title"
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
    tag_title_deprioritized: bool = False,
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
    if tag_title_deprioritized:
        evidence["tag_title_deprioritized"] = True
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
                filename_observations.possible_mix AS filename_mix,
                filename_observations.possible_track_number AS filename_track_number
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
                filename_track_number=row["filename_track_number"],
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
    title_artist: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    if tag_artist and filename_artist:
        tag_seed = match_seed_artist(tag_artist)
        filename_seed = match_seed_artist(filename_artist)
        if (
            tag_seed
            and filename_seed
            and normalize_artist_name(tag_seed.artist)
            != normalize_artist_name(filename_seed.artist)
        ):
            reasons.append("tag_artist_conflicts_with_filename_artist")
    if tag_artist and title_artist:
        tag_seed = match_seed_artist(tag_artist)
        title_seed = match_seed_artist(title_artist)
        if (
            tag_seed
            and title_seed
            and normalize_artist_name(tag_seed.artist)
            != normalize_artist_name(title_seed.artist)
        ):
            reasons.append("tag_artist_conflicts_with_title_artist")
    if filename_artist and title_artist:
        filename_seed = match_seed_artist(filename_artist)
        title_seed = match_seed_artist(title_artist)
        if (
            filename_seed
            and title_seed
            and normalize_artist_name(filename_seed.artist)
            != normalize_artist_name(title_seed.artist)
        ):
            reasons.append("filename_artist_conflicts_with_title_artist")
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
    seed_artist_available: bool,
    chapter_album_context: bool = False,
    chapter_tag_title_album_context: bool = False,
) -> bool:
    if not tag_artist or tag_artist_seed_matched:
        return False

    if chapter_album_context and chapter_tag_title_album_context:
        return True

    if not seed_artist_available and not chapter_album_context:
        return False

    if _is_known_label_uploader_name(tag_artist):
        return True

    normalized_tag_artist = tag_artist.lower()
    if any(term in normalized_tag_artist for term in CONTAMINATED_TAG_ARTIST_TERMS):
        return True
    return seed_artist_available


def _has_chapter_album_context(
    *,
    filename_artist: str | None,
    filename_title: str | None,
    filename_track_number: str | None,
    parent_folder: str | None,
) -> bool:
    return bool(
        filename_track_number
        and filename_title
        and not filename_artist
        and parent_folder
    )


def _resolve_probable_album(
    *,
    tag_album: str | None,
    parent_folder: str | None,
    probable_artist: str | None,
    probable_title: str | None,
    chapter_album_context: bool,
) -> str | None:
    if tag_album:
        return tag_album
    if not chapter_album_context:
        return None

    chapter_album = _chapter_album_candidate(
        parent_folder,
        artist=probable_artist,
    )
    if chapter_album:
        return chapter_album

    inference = infer_album(
        album_tag=None,
        parent_folder=parent_folder,
        title=probable_title,
        artist=probable_artist,
    )
    if inference.album == UNKNOWN_ALBUM:
        return None
    return inference.album


def _chapter_tag_title_matches_parent_album(
    *,
    tag_title: str | None,
    parent_folder: str | None,
) -> bool:
    parent_album = _chapter_album_candidate(parent_folder)
    tag_album = _chapter_album_title_candidate(tag_title)
    if not parent_album or not tag_album:
        return False
    if _normalize_title(parent_album) == _normalize_title(tag_album):
        return True

    for match in ALBUM_ARTIST_SEPARATOR.finditer(tag_album):
        suffix = tag_album[match.end() :].strip()
        if suffix and _normalize_title(suffix) == _normalize_title(parent_album):
            return True
    return False


def _chapter_album_candidate(
    parent_folder: str | None,
    *,
    artist: str | None = None,
) -> str | None:
    candidate = _immediate_parent_folder(parent_folder)
    candidate = _strip_full_album_decoration(candidate)
    candidate = _strip_artist_album_prefix(candidate, artist=artist)
    candidate = _strip_full_album_decoration(candidate)
    return candidate


def _chapter_album_title_candidate(tag_title: str | None) -> str | None:
    return _strip_full_album_decoration(tag_title)


def _immediate_parent_folder(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    parts = [part.strip() for part in re.split(r"[\\/]", cleaned) if part.strip()]
    return parts[-1] if parts else None


def _strip_full_album_decoration(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = _clean(value)
    if not cleaned:
        return None
    while True:
        next_cleaned = FULL_ALBUM_DECORATION.sub("", cleaned).strip()
        if next_cleaned == cleaned:
            return _clean(next_cleaned)
        cleaned = next_cleaned


def _strip_artist_album_prefix(value: str | None, *, artist: str | None) -> str | None:
    if not value or not artist:
        return value
    for match in ALBUM_ARTIST_SEPARATOR.finditer(value):
        prefix = value[: match.start()].strip()
        suffix = value[match.end() :].strip()
        if suffix and normalize_artist_name(prefix) == normalize_artist_name(artist):
            return suffix
    return value


def _is_known_label_uploader_name(value: str) -> bool:
    return normalize_artist_name(value) in KNOWN_LABEL_UPLOADER_KEYS


def _has_seed_artist_support(
    *,
    probable_artist: str | None,
    filename_artist: str | None,
    parent_artist: str | None,
    title_artist: str | None = None,
) -> bool:
    probable_seed = match_seed_artist(probable_artist) if probable_artist else None
    if probable_seed is None:
        return False

    for candidate in (filename_artist, parent_artist, title_artist):
        candidate_seed = match_seed_artist(candidate) if candidate else None
        if candidate_seed and normalize_artist_name(candidate_seed.artist) == (
            normalize_artist_name(probable_seed.artist)
        ):
            return True
    return False


def _parent_folder_artist(parent_folder: str | None) -> str | None:
    if parent_folder is None:
        return None

    candidates = [part for part in re.split(r"[\\/]", parent_folder) if part]
    for candidate in reversed(candidates):
        alias_artist = PARENT_ARTIST_ALIASES.get(normalize_artist_name(candidate))
        if alias_artist:
            return alias_artist
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

    cleaned = _normalize_punctuation(value)
    cleaned = _remove_duplicate_artist_prefix(cleaned, probable_artist=probable_artist)
    for removal_pattern in TITLE_REMOVAL_PATTERNS:
        cleaned = removal_pattern.sub(" ", cleaned)
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


def _title_artist_evidence(
    *,
    filename_title: str | None,
    tag_title: str | None,
) -> TitleArtistEvidence | None:
    for source, value in (
        ("filename_title", filename_title),
        ("tag_title", tag_title),
    ):
        evidence = _extract_title_artist(value, source=source)
        if evidence:
            return evidence
    return None


def _extract_title_artist(
    value: str | None, *, source: str
) -> TitleArtistEvidence | None:
    if value is None:
        return None

    normalized_value = _normalize_punctuation(value).strip()
    if not normalized_value:
        return None

    seed_prefix_evidence = _extract_seed_prefix_title_artist(
        normalized_value, source=source
    )
    if seed_prefix_evidence:
        return seed_prefix_evidence

    whitespace_evidence = _extract_whitespace_title_artist(
        normalized_value, source=source
    )
    if whitespace_evidence:
        return whitespace_evidence

    separator_match = TITLE_ARTIST_SEPARATORS.search(normalized_value)
    if separator_match is None:
        return None

    left = normalized_value[: separator_match.start()].strip()
    right = normalized_value[separator_match.end() :].strip()
    if not left or not right:
        return None

    left_seed = _primary_seed_from_artist_phrase(left)
    if left_seed:
        cleaned_title = _clean_title(right, probable_artist=left_seed.artist)
        if cleaned_title:
            return TitleArtistEvidence(
                artist=left_seed.artist,
                title=cleaned_title,
                source=source,
            )

    right_seed = match_seed_artist(_strip_title_noise(right))
    if right_seed:
        cleaned_title = _clean_title(left, probable_artist=right_seed.artist)
        if cleaned_title:
            return TitleArtistEvidence(
                artist=right_seed.artist,
                title=cleaned_title,
                source=source,
            )

    return None


def _extract_seed_prefix_title_artist(
    value: str, *, source: str
) -> TitleArtistEvidence | None:
    for candidate in _source_stripped_title_candidates(value):
        for seed in sorted(
            list_seed_artists(),
            key=lambda item: len(normalize_artist_name(item.artist)),
            reverse=True,
        ):
            match = re.match(
                rf"^\s*{re.escape(seed.artist)}(?P<after>(?:\W|_).*)$",
                candidate,
                re.IGNORECASE,
            )
            if not match:
                continue
            title = _title_after_seed_artist_prefix(match.group("after"))
            if not title:
                continue
            cleaned_title = _clean_title(title, probable_artist=seed.artist)
            if cleaned_title:
                return TitleArtistEvidence(
                    artist=seed.artist,
                    title=cleaned_title,
                    source=source,
                )
    return None


def _source_stripped_title_candidates(value: str) -> list[str]:
    candidates = [value]
    slash_parts = [part.strip() for part in re.split(r"\s*/\s*", value) if part.strip()]
    if len(slash_parts) < 2:
        return candidates

    for index in range(1, len(slash_parts)):
        source_parts = slash_parts[:index]
        if all(_is_known_label_uploader_name(part) for part in source_parts):
            candidates.append(" / ".join(slash_parts[index:]))
    return candidates


def _title_after_seed_artist_prefix(value: str) -> str | None:
    after = value.strip()
    if not after:
        return None

    direct_separator = re.match(r"^(?:[-–—]\s+|:\s+)(?P<title>.+)$", after)
    if direct_separator:
        return direct_separator.group("title")

    separator_match = TITLE_ARTIST_SEPARATORS.search(after)
    if separator_match is None:
        return None
    return after[separator_match.end() :].strip() or None


def _extract_whitespace_title_artist(
    value: str, *, source: str
) -> TitleArtistEvidence | None:
    for seed in sorted(list_seed_artists(), key=lambda item: len(item.artist), reverse=True):
        match = re.match(
            rf"^\s*{re.escape(seed.artist)}\s{{2,}}(?P<title>.+)$",
            value,
            re.IGNORECASE,
        )
        if not match:
            continue
        cleaned_title = _clean_title(match.group("title"), probable_artist=seed.artist)
        if cleaned_title:
            return TitleArtistEvidence(
                artist=seed.artist,
                title=cleaned_title,
                source=source,
            )
    return None


def _primary_seed_from_artist_phrase(value: str):
    phrase = _strip_title_noise(value)
    seed = match_seed_artist(phrase)
    if seed:
        return seed

    first_feature = re.split(
        r"\s+(?:ft\.?|feat\.?|featuring)\s+", phrase, maxsplit=1, flags=re.IGNORECASE
    )[0]
    first_collaborator = re.split(
        r"\s*(?:&|\+|,|\bx\b)\s*",
        first_feature,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return match_seed_artist(first_collaborator)


def _strip_title_noise(value: str) -> str:
    stripped = _normalize_punctuation(value)
    for removal_pattern in TITLE_REMOVAL_PATTERNS:
        stripped = removal_pattern.sub(" ", stripped)
    return _clean(stripped) or ""


def _normalize_punctuation(value: str) -> str:
    return value.translate(FULL_WIDTH_PUNCTUATION)


def _remove_duplicate_artist_prefix(
    value: str, *, probable_artist: str | None
) -> str:
    if probable_artist is None:
        return value

    match = re.match(r"^\s*(?P<prefix>.+?)\s*[-–—]\s+(?P<title>.+)$", value)
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
    cleaned = re.sub(r"\s+", " ", _normalize_punctuation(value)).strip()
    return cleaned or None
