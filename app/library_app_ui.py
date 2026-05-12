"""Unified local-first music library application UI routes."""

from __future__ import annotations

import base64
import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.album_organization import (
    UNKNOWN_ALBUM,
    read_album_plan_rows,
    read_album_plan_summary,
)
from app.manual_review_ui import _review_data
from app.metadata_suggestion_ui import _read_suggestions
from app.report_ui import (
    DEFAULT_REPORTS_DIR,
    TEMPLATE_DIR,
    _artist_totals,
    _duplicate_groups,
    _genre_tree,
    _int_value,
    _library_qa,
    _read_json,
)


DEFAULT_LIBRARY_ROOT = Path(
    os.environ.get("MUSIC_LIBRARY_ROOT", "~/Music/Organised_Library")
).expanduser()
DEFAULT_QUARANTINE_ROOT = Path(
    os.environ.get("MUSIC_LIBRARY_QUARANTINE_ROOT", "quarantine")
)
DEFAULT_SCREENSHOT_DIR = Path("docs/screenshots")

router = APIRouter(tags=["music-library-app"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("/media/audio")
def audio_file(request: Request, path: str = Query(..., min_length=1)):
    root = _library_root(request).resolve()
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Audio file not found") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(candidate, media_type=_audio_media_type(candidate))


@router.get("/")
def dashboard(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    duplicate_groups = _duplicate_groups(reports_dir)
    metadata = _metadata_summary(reports_dir)
    suggestions = _suggestion_summary(reports_dir)
    summary = qa["summary"]
    tracks = _album_browser_tracks(
        reports_dir,
        qa["file_health"],
        _library_root(request),
    )
    albums = _albums_from_tracks(tracks)
    cards = [
        ("Total tracks", summary.get("total_library_files", 0)),
        ("Albums", len(albums)),
        ("Unknown albums", _unknown_album_count(albums)),
        ("Album plan rows", _album_plan_count(reports_dir)),
        ("Duplicate groups", len(duplicate_groups["active"])),
        ("Metadata issues", metadata["issue_count"]),
        ("Suggestions", suggestions["total"]),
        ("Quarantine files", summary.get("total_quarantine_files", 0)),
        ("Unresolved missing", summary.get("unresolved_missing_file_count", 0)),
    ]
    latest_reports = [
        ("Library QA", summary.get("created_at"), "/library"),
        ("Duplicate Review", duplicate_groups["latest_timestamp"], "/review/duplicates"),
        ("Metadata Review", metadata["timestamp"], "/review/metadata"),
    ]
    quick_actions = [
        ("Import messy music", "/import"),
        ("Analyze library", "/library"),
        ("Browse albums", "/library/albums"),
        ("Review issues", "/review"),
        ("Review duplicates", "/review/duplicates"),
        ("Review metadata", "/review/metadata"),
        ("Play tracks", "/player"),
    ]
    return _render(
        request,
        "reports/dashboard.html",
        {
            "title": "Dashboard",
            "eyebrow": "Local Music Library",
            "intro": "Your home base for importing, reviewing, browsing, and playing the organized local library.",
            "cards": cards,
            "latest_reports": latest_reports,
            "quick_actions": quick_actions,
            "top_albums": albums[:5],
            "incomplete_album_count": _incomplete_album_count(
                _track_rows(qa["file_health"], _library_root(request))
            ),
            "timestamp": summary.get("created_at") or metadata["timestamp"],
            "missing_files": [
                *qa["missing_files"],
                *duplicate_groups["missing_files"],
                *metadata["missing_files"],
                *suggestions["missing_files"],
            ],
        },
    )


@router.get("/import")
def import_page(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    metadata = _metadata_summary(reports_dir)
    steps = [
        ("Scan intake", "python -m app.main scan --source ~/Music/Library_Intake"),
        ("Identify tracks", "python -m app.main identify --scan-run-id 1"),
        ("Classify library", "python -m app.main classify --scan-run-id 1"),
        ("Plan placement", "python -m app.main plan-placement --scan-run-id 1"),
        ("Generate reports", "python -m app.main review-report --scan-run-id 1 --out reports"),
    ]
    summaries = [
        ("Latest library QA", qa["summary"].get("created_at", "No report timestamp")),
        ("Latest metadata audit", metadata["timestamp"] or "No report timestamp"),
    ]
    return _render(
        request,
        "reports/import.html",
        {
            "title": "Import",
            "eyebrow": "Intake Workflow",
            "intro": "Use this page as the checklist for turning a messy local folder into reviewed library evidence.",
            "back_links": [("Back to Dashboard", "/")],
            "intake_path": _library_root(request),
            "reports_dir": reports_dir,
            "steps": steps,
            "summaries": summaries,
            "missing_files": [*qa["missing_files"], *metadata["missing_files"]],
        },
    )


@router.get("/library")
def library(request: Request):
    qa = _library_qa(_reports_dir(request))
    library_root = _library_root(request)
    summary = qa["summary"]
    return _render(
        request,
        "reports/library.html",
        {
            "title": "Library",
            "eyebrow": "Organized Browser",
            "intro": "Browse the organized library by artist, genre, or track, then jump straight into local playback.",
            "back_links": [("Back to Dashboard", "/")],
            "cards": [
                ("Total tracks", summary.get("total_library_files", 0)),
                ("Artists", summary.get("artist_count", 0)),
                ("Albums", summary.get("album_count", 0)),
                ("Genres", summary.get("genre_count", 0)),
                ("Quarantine files", summary.get("total_quarantine_files", 0)),
            ],
            "sample_tracks": _track_rows(qa["file_health"], library_root)[:10],
            "timestamp": summary.get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/library/artists")
def library_artists(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    tracks = _album_browser_tracks(
        _reports_dir(request),
        qa["file_health"],
        _library_root(request),
    )
    return _render(
        request,
        "reports/artists.html",
        {
            "title": "Artists",
            "eyebrow": "Library Browser",
            "intro": "Find artists in the organized library and open their tracks from one place.",
            "breadcrumbs": [("Library", "/library"), ("Artists", "")],
            "back_links": [("Back to Library", "/library")],
            "artists": _filter_rows(
                _artists_with_albums(_artist_totals(qa["artists"]), tracks),
                q,
            ),
            "query": q,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/library/albums")
def library_albums(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    library_root = _library_root(request)
    tracks = _album_browser_tracks(
        _reports_dir(request),
        qa["file_health"],
        library_root,
    )
    return _render(
        request,
        "reports/albums.html",
        {
            "title": "Albums",
            "eyebrow": "Library Browser",
            "intro": "Browse album folders in the organized library and open their local tracks.",
            "breadcrumbs": [("Library", "/library"), ("Albums", "")],
            "back_links": [("Back to Library", "/library")],
            "albums": _filter_rows(
                _albums_from_tracks(tracks),
                q,
            ),
            "query": q,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/library/albums/{album_key}")
def library_album_detail(request: Request, album_key: str):
    qa = _library_qa(_reports_dir(request))
    library_root = _library_root(request)
    tracks = _album_browser_tracks(
        _reports_dir(request),
        qa["file_health"],
        library_root,
    )
    albums = _albums_from_tracks(tracks)
    album = next((item for item in albums if item["key"] == album_key), None)
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found")
    return _render(
        request,
        "reports/album_detail.html",
        {
            "title": album["title"],
            "eyebrow": "Album",
            "intro": "Review the album grouping and play available local tracks.",
            "breadcrumbs": [
                ("Library", "/library"),
                ("Albums", "/library/albums"),
                (album["title"], ""),
            ],
            "back_links": [("Back to Albums", "/library/albums")],
            "album": album,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/library/genres")
def library_genres(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    return _render(
        request,
        "reports/genres.html",
        {
            "title": "Genres",
            "eyebrow": "Library Browser",
            "intro": "Use genres and subgenres to understand how the library is organized.",
            "breadcrumbs": [("Library", "/library"), ("Genres", "")],
            "back_links": [("Back to Library", "/library")],
            "genres": _genre_tree(_filter_rows(qa["genres"], q)),
            "query": q,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/library/tracks")
def library_tracks(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    library_root = _library_root(request)
    return _render(
        request,
        "reports/tracks.html",
        {
            "title": "Tracks",
            "eyebrow": "Library Browser",
            "intro": "Search tracks, inspect their library placement, and play files that are available under the library root.",
            "breadcrumbs": [("Library", "/library"), ("Tracks", "")],
            "back_links": [("Back to Library", "/library")],
            "rows": _filter_rows(_track_rows(qa["file_health"], library_root), q),
            "query": q,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/review")
def review_hub(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    duplicate_groups = _duplicate_groups(reports_dir)
    review = _review_data(reports_dir)
    suggestions = _suggestion_summary(reports_dir)
    return _render(
        request,
        "reports/review.html",
        {
            "title": "Review",
            "eyebrow": "Unified Review Hub",
            "intro": "Review duplicate groups, metadata suggestions, and blocked items before taking any file action outside this UI.",
            "back_links": [("Back to Dashboard", "/")],
            "cards": [
                ("Active duplicate groups", len(duplicate_groups["active"])),
                ("Quarantined duplicate files", review["quarantine_count"]),
                ("Metadata suggestions", suggestions["total"]),
                ("Blocked classification", review["blocked_classification_count"]),
                ("Conflicts", len(review["conflicts"])),
                ("Low confidence", suggestions["confidence_counts"].get("low", 0)),
            ],
            "review_links": [
                ("Duplicate Review", "/review/duplicates", "Keep/remove candidates and active duplicate groups."),
                ("Metadata Review", "/review/metadata", "Review-only tag cleanup suggestions."),
                ("Blocked Items", "/review/blocked", "Items that need manual classification."),
            ],
            "confidence_counts": suggestions["confidence_counts"],
            "missing_files": [
                *qa["missing_files"],
                *duplicate_groups["missing_files"],
                *review["missing_files"],
                *suggestions["missing_files"],
            ],
        },
    )


@router.get("/review/duplicates")
def review_duplicates(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    groups = _duplicate_groups(reports_dir)
    return _render(
        request,
        "reports/duplicates.html",
        {
            "title": "Duplicate Review",
            "eyebrow": "Review Queue",
            "intro": "Compare active and historical duplicate groups before deciding what belongs in quarantine.",
            "breadcrumbs": [("Review", "/review"), ("Duplicates", "")],
            "back_links": [("Back to Review", "/review")],
            "cards": [
                ("Active groups", len(groups["active"])),
                ("Historical groups", len(groups["historical"])),
                ("Quarantine files", qa["summary"].get("total_quarantine_files", 0)),
            ],
            "historical_groups": groups["historical"],
            "active_groups": groups["active"],
            "timestamp": qa["summary"].get("created_at") or groups["latest_timestamp"],
            "missing_files": [*qa["missing_files"], *groups["missing_files"]],
        },
    )


@router.get("/review/metadata")
def review_metadata(request: Request, q: str = ""):
    reports_dir = _reports_dir(request)
    metadata = _metadata_summary(reports_dir)
    suggestions = _suggestion_summary(reports_dir)
    return _render(
        request,
        "reports/metadata.html",
        {
            "title": "Metadata Review",
            "eyebrow": "Suggestions",
            "intro": "Review suggested tag cleanup without writing metadata. Confidence badges help decide what needs closer attention.",
            "breadcrumbs": [("Review", "/review"), ("Metadata", "")],
            "back_links": [("Back to Review", "/review")],
            "cards": [
                ("Metadata issues", metadata["issue_count"]),
                ("Proposed updates", metadata["proposed_updates"]),
                ("Suggestions", suggestions["total"]),
                ("Requires review", suggestions["requires_human_review"]),
            ],
            "suggestions": _filter_rows(suggestions["suggestions"], q),
            "confidence_counts": suggestions["confidence_counts"],
            "query": q,
            "timestamp": metadata["timestamp"],
            "missing_files": [*metadata["missing_files"], *suggestions["missing_files"]],
        },
    )


@router.get("/player")
def player(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    library_root = _library_root(request)
    rows = [
        row
        for row in _filter_rows(_track_rows(qa["file_health"], library_root), q)
        if row["playable"]
    ]
    albums = _albums_from_tracks(rows)
    return _render(
        request,
        "reports/player.html",
        {
            "title": "Player",
            "eyebrow": "Local Playback",
            "intro": "Play organized local tracks directly from the configured library root when your browser supports the format.",
            "back_links": [("Back to Library", "/library")],
            "selected": rows[0] if rows else None,
            "rows": rows[:50],
            "albums": albums[:20],
            "query": q,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/settings")
def settings(request: Request):
    return _render(
        request,
        "reports/settings.html",
        {
            "title": "Settings",
            "eyebrow": "Read-only Paths",
            "intro": "These paths define where the app reads reports, organized tracks, quarantine files, and demo assets.",
            "back_links": [("Back to Dashboard", "/")],
            "settings": [
                ("Library root", _library_root(request)),
                ("Quarantine root", _quarantine_root(request)),
                ("Reports directory", _reports_dir(request)),
                ("Database path", getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)),
                ("Screenshot/demo paths", f"{DEFAULT_SCREENSHOT_DIR} / demo"),
            ],
            "missing_files": [],
        },
    )


def _render(request: Request, template_name: str, context: dict[str, Any]):
    return templates.TemplateResponse(
        name=template_name,
        request=request,
        context={
            "request": request,
            "app_name": "Local Music Library",
            "nav_items": _nav_items(),
            "active_section": _active_section(request.url.path),
            **context,
        },
    )


def _reports_dir(request: Request) -> Path:
    configured = getattr(request.app.state, "reports_dir", DEFAULT_REPORTS_DIR)
    return Path(configured).expanduser()


def _library_root(request: Request) -> Path:
    configured = getattr(request.app.state, "library_root", DEFAULT_LIBRARY_ROOT)
    return Path(configured).expanduser()


def _quarantine_root(request: Request) -> Path:
    configured = getattr(request.app.state, "quarantine_root", DEFAULT_QUARANTINE_ROOT)
    return Path(configured).expanduser()


def _metadata_summary(reports_dir: Path) -> dict[str, Any]:
    audit, missing_audit = _read_json(
        reports_dir / "metadata_audit" / "metadata_summary.json"
    )
    plan, missing_plan = _read_json(
        reports_dir / "metadata_plan" / "metadata_plan_summary.json"
    )
    issue_count = sum(
        _int_value(audit.get(key))
        for key in (
            "missing_tag_count",
            "malformed_tag_count",
            "inconsistent_artist_count",
            "inconsistent_title_count",
            "unreadable_flac_files",
        )
    )
    return {
        "issue_count": issue_count,
        "proposed_updates": _int_value(plan.get("proposed_update_count")),
        "timestamp": audit.get("created_at") or plan.get("created_at"),
        "missing_files": [label for label in [missing_audit, missing_plan] if label],
    }


def _suggestion_summary(reports_dir: Path) -> dict[str, Any]:
    suggestions, missing_files = _read_suggestions(reports_dir)
    confidence_counts = Counter({"high": 0, "medium": 0, "low": 0})
    requires_human_review = 0
    for suggestion in suggestions:
        confidence_counts[suggestion["confidence"]] += 1
        if suggestion["requires_human_review"]:
            requires_human_review += 1
    return {
        "suggestions": suggestions,
        "total": len(suggestions),
        "requires_human_review": requires_human_review,
        "confidence_counts": dict(confidence_counts),
        "missing_files": missing_files,
    }


def _album_browser_tracks(
    reports_dir: Path,
    rows: list[dict[str, str]],
    library_root: Path,
) -> list[dict[str, Any]]:
    tracks = _track_rows(rows, library_root)
    plan_by_path = _album_plan_by_current_path(reports_dir)
    for track in tracks:
        plan = plan_by_path.get(str(Path(track["path"]).expanduser()))
        if not plan:
            continue
        track["artist"] = plan.get("artist") or track["artist"]
        track["album"] = plan.get("album") or track["album"]
        track["title"] = plan.get("title") or track["title"]
    return tracks


def _album_plan_by_current_path(reports_dir: Path) -> dict[str, dict[str, str]]:
    return {
        str(Path(row.get("current_path", "")).expanduser()): row
        for row in read_album_plan_rows(reports_dir)
        if row.get("current_path")
    }


def _album_plan_count(reports_dir: Path) -> int:
    summary = read_album_plan_summary(reports_dir)
    return _int_value(summary.get("total_files")) if summary else 0


def _track_rows(rows: list[dict[str, str]], library_root: Path) -> list[dict[str, Any]]:
    tracks = []
    root = library_root.resolve()
    for row in rows:
        if row.get("status") != "library_present":
            continue
        path = Path(row.get("path", ""))
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            relative_path = resolved.relative_to(root)
        except ValueError:
            relative_path = None
        display_parts = relative_path.parts if relative_path is not None else path.parts
        genre = display_parts[0] if len(display_parts) >= 4 else ""
        subgenre = display_parts[1] if len(display_parts) >= 4 else ""
        artist = display_parts[2] if len(display_parts) >= 4 else ""
        album = display_parts[3] if len(display_parts) >= 5 else ""
        playable = relative_path is not None and resolved.is_file()
        media_path = relative_path.as_posix() if relative_path else ""
        tracks.append(
            {
                "path": row.get("path", ""),
                "relative_path": media_path,
                "title": path.stem,
                "artist": artist,
                "album": album,
                "genre": genre,
                "subgenre": subgenre,
                "extension": row.get("extension", path.suffix),
                "size_bytes": row.get("size_bytes", ""),
                "playable": playable,
                "url": f"/media/audio?path={quote(media_path)}" if playable else "",
            }
        )
    return sorted(tracks, key=lambda item: item["path"].casefold())


def _albums_from_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    albums: dict[str, dict[str, Any]] = {}
    for track in tracks:
        album_title = track.get("album") or UNKNOWN_ALBUM
        artist = track.get("artist") or "Unknown Artist"
        key = _album_key(
            track.get("genre", ""),
            track.get("subgenre", ""),
            artist,
            album_title,
        )
        album = albums.setdefault(
            key,
            {
                "key": key,
                "title": album_title,
                "artist": artist,
                "genre": track.get("genre", ""),
                "subgenre": track.get("subgenre", ""),
                "track_count": 0,
                "tracks": [],
                "path": str(Path(track.get("relative_path") or track.get("path", "")).parent),
            },
        )
        album["track_count"] += 1
        album["tracks"].append(track)
    for album in albums.values():
        album["tracks"] = sorted(
            album["tracks"],
            key=lambda item: (item.get("relative_path") or item.get("path", "")).casefold(),
        )
    return sorted(
        albums.values(),
        key=lambda item: (-item["track_count"], item["artist"].casefold(), item["title"].casefold()),
    )


def _album_key(genre: str, subgenre: str, artist: str, album: str) -> str:
    payload = "\0".join([genre, subgenre, artist, album]).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _incomplete_album_count(tracks: list[dict[str, Any]]) -> int:
    return sum(1 for track in tracks if not track.get("album"))


def _unknown_album_count(albums: list[dict[str, Any]]) -> int:
    return sum(1 for album in albums if album.get("title") == UNKNOWN_ALBUM)


def _artists_with_albums(
    artists: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    albums_by_artist: dict[str, list[dict[str, Any]]] = {}
    for album in _albums_from_tracks(tracks):
        albums_by_artist.setdefault(album["artist"], []).append(album)
    for artist in artists:
        artist["albums"] = albums_by_artist.get(artist["artist"], [])
    return artists


def _filter_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized = query.casefold().strip()
    if not normalized:
        return rows
    return [
        row
        for row in rows
        if normalized in " ".join(str(value) for value in row.values()).casefold()
    ]


def _nav_items() -> list[tuple[str, str]]:
    return [
        ("/", "Dashboard"),
        ("/import", "Import"),
        ("/library", "Library"),
        ("/library/artists", "Artists"),
        ("/library/albums", "Albums"),
        ("/library/genres", "Genres"),
        ("/library/tracks", "Tracks"),
        ("/review", "Review"),
        ("/review/duplicates", "Duplicates"),
        ("/review/metadata", "Metadata"),
        ("/player", "Player"),
        ("/settings", "Settings"),
    ]


def _active_section(path: str) -> str:
    if path == "/":
        return "/"
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "/"
    if parts[0] == "media":
        return "/player"
    if parts[0] == "library":
        return "/library"
    if parts[0] == "review":
        return "/review"
    return f"/{parts[0]}"


def _audio_media_type(path: Path) -> str:
    extension = path.suffix.casefold()
    if extension == ".flac":
        return "audio/flac"
    if extension == ".mp3":
        return "audio/mpeg"
    if extension == ".m4a":
        return "audio/mp4"
    if extension == ".ogg":
        return "audio/ogg"
    if extension == ".wav":
        return "audio/wav"
    return "application/octet-stream"
