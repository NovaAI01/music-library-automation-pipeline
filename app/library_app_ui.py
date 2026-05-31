"""Unified local-first music library application UI routes."""

from __future__ import annotations

import base64
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.album_cohesion import read_album_cohesion_report
from app.album_organization import (
    UNKNOWN_ALBUM,
    read_album_plan_rows,
    read_album_plan_summary,
)
from app.canonical_entity_graph import read_canonical_graph_report
from app.canonical_entity_classifier import read_entity_classification_report
from app.entity_roles import read_entity_role_report
from app.evidence_reliability import read_evidence_reliability_report
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
from app.review_decisions import (
    attach_decisions_to_suggestions,
    decisions_by_key,
    list_review_decisions,
    review_decision_summary,
)


DEFAULT_LIBRARY_ROOT = Path(
    os.environ.get("MUSIC_LIBRARY_ROOT", "~/Music/Organised_Library")
).expanduser()
DEFAULT_QUARANTINE_ROOT = Path(
    os.environ.get("MUSIC_LIBRARY_QUARANTINE_ROOT", "quarantine")
)
DEFAULT_SCREENSHOT_DIR = Path("tools/portfolio_demo/docs/screenshots")

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
    suggestions = _suggestion_summary(reports_dir, db_path=_db_path(request))
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
            "eyebrow": "Music Library Intelligence Platform",
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


@router.get("/library/organization-preview")
def organization_preview(
    request: Request,
    scan_run_id: int | None = None,
    placement_status: str = "",
    identity_status: str = "",
    classification_status: str = "",
    q: str = "",
):
    preview = _organization_preview_data(
        db_path=_db_path(request),
        scan_run_id=scan_run_id,
        placement_status=placement_status,
        identity_status=identity_status,
        classification_status=classification_status,
        query=q,
    )
    return _render(
        request,
        "reports/organization_preview.html",
        {
            "title": "Organization Preview",
            "eyebrow": "Messy Source -> System Judgment -> Organized Destination",
            "intro": "Inspect source paths, system judgments, and canonical destination plans without moving, copying, deleting, or tagging files.",
            "breadcrumbs": [("Library", "/library"), ("Organization Preview", "")],
            "back_links": [("Back to Library", "/library")],
            **preview,
        },
    )


@router.get("/library/organization-preview/tree")
def organization_preview_tree(request: Request, scan_run_id: int | None = None):
    preview = _organization_preview_data(
        db_path=_db_path(request),
        scan_run_id=scan_run_id,
        placement_status="",
        identity_status="",
        classification_status="",
        query="",
    )
    return _render(
        request,
        "reports/organization_preview_tree.html",
        {
            "title": "Folder Tree Preview",
            "eyebrow": "Read-only OrganizedLibrary Layout",
            "intro": "Review planned organized paths grouped by governance zone. This page does not execute placement.",
            "breadcrumbs": [
                ("Library", "/library"),
                ("Organization Preview", "/library/organization-preview"),
                ("Folder Tree", ""),
            ],
            "back_links": [("Back to Organization Preview", "/library/organization-preview")],
            **preview,
        },
    )


