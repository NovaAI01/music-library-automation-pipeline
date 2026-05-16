"""Review-only album metadata discovery for Unknown Album tracks."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen import MutagenError

from app.album_organization import UNKNOWN_ALBUM, sanitize_path_component
from app.filename_parser import parse_filename
from app.scanner import is_supported_audio_file


DISCOVERY_DIRNAME = "album_discovery"
SUMMARY_FILENAME = "album_discovery_summary.json"
SUGGESTIONS_CSV_FILENAME = "album_discovery_suggestions.csv"
SUGGESTIONS_JSON_FILENAME = "album_discovery_suggestions.json"
CACHE_DIRNAME = "cache"
SUGGESTION_HEADERS: tuple[str, ...] = (
    "file_path",
    "artist",
    "title",
    "current_album",
    "suggested_album",
    "release_year",
    "confidence",
    "confidence_reason",
    "source",
    "source_url",
    "requires_human_review",
)

UNKNOWN_ALBUM_VALUES = {
    "",
    "unknown",
    "unknown album",
    "n/a",
    "na",
    "none",
    "null",
}
_DUPLICATE_WHITESPACE_RE = re.compile(r"\s+")
_ALBUM_TRACK_TITLE_RE = re.compile(
    r"^(?P<album>.+?)\s+-\s+(?P<track>\d{1,3})\s+-\s+(?P<title>.+)$"
)
_ARTIST_ALBUM_TITLE_RE = re.compile(
    r"^(?P<artist>.+?)\s+-\s+(?P<album>.+?)\s+-\s+(?P<title>.+)$"
)


@dataclass(frozen=True)
class TrackEvidence:
    file_path: str
    absolute_path: Path
    artist: str
    title: str
    current_album: str
    filename_album: str | None


@dataclass(frozen=True)
class AlbumDiscoverySuggestion:
    file_path: str
    artist: str
    title: str
    current_album: str
    suggested_album: str
    release_year: str
    confidence: str
    confidence_reason: str
    source: str
    source_url: str
    requires_human_review: bool


@dataclass(frozen=True)
class AlbumDiscoveryResult:
    report_path: str
    total_tracks_checked: int
    unknown_album_tracks: int
    total_suggestions: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    network_lookup_used: bool
    cache_entries: int


def generate_album_discovery(
    *,
    library_root: str | Path,
    out_dir: str | Path = "reports",
) -> AlbumDiscoveryResult:
    """Generate review-only album suggestions for missing or Unknown Album tracks."""

    library_root_path = Path(library_root).expanduser()
    report_dir = Path(out_dir).expanduser() / DISCOVERY_DIRNAME
    cache_dir = report_dir / CACHE_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    tracks = [_track_evidence(path, library_root_path) for path in _audio_files(library_root_path)]
    unknown_tracks = [track for track in tracks if _is_unknown_album(track.current_album)]
    suggestions = [
        suggestion
        for track in unknown_tracks
        if (suggestion := _suggestion_for_track(track))
        is not None
    ]
    suggestions = sorted(suggestions, key=lambda row: (row.file_path, row.source, row.suggested_album))

    counts = Counter(suggestion.confidence for suggestion in suggestions)
    summary = {
        "library_root": str(library_root_path),
        "total_tracks_checked": len(tracks),
        "unknown_album_tracks": len(unknown_tracks),
        "total_suggestions": len(suggestions),
        "high_confidence_count": counts["high"],
        "medium_confidence_count": counts["medium"],
        "low_confidence_count": counts["low"],
        "network_lookup_used": False,
        "cache_entries": len(list(cache_dir.glob("*.json"))),
        "requires_human_review_count": sum(1 for suggestion in suggestions if suggestion.requires_human_review),
    }

    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_json(
        report_dir / SUGGESTIONS_JSON_FILENAME,
        {"suggestions": [asdict(suggestion) for suggestion in suggestions]},
    )
    _write_csv(report_dir / SUGGESTIONS_CSV_FILENAME, SUGGESTION_HEADERS, [asdict(suggestion) for suggestion in suggestions])

    return AlbumDiscoveryResult(
        report_path=str(report_dir),
        total_tracks_checked=summary["total_tracks_checked"],
        unknown_album_tracks=summary["unknown_album_tracks"],
        total_suggestions=summary["total_suggestions"],
        high_confidence_count=summary["high_confidence_count"],
        medium_confidence_count=summary["medium_confidence_count"],
        low_confidence_count=summary["low_confidence_count"],
        network_lookup_used=summary["network_lookup_used"],
        cache_entries=summary["cache_entries"],
    )


def _suggestion_for_track(
    track: TrackEvidence,
) -> AlbumDiscoverySuggestion | None:
    if track.filename_album:
        return AlbumDiscoverySuggestion(
            file_path=track.file_path,
            artist=track.artist,
            title=track.title,
            current_album=track.current_album,
            suggested_album=track.filename_album,
            release_year="",
            confidence="low",
            confidence_reason="Local filename evidence contains an album-like token; no external metadata was used.",
            source="local_filename",
            source_url="",
            requires_human_review=True,
        )
    return None


def _track_evidence(path: Path, library_root: Path) -> TrackEvidence:
    relative_path = path.relative_to(library_root).as_posix()
    relative = path.relative_to(library_root)
    tags = _read_audio_tags(path)
    filename = parse_filename(path.name)
    filename_album, filename_title = _album_and_title_from_filename(path.name)
    path_artist = _artist_from_path(relative)
    artist = _clean_text(tags.get("artist")) or path_artist or filename.possible_artist or ""
    title = _clean_text(tags.get("title")) or filename_title or filename.possible_title or Path(path.name).stem
    current_album = _clean_text(tags.get("album")) or _album_from_path(relative) or ""
    return TrackEvidence(
        file_path=relative_path,
        absolute_path=path,
        artist=artist,
        title=title,
        current_album=current_album,
        filename_album=filename_album,
    )


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


def _read_audio_tags(path: Path) -> dict[str, str | None]:
    try:
        audio = MutagenFile(path, easy=True)
    except (MutagenError, OSError):
        return {}
    if audio is None:
        return {}
    return {
        "artist": _first_tag(audio.get("artist")),
        "title": _first_tag(audio.get("title")),
        "album": _first_tag(audio.get("album")),
    }


def _first_tag(values: Any) -> str | None:
    if not values:
        return None
    if isinstance(values, (list, tuple)):
        return str(values[0]) if values else None
    return str(values)


def _album_and_title_from_filename(filename: str) -> tuple[str | None, str | None]:
    cleaned = _DUPLICATE_WHITESPACE_RE.sub(" ", Path(filename).stem.replace("_", " ")).strip()
    for pattern in (_ALBUM_TRACK_TITLE_RE, _ARTIST_ALBUM_TITLE_RE):
        match = pattern.match(cleaned)
        if match:
            return _clean_album_candidate(match.group("album")), _clean_text(match.group("title"))
    return None, None


def _artist_from_path(relative_path: Path) -> str | None:
    parts = relative_path.parts
    if len(parts) >= 3:
        if _is_unknown_album(parts[-2]) and len(parts) >= 4:
            return parts[-3]
        return parts[-2]
    return None


def _album_from_path(relative_path: Path) -> str | None:
    parts = relative_path.parts
    if len(parts) >= 2:
        return parts[-2]
    return None


def _clean_album_candidate(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned or _is_unknown_album(cleaned):
        return None
    return sanitize_path_component(cleaned)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _DUPLICATE_WHITESPACE_RE.sub(" ", str(value)).strip()
    return cleaned or None


def _is_unknown_album(value: str | None) -> bool:
    return (value or "").strip().casefold() in UNKNOWN_ALBUM_VALUES


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["requires_human_review"] = str(csv_row["requires_human_review"]).lower()
            writer.writerow(csv_row)
