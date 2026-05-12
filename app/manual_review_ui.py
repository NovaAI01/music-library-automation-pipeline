"""Read-only FastAPI routes for manual review report files."""

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
DEFAULT_SCAN_RUN_ID = 1

router = APIRouter(prefix="/review", tags=["manual-review"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("")
def summary(request: Request):
    review = _review_data(_reports_dir(request))
    cards = [
        ("Quarantined duplicate files", review["quarantine_count"]),
        ("Conflicts", len(review["conflicts"])),
        ("Blocked classification", review["blocked_classification_count"]),
        ("Unresolved missing files", review["unresolved_missing_count"]),
    ]
    return _render(
        request,
        "manual_review/summary.html",
        {
            "title": "Manual Review",
            "cards": cards,
            "missing_files": review["missing_files"],
        },
    )


@router.get("/quarantine")
def quarantine(request: Request):
    review = _review_data(_reports_dir(request))
    return _render(
        request,
        "manual_review/quarantine.html",
        {
            "title": "Quarantined Duplicates",
            "files": review["quarantined_files"],
            "missing_files": review["missing_files"],
        },
    )


@router.get("/conflicts")
def conflicts(request: Request):
    rows, missing_files = _scan_csv(_reports_dir(request), "conflicts.csv")
    return _render(
        request,
        "manual_review/table.html",
        {
            "title": "Conflicts",
            "headers": _headers(rows),
            "rows": rows,
            "empty_message": "No conflict rows available.",
            "missing_files": missing_files,
        },
    )


@router.get("/blocked")
def blocked(request: Request):
    rows, missing_files = _scan_csv(_reports_dir(request), "blocked_items.csv")
    return _render(
        request,
        "manual_review/table.html",
        {
            "title": "Blocked Classification",
            "headers": _headers(rows),
            "rows": rows,
            "empty_message": "No blocked item rows available.",
            "missing_files": missing_files,
        },
    )


@router.get("/duplicates/latest")
def duplicate_review_latest(request: Request):
    return summary(request)


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


def _review_data(reports_dir: Path) -> dict[str, Any]:
    qa = _library_qa(reports_dir)
    conflicts, missing_conflicts = _scan_csv(reports_dir, "conflicts.csv")
    blocked_rows, missing_blocked = _scan_csv(reports_dir, "blocked_items.csv")

    blocked_classification_rows = [
        row
        for row in blocked_rows
        if row.get("placement_status") == "blocked_unknown_classification"
    ]
    blocked_classification_count = (
        len(blocked_classification_rows) if blocked_classification_rows else len(blocked_rows)
    )

    missing_files = [
        *qa["missing_files"],
        *missing_conflicts,
        *missing_blocked,
    ]
    return {
        "quarantined_files": qa["quarantined_files"],
        "quarantine_count": _summary_int(
            qa["summary"],
            "quarantined_duplicate_file_count",
            len(qa["quarantined_files"]),
        ),
        "unresolved_missing_count": _summary_int(
            qa["summary"],
            "unresolved_missing_file_count",
            qa["unresolved_missing_count"],
        ),
        "conflicts": conflicts,
        "blocked_rows": blocked_rows,
        "blocked_classification_count": blocked_classification_count,
        "missing_files": missing_files,
    }


def _library_qa(reports_dir: Path) -> dict[str, Any]:
    qa_dir = reports_dir / "library_qa"
    summary, missing_summary = _read_json(qa_dir / "library_qa_summary.json")
    file_health, missing_file_health = _read_csv(qa_dir / "file_health.csv")
    quarantined_files = [
        _quarantine_row(row)
        for row in file_health
        if row.get("status") == "quarantine_present"
    ]
    unresolved_missing_count = len(
        [row for row in file_health if row.get("status") == "missing_placement_file"]
    )
    return {
        "summary": summary,
        "quarantined_files": quarantined_files,
        "unresolved_missing_count": unresolved_missing_count,
        "missing_files": [
            label for label in [missing_summary, missing_file_health] if label
        ],
    }


def _quarantine_row(row: dict[str, str]) -> dict[str, str]:
    path = Path(row.get("path", ""))
    return {
        "filename": path.name or row.get("path", ""),
        "artist_path": str(path.parent) if path.parent != Path(".") else "",
        "size_bytes": row.get("size_bytes", ""),
    }


def _scan_csv(reports_dir: Path, filename: str) -> tuple[list[dict[str, str]], list[str]]:
    rows, missing = _read_csv(reports_dir / f"scan_{DEFAULT_SCAN_RUN_ID}" / filename)
    return rows, [missing] if missing else []


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


def _headers(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return list(rows[0].keys())


def _summary_int(summary: dict[str, Any], key: str, fallback: int) -> int:
    try:
        return int(summary.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


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
