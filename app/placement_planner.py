"""Deterministic placement planning for classified tracks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from app import db
from app.album_organization import UNKNOWN_ALBUM, infer_album


PLACEMENT_STATUSES: frozenset[str] = frozenset(
    {
        "planned",
        "needs_review",
        "blocked_unknown_identity",
        "blocked_unknown_classification",
        "conflict",
    }
)
ORGANIZED_ROOT = "OrganizedLibrary"
MUSIC_ROOT = "Music"
REVIEW_ROOT = "_Review"
UNRESOLVED_ROOT = "_Unresolved"
SINGLE_ARTIST_COMPILATION_TERMS: tuple[str, ...] = (
    "anthology",
    "best of",
    "collection",
    "compilation",
    "essential",
    "greatest hits",
)
FULL_ALBUM_SOURCE_TERMS: tuple[str, ...] = (
    "album stream",
    "full album",
    "full album hq",
    "full album stream",
)


@dataclass(frozen=True)
class PlacementPlan:
    observed_file_id: int
    scan_run_id: int
    source_path: str
    planned_relative_path: str | None
    planned_artist: str | None
    planned_album: str | None
    planned_title: str | None
    planned_primary_genre: str | None
    planned_subgenre: str | None
    placement_confidence: float
    placement_status: str
    reason: dict[str, Any]


@dataclass(frozen=True)
class PlacementSummary:
    total: int
    planned: int
    needs_review: int
    blocked_unknown_identity: int
    blocked_unknown_classification: int
    conflict: int


def sanitize_path_component(value: str | None) -> str:
    """Return a safe single path component with traversal stripped."""

    if value is None:
        return "_Unknown"

    cleaned = value.replace("\\", "/")
    cleaned = cleaned.replace("..", "")
    cleaned = cleaned.replace("/", " ")
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "_Unknown"


def build_planned_relative_path(
    *,
    primary_genre: str | None = None,
    subgenre: str | None = None,
    artist: str,
    album: str | None,
    title: str,
    extension: str,
    year: str | None = None,
    track_number: str | None = None,
    disc_number: str | None = None,
    album_artist: str | None = None,
) -> str:
    """Build the canonical organized relative placement path."""

    safe_artist = sanitize_path_component(artist)
    safe_title = sanitize_path_component(title)
    safe_extension = _sanitize_extension(extension)
    safe_album = sanitize_path_component(album) if album else None
    safe_year_album = _release_folder(year=year, release=safe_album)
    track_prefix = _track_prefix(track_number=track_number, disc_number=disc_number)
    release_type = _release_type(
        artist=artist,
        album=album,
        title=title,
        album_artist=album_artist,
    )

    if release_type == "various_artists_compilation":
        filename = f"{track_prefix}{safe_artist} - {safe_title}{safe_extension}"
        relative = PurePosixPath(
            ORGANIZED_ROOT,
            MUSIC_ROOT,
            "Compilations",
            "Various Artists",
            safe_year_album or "_Unknown",
            filename,
        )
    elif release_type == "single_artist_compilation":
        compilation_folder = _release_folder(
            year=year,
            release=f"{safe_artist} - {safe_album or UNKNOWN_ALBUM}",
        )
        filename = f"{track_prefix}{safe_title}{safe_extension}"
        relative = PurePosixPath(
            ORGANIZED_ROOT,
            MUSIC_ROOT,
            "Compilations",
            "Single Artist",
            compilation_folder,
            filename,
        )
    elif release_type == "single":
        single_name = _release_folder(year=year, release=safe_title)
        relative = PurePosixPath(
            ORGANIZED_ROOT,
            MUSIC_ROOT,
            "Artists",
            safe_artist,
            "Singles",
            f"{single_name}{safe_extension}",
        )
    else:
        bucket = {
            "ep": "EPs",
            "live": "Live",
        }.get(release_type, "Albums")
        filename = f"{track_prefix}{safe_title}{safe_extension}"
        relative = PurePosixPath(
            ORGANIZED_ROOT,
            MUSIC_ROOT,
            "Artists",
            safe_artist,
            bucket,
            safe_year_album or UNKNOWN_ALBUM,
            filename,
        )
    return relative.as_posix()


def build_governance_relative_path(
    *,
    zone: str,
    queue: str,
    original_relative_path: str | None,
    source_path: str | None,
    title: str | None,
    extension: str,
) -> str:
    """Build a review/unresolved path while preserving original path shape."""

    relative = _sanitize_original_relative_path(original_relative_path)
    if relative is None:
        relative = _fallback_relative_path(
            source_path=source_path,
            title=title,
            extension=extension,
        )
    return PurePosixPath(ORGANIZED_ROOT, zone, queue, relative).as_posix()


def detect_planned_path_collision(
    planned_relative_path: str, existing_paths: set[str]
) -> str:
    """Append numeric suffixes when a planned path already exists."""

    if planned_relative_path not in existing_paths:
        return planned_relative_path

    path = PurePosixPath(planned_relative_path)
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    for index in range(2, 10000):
        candidate = path.with_name(f"{stem} ({index}){suffix}").as_posix()
        if candidate not in existing_paths:
            return candidate

    raise ValueError(f"Could not resolve planned path collision: {planned_relative_path}")


def calculate_placement_confidence(
    *,
    identity_confidence: float | None,
    classification_confidence: float | None,
    placement_status: str,
) -> float:
    """Return deterministic placement confidence."""

    if placement_status in {
        "blocked_unknown_identity",
        "blocked_unknown_classification",
        "conflict",
    }:
        return 0.0
    if placement_status == "needs_review":
        return min(identity_confidence or 0.0, classification_confidence or 0.0, 0.5)
    if placement_status == "planned":
        return min(identity_confidence or 0.0, classification_confidence or 0.0)
    raise ValueError(f"Unknown placement_status: {placement_status}")


def create_placement_plan(
    *,
    observed_file_id: int,
    scan_run_id: int,
    source_path: str,
    extension: str,
    identity_status: str | None,
    identity_confidence: float | None,
    probable_artist: str | None,
    probable_title: str | None,
    original_relative_path: str | None = None,
    probable_album: str | None = None,
    probable_year: str | None = None,
    tag_album: str | None = None,
    tag_album_artist: str | None = None,
    tag_track_number: str | None = None,
    tag_disc_number: str | None = None,
    filename_track_number: str | None = None,
    parent_folder: str | None = None,
    filename: str | None = None,
    classification_status: str | None,
    classification_confidence: float | None,
    primary_genre: str | None,
    subgenre: str | None,
    existing_paths: set[str] | None = None,
) -> PlacementPlan:
    """Create one deterministic placement plan from joined ledger evidence."""

    existing_paths = existing_paths if existing_paths is not None else set()
    reasons: list[str] = []

    if identity_status == "conflicting":
        status = "conflict"
        reasons.append("identity_conflicting")
    elif identity_status == "unknown" or not probable_artist or not probable_title:
        status = "blocked_unknown_identity"
        reasons.append("identity_unknown")
    elif classification_status == "unknown" or not primary_genre:
        status = "blocked_unknown_classification"
        reasons.append("classification_unknown")
    elif classification_status == "uncertain":
        status = "needs_review"
        reasons.append("classification_uncertain")
    else:
        status = "planned"

    planned_relative_path = None
    planned_subgenre = subgenre or "_Unsorted" if primary_genre else None
    album_inference = infer_album(
        album_tag=tag_album,
        parent_folder=parent_folder,
        filename=filename,
        title=probable_title,
        artist=probable_artist,
    )
    if album_inference.requires_review and probable_album:
        album_inference = infer_album(
            album_tag=None,
            parent_folder=probable_album,
            filename=filename,
            title=probable_title,
            artist=probable_artist,
        )
    track_number = (
        tag_track_number or filename_track_number or _track_number_from_filename(filename)
    )
    planned_album = _planned_album_value(
        album=album_inference.album,
        tag_album=tag_album,
        probable_album=probable_album,
        parent_folder=parent_folder,
    )
    if status == "planned" and _is_unsplit_full_album_source(
        title=probable_title,
        album=planned_album,
        parent_folder=parent_folder,
        filename=filename,
        original_relative_path=original_relative_path,
        track_number=track_number,
    ):
        status = "needs_review"
        reasons.append("unsplit_full_album")

    if status == "planned":
        planned_relative_path = build_planned_relative_path(
            artist=probable_artist or "_Unknown",
            album=planned_album,
            title=probable_title or "_Unknown",
            extension=extension,
            year=probable_year,
            track_number=track_number,
            disc_number=tag_disc_number,
            album_artist=tag_album_artist,
        )
    elif status in {"blocked_unknown_identity", "conflict"}:
        queue = "identity"
        zone = REVIEW_ROOT
        if _has_no_usable_identity_title_or_path(
            probable_artist=probable_artist,
            probable_title=probable_title,
            original_relative_path=original_relative_path,
            source_path=source_path,
        ):
            zone = UNRESOLVED_ROOT
            queue = "unknown"
        planned_relative_path = build_governance_relative_path(
            zone=zone,
            queue=queue,
            original_relative_path=original_relative_path,
            source_path=source_path,
            title=probable_title,
            extension=extension,
        )
    elif status == "blocked_unknown_classification":
        planned_relative_path = build_governance_relative_path(
            zone=REVIEW_ROOT,
            queue="classification",
            original_relative_path=original_relative_path,
            source_path=source_path,
            title=probable_title,
            extension=extension,
        )
    elif status == "needs_review":
        queue = "placement" if "unsplit_full_album" in reasons else "classification"
        planned_relative_path = build_governance_relative_path(
            zone=REVIEW_ROOT,
            queue=queue,
            original_relative_path=original_relative_path,
            source_path=source_path,
            title=probable_title,
            extension=extension,
        )

    if planned_relative_path:
        planned_relative_path = detect_planned_path_collision(
            planned_relative_path, existing_paths
        )
        existing_paths.add(planned_relative_path)

    confidence = calculate_placement_confidence(
        identity_confidence=identity_confidence,
        classification_confidence=classification_confidence,
        placement_status=status,
    )
    reason = {
        "identity_status": identity_status,
        "classification_status": classification_status,
        "album_confidence": album_inference.confidence,
        "album_reason": album_inference.reason,
        "reasons": reasons,
    }
    return PlacementPlan(
        observed_file_id=observed_file_id,
        scan_run_id=scan_run_id,
        source_path=source_path,
        planned_relative_path=planned_relative_path,
        planned_artist=probable_artist,
        planned_album=(
            planned_album if status in {"planned", "needs_review"} else None
        ),
        planned_title=probable_title,
        planned_primary_genre=primary_genre,
        planned_subgenre=planned_subgenre,
        placement_confidence=confidence,
        placement_status=status,
        reason=reason,
    )


def plan_scan_run_placements(
    scan_run_id: int, db_path: str = db.DEFAULT_DB_PATH
) -> PlacementSummary:
    """Create placement plans for all observed files in a scan run."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                observed_files.id AS observed_file_id,
                observed_files.scan_run_id,
                observed_files.source_path,
                observed_files.relative_path,
                observed_files.extension,
                observed_files.parent_folder,
                observed_files.filename,
                track_identity.probable_artist,
                track_identity.probable_album,
                track_identity.probable_title,
                track_identity.probable_year,
                track_identity.identity_confidence,
                track_identity.identity_status,
                classification_results.primary_genre,
                classification_results.subgenre,
                classification_results.classification_confidence,
                classification_results.classification_status,
                tag_observations.album AS tag_album,
                tag_observations.album_artist AS tag_album_artist,
                tag_observations.track_number AS tag_track_number,
                tag_observations.disc_number AS tag_disc_number,
                filename_observations.possible_track_number AS filename_track_number
            FROM observed_files
            LEFT JOIN track_identity
                ON track_identity.observed_file_id = observed_files.id
            LEFT JOIN classification_results
                ON classification_results.observed_file_id = observed_files.id
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
                DELETE FROM placement_plans
                WHERE scan_run_id = ?
                    AND observed_file_id IN ({placeholders})
                """,
                [scan_run_id, *observed_file_ids],
            )

        counts = {
            "planned": 0,
            "needs_review": 0,
            "blocked_unknown_identity": 0,
            "blocked_unknown_classification": 0,
            "conflict": 0,
        }
        existing_paths: set[str] = set()
        for row in rows:
            source_path = _source_file_path(row["source_path"], row["relative_path"])
            plan = create_placement_plan(
                observed_file_id=row["observed_file_id"],
                scan_run_id=row["scan_run_id"],
                source_path=source_path,
                original_relative_path=row["relative_path"],
                extension=row["extension"],
                identity_status=row["identity_status"],
                identity_confidence=row["identity_confidence"],
                probable_artist=row["probable_artist"],
                probable_album=row["probable_album"],
                probable_title=row["probable_title"],
                probable_year=row["probable_year"],
                tag_album=row["tag_album"],
                tag_album_artist=row["tag_album_artist"],
                tag_track_number=row["tag_track_number"],
                tag_disc_number=row["tag_disc_number"],
                filename_track_number=row["filename_track_number"],
                parent_folder=row["parent_folder"],
                filename=row["filename"],
                classification_status=row["classification_status"],
                classification_confidence=row["classification_confidence"],
                primary_genre=row["primary_genre"],
                subgenre=row["subgenre"],
                existing_paths=existing_paths,
            )
            _insert_placement_plan(connection, plan)
            counts[plan.placement_status] += 1

    return PlacementSummary(
        total=len(rows),
        planned=counts["planned"],
        needs_review=counts["needs_review"],
        blocked_unknown_identity=counts["blocked_unknown_identity"],
        blocked_unknown_classification=counts["blocked_unknown_classification"],
        conflict=counts["conflict"],
    )


def _insert_placement_plan(connection, plan: PlacementPlan) -> None:
    connection.execute(
        """
        INSERT INTO placement_plans (
            observed_file_id,
            scan_run_id,
            source_path,
            planned_relative_path,
            planned_artist,
            planned_album,
            planned_title,
            planned_primary_genre,
            planned_subgenre,
            placement_confidence,
            placement_status,
            reason_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan.observed_file_id,
            plan.scan_run_id,
            plan.source_path,
            plan.planned_relative_path,
            plan.planned_artist,
            plan.planned_album,
            plan.planned_title,
            plan.planned_primary_genre,
            plan.planned_subgenre,
            plan.placement_confidence,
            plan.placement_status,
            json.dumps(plan.reason, sort_keys=True),
            datetime.now(UTC).isoformat(),
        ),
    )