@router.get("/review")
def review_hub(request: Request):
    reports_dir = _reports_dir(request)
    qa = _library_qa(reports_dir)
    duplicate_groups = _duplicate_groups(reports_dir)
    review = _review_data(reports_dir)
    suggestions = _suggestion_summary(reports_dir, db_path=_db_path(request))
    album_cohesion = _album_cohesion_summary(reports_dir)
    reliability = _reliability_summary(reports_dir)
    canonical_graph = _canonical_graph_summary(reports_dir)
    entity_classification = _entity_classification_summary(reports_dir)
    decision_counts = review_decision_summary(list_review_decisions(_db_path(request)))
    learned_rule_count = _learned_rule_count(reports_dir)
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
                ("Metadata decisions", decision_counts["total_decisions"]),
                ("Album groups", album_cohesion["summary"].get("total_album_groups", 0)),
                ("Canonical artists", canonical_graph["summary"].get("canonical_artist_count", 0)),
                ("Blocked entity candidates", entity_classification["summary"].get("blocked_candidates", 0)),
                ("Low reliability evidence", reliability["summary"].get("low_reliability", 0)),
                ("Learned rules", learned_rule_count),
                ("Blocked classification", review["blocked_classification_count"]),
                (
                    "Conflicts",
                    len(review["conflicts"])
                    + album_cohesion["summary"].get("conflicting_album_groups", 0),
                ),
                ("Graph conflicts", canonical_graph["summary"].get("unresolved_conflicts", 0)),
                ("Low confidence", suggestions["confidence_counts"].get("low", 0)),
            ],
            "review_links": [
                ("Duplicate Review", "/review/duplicates", "Keep/remove candidates and active duplicate groups."),
                ("Metadata Review", "/review/metadata", "Review-only tag cleanup suggestions."),
                ("Canonical Graph", "/review/canonical-graph", "Canonical artists, albums, tracks, relationships, and unresolved ambiguity."),
                ("Entity Classification", "/review/entity-classification", "Blocked, ambiguous, source, and misclassified canonical candidates."),
                ("Entity Roles", "/review/entity-roles", "Role-aware entity evidence, multi-role values, conflicts, and blocked collisions."),
                ("Album Cohesion", "/review/albums", "Repeated-evidence album grouping, conflicts, singles, and orphans."),
                ("Evidence Reliability", "/review/reliability", "Uploader artifacts, polluted names, canonical matches, and reliability tiers."),
                ("Knowledge Review", "/review/knowledge", "Reusable evidence from approved and rejected decisions."),
                ("Blocked Items", "/review/blocked", "Items that need manual classification."),
            ],
            "confidence_counts": suggestions["confidence_counts"],
            "decision_counts": decision_counts,
            "learned_rule_count": learned_rule_count,
            "missing_files": [
                *qa["missing_files"],
                *duplicate_groups["missing_files"],
                *review["missing_files"],
                *suggestions["missing_files"],
                *album_cohesion["missing_files"],
                *reliability["missing_files"],
                *canonical_graph["missing_files"],
                *entity_classification["missing_files"],
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
    suggestions = _suggestion_summary(reports_dir, db_path=_db_path(request))
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
                ("Approved", suggestions["decision_counts"]["approved_count"]),
                ("Rejected", suggestions["decision_counts"]["rejected_count"]),
                ("Deferred", suggestions["decision_counts"]["deferred_count"]),
                ("Undecided", suggestions["decision_counts"]["undecided_count"]),
            ],
            "suggestions": _filter_rows(suggestions["suggestions"], q),
            "confidence_counts": suggestions["confidence_counts"],
            "decision_counts": suggestions["decision_counts"],
            "query": q,
            "timestamp": metadata["timestamp"],
            "missing_files": [*metadata["missing_files"], *suggestions["missing_files"]],
        },
    )


@router.get("/review/albums")
def review_albums(request: Request, q: str = ""):
    album_cohesion = _album_cohesion_summary(_reports_dir(request))
    groups = _filter_rows(album_cohesion["groups"], q)
    return _render(
        request,
        "reports/album_cohesion.html",
        {
            "title": "Album Cohesion",
            "eyebrow": "Repeated Evidence",
            "intro": "Review inferred album groupings, singles, conflicts, and orphan tracks without writing metadata or moving files.",
            "breadcrumbs": [("Review", "/review"), ("Albums", "")],
            "back_links": [("Back to Review", "/review")],
            "cards": [
                ("Album groups", album_cohesion["summary"].get("total_album_groups", 0)),
                ("High confidence", album_cohesion["summary"].get("high_confidence_groups", 0)),
                ("Medium confidence", album_cohesion["summary"].get("medium_confidence_groups", 0)),
                ("Low confidence", album_cohesion["summary"].get("low_confidence_groups", 0)),
                ("Probable singles", album_cohesion["summary"].get("probable_singles", 0)),
                ("Orphan tracks", album_cohesion["summary"].get("orphan_tracks", 0)),
                ("Conflicting groups", album_cohesion["summary"].get("conflicting_album_groups", 0)),
            ],
            "groups": groups,
            "conflicts": _filter_rows(album_cohesion["conflicts"], q),
            "orphans": _filter_rows(album_cohesion["orphans"], q),
            "query": q,
            "timestamp": album_cohesion["summary"].get("created_at"),
            "missing_files": album_cohesion["missing_files"],
        },
    )


