"""Read-only local music library application routes."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


DEFAULT_REPORTS_DIR = Path(os.environ.get("MUSIC_LIBRARY_REPORTS_DIR", "reports"))
TEMPLATE_DIR = Path(__file__).parent / "templates"

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("")
def dashboard(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    duplicate_groups = _duplicate_groups(reports_dir)
    summary = qa["summary"]

    cards = [
        ("Total library files", summary.get("total_library_files", 0)),
        ("Quarantine files", summary.get("total_quarantine_files", 0)),
        ("Artist count", summary.get("artist_count", 0)),
        ("Genre count", summary.get("genre_count", 0)),
        (
            "Active duplicates",
            summary.get("active_duplicate_group_count", len(duplicate_groups["active"])),
        ),
        ("Unresolved missing", summary.get("unresolved_missing_file_count", 0)),
    ]

    return _render(
        request,
        "reports/dashboard.html",
        {
            "title": "Library Reports",
            "cards": cards,
            "timestamp": summary.get("created_at"),
            "reports_dir": reports_dir,
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/artists")
def artists(request: Request):
    qa = _library_qa(_reports_dir(request))
    artists = _artist_totals(qa["artists"])
    return _render(
        request,
        "reports/artists.html",
        {
            "title": "Artists",
            "artists": artists,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/genres")
def genres(request: Request):
    qa = _library_qa(_reports_dir(request))
    tree = _genre_tree(qa["genres"])
    return _render(
        request,
        "reports/genres.html",
        {
            "title": "Genres",
            "genres": tree,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/quarantine")
def quarantine(request: Request):
    qa = _library_qa(_reports_dir(request))
    files = [
        row for row in qa["file_health"] if row.get("status") == "quarantine_present"
    ]
    return _render(
        request,
        "reports/quarantine.html",
        {
            "title": "Quarantine",
            "files": files,
            "summary": qa["quarantine_summary"],
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/file-health")
def file_health(request: Request, q: str = ""):
    qa = _library_qa(_reports_dir(request))
    query = q.casefold().strip()
    rows = qa["file_health"]
    if query:
        rows = [
            row
            for row in rows
            if query in " ".join(str(value) for value in row.values()).casefold()
        ]

    return _render(
        request,
        "reports/file_health.html",
        {
            "title": "File Health",
            "rows": rows,
            "query": q,
            "timestamp": qa["summary"].get("created_at"),
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/duplicates")
def duplicates(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    groups = _duplicate_groups(reports_dir)
    return _render(
        request,
        "reports/duplicates.html",
        {
            "title": "Duplicates",
            "historical_groups": groups["historical"],
            "active_groups": groups["active"],
            "timestamp": qa["summary"].get("created_at") or groups["latest_timestamp"],
            "missing_files": [*qa["missing_files"], *groups["missing_files"]],
        },
    )


@router.get("/duplicates/latest")
def duplicates_latest(request: Request):
    return duplicates(request)


@router.get("/library-qa/latest")
def library_qa_latest(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    summary = qa["summary"]
    cards = [
        ("Total library files", summary.get("total_library_files", 0)),
        ("Quarantine files", summary.get("total_quarantine_files", 0)),
        ("Artist count", summary.get("artist_count", 0)),
        ("Genre count", summary.get("genre_count", 0)),
        ("Active duplicates", summary.get("active_duplicate_group_count", 0)),
        ("Unresolved missing", summary.get("unresolved_missing_file_count", 0)),
    ]
    return _render(
        request,
        "reports/dashboard.html",
        {
            "title": "Library QA",
            "cards": cards,
            "timestamp": summary.get("created_at"),
            "reports_dir": reports_dir,
            "missing_files": qa["missing_files"],
        },
    )


@router.get("/metadata/latest")
def metadata_latest(request: Request):
    reports_dir = _reports_dir(request)
    audit, missing_audit = _read_json(
        reports_dir / "metadata_audit" / "metadata_summary.json"
    )
    plan, missing_plan = _read_json(
        reports_dir / "metadata_plan" / "metadata_plan_summary.json"
    )
    cards = [
        ("Total FLAC files", audit.get("total_flac_files", 0)),
        ("Readable FLAC files", audit.get("readable_flac_files", 0)),
        ("Missing tags", audit.get("missing_tag_count", 0)),
        ("Malformed tags", audit.get("malformed_tag_count", 0)),
        ("Proposed updates", plan.get("proposed_update_count", 0)),
        ("Unreadable FLAC files", audit.get("unreadable_flac_files", 0)),
    ]
    return _render(
        request,
        "reports/dashboard.html",
        {
            "title": "Metadata Audit",
            "cards": cards,
            "timestamp": audit.get("created_at") or plan.get("created_at"),
            "reports_dir": reports_dir,
            "missing_files": [
                label for label in [missing_audit, missing_plan] if label
            ],
        },
    )


def _render(request: Request, template_name: str, context: dict[str, Any]):
    return templates.TemplateResponse(
        name=template_name,
        request=request,
        context={
            "request": request,
            "nav_items": _nav_items(),
            **context,
        },
    )


def _reports_dir(request: Request) -> Path:
    configured = getattr(request.app.state, "reports_dir", DEFAULT_REPORTS_DIR)
    return Path(configured).expanduser()


def _library_qa(reports_dir: Path) -> dict[str, Any]:
    qa_dir = reports_dir / "library_qa"
    summary, missing_summary = _read_json(qa_dir / "library_qa_summary.json")
    artists, missing_artists = _read_csv(qa_dir / "artists.csv")
    genres, missing_genres = _read_csv(qa_dir / "genres.csv")
    quarantine_summary, missing_quarantine = _read_csv(
        qa_dir / "quarantine_summary.csv"
    )
    file_health_rows, missing_file_health = _read_csv(qa_dir / "file_health.csv")
    return {
        "summary": summary,
        "artists": artists,
        "genres": genres,
        "quarantine_summary": quarantine_summary,
        "file_health": file_health_rows,
        "missing_files": [
            label
            for label in [
                missing_summary,
                missing_artists,
                missing_genres,
                missing_quarantine,
                missing_file_health,
            ]
            if label
        ],
    }


def _duplicate_groups(reports_dir: Path) -> dict[str, Any]:
    historical: dict[str, dict[str, Any]] = {}
    missing_files: list[str] = []
    latest_timestamp: str | None = None

    duplicate_dirs = sorted(reports_dir.glob("duplicates_scan_*"))
    if not duplicate_dirs:
        missing_files.append("reports/duplicates_scan_*/")

    for report_dir in duplicate_dirs:
        summary, missing_summary = _read_json(report_dir / "duplicate_summary.json")
        if missing_summary:
            missing_files.append(missing_summary)
        latest_timestamp = summary.get("created_at") or latest_timestamp
        for filename in (
            "exact_hash_duplicates.csv",
            "same_artist_title_duplicates.csv",
            "probable_variants.csv",
        ):
            rows, missing_csv = _read_csv(report_dir / filename)
            if missing_csv:
                missing_files.append(missing_csv)
                continue
            for row in rows:
                group_key = row.get("duplicate_group_key", "")
                if not group_key:
                    continue
                group = historical.setdefault(
                    group_key,
                    {
                        "key": group_key,
                        "type": row.get("duplicate_type", ""),
                        "artist": row.get("artist", ""),
                        "title": row.get("normalized_title", ""),
                        "files": [],
                    },
                )
                group["files"].append(row)

    historical_groups = sorted(historical.values(), key=lambda row: row["key"])
    active_groups = [
        group
        for group in historical_groups
        if len(
            {
                row.get("file_path", "")
                for row in group["files"]
                if row.get("file_path") and Path(row["file_path"]).is_file()
            }
        )
        >= 2
    ]
    return {
        "historical": historical_groups,
        "active": active_groups,
        "latest_timestamp": latest_timestamp,
        "missing_files": missing_files,
    }


def _artist_totals(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        artist = row.get("artist", "") or "Unknown"
        item = totals.setdefault(
            artist,
            {"artist": artist, "file_count": 0, "locations": []},
        )
        item["file_count"] += _int_value(row.get("file_count"))
        item["locations"].append(
            {
                "genre": row.get("genre", ""),
                "subgenre": row.get("subgenre", ""),
                "file_count": _int_value(row.get("file_count")),
            }
        )
    return sorted(totals.values(), key=lambda item: item["artist"].casefold())


def _genre_tree(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    genres: dict[str, dict[str, Any]] = {}
    for row in rows:
        genre = row.get("genre", "") or "Unknown"
        item = genres.setdefault(
            genre,
            {"genre": genre, "file_count": 0, "artist_count": 0, "subgenres": []},
        )
        item["file_count"] += _int_value(row.get("file_count"))
        item["artist_count"] += _int_value(row.get("artist_count"))
        item["subgenres"].append(
            {
                "subgenre": row.get("subgenre", "") or "Unspecified",
                "artist_count": _int_value(row.get("artist_count")),
                "file_count": _int_value(row.get("file_count")),
            }
        )
    return sorted(genres.values(), key=lambda item: item["genre"].casefold())


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, str(path)
    try:
        with path.open(encoding="utf-8") as file_handle:
            data = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return {}, str(path)
    if isinstance(data, dict):
        return data, None
    return {}, str(path)


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.exists():
        return [], str(path)
    try:
        with path.open(newline="", encoding="utf-8") as file_handle:
            return list(csv.DictReader(file_handle)), None
    except OSError:
        return [], str(path)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
        ("/review/knowledge", "Knowledge"),
        ("/player", "Player"),
        ("/settings", "Settings"),
    ]