def _source_file_path(source_path: str, relative_path: str) -> str:
    return str(PurePosixPath(source_path) / relative_path)


def _release_type(
    *,
    artist: str,
    album: str | None,
    title: str,
    album_artist: str | None,
) -> str:
    normalized_album_artist = _normalize_text(album_artist)
    normalized_album = _normalize_text(album)
    normalized_title = _normalize_text(title)

    if normalized_album_artist in {"various artists", "various"}:
        return "various_artists_compilation"
    if album and any(term in normalized_album for term in SINGLE_ARTIST_COMPILATION_TERMS):
        return "single_artist_compilation"
    if album and "live" in normalized_album:
        return "live"
    if " live " in f" {normalized_title} ":
        return "live"
    if album and re.search(r"(?:^|\W)ep(?:$|\W)", normalized_album):
        return "ep"
    if not album:
        return "single"
    return "album"


def _planned_album_value(
    *,
    album: str,
    tag_album: str | None,
    probable_album: str | None,
    parent_folder: str | None,
) -> str | None:
    if album == UNKNOWN_ALBUM and not any(
        _has_text(value) for value in (tag_album, probable_album, parent_folder)
    ):
        return None
    return album


def _is_unsplit_full_album_source(
    *,
    title: str | None,
    album: str | None,
    parent_folder: str | None,
    filename: str | None,
    original_relative_path: str | None,
    track_number: str | None,
) -> bool:
    if _number_value(track_number):
        return False

    title_key = _album_source_key(title)
    album_key = _album_source_key(album)
    evidence_values = (title, album, parent_folder, filename, original_relative_path)
    if not any(_has_full_album_source_signal(value) for value in evidence_values):
        return False

    if title_key and album_key and (
        title_key == album_key
        or title_key.startswith(album_key)
        or album_key.startswith(title_key)
    ):
        return True

    for value in (parent_folder, filename, original_relative_path):
        value_key = _album_source_key(value)
        if title_key and value_key and title_key in value_key:
            return True
        if album_key and value_key and album_key in value_key:
            return True
    return False