@router.get("/review/reliability")
def review_reliability(request: Request, q: str = ""):
    reliability = _reliability_summary(_reports_dir(request))
    records = _filter_rows(reliability["records"], q)
    unreliable = [record for record in records if record["reliability_tier"] == "low"]
    uploader_artifacts = [
        record
        for record in records
        if "uploader_or_channel_signature" in record["reliability_flags"]
        or "label_channel_signature" in record["reliability_flags"]
    ]
    canonical_matches = [
        record
        for record in records
        if "canonical_match" in record["reliability_flags"]
        or "repeated_canonical_agreement" in record["reliability_flags"]
    ]
    return _render(
        request,
        "reports/evidence_reliability.html",
        {
            "title": "Evidence Reliability",
            "eyebrow": "Evidence Quality",
            "intro": "Review metadata evidence quality before downstream normalization and album inference use it.",
            "breadcrumbs": [("Review", "/review"), ("Reliability", "")],
            "back_links": [("Back to Review", "/review")],
            "cards": [
                ("Total records", reliability["summary"].get("total_records", 0)),
                ("High reliability", reliability["summary"].get("high_reliability", 0)),
                ("Medium reliability", reliability["summary"].get("medium_reliability", 0)),
                ("Low reliability", reliability["summary"].get("low_reliability", 0)),
                ("Uploader artifacts", reliability["summary"].get("uploader_artifacts_detected", 0)),
                ("Noisy titles", reliability["summary"].get("noisy_titles_detected", 0)),
                ("Canonical matches", reliability["summary"].get("canonical_matches", 0)),
            ],
            "records": records,
            "unreliable": unreliable,
            "uploader_artifacts": uploader_artifacts,
            "canonical_matches": canonical_matches,
            "query": q,
            "timestamp": reliability["summary"].get("created_at"),
            "missing_files": reliability["missing_files"],
        },
    )


@router.get("/review/canonical-graph")
def review_canonical_graph(request: Request, q: str = ""):
    graph = _canonical_graph_summary(_reports_dir(request))
    query_rows = lambda rows: _filter_rows(rows, q)
    relationships = query_rows(graph["relationships"])
    aliases = [row for row in relationships if row.get("relationship_type") == "alias_of"]
    return _render(
        request,
        "reports/canonical_graph.html",
        {
            "title": "Canonical Graph",
            "eyebrow": "Entity Resolution",
            "intro": "Inspect persistent canonical entity hypotheses and evidence-governed relationships without applying metadata changes.",
            "breadcrumbs": [("Review", "/review"), ("Canonical Graph", "")],
            "back_links": [("Back to Review", "/review")],
            "cards": [
                ("Canonical artists", graph["summary"].get("canonical_artist_count", 0)),
                ("Canonical albums", graph["summary"].get("canonical_album_count", 0)),
                ("Canonical tracks", graph["summary"].get("canonical_track_count", 0)),
                ("Alias relationships", graph["summary"].get("alias_relationships", 0)),
                ("Duplicate relationships", graph["summary"].get("duplicate_relationships", 0)),
                ("Unresolved conflicts", graph["summary"].get("unresolved_conflicts", 0)),
                ("High confidence", graph["summary"].get("high_confidence_entities", 0)),
                ("Low confidence", graph["summary"].get("low_confidence_entities", 0)),
            ],
            "artists": query_rows(graph["artists"]),
            "albums": query_rows(graph["albums"]),
            "tracks": query_rows(graph["tracks"]),
            "aliases": aliases,
            "relationships": relationships,
            "conflicts": query_rows(graph["conflicts"]),
            "query": q,
            "timestamp": graph["summary"].get("created_at"),
            "missing_files": graph["missing_files"],
        },
    )


