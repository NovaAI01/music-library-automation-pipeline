"""Read-only album inference and organization planning."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from mutagen.flac import FLAC
from mutagen import MutagenError

from app.filename_parser import parse_filename
from app.scanner import is_supported_audio_file


UNKNOWN_ALBUM = "Unknown Album"
PLAN_DIRNAME = "album_organization_plan"
SUMMARY_FILENAME = "album_organization_summary.json"
PLAN_FILENAME = "album_organization_plan.csv"
PLAN_HEADERS: tuple[str, ...] = (
    "current_path",
    "proposed_path",
    "artist",
    "album",
    "title",
    "confidence",
    "reason",
    "requires_review",
)


@dataclass(frozen=True)
class AlbumInference:
    album: str
    confidence: str
    reason: str
    requires_review: bool


@dataclass(frozen=True)
class AlbumOrganizationResult:
    report_path: str
    total_files: int
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    requires_review: int
    unknown_album_count: int


def infer_album(
    *,
    album_tag: str | None = None,
    parent_folder: str | None = None,
    filename: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    path_parts: tuple[str, ...] = (),
) -> AlbumInference:
    """Infer an album name from local evidence only."""

    clean_tag = _clean_album(album_tag)
    if clean_tag:
        return AlbumInference(
            album=clean_tag,
            confidence="high",
            reason="album_tag_present",
            requires_review=False,
        )

    parent_candidate = _clean_album(parent_folder)
    if parent_candidate and _is_album_like_parent(
        parent_candidate,
        artist=artist,
        title=title,
        path_parts=path_parts,
    ):
        return AlbumInference(
            album=parent_candidate,
            confidence="medium",
            reason="album_like_parent_folder",
            requires_review=False,
        )

    filename_candidate = _album_from_filename_or_title(filename=filename, title=title)
    if filename_candidate:
        return AlbumInference(
            album=filename_candidate,
            confidence="medium",
            reason="filename_title_album_evidence",
            requires_review=False,
        )

    return AlbumInference(
        album=UNKNOWN_ALBUM,
        confidence="low",
        reason="fallback_unknown_album",
        requires_review=True,
    )


def generate_album_organization_plan(
    *,
    library_root: str | Path,
    out_dir: str | Path = "reports",
) -> AlbumOrganizationResult:
    """Write a read-only album organization plan for an existing library tree."""

    library_root_path = Path(library_root).expanduser()
    report_dir = Path(out_dir).expanduser() / PLAN_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    existing_proposals: set[str] = set()
    for path in _audio_files(library_root_path):
        row = _plan_row(path, library_root_path, existing_proposals)
        rows.append(row)

    counts = Counter(row["confidence"] for row in rows)
    unknown_album_count = sum(1 for row in rows if row["album"] == UNKNOWN_ALBUM)
    requires_review = sum(1 for row in rows if row["requires_review"])
    created_at = datetime.now(UTC).isoformat()
    summary = {
        "library_root": str(library_root_path),
        "total_files": len(rows),
        "high_confidence": counts["high"],
        "medium_confidence": counts["medium"],
        "low_confidence": counts["low"],
        "requires_review": requires_review,
        "unknown_album_count": unknown_album_count,
        "created_at": created_at,
        "plan_file": str(report_dir / PLAN_FILENAME),
    }

    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_csv(report_dir / PLAN_FILENAME, rows)

    return AlbumOrganizationResult(
        report_path=str(report_dir),
        total_files=len(rows),
        high_confidence=counts["high"],
        medium_confidence=counts["medium"],
        low_confidence=counts["low"],
        requires_review=requires_review,
        unknown_album_count=unknown_album_count,
    )


def read_album_plan_rows(reports_dir: str | Path) -> list[dict[str, str]]:
    path = Path(reports_dir).expanduser() / PLAN_DIRNAME / PLAN_FILENAME
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def read_album_plan_summary(reports_dir: str | Path) -> dict[str, Any]:
    path = Path(reports_dir).expanduser() / PLAN_DIRNAME / SUMMARY_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _plan_row(
    path: Path,
    library_root: Path,
    existing_proposals: set[str],
) -> dict[str, Any]:
    relative = path.relative_to(library_root)
    tags = _read_flac_tags(path) if path.suffix.casefold() == ".flac" else {}
    filename_observation = parse_filename(path.name)
    layout = _path_layout(relative, filename_observation.possible_artist)
    artist = (
        _clean_text(tags.get("artist"))
        or filename_observation.possible_artist
        or layout["artist"]
        or "_Unknown"
    )
    title = (
        _clean_text(tags.get("title"))
        or filename_observation.possible_title
        or path.stem
    )
    inference = infer_album(
        album_tag=tags.get("album"),
        parent_folder=layout["album_candidate"],
        filename=path.name,
        title=title,
        artist=artist,
        path_parts=relative.parts,
    )
    genre = layout["genre"] or "_Unknown"
    proposed_relative = build_album_relative_path(
        genre=genre,
        artist=artist,
        album=inference.album,
        filename=path.name,
    )
    proposed_relative = detect_planned_path_collision(
        proposed_relative,
        existing_proposals,
    )
    existing_proposals.add(proposed_relative)
    return {
        "current_path": str(path),
        "proposed_path": str(library_root / PurePosixPath(proposed_relative)),
        "artist": sanitize_path_component(artist),
        "album": inference.album,
        "title": title,
        "confidence": inference.confidence,
        "reason": inference.reason,
        "requires_review": inference.requires_review,
    }


def build_album_relative_path(
    *,
    genre: str,
    artist: str,
    album: str,
    filename: str,
) -> str:
    return PurePosixPath(
        sanitize_path_component(genre),
        sanitize_path_component(artist),
        sanitize_path_component(album),
        sanitize_path_component(filename),
    ).as_posix()


def sanitize_path_component(value: str | None) -> str:
    if value is None:
        return "_Unknown"
    cleaned = value.replace("\\", "/")
    cleaned = cleaned.replace("..", "")
    cleaned = cleaned.replace("/", " ")
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "_Unknown"


def detect_planned_path_collision(
    planned_relative_path: str, existing_paths: set[str]
) -> str:
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


def _audio_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
        and is_supported_audio_file(path)
    )


def _path_layout(relative_path: Path, filename_artist: str | None) -> dict[str, str]:
    parts = relative_path.parts
    genre = parts[0] if len(parts) >= 2 else ""
    artist = ""
    album_candidate = ""
    if len(parts) >= 5:
        artist = parts[2]
        album_candidate = parts[3]
    elif len(parts) >= 4:
        if filename_artist and _same_text(parts[1], filename_artist):
            artist = parts[1]
            album_candidate = parts[2]
        else:
            artist = parts[2]
            album_candidate = ""
    elif len(parts) >= 3:
        artist = parts[1]
    return {"genre": genre, "artist": artist, "album_candidate": album_candidate}


def _read_flac_tags(path: Path) -> dict[str, str | None]:
    try:
        tags = FLAC(path)
    except (MutagenError, OSError):
        return {}
    return {
        "album": _first_tag(tags.get("album")),
        "artist": _first_tag(tags.get("artist")),
        "title": _first_tag(tags.get("title")),
    }


def _first_tag(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def _clean_album(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    if cleaned.casefold() in {"unknown", "unknown album", "n/a", "na", "none"}:
        return None
    return sanitize_path_component(cleaned)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _is_album_like_parent(
    value: str,
    *,
    artist: str | None,
    title: str | None,
    path_parts: tuple[str, ...],
) -> bool:
    blocked = {
        "_unsorted",
        "unsorted",
        "various",
        "various artists",
        "unknown",
        "unknown artist",
    }
    normalized = value.casefold()
    if normalized in blocked:
        return False
    if artist and _same_text(value, artist):
        return False
    if title and _same_text(value, title):
        return False
    if path_parts and _same_text(value, path_parts[0]):
        return False
    return True


def _album_from_filename_or_title(
    *,
    filename: str | None,
    title: str | None,
) -> str | None:
    candidates = [Path(filename).stem if filename else "", title or ""]
    for candidate in candidates:
        cleaned = re.sub(r"\s+", " ", candidate).strip()
        match = re.match(r"^(?P<album>.+?)\s+-\s+\d{1,3}\s+-\s+.+$", cleaned)
        if match:
            return _clean_album(match.group("album"))
    return None


def _same_text(left: str, right: str) -> bool:
    return left.casefold().strip() == right.casefold().strip()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=PLAN_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