def _has_full_album_source_signal(value: str | None) -> bool:
    normalized = _normalize_text(value)
    return any(term in normalized for term in FULL_ALBUM_SOURCE_TERMS)


def _album_source_key(value: str | None) -> str:
    normalized = _normalize_text(value)
    for term in FULL_ALBUM_SOURCE_TERMS:
        normalized = normalized.replace(term, " ")
    normalized = re.sub(r"\bhq\b", " ", normalized)
    normalized = re.sub(r"\bfull\b|\balbum\b|\bstream\b", " ", normalized)
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _release_folder(*, year: str | None, release: str | None) -> str | None:
    safe_release = sanitize_path_component(release) if release else None
    safe_year = _year_value(year)
    if not safe_release:
        return None
    if safe_year:
        return f"[{safe_year}] {safe_release}"
    return safe_release


def _track_prefix(*, track_number: str | None, disc_number: str | None) -> str:
    track = _number_value(track_number)
    if not track:
        return ""
    disc = _number_value(disc_number)
    if disc and disc != "1":
        return f"{disc}-{track} - "
    return f"{track} - "


def _number_value(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    return f"{int(match.group(0)):02d}"


def _track_number_from_filename(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.match(
        r"^\s*(?:track\s+)?(?P<track>\d{1,3})(?:\D|$)",
        value,
        re.IGNORECASE,
    )
    return _number_value(match.group("track")) if match else None


def _year_value(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value))
    return match.group(1) if match else None


def _sanitize_original_relative_path(value: str | None) -> PurePosixPath | None:
    if not value:
        return None
    parts = [
        sanitize_path_component(part)
        for part in re.split(r"[\\/]", value)
        if part and part not in {".", ".."}
    ]
    if not parts:
        return None
    return PurePosixPath(*parts)


def _fallback_relative_path(
    *,
    source_path: str | None,
    title: str | None,
    extension: str,
) -> PurePosixPath:
    source_name = PurePosixPath(str(source_path)).name if source_path else ""
    safe_source_name = sanitize_path_component(source_name) if source_name else None
    if safe_source_name and safe_source_name != "_Unknown":
        return PurePosixPath(safe_source_name)

    safe_title = sanitize_path_component(title)
    return PurePosixPath(f"{safe_title}{_sanitize_extension(extension)}")


def _has_no_usable_identity_title_or_path(
    *,
    probable_artist: str | None,
    probable_title: str | None,
    original_relative_path: str | None,
    source_path: str | None,
) -> bool:
    return not any(
        _has_text(value)
        for value in (
            probable_artist,
            probable_title,
            original_relative_path,
            source_path,
        )
    )


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _has_text(value: str | None) -> bool:
    return bool(value and str(value).strip())


def _sanitize_extension(extension: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9.]", "", extension.strip())
    if not cleaned:
        return ""
    if not cleaned.startswith("."):
        cleaned = f".{cleaned}"
    return cleaned.lower()