@router.get("/review/entity-classification")
def review_entity_classification(request: Request, q: str = ""):
    classification = _entity_classification_summary(_reports_dir(request))
    records = _filter_rows(classification["classifications"], q)
    blocked = _filter_rows(classification["blocked"], q)
    ambiguous = _filter_rows(classification["ambiguous"], q)
    source_artifacts = [
        row
        for row in records
        if row.get("proposed_entity_type") in {"source_or_label_artifact", "uploader_channel_artifact"}
    ]
    misclassified_artists = [
        row
        for row in records
        if row.get("proposed_entity_type") in {"track_title_misclassified_as_artist", "album_title_misclassified_as_artist"}
    ]
    return _render(
        request,
        "reports/entity_classification.html",
        {
            "title": "Entity Classification",
            "eyebrow": "Canonical Guardrail",
            "intro": "Inspect deterministic candidate classifications before canonical graph promotion. This page is read-only.",
            "breadcrumbs": [("Review", "/review"), ("Entity Classification", "")],
            "back_links": [("Back to Review", "/review")],
            "cards": [
                ("Total candidates", classification["summary"].get("total_candidates", 0)),
                ("Canonical artists", classification["summary"].get("canonical_artist_candidates", 0)),
                ("Canonical albums", classification["summary"].get("canonical_album_candidates", 0)),
                ("Canonical tracks", classification["summary"].get("canonical_track_candidates", 0)),
                ("Blocked", classification["summary"].get("blocked_candidates", 0)),
                ("Ambiguous", classification["summary"].get("ambiguous_candidates", 0)),
                ("Source artifacts", classification["summary"].get("source_artifacts", 0)),
                ("Misclassified track titles", classification["summary"].get("misclassified_track_titles", 0)),
            ],
            "blocked": blocked,
            "ambiguous": ambiguous,
            "source_artifacts": source_artifacts,
            "misclassified_artists": misclassified_artists,
            "records": records,
            "query": q,
            "timestamp": classification["summary"].get("created_at"),
            "missing_files": classification["missing_files"],
        },
    )


