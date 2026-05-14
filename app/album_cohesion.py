"""Repeated-evidence album cohesion reports.

The engine is intentionally read-only: it observes local files, tags, filenames,
and placement patterns, then writes review reports without changing audio files.
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

from mutagen import MutagenError
from mutagen.flac import FLAC

from app.album_organization import sanitize_path_component
from app.evidence_reliability import score_evidence
from app.filename_parser import parse_filename
from app.scanner import is_supported_audio_file


REPORT_DIRNAME = "album_cohesion"
SUMMARY_FILENAME = "album_cohesion_summary.json"
GROUPS_JSON_FILENAME = "album_groups.json"
GROUPS_CSV_FILENAME = "album_groups.csv"
CONFLICTS_CSV_FILENAME = "album_conflicts.csv"
ORPHANS_CSV_FILENAME = "orphan_tracks.csv"
UNKNOWN_ALBUM = "Unknown Album"

GROUP_HEADERS: tuple[str, ...] = (
    "group_key",
    "album",
    "artist",
    "track_count",
    "cohesion_score",
    "confidence_tier",
    "classification",
    "rationale",
    "source_folders",
    "album_tags",
    "years",
    "file_paths",
)
CONFLICT_HEADERS: tuple[str, ...] = (
    "group_key",
    "album",
    "artist",
    "conflict_type",
    "details",
    "file_paths",
)
ORPHAN_HEADERS: tuple[str, ...] = (
    "file_path",
    "artist",
    "title",
    "source_folder",
    "reason",
)


@dataclass(frozen=True)
class AlbumCohesionTrack:
    file_path: str
    artist: str
    title: str
    album_tag: str
    track_number: int | None
    year: str
    source_folder: str
    album_folder: str
    filename_album: str
    filename_artist: str
    filename_title: str


@dataclass(frozen=True)
class AlbumCohesionGroup:
    group_key: str
    album: str
    artist: str
    track_count: int
    cohesion_score: float
    confidence_tier: str
    classification: str
    rationale: list[str]
    source_folders: list[str]
    album_tags: list[str]
    years: list[str]
    tracks: list[dict[str, Any]]


@dataclass(frozen=True)
class AlbumCohesionResult:
    report_path: str
    total_album_groups: int
    high_confidence_groups: int
    medium_confidence_groups: int
    low_confidence_groups: int
    probable_singles: int
    orphan_tracks: int
    conflicting_album_groups: int


def generate_album_cohesion_report(
    *,
    out_dir: str | Path = "reports",
    library_root: str | Path | None = None,
) -> AlbumCohesionResult:
    """Generate read-only album grouping and conflict reports."""

    out_path = Path(out_dir).expanduser()
    report_dir = out_path / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)

    tracks = collect_album_cohesion_tracks(
        reports_dir=out_path,
        library_root=Path(library_root).expanduser() if library_root else None,
    )
    groups, conflicts, orphan_tracks = infer_album_cohesion(tracks)
    summary = album_cohesion_summary(groups, conflicts, orphan_tracks)
    summary["created_at"] = datetime.now(UTC).isoformat()
    summary["report_file"] = str(report_dir / GROUPS_JSON_FILENAME)

    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_json(
        report_dir / GROUPS_JSON_FILENAME,
        {
            "groups": [asdict(group) for group in groups],
            "conflicts": conflicts,
            "orphan_tracks": [asdict(track) for track in orphan_tracks],
        },
    )
    _write_csv(report_dir / GROUPS_CSV_FILENAME, GROUP_HEADERS, _group_csv_rows(groups))
    _write_csv(report_dir / CONFLICTS_CSV_FILENAME, CONFLICT_HEADERS, conflicts)
    _write_csv(
        report_dir / ORPHANS_CSV_FILENAME,
        ORPHAN_HEADERS,
        (_orphan_csv_row(track) for track in orphan_tracks),
    )

    return AlbumCohesionResult(report_path=str(report_dir), **summary_without_metadata(summary))


def collect_album_cohesion_tracks(
    *,
    reports_dir: str | Path = "reports",
    library_root: Path | None = None,
) -> list[AlbumCohesionTrack]:
    if library_root is not None:
        paths = _audio_files(library_root)
    else:
        paths = _paths_from_file_health(Path(reports_dir).expanduser())
    return [_track_from_path(path, library_root) for path in paths]


def infer_album_cohesion(
    tracks: Iterable[AlbumCohesionTrack],
) -> tuple[list[AlbumCohesionGroup], list[dict[str, str]], list[AlbumCohesionTrack]]:
    track_list = list(tracks)
    album_tag_counts = Counter(_norm(track.album_tag) for track in track_list if track.album_tag)
    folder_counts = Counter(_norm(track.album_folder) for track in track_list if track.album_folder)
    filename_album_counts = Counter(_norm(track.filename_album) for track in track_list if track.filename_album)

    grouped: defaultdict[tuple[str, str], list[AlbumCohesionTrack]] = defaultdict(list)
    orphan_tracks: list[AlbumCohesionTrack] = []
    for track in track_list:
        album = _candidate_album(
            track,
            album_tag_counts=album_tag_counts,
            folder_counts=folder_counts,
            filename_album_counts=filename_album_counts,
        )
        if not album:
            orphan_tracks.append(track)
            continue
        artist_key = _artist_group_key(track)
        grouped[(artist_key, _norm(album))].append(track)

    groups: list[AlbumCohesionGroup] = []
    conflicts: list[dict[str, str]] = []
    for (artist_key, album_key), members in grouped.items():
        group = _build_group(artist_key, album_key, members)
        groups.append(group)
        conflicts.extend(_conflicts_for_group(group, members))

    groups = sorted(
        groups,
        key=lambda group: (
            group.classification != "album",
            -group.cohesion_score,
            group.artist.casefold(),
            group.album.casefold(),
        ),
    )
    orphan_tracks = sorted(orphan_tracks, key=lambda track: track.file_path.casefold())
    return groups, conflicts, orphan_tracks


def album_cohesion_summary(
    groups: list[AlbumCohesionGroup],
    conflicts: list[dict[str, str]],
    orphan_tracks: list[AlbumCohesionTrack],
) -> dict[str, int]:
    counts = Counter(group.confidence_tier for group in groups)
    conflict_group_keys = {row["group_key"] for row in conflicts}
    return {
        "total_album_groups": len(groups),
        "high_confidence_groups": counts["high"],
        "medium_confidence_groups": counts["medium"],
        "low_confidence_groups": counts["low"],
        "probable_singles": sum(1 for group in groups if group.classification == "single"),
        "orphan_tracks": len(orphan_tracks),
        "conflicting_album_groups": len(conflict_group_keys),
    }


def summary_without_metadata(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "total_album_groups": int(summary["total_album_groups"]),
        "high_confidence_groups": int(summary["high_confidence_groups"]),
        "medium_confidence_groups": int(summary["medium_confidence_groups"]),
        "low_confidence_groups": int(summary["low_confidence_groups"]),
        "probable_singles": int(summary["probable_singles"]),
        "orphan_tracks": int(summary["orphan_tracks"]),
        "conflicting_album_groups": int(summary["conflicting_album_groups"]),
    }


def read_album_cohesion_report(reports_dir: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]], list[str]]:
    report_dir = Path(reports_dir).expanduser() / REPORT_DIRNAME
    summary, missing_summary = _read_json(report_dir / SUMMARY_FILENAME)
    groups_payload, missing_groups = _read_json(report_dir / GROUPS_JSON_FILENAME)
    conflicts, missing_conflicts = _read_csv(report_dir / CONFLICTS_CSV_FILENAME)
    orphans, missing_orphans = _read_csv(report_dir / ORPHANS_CSV_FILENAME)
    groups = groups_payload.get("groups", []) if isinstance(groups_payload, dict) else []
    if not isinstance(groups, list):
        groups = []
    return (
        summary,
        [group for group in groups if isinstance(group, dict)],
        conflicts,
        orphans,
        [
            label
            for label in (missing_summary, missing_groups, missing_conflicts, missing_orphans)
            if label
        ],
    )


def album_cohesion_by_file(reports_dir: str | Path) -> dict[str, dict[str, Any]]:
    _, groups, _, _, _ = read_album_cohesion_report(reports_dir)
    lookup: dict[str, dict[str, Any]] = {}
    for group in groups:
        for track in group.get("tracks", []):
            if not isinstance(track, dict):
                continue
            file_path = str(track.get("file_path", ""))
            if file_path:
                lookup[file_path] = group
    return lookup


def _candidate_album(
    track: AlbumCohesionTrack,
    *,
    album_tag_counts: Counter[str],
    folder_counts: Counter[str],
    filename_album_counts: Counter[str],
) -> str:
    album_tag = _clean_album(track.album_tag)
    folder = _clean_album(track.album_folder)
    filename_album = _clean_album(track.filename_album)
    reliable_tag = (
        album_tag
        if score_evidence(album_tag, field="album", folder_value=track.album_folder).reliability_tier != "low"
        else ""
    )
    if album_tag and album_tag_counts[_norm(album_tag)] >= 2:
        return album_tag
    if reliable_tag and folder and _same(reliable_tag, folder):
        return album_tag
    if folder and folder_counts[_norm(folder)] >= 2:
        return folder
    if filename_album and filename_album_counts[_norm(filename_album)] >= 2:
        return filename_album
    if album_tag and track.track_number is not None:
        return album_tag
    if album_tag:
        return album_tag
    return ""


def _build_group(
    artist_key: str,
    album_key: str,
    members: list[AlbumCohesionTrack],
) -> AlbumCohesionGroup:
    album = _display_consensus([track.album_tag for track in members]) or _display_consensus(
        [track.album_folder for track in members]
    ) or _display_consensus([track.filename_album for track in members]) or UNKNOWN_ALBUM
    artist = _display_consensus([track.artist for track in members]) or artist_key or "Unknown Artist"
    album_tags = sorted({track.album_tag for track in members if track.album_tag}, key=str.casefold)
    folders = sorted({track.source_folder for track in members if track.source_folder}, key=str.casefold)
    years = sorted({track.year for track in members if track.year})
    score, rationale = _score_group(members, album=album, artist=artist)
    classification = _classification(members, rationale, album_tags)
    if classification == "single":
        score = min(score, 0.64)
    confidence = _confidence_tier(score)
    group_key = f"{_slug(artist)}:{_slug(album_key)}"
    return AlbumCohesionGroup(
        group_key=group_key,
        album=album,
        artist=artist,
        track_count=len(members),
        cohesion_score=round(score, 3),
        confidence_tier=confidence,
        classification=classification,
        rationale=rationale,
        source_folders=folders,
        album_tags=album_tags,
        years=years,
        tracks=[asdict(track) for track in sorted(members, key=_track_sort_key)],
    )


def _score_group(
    members: list[AlbumCohesionTrack],
    *,
    album: str,
    artist: str,
) -> tuple[float, list[str]]:
    score = 0.0
    rationale: list[str] = []
    album_tag_values = {track.album_tag for track in members if track.album_tag}
    folder_values = {track.album_folder for track in members if track.album_folder}
    year_values = {track.year for track in members if track.year}
    normalized_artists = {_norm(track.artist) for track in members if track.artist}
    track_numbers = sorted({track.track_number for track in members if track.track_number is not None})

    if len(members) >= 2:
        score += 0.16
        rationale.append("repeated track co-occurrence")
    if len(members) >= 2 and any(_same(value, album) for value in folder_values):
        score += 0.20
        rationale.append("repeated album folder structure")
    if len(members) >= 2 and album_tag_values and len({_norm(value) for value in album_tag_values}) == 1:
        score += 0.18
        rationale.append("consistent album tag repetition")
    if len(track_numbers) >= 2 and _has_sequential_numbers(track_numbers):
        score += 0.22
        rationale.append("sequential track numbering")
    if year_values and len(year_values) == 1 and len(members) >= 2:
        score += 0.10
        rationale.append("shared release year")
    if len(normalized_artists) == 1 and artist:
        score += 0.10
        rationale.append("consistent artist normalization")
    if _filename_similarity(members) >= 0.65 and len(members) >= 2:
        score += 0.08
        rationale.append("filename similarity")
    if len({_norm(value) for value in album_tag_values}) > 1:
        score -= 0.24
        rationale.append("conflicting album tags detected")
    if len(normalized_artists) > 2:
        score -= 0.10
        rationale.append("probable compilation mix")
    album_reliability = score_evidence(album, field="album", repeated_count=len(members))
    artist_reliability = score_evidence(artist, field="artist", repeated_count=len(members))
    low_track_reliability = [
        score_evidence(track.album_tag, field="album", folder_value=track.album_folder)
        for track in members
        if track.album_tag
    ]
    if album_reliability.reliability_tier == "low":
        score -= 0.18
        rationale.append("polluted album-name evidence down-ranked")
    elif album_reliability.reliability_tier == "high":
        score += 0.05
        rationale.append("reliable album-name evidence")
    if artist_reliability.reliability_tier == "low":
        score -= 0.10
        rationale.append("unreliable artist evidence down-ranked")
    if any(item.reliability_tier == "low" for item in low_track_reliability):
        score -= 0.10
        rationale.append("low-reliability uploader artifacts ignored where possible")

    if not rationale:
        rationale.append("limited album evidence")
    return max(0.0, min(1.0, score)), rationale


def _classification(
    members: list[AlbumCohesionTrack],
    rationale: list[str],
    album_tags: list[str],
) -> str:
    if len({_norm(track.artist) for track in members if track.artist}) > 2:
        return "compilation_mix"
    if any(_norm(track.artist) in {"various artists", "various"} for track in members):
        return "compilation_mix"
    if "conflicting album tags detected" in rationale or len({_norm(tag) for tag in album_tags}) > 1:
        return "conflict"
    if len(members) == 1:
        track = members[0]
        if track.album_tag or track.album_folder:
            return "single"
        return "orphan"
    return "album"


def _conflicts_for_group(
    group: AlbumCohesionGroup,
    members: list[AlbumCohesionTrack],
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    tag_values = sorted({track.album_tag for track in members if track.album_tag}, key=str.casefold)
    if len({_norm(value) for value in tag_values}) > 1:
        conflicts.append(
            {
                "group_key": group.group_key,
                "album": group.album,
                "artist": group.artist,
                "conflict_type": "conflicting_album_tags",
                "details": " | ".join(tag_values),
                "file_paths": " | ".join(track.file_path for track in members),
            }
        )
    folder_to_tags: defaultdict[str, set[str]] = defaultdict(set)
    for track in members:
        if track.source_folder and track.album_tag:
            folder_to_tags[track.source_folder].add(track.album_tag)
    for folder, tags in folder_to_tags.items():
        if len({_norm(tag) for tag in tags}) > 1:
            conflicts.append(
                {
                    "group_key": group.group_key,
                    "album": group.album,
                    "artist": group.artist,
                    "conflict_type": "folder_contains_conflicting_album_tags",
                    "details": f"{folder}: {' | '.join(sorted(tags, key=str.casefold))}",
                    "file_paths": " | ".join(track.file_path for track in members if track.source_folder == folder),
                }
            )
    return conflicts


def _track_from_path(path: Path, library_root: Path | None) -> AlbumCohesionTrack:
    tags = _read_flac_tags(path) if path.suffix.casefold() == ".flac" else {}
    parsed = parse_filename(path.name)
    relative_parts = _relative_parts(path, library_root)
    folder = str(path.parent)
    return AlbumCohesionTrack(
        file_path=str(path),
        artist=_clean_text(tags.get("artist")) or parsed.possible_artist or _artist_from_parts(relative_parts),
        title=_clean_text(tags.get("title")) or parsed.possible_title or path.stem,
        album_tag=_clean_album(tags.get("album")) or "",
        track_number=_track_number(tags.get("tracknumber")) or _track_number_from_filename(path.name),
        year=_year(tags.get("date") or tags.get("year")),
        source_folder=folder,
        album_folder=_album_folder_from_parts(relative_parts),
        filename_album=_filename_album(path.name),
        filename_artist=parsed.possible_artist or "",
        filename_title=parsed.possible_title or path.stem,
    )


def _read_flac_tags(path: Path) -> dict[str, str | None]:
    try:
        tags = FLAC(path)
    except (MutagenError, OSError):
        return {}
    return {
        "artist": _first_tag(tags.get("artist")),
        "album": _first_tag(tags.get("album")),
        "title": _first_tag(tags.get("title")),
        "tracknumber": _first_tag(tags.get("tracknumber")),
        "date": _first_tag(tags.get("date")),
        "year": _first_tag(tags.get("year")),
    }


def _paths_from_file_health(reports_dir: Path) -> list[Path]:
    rows = _read_csv_rows(reports_dir / "library_qa" / "file_health.csv")
    return sorted(
        Path(row.get("path", "")).expanduser()
        for row in rows
        if row.get("status") == "library_present" and row.get("path")
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


def _relative_parts(path: Path, library_root: Path | None) -> tuple[str, ...]:
    if library_root is not None:
        try:
            return path.relative_to(library_root).parts
        except ValueError:
            pass
    return path.parts


def _artist_from_parts(parts: tuple[str, ...]) -> str:
    if len(parts) >= 5:
        return parts[-3]
    if len(parts) >= 3:
        return parts[-2]
    return ""


def _album_folder_from_parts(parts: tuple[str, ...]) -> str:
    if len(parts) >= 5:
        return _clean_album(parts[-2]) or ""
    return ""


def _filename_album(filename: str) -> str:
    cleaned = re.sub(r"\s+", " ", Path(filename).stem).strip()
    match = re.match(r"^(?P<album>.+?)\s+-\s+\d{1,3}\s+-\s+.+$", cleaned)
    if match:
        return _clean_album(match.group("album")) or ""
    return ""


def _track_number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _track_number_from_filename(filename: str) -> int | None:
    match = re.match(r"^\s*(?:disc\s*\d+\s*)?(?P<num>\d{1,2})[\s._-]+", Path(filename).stem, re.IGNORECASE)
    if not match:
        match = re.match(r"^.+?\s+-\s+(?P<num>\d{1,3})\s+-\s+.+$", Path(filename).stem)
    return _track_number(match.group("num")) if match else None


def _year(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"(?:19|20)\d{2}", str(value))
    return match.group(0) if match else ""


def _filename_similarity(members: list[AlbumCohesionTrack]) -> float:
    tokens = [_tokens(track.filename_title) for track in members]
    tokens = [item for item in tokens if item]
    if len(tokens) < 2:
        return 0.0
    shared = set.intersection(*tokens)
    union = set.union(*tokens)
    return len(shared) / len(union) if union else 0.0


def _has_sequential_numbers(numbers: list[int]) -> bool:
    if len(numbers) < 2:
        return False
    expected = list(range(min(numbers), max(numbers) + 1))
    return numbers == expected or len(numbers) >= 3


def _track_sort_key(track: AlbumCohesionTrack) -> tuple[int, str]:
    return (track.track_number if track.track_number is not None else 9999, track.file_path.casefold())


def _group_csv_rows(groups: list[AlbumCohesionGroup]) -> Iterable[dict[str, Any]]:
    for group in groups:
        yield {
            "group_key": group.group_key,
            "album": group.album,
            "artist": group.artist,
            "track_count": group.track_count,
            "cohesion_score": f"{group.cohesion_score:.3f}",
            "confidence_tier": group.confidence_tier,
            "classification": group.classification,
            "rationale": " | ".join(group.rationale),
            "source_folders": " | ".join(group.source_folders),
            "album_tags": " | ".join(group.album_tags),
            "years": " | ".join(group.years),
            "file_paths": " | ".join(track["file_path"] for track in group.tracks),
        }


def _orphan_csv_row(track: AlbumCohesionTrack) -> dict[str, str]:
    return {
        "file_path": track.file_path,
        "artist": track.artist,
        "title": track.title,
        "source_folder": track.source_folder,
        "reason": "no repeated album, folder, tag, sequence, or filename album evidence",
    }


def _display_consensus(values: Iterable[str]) -> str:
    cleaned = [_clean_text(value) for value in values]
    cleaned = [value for value in cleaned if value]
    if not cleaned:
        return ""
    counts = Counter(_norm(value) for value in cleaned)
    key, _ = counts.most_common(1)[0]
    return next(value for value in cleaned if _norm(value) == key)


def _confidence_tier(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _clean_album(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    if cleaned.casefold() in {"unknown", "unknown album", "n/a", "na", "none"}:
        return None
    return sanitize_path_component(cleaned)


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _first_tag(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def _artist_group_key(track: AlbumCohesionTrack) -> str:
    if track.artist.casefold() in {"various", "various artists"}:
        return "various artists"
    return _norm(track.artist or track.filename_artist or "unknown artist")


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.casefold()) if len(token) > 2}


def _same(left: str, right: str) -> bool:
    return _norm(left) == _norm(right)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, str(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(
    path: Path,
    headers: tuple[str, ...],
    rows: Iterable[dict[str, Any]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
