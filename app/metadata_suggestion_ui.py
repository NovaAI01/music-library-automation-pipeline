"""Read-only FastAPI routes for metadata suggestion review reports."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import db
from app.review_decisions import (
    attach_decisions_to_suggestions,
    decisions_by_key,
    review_decision_summary,
    suggestion_key_from_row,
)


DEFAULT_REPORTS_DIR = Path(os.environ.get("MUSIC_LIBRARY_REPORTS_DIR", "reports"))
TEMPLATE_DIR = Path(__file__).parent / "templates"
CONFIDENCE_LEVELS = ("high", "medium", "low")

router = APIRouter(prefix="/review/metadata-suggestions", tags=["metadata-suggestions"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("")
def metadata_suggestions(request: Request):
    return _metadata_suggestions(request, confidence=None)


@router.get("/high")
def high_confidence(request: Request):
    return _metadata_suggestions(request, confidence="high")


@router.get("/medium")
def medium_confidence(request: Request):
    return _metadata_suggestions(request, confidence="medium")


@router.get("/low")
def low_confidence(request: Request):
    return _metadata_suggestions(request, confidence="low")


def _metadata_suggestions(request: Request, *, confidence: str | None):
    suggestions, missing_files = _read_suggestions(_reports_dir(request))
    suggestions = attach_decisions_to_suggestions(
        suggestions,
        decisions_by_key(_db_path(request)),
    )
    summary = _summary(suggestions)
    visible_suggestions = _filter_suggestions(suggestions, confidence)
    title = "Metadata Suggestions"
    if confidence:
        title = f"{confidence.title()} Confidence Metadata Suggestions"

    return templates.TemplateResponse(
        name="metadata_suggestions/review.html",
        request=request,
        context={
            "request": request,
            "title": title,
            "nav_items": _nav_items(),
            "missing_files": missing_files,
            "suggestions": visible_suggestions,
            "cards": [
                ("Total suggestions", summary["total"]),
                ("Requires human review", summary["requires_human_review"]),
                ("Visible suggestions", len(visible_suggestions)),
                ("Approved", summary["decision_counts"]["approved_count"]),
                ("Rejected", summary["decision_counts"]["rejected_count"]),
                ("Deferred", summary["decision_counts"]["deferred_count"]),
            ],
            "confidence_counts": summary["confidence_counts"],
            "type_counts": summary["type_counts"],
            "decision_counts": summary["decision_counts"],
            "active_confidence": confidence or "all",
            "empty_message": _empty_message(confidence, missing_files),
        },
    )


def _reports_dir(request: Request) -> Path:
    configured = getattr(request.app.state, "reports_dir", DEFAULT_REPORTS_DIR)
    return Path(configured).expanduser()


def _db_path(request: Request) -> Path:
    configured = getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)
    return Path(configured).expanduser()


def _read_suggestions(reports_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    path = reports_dir / "metadata_suggestions" / "metadata_suggestions.json"
    if not path.exists():
        return [], [str(path)]
    try:
        with path.open(encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return [], [str(path)]

    raw_suggestions = payload.get("suggestions", []) if isinstance(payload, dict) else []
    if not isinstance(raw_suggestions, list):
        return [], [str(path)]
    return [_normalize_suggestion(item) for item in raw_suggestions if isinstance(item, dict)], []


def _normalize_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    confidence = str(item.get("confidence", "")).lower()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "low"
    source_evidence = item.get("source_evidence", [])
    if isinstance(source_evidence, str):
        source_evidence = [source_evidence] if source_evidence else []
    elif not isinstance(source_evidence, list):
        source_evidence = []
    return {
        "file_path": str(item.get("file_path", "")),
        "field": str(item.get("field", "")),
        "current_value": str(item.get("current_value", "")),
        "proposed_value": str(item.get("proposed_value", "")),
        "confidence": confidence,
        "suggestion_type": str(item.get("suggestion_type", "")),
        "rationale": str(item.get("rationale", "")),
        "source_evidence": [str(value) for value in source_evidence],
        "requires_human_review": bool(item.get("requires_human_review", False)),
        "suggestion_key": suggestion_key_from_row(item),
    }


def _summary(suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    confidence_counts = Counter({level: 0 for level in CONFIDENCE_LEVELS})
    type_counts: Counter[str] = Counter()
    requires_human_review = 0
    for suggestion in suggestions:
        confidence_counts[suggestion["confidence"]] += 1
        type_counts[suggestion["suggestion_type"]] += 1
        if suggestion["requires_human_review"]:
            requires_human_review += 1
    decided = [suggestion for suggestion in suggestions if suggestion.get("decision")]
    return {
        "total": len(suggestions),
        "requires_human_review": requires_human_review,
        "confidence_counts": dict(confidence_counts),
        "type_counts": dict(sorted(type_counts.items())),
        "decision_counts": review_decision_summary(decided),
    }


def _filter_suggestions(
    suggestions: list[dict[str, Any]], confidence: str | None
) -> list[dict[str, Any]]:
    if confidence is None:
        return suggestions
    return [item for item in suggestions if item["confidence"] == confidence]


def _empty_message(confidence: str | None, missing_files: list[str]) -> str:
    if missing_files:
        return "No metadata suggestion report data is available."
    if confidence:
        return f"No {confidence} confidence metadata suggestions available."
    return "No metadata suggestions available."


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