@router.get("/review/entity-roles")
def review_entity_roles(request: Request, q: str = ""):
    entity_roles = _entity_role_summary(_reports_dir(request))
    records = _filter_rows(entity_roles["records"], q)
    return _render(
        request,
        "reports/entity_roles.html",
        {
            "title": "Entity Roles",
            "eyebrow": "Contextual Roles",
            "intro": "Inspect role-aware entity evidence without globally blocking values that appear in more than one role. This page is read-only.",
            "breadcrumbs": [("Review", "/review"), ("Entity Roles", "")],
            "back_links": [("Back to Review", "/review")],
            "cards": [
                ("Role records", entity_roles["summary"].get("total_role_records", 0)),
                ("Multi-role entities", entity_roles["summary"].get("multi_role_entities", 0)),
                ("Conflicted roles", entity_roles["summary"].get("conflicted_roles", 0)),
                ("Canonical agreements", entity_roles["summary"].get("canonical_role_agreements", 0)),
                ("Blocked collisions", entity_roles["summary"].get("blocked_role_collisions", 0)),
            ],
            "records": records,
            "multi_role": _filter_rows(entity_roles["multi_role"], q),
            "conflicted": _filter_rows(entity_roles["conflicted"], q),
            "blocked": _filter_rows(entity_roles["blocked"], q),
            "query": q,
            "timestamp": entity_roles["summary"].get("created_at"),
            "missing_files": entity_roles["missing_files"],
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
            "app_name": "Music Library Intelligence Platform",
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


def _db_path(request: Request) -> Path:
    configured = getattr(request.app.state, "db_path", db.DEFAULT_DB_PATH)
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


def _suggestion_summary(reports_dir: Path, *, db_path: Path | str) -> dict[str, Any]:
    suggestions, missing_files = _read_suggestions(reports_dir)
    suggestions = attach_decisions_to_suggestions(suggestions, decisions_by_key(db_path))
    confidence_counts = Counter({"high": 0, "medium": 0, "low": 0})
    requires_human_review = 0
    for suggestion in suggestions:
        confidence_counts[suggestion["confidence"]] += 1
        if suggestion["requires_human_review"]:
            requires_human_review += 1
    decided = [suggestion for suggestion in suggestions if suggestion.get("decision")]
    decision_counts = review_decision_summary(decided)
    decision_counts["undecided_count"] = len(suggestions) - decision_counts["total_decisions"]
    return {
        "suggestions": suggestions,
        "total": len(suggestions),
        "requires_human_review": requires_human_review,
        "confidence_counts": dict(confidence_counts),
        "decision_counts": decision_counts,
        "missing_files": missing_files,
    }


def _album_cohesion_summary(reports_dir: Path) -> dict[str, Any]:
    summary, groups, conflicts, orphans, missing_files = read_album_cohesion_report(
        reports_dir
    )
    normalized_groups = []
    for group in groups:
        rationale = group.get("rationale", [])
        if isinstance(rationale, str):
            rationale = [rationale]
        elif not isinstance(rationale, list):
            rationale = []
        normalized_groups.append(
            {
                **group,
                "cohesion_score": float(group.get("cohesion_score", 0.0) or 0.0),
                "confidence_tier": str(group.get("confidence_tier", "low") or "low"),
                "rationale": [str(item) for item in rationale],
                "tracks": group.get("tracks", []) if isinstance(group.get("tracks"), list) else [],
            }
        )
    return {
        "summary": summary,
        "groups": normalized_groups,
        "conflicts": conflicts,
        "orphans": orphans,
        "missing_files": missing_files,
    }


def _reliability_summary(reports_dir: Path) -> dict[str, Any]:
    summary, records, unreliable, reliable, missing_files = read_evidence_reliability_report(reports_dir)
    return {
        "summary": summary,
        "records": records,
        "unreliable": unreliable,
        "reliable": reliable,
        "missing_files": missing_files,
    }


def _canonical_graph_summary(reports_dir: Path) -> dict[str, Any]:
    summary, artists, albums, tracks, relationships, conflicts, missing_files = read_canonical_graph_report(reports_dir)
    return {
        "summary": summary,
        "artists": artists,
        "albums": albums,
        "tracks": tracks,
        "relationships": relationships,
        "conflicts": conflicts,
        "missing_files": missing_files,
    }


def _entity_classification_summary(reports_dir: Path) -> dict[str, Any]:
    summary, classifications, blocked, ambiguous, missing_files = read_entity_classification_report(reports_dir)
    return {
        "summary": summary,
        "classifications": classifications,
        "blocked": blocked,
        "ambiguous": ambiguous,
        "missing_files": missing_files,
    }


def _entity_role_summary(reports_dir: Path) -> dict[str, Any]:
    summary, records, multi_role, conflicted, blocked, missing_files = read_entity_role_report(reports_dir)
    return {
        "summary": summary,
        "records": records,
        "multi_role": multi_role,
        "conflicted": conflicted,
        "blocked": blocked,
        "missing_files": missing_files,
    }


def _learned_rule_count(reports_dir: Path) -> int:
    path = reports_dir / "normalization_knowledge" / "normalization_knowledge_rules.json"
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    return len(rules) if isinstance(rules, list) else 0


def _organization_preview_data(
    *,
    db_path: Path,
    scan_run_id: int | None,
    placement_status: str,
    identity_status: str,
    classification_status: str,
    query: str,
) -> dict[str, Any]:
    if not db_path.exists():
        return _empty_organization_preview(
            missing_files=[str(db_path)],
            filters=_organization_filters(
                scan_run_id=scan_run_id,
                placement_status=placement_status,
                identity_status=identity_status,
                classification_status=classification_status,
                query=query,
            ),
        )

    with db.connect(db_path) as connection:
        scan_runs = _organization_scan_runs(connection)
        selected_scan = _selected_scan_run(
            scan_runs=scan_runs,
            scan_run_id=scan_run_id,
        )
        if selected_scan is None:
            return _empty_organization_preview(
                scan_runs=scan_runs,
                missing_files=[],
                filters=_organization_filters(
                    scan_run_id=scan_run_id,
                    placement_status=placement_status,
                    identity_status=identity_status,
                    classification_status=classification_status,
                    query=query,
                ),
            )
        all_rows = _organization_rows(connection, selected_scan["id"])

    status_options = {
        "placement_statuses": _status_options(all_rows, "placement_status"),
        "identity_statuses": _status_options(all_rows, "identity_status"),
        "classification_statuses": _status_options(all_rows, "classification_status"),
    }
    filters = _organization_filters(
        scan_run_id=selected_scan["id"],
        placement_status=placement_status,
        identity_status=identity_status,
        classification_status=classification_status,
        query=query,
    )
    rows = _filter_organization_rows(
        all_rows,
        placement_status=placement_status,
        identity_status=identity_status,
        classification_status=classification_status,
        query=query,
    )
    return {
        "cards": _organization_cards(selected_scan, all_rows),
        "scan_run": selected_scan,
        "scan_runs": scan_runs,
        "latest_scan_run": scan_runs[0] if scan_runs else None,
        "rows": rows,
        "row_count": len(rows),
        "total_row_count": len(all_rows),
        "tree_groups": _organization_tree_groups(all_rows),
        "filters": filters,
        **status_options,
        "missing_files": [],
    }


def _empty_organization_preview(
    *,
    missing_files: list[str],
    filters: dict[str, Any],
    scan_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "cards": _organization_cards(None, []),
        "scan_run": None,
        "scan_runs": scan_runs or [],
        "latest_scan_run": scan_runs[0] if scan_runs else None,
        "rows": [],
        "row_count": 0,
        "total_row_count": 0,
        "tree_groups": _organization_tree_groups([]),
        "filters": filters,
        "placement_statuses": [],
        "identity_statuses": [],
        "classification_statuses": [],
        "missing_files": missing_files,
    }


def _organization_scan_runs(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            id,
            source_path,
            started_at,
            completed_at,
            status,
            total_files_seen,
            audio_files_seen,
            files_failed
        FROM scan_runs
        ORDER BY id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _selected_scan_run(
    *,
    scan_runs: list[dict[str, Any]],
    scan_run_id: int | None,
) -> dict[str, Any] | None:
    if scan_run_id is None:
        return scan_runs[0] if scan_runs else None
    return next((row for row in scan_runs if row["id"] == scan_run_id), None)


def _organization_rows(connection, scan_run_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            observed_files.id AS observed_file_id,
            observed_files.relative_path AS original_relative_path,
            observed_files.filename,
            observed_files.extension,
            track_identity.identity_status,
            track_identity.probable_artist,
            track_identity.probable_album,
            track_identity.probable_title,
            classification_results.classification_status,
            classification_results.primary_genre,
            classification_results.subgenre,
            placement_plans.placement_status,
            placement_plans.planned_relative_path,
            placement_plans.reason_json
        FROM observed_files
        LEFT JOIN track_identity
            ON track_identity.observed_file_id = observed_files.id
        LEFT JOIN classification_results
            ON classification_results.observed_file_id = observed_files.id
        LEFT JOIN placement_plans
            ON placement_plans.observed_file_id = observed_files.id
            AND placement_plans.scan_run_id = observed_files.scan_run_id
        WHERE observed_files.scan_run_id = ?
        ORDER BY observed_files.relative_path
        """,
        (scan_run_id,),
    ).fetchall()
    return [_organization_row(dict(row)) for row in rows]


def _organization_row(row: dict[str, Any]) -> dict[str, Any]:
    identity_status = row.get("identity_status") or "unknown"
    classification_status = row.get("classification_status") or "unknown"
    placement_status = row.get("placement_status") or "not_planned"
    reason = _compact_reason(row.get("reason_json"))
    return {
        **row,
        "identity_status": identity_status,
        "classification_status": classification_status,
        "placement_status": placement_status,
        "reason_summary": reason,
        "tree_zone": _organization_zone(row.get("planned_relative_path")),
    }


def _compact_reason(reason_json: str | None) -> str:
    if not reason_json:
        return ""
    try:
        payload = json.loads(reason_json)
    except (TypeError, json.JSONDecodeError):
        return str(reason_json)
    if not isinstance(payload, dict):
        return str(reason_json)
    parts: list[str] = []
    reasons = payload.get("reasons")
    if isinstance(reasons, list) and reasons:
        parts.append(", ".join(str(reason) for reason in reasons))
    album_reason = payload.get("album_reason")
    if album_reason:
        parts.append(f"album: {album_reason}")
    return " | ".join(parts) if parts else json.dumps(payload, sort_keys=True)


def _organization_cards(
    scan_run: dict[str, Any] | None,
    rows: list[dict[str, Any]],
) -> list[tuple[str, Any]]:
    identity_counts = Counter(row["identity_status"] for row in rows)
    classification_counts = Counter(row["classification_status"] for row in rows)
    placement_counts = Counter(row["placement_status"] for row in rows)
    blocked_count = sum(
        count
        for status, count in placement_counts.items()
        if str(status).startswith("blocked_")
    )
    return [
        ("Scan run", scan_run["id"] if scan_run else "None"),
        ("Total files", scan_run.get("total_files_seen", 0) if scan_run else 0),
        ("Audio files", scan_run.get("audio_files_seen", 0) if scan_run else 0),
        ("Files failed", scan_run.get("files_failed", 0) if scan_run else 0),
        ("Identified", identity_counts.get("identified", 0)),
        ("Partial", identity_counts.get("partial", 0)),
        ("Conflicting", identity_counts.get("conflicting", 0)),
        ("Identity unknown", identity_counts.get("unknown", 0)),
        ("Classified", classification_counts.get("classified", 0)),
        ("Uncertain", classification_counts.get("uncertain", 0)),
        ("Classification unknown", classification_counts.get("unknown", 0)),
        ("Planned", placement_counts.get("planned", 0)),
        ("Review", placement_counts.get("needs_review", 0)),
        ("Blocked", blocked_count),
        ("Conflict", placement_counts.get("conflict", 0)),
    ]


def _filter_organization_rows(
    rows: list[dict[str, Any]],
    *,
    placement_status: str,
    identity_status: str,
    classification_status: str,
    query: str,
) -> list[dict[str, Any]]:
    query_key = query.casefold().strip()
    filtered = []
    for row in rows:
        if placement_status and row["placement_status"] != placement_status:
            continue
        if identity_status and row["identity_status"] != identity_status:
            continue
        if classification_status and row["classification_status"] != classification_status:
            continue
        if query_key and query_key not in " ".join(
            str(row.get(key) or "")
            for key in (
                "original_relative_path",
                "probable_artist",
                "probable_album",
                "probable_title",
                "planned_relative_path",
            )
        ).casefold():
            continue
        filtered.append(row)
    return filtered


def _organization_tree_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = {
        "OrganizedLibrary/Music": [],
        "OrganizedLibrary/_Review": [],
        "OrganizedLibrary/_Unresolved": [],
        "Other": [],
    }
    for row in rows:
        path = row.get("planned_relative_path")
        if not path:
            continue
        groups.setdefault(_organization_zone(path), []).append(path)
    return [
        {
            "zone": zone,
            "count": len(paths),
            "paths": sorted(paths, key=str.casefold),
        }
        for zone, paths in groups.items()
        if paths or zone != "Other"
    ]


def _organization_zone(path: str | None) -> str:
    if not path:
        return "Other"
    parts = str(path).split("/")
    if len(parts) >= 2 and parts[0] == "OrganizedLibrary":
        if parts[1] == "Music":
            return "OrganizedLibrary/Music"
        if parts[1] == "_Review":
            return "OrganizedLibrary/_Review"
        if parts[1] == "_Unresolved":
            return "OrganizedLibrary/_Unresolved"
    return "Other"


def _status_options(rows: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(row[key]) for row in rows if row.get(key)})


def _organization_filters(
    *,
    scan_run_id: int | None,
    placement_status: str,
    identity_status: str,
    classification_status: str,
    query: str,
) -> dict[str, Any]:
    return {
        "scan_run_id": scan_run_id,
        "placement_status": placement_status,
        "identity_status": identity_status,
        "classification_status": classification_status,
        "query": query,
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
        ("/library/organization-preview", "Organization Preview"),
        ("/review", "Review"),
        ("/review/duplicates", "Duplicates"),
        ("/review/metadata", "Metadata"),
        ("/review/canonical-graph", "Canonical Graph"),
        ("/review/entity-classification", "Entity Classification"),
        ("/review/entity-roles", "Entity Roles"),
        ("/review/albums", "Album Cohesion"),
        ("/review/reliability", "Reliability"),
        ("/review/knowledge", "Knowledge"),
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
