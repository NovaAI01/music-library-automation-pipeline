"""Unified local-first music library application UI routes."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import db
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


DEFAULT_LIBRARY_ROOT = Path(os.environ.get("MUSIC_LIBRARY_ROOT", "library"))
DEFAULT_QUARANTINE_ROOT = Path(
    os.environ.get("MUSIC_LIBRARY_QUARANTINE_ROOT", "quarantine")
)
DEFAULT_SCREENSHOT_DIR = Path("docs/screenshots")

router = APIRouter(tags=["music-library-app"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("/")
def dashboard(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    duplicate_groups = _duplicate_groups(reports_dir)
    metadata = _metadata_summary(reports_dir)
    suggestions = _suggestion_summary(reports_dir)
    summary = qa["summary"]
    cards = [
        ("Total tracks", summary.get("total_library_files", 0)),
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
            "cards": cards,
            "latest_reports": latest_reports,
            "quick_actions": quick_actions,
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
    summary = qa["summary"]
    return _render(
        request,
        "reports/library.html",
        {
            "title": "Library",
            "eyebrow": "Organized Browser",
            "cards": [
                ("Total tracks", summary.get("total_library_files", 0)),
                ("Artists", summary.get("artist_count", 0)),
                ("Genres", summary.get("genre_count", 0)),
                ("Quarantine files", summary.get("total_quarantine_files", 0)),
            ],
            "sample_tracks": _track_rows(qa["file_health"])[:10],
            "timestamp": summary.get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/library/artists")
def library_artists(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    return _render(
        request,
        "reports/artists.html",
        {
            "title": "Artists",
            "eyebrow": "Library Browser",
            "artists": _filter_rows(_artist_totals(qa["artists"]), q),
            "query": q,
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
            "genres": _genre_tree(_filter_rows(qa["genres"], q)),
            "query": q,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/library/tracks")
def library_tracks(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    return _render(
        request,
        "reports/tracks.html",
        {
            "title": "Tracks",
            "eyebrow": "Library Browser",
            "rows": _filter_rows(_track_rows(qa["file_health"]), q),
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
    from app.report_ui import duplicates

    return duplicates(request)


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
    rows = [
        row for row in _filter_rows(_track_rows(qa["file_health"]), q) if row["playable"]
    ]
    return _render(
        request,
        "reports/player.html",
        {
            "title": "Player",
            "eyebrow": "Local Playback",
            "selected": rows[0] if rows else None,
            "rows": rows[:50],
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


def _track_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    tracks = []
    for row in rows:
        if row.get("status") != "library_present":
            continue
        path = Path(row.get("path", ""))
        parts = path.parts
        tracks.append(
            {
                "path": row.get("path", ""),
                "title": path.stem,
                "artist": parts[-2] if len(parts) >= 2 else "",
                "genre": parts[-4] if len(parts) >= 4 else "",
                "subgenre": parts[-3] if len(parts) >= 3 else "",
                "extension": row.get("extension", path.suffix),
                "size_bytes": row.get("size_bytes", ""),
                "playable": path.is_file(),
                "url": path.as_uri() if path.is_absolute() and path.is_file() else "",
            }
        )
    return sorted(tracks, key=lambda item: item["path"].casefold())


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
        ("/library/genres", "Genres"),
        ("/library/tracks", "Tracks"),
        ("/review", "Review"),
        ("/review/duplicates", "Duplicates"),
        ("/review/metadata", "Metadata"),
        ("/player", "Player"),
        ("/settings", "Settings"),
    ]
