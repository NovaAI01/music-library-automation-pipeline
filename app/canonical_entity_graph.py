"""Persistent evidence-governed canonical entity graph.

The graph is observational. It records canonical entity hypotheses and
relationships from accumulated local evidence, but it never writes tags, moves
files, or collapses conflicting entities automatically.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.album_cohesion import read_album_cohesion_report
from app.canonical_entity_classifier import (
    AMBIGUOUS_TYPE,
    BLOCKING_TYPES,
    EntityClassification,
    build_candidate_contexts,
    classify_candidate,
    classification_summary,
)
from app.canonical_confidence import confidence_tier as weighted_confidence_tier
from app.canonical_confidence import score_canonical_entity
from app.entity_roles import EntityRoleRecord, aggregate_entity_roles, entity_role_summary
from app.evidence_reliability import read_evidence_reliability_report, score_evidence
from app.filename_parser import parse_filename
from app.normalization_knowledge import derive_normalization_rules
from app.promotion_lifecycle import graph_lifecycle_state
from app.review_decisions import list_review_decisions


REPORT_DIRNAME = "canonical_graph"
ENTITY_FIELDS: tuple[str, ...] = (
    "canonical_id",
    "canonical_name",
    "confidence_score",
    "confidence_tier",
    "evidence_count",
    "conflict_count",
    "first_seen",
    "last_seen",
    "status",
)
RELATIONSHIP_FIELDS: tuple[str, ...] = (
    "relationship_id",
    "source_entity",
    "target_entity",
    "relationship_type",
    "confidence_score",
    "supporting_evidence_count",
    "conflicting_evidence_count",
    "rationale",
    "created_at",
)
CONFLICT_FIELDS: tuple[str, ...] = (
    "conflict_id",
    "entity_type",
    "entity_key",
    "variants",
    "evidence_count",
    "conflict_count",
    "rationale",
    "created_at",
)


@dataclass(frozen=True)
class CanonicalEntity:
    canonical_id: str
    canonical_name: str
    confidence_score: float
    confidence_tier: str
    evidence_count: int
    conflict_count: int
    first_seen: str
    last_seen: str
    status: str


@dataclass(frozen=True)
class EntityRelationship:
    relationship_id: str
    source_entity: str
    target_entity: str
    relationship_type: str
    confidence_score: float
    supporting_evidence_count: int
    conflicting_evidence_count: int
    rationale: str
    created_at: str


@dataclass(frozen=True)
class UnresolvedConflict:
    conflict_id: str
    entity_type: str
    entity_key: str
    variants: str
    evidence_count: int
    conflict_count: int
    rationale: str
    created_at: str


@dataclass(frozen=True)
class CanonicalGraph:
    artists: list[CanonicalEntity]
    albums: list[CanonicalEntity]
    tracks: list[CanonicalEntity]
    versions: list[CanonicalEntity]
    relationships: list[EntityRelationship]
    unresolved_conflicts: list[UnresolvedConflict]
    summary: dict[str, Any]


@dataclass(frozen=True)
class CanonicalGraphResult:
    report_path: str
    canonical_artist_count: int
    canonical_album_count: int
    canonical_track_count: int
    blocked_candidate_count: int
    alias_relationships: int
    duplicate_relationships: int
    unresolved_conflicts: int
    high_confidence_entities: int
    medium_confidence_entities: int
    low_confidence_entities: int


@dataclass(frozen=True)
class TrackEvidence:
    file_path: str
    artist: str
    title: str
    album: str
    source_folder: str
    filename_artist: str
    filename_title: str
    observed_at: str
    reliability: float


def generate_canonical_graph(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> CanonicalGraphResult:
    """Build, persist, and export canonical graph reports."""

    db.init_db(db_path)
    out_path = Path(out_dir).expanduser()
    report_dir = out_path / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)

    graph = build_canonical_graph(reports_dir=out_path, db_path=db_path)
    persist_canonical_graph(graph, db_path=db_path)
    _write_reports(report_dir, graph)
    result_payload = {
        field: graph.summary[field]
        for field in CanonicalGraphResult.__dataclass_fields__
        if field != "report_path"
    }
    return CanonicalGraphResult(report_path=str(report_dir), **result_payload)


def build_canonical_graph(
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> CanonicalGraph:
    now = _utc_now()
    track_evidence = _load_track_evidence(db_path)
    decisions = list_review_decisions(db_path)
    rules = list(derive_normalization_rules(db_path=db_path))
    _, album_groups, album_conflicts, _, _ = read_album_cohesion_report(reports_dir)
    reliability_summary, reliability_records, _, _, _ = read_evidence_reliability_report(reports_dir)
    entity_classifications = _classify_graph_candidates(
        track_evidence=track_evidence,
        reports_dir=reports_dir,
        db_path=db_path,
    )
    role_records = _graph_role_records(track_evidence)

    artist_aliases = _artist_alias_map(decisions, rules)
    artists, artist_lookup, artist_conflicts = _build_artists(
        track_evidence=track_evidence,
        decisions=decisions,
        rules=rules,
        artist_aliases=artist_aliases,
        entity_classifications=entity_classifications,
        now=now,
    )
    albums, album_lookup, album_conflicts_out = _build_albums(
        track_evidence=track_evidence,
        album_groups=album_groups,
        album_conflicts=album_conflicts,
        artist_lookup=artist_lookup,
        artist_aliases=artist_aliases,
        entity_classifications=entity_classifications,
        now=now,
    )
    tracks, track_lookup, track_groups, track_conflicts = _build_tracks(
        track_evidence=track_evidence,
        artist_lookup=artist_lookup,
        artist_aliases=artist_aliases,
        now=now,
    )
    versions = _dedupe_entities(_build_versions(track_evidence, track_lookup, now=now))
    artists = _dedupe_entities(artists)
    albums = _dedupe_entities(albums)
    tracks = _dedupe_entities(tracks)
    relationships = _dedupe_relationships(_relationships(
        artists=artists,
        artist_lookup=artist_lookup,
        artist_aliases=artist_aliases,
        albums=albums,
        album_lookup=album_lookup,
        tracks=tracks,
        track_lookup=track_lookup,
        track_groups=track_groups,
        versions=versions,
        track_evidence=track_evidence,
        album_groups=album_groups,
        reliability_records=reliability_records,
        now=now,
    ))
    unresolved = sorted(
        [*artist_conflicts, *album_conflicts_out, *track_conflicts, *_role_conflicts(role_records, now)],
        key=lambda item: (item.entity_type, item.entity_key),
    )
    summary = _summary(
        artists=artists,
        albums=albums,
        tracks=tracks,
        versions=versions,
        relationships=relationships,
        unresolved=unresolved,
        reliability_summary=reliability_summary,
        classification_summary=classification_summary(entity_classifications.values()),
        role_summary=entity_role_summary(role_records),
        now=now,
    )
    return CanonicalGraph(
        artists=artists,
        albums=albums,
        tracks=tracks,
        versions=versions,
        relationships=relationships,
        unresolved_conflicts=unresolved,
        summary=summary,
    )


def persist_canonical_graph(
    graph: CanonicalGraph,
    *,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> None:
    """Persist the current graph snapshot without touching media metadata."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        for table in (
            "canonical_artists",
            "canonical_albums",
            "canonical_tracks",
            "canonical_versions",
            "entity_relationships",
            "canonical_unresolved_conflicts",
        ):
            connection.execute(f"DELETE FROM {table}")
        _insert_entities(connection, "canonical_artists", _dedupe_entities(graph.artists))
        _insert_entities(connection, "canonical_albums", _dedupe_entities(graph.albums))
        _insert_entities(connection, "canonical_tracks", _dedupe_entities(graph.tracks))
        _insert_entities(connection, "canonical_versions", _dedupe_entities(graph.versions))
        _insert_relationships(connection, _dedupe_relationships(graph.relationships))
        _insert_conflicts(connection, graph.unresolved_conflicts)


def read_canonical_graph_report(
    reports_dir: str | Path = "reports",
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[str]]:
    report_dir = Path(reports_dir).expanduser() / REPORT_DIRNAME
    summary, missing_summary = _read_json(report_dir / "graph_summary.json")
    artists, missing_artists = _read_csv(report_dir / "canonical_artists.csv")
    albums, missing_albums = _read_csv(report_dir / "canonical_albums.csv")
    tracks, missing_tracks = _read_csv(report_dir / "canonical_tracks.csv")
    relationships, missing_relationships = _read_csv(report_dir / "entity_relationships.csv")
    conflicts, missing_conflicts = _read_csv(report_dir / "unresolved_conflicts.csv")
    return (
        summary,
        artists,
        albums,
        tracks,
        relationships,
        conflicts,
        [
            label
            for label in (
                missing_summary,
                missing_artists,
                missing_albums,
                missing_tracks,
                missing_relationships,
                missing_conflicts,
            )
            if label
        ],
    )


def canonical_artist_lookup(
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> dict[str, dict[str, Any]]:
    graph = build_canonical_graph(reports_dir=reports_dir, db_path=db_path)
    lookup: dict[str, dict[str, Any]] = {}
    for artist in graph.artists:
        payload = asdict(artist)
        lookup[_norm(artist.canonical_name)] = payload
    for relationship in graph.relationships:
        if relationship.relationship_type != "alias_of":
            continue
        source_name = relationship.source_entity.split(":", 1)[-1]
        target = next(
            (
                artist
                for artist in graph.artists
                if f"canonical_artists:{artist.canonical_id}" == relationship.target_entity
            ),
            None,
        )
        if target is not None:
            lookup[_norm(source_name)] = asdict(target)
    return lookup


def canonical_track_lookup(
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> dict[str, dict[str, Any]]:
    graph = build_canonical_graph(reports_dir=reports_dir, db_path=db_path)
    return {_norm(track.canonical_name): asdict(track) for track in graph.tracks}


def _load_track_evidence(db_path: str | Path) -> list[TrackEvidence]:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                observed_files.source_path,
                observed_files.relative_path,
                observed_files.parent_folder,
                observed_files.filename,
                observed_files.created_at,
                tag_observations.artist AS tag_artist,
                tag_observations.album_artist AS tag_album_artist,
                tag_observations.title AS tag_title,
                tag_observations.album AS tag_album,
                filename_observations.possible_artist AS filename_artist,
                filename_observations.possible_title AS filename_title,
                track_identity.probable_artist,
                track_identity.probable_title,
                track_identity.probable_album
            FROM observed_files
            LEFT JOIN tag_observations
                ON tag_observations.observed_file_id = observed_files.id
            LEFT JOIN filename_observations
                ON filename_observations.observed_file_id = observed_files.id
            LEFT JOIN track_identity
                ON track_identity.observed_file_id = observed_files.id
            ORDER BY observed_files.id
            """
        ).fetchall()
    evidence: list[TrackEvidence] = []
    for row in rows:
        parsed = parse_filename(str(row["filename"] or ""))
        artist = _clean(row["probable_artist"]) or _clean(row["tag_artist"]) or _clean(row["tag_album_artist"]) or _clean(row["filename_artist"]) or parsed.possible_artist or ""
        title = _clean(row["probable_title"]) or _clean(row["tag_title"]) or _clean(row["filename_title"]) or parsed.possible_title or Path(str(row["filename"] or "")).stem
        album = _clean(row["probable_album"]) or _clean(row["tag_album"]) or ""
        reliability = score_evidence(artist, field="artist", folder_value=str(row["parent_folder"] or "")).reliability_score
        evidence.append(
            TrackEvidence(
                file_path=str(row["source_path"] or row["relative_path"] or row["filename"]),
                artist=artist,
                title=title,
                album=album,
                source_folder=str(row["parent_folder"] or ""),
                filename_artist=_clean(row["filename_artist"]) or parsed.possible_artist or "",
                filename_title=_clean(row["filename_title"]) or parsed.possible_title or "",
                observed_at=str(row["created_at"] or _utc_now()),
                reliability=reliability,
            )
        )
    return evidence


def _artist_alias_map(decisions: list[dict[str, Any]], rules: list[Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for row in decisions:
        field = str(row.get("field", ""))
        if row.get("decision") != "approved" or field not in {"artist", "album_artist"}:
            continue
        current = _clean(row.get("current_value"))
        proposed = _clean(row.get("proposed_value"))
        if current and proposed:
            aliases[_norm(current)] = proposed
    for rule in rules:
        if getattr(rule, "rule_type", "") == "artist_alias" and getattr(rule, "confidence", "") != "rejected_pattern":
            source = _clean(getattr(rule, "source_value", ""))
            target = _clean(getattr(rule, "target_value", ""))
            if source and target:
                aliases[_norm(source)] = target
    return aliases


def _build_artists(
    *,
    track_evidence: list[TrackEvidence],
    decisions: list[dict[str, Any]],
    rules: list[Any],
    artist_aliases: dict[str, str],
    entity_classifications: dict[tuple[str, str, str], EntityClassification],
    now: str,
) -> tuple[list[CanonicalEntity], dict[str, str], list[UnresolvedConflict]]:
    grouped: defaultdict[str, list[tuple[str, float, str]]] = defaultdict(list)
    blocked_conflicts: dict[tuple[str, str], UnresolvedConflict] = {}
    for item in track_evidence:
        if item.artist:
            classification = _classification_for(entity_classifications, "artist", item.file_path, item.artist)
            if _blocks_promotion(classification):
                blocked_conflicts[("artist", _norm(item.artist))] = _classification_conflict("artist", item.artist, classification, now)
            else:
                canonical = artist_aliases.get(_norm(item.artist), item.artist)
                grouped[_norm(canonical)].append((item.artist, item.reliability, item.observed_at))
        if item.filename_artist:
            classification = _classification_for(entity_classifications, "filename_artist", item.file_path, item.filename_artist)
            if _blocks_promotion(classification):
                blocked_conflicts[("artist", _norm(item.filename_artist))] = _classification_conflict("artist", item.filename_artist, classification, now)
            else:
                canonical = artist_aliases.get(_norm(item.filename_artist), item.filename_artist)
                grouped[_norm(canonical)].append((item.filename_artist, 0.58, item.observed_at))
    for row in decisions:
        if str(row.get("field", "")) not in {"artist", "album_artist"}:
            continue
        value = _clean(row.get("proposed_value")) if row.get("decision") == "approved" else _clean(row.get("current_value"))
        if value:
            grouped[_norm(artist_aliases.get(_norm(value), value))].append((value, 0.86 if row.get("decision") == "approved" else 0.45, str(row.get("decided_at", now))))
    for rule in rules:
        if getattr(rule, "rule_type", "") == "artist_alias":
            target = _clean(getattr(rule, "target_value", ""))
            if target:
                grouped[_norm(target)].append((target, 0.82, now))

    entities: list[CanonicalEntity] = []
    lookup: dict[str, str] = {}
    conflicts: list[UnresolvedConflict] = []
    for key, values in sorted(grouped.items()):
        names = [name for name, _, _ in values if name]
        variants = {_display_key(name): name for name in names}
        conflict_count = _case_conflict_count(names)
        approved_targets = {target for source, target in artist_aliases.items() if _norm(target) == key}
        if approved_targets:
            conflict_count = 0
        canonical_name = _best_name(names, preferred=approved_targets)
        score = _score_entity(
            entity_type="artist",
            entity_value=canonical_name,
            evidence_count=len(values),
            conflict_count=conflict_count,
            average_reliability=sum(score for _, score, _ in values) / len(values),
            approvals=len(approved_targets),
            seen_values=[seen for _, _, seen in values],
            folder_agreement=True,
            role_agreement=True,
        )
        entity = _entity("artist", key, canonical_name, score, len(values), conflict_count, [seen for _, _, seen in values], now)
        entities.append(entity)
        for name in variants.values():
            lookup[_norm(name)] = entity.canonical_id
        lookup[key] = entity.canonical_id
        if conflict_count:
            conflicts.append(
                _conflict(
                    "artist",
                    key,
                    sorted(variants.values(), key=str.casefold),
                    len(values),
                    conflict_count,
                    "artist variants disagree without enough approved alias evidence",
                    now,
                )
            )
    return entities, lookup, [*blocked_conflicts.values(), *conflicts]


def _build_albums(
    *,
    track_evidence: list[TrackEvidence],
    album_groups: list[dict[str, Any]],
    album_conflicts: list[dict[str, str]],
    artist_lookup: dict[str, str],
    artist_aliases: dict[str, str],
    entity_classifications: dict[tuple[str, str, str], EntityClassification],
    now: str,
) -> tuple[list[CanonicalEntity], dict[str, str], list[UnresolvedConflict]]:
    grouped: defaultdict[str, list[tuple[str, float, str]]] = defaultdict(list)
    conflict_keys = {_norm(row.get("artist", "") + ":" + row.get("album", "")) for row in album_conflicts}
    blocked_conflicts: dict[tuple[str, str], UnresolvedConflict] = {}
    for item in track_evidence:
        if not item.album:
            continue
        classification = _classification_for(entity_classifications, "album", item.file_path, item.album)
        if _blocks_promotion(classification):
            blocked_conflicts[("album", _norm(item.album))] = _classification_conflict("album", item.album, classification, now)
            continue
        artist = artist_aliases.get(_norm(item.artist), item.artist)
        key = f"{artist_lookup.get(_norm(artist), _norm(artist))}:{_norm(item.album)}"
        grouped[key].append((item.album, 0.62, item.observed_at))
    for group in album_groups:
        album = _clean(group.get("album"))
        artist = artist_aliases.get(_norm(group.get("artist", "")), _clean(group.get("artist")))
        if not album:
            continue
        key = f"{artist_lookup.get(_norm(artist), _norm(artist))}:{_norm(album)}"
        grouped[key].append((album, float(group.get("cohesion_score") or 0.5), now))

    entities: list[CanonicalEntity] = []
    lookup: dict[str, str] = {}
    conflicts: list[UnresolvedConflict] = []
    for key, values in sorted(grouped.items()):
        names = [name for name, _, _ in values if name]
        conflict_count = _case_conflict_count(names)
        if _norm(key) in conflict_keys:
            conflict_count += 1
        canonical_name = _best_name(names)
        score = _score_entity(
            entity_type="album",
            entity_value=canonical_name,
            evidence_count=len(values),
            conflict_count=conflict_count,
            average_reliability=sum(score for _, score, _ in values) / len(values),
            approvals=0,
            seen_values=[seen for _, _, seen in values],
            role_agreement=True,
            album_cohesion_count=sum(1 for _, score, _ in values if score >= 0.7),
            weak_album_cohesion=any(score < 0.55 for _, score, _ in values),
        )
        entity = _entity("album", key, canonical_name, score, len(values), conflict_count, [seen for _, _, seen in values], now)
        entities.append(entity)
        lookup[key] = entity.canonical_id
        if conflict_count:
            conflicts.append(_conflict("album", key, sorted(set(names), key=str.casefold), len(values), conflict_count, "album evidence has unresolved tag, folder, or casing conflict", now))
    return entities, lookup, [*blocked_conflicts.values(), *conflicts]


def _build_tracks(
    *,
    track_evidence: list[TrackEvidence],
    artist_lookup: dict[str, str],
    artist_aliases: dict[str, str],
    now: str,
) -> tuple[list[CanonicalEntity], dict[str, str], dict[str, list[TrackEvidence]], list[UnresolvedConflict]]:
    grouped: defaultdict[str, list[TrackEvidence]] = defaultdict(list)
    for item in track_evidence:
        artist = artist_aliases.get(_norm(item.artist), item.artist)
        artist_id = artist_lookup.get(_norm(artist), _norm(artist))
        key = f"{artist_id}:{_norm(_base_title(item.title))}"
        grouped[key].append(item)
    entities: list[CanonicalEntity] = []
    lookup: dict[str, str] = {}
    conflicts: list[UnresolvedConflict] = []
    for key, values in sorted(grouped.items()):
        titles = [item.title for item in values if item.title]
        variants = sorted(set(titles), key=str.casefold)
        conflict_count = max(0, len({_version_marker(title) for title in titles if _version_marker(title)}) - 1)
        canonical_name = _best_name([_base_title(title) for title in titles]) or _best_name(titles)
        avg_reliability = sum(item.reliability for item in values) / len(values)
        score = _score_entity(
            entity_type="track",
            entity_value=canonical_name,
            evidence_count=len(values),
            conflict_count=conflict_count,
            average_reliability=avg_reliability,
            approvals=0,
            seen_values=[item.observed_at for item in values],
            role_agreement=True,
        )
        entity = _entity("track", key, canonical_name, score, len(values), conflict_count, [item.observed_at for item in values], now)
        entities.append(entity)
        lookup[key] = entity.canonical_id
        if conflict_count:
            conflicts.append(_conflict("track", key, variants, len(values), conflict_count, "alternate version markers conflict with base track identity", now))
    return entities, lookup, dict(grouped), conflicts


def _build_versions(track_evidence: list[TrackEvidence], track_lookup: dict[str, str], *, now: str) -> list[CanonicalEntity]:
    versions: list[CanonicalEntity] = []
    for item in track_evidence:
        version_name = item.title
        marker = _version_marker(item.title)
        if marker:
            version_name = f"{_base_title(item.title)} ({marker})"
        key = f"{item.file_path}:{_norm(version_name)}"
        score = _score_entity(
            entity_type="version",
            entity_value=version_name,
            evidence_count=1,
            conflict_count=0,
            average_reliability=item.reliability,
            approvals=0,
            seen_values=[item.observed_at],
            role_agreement=False,
        )
        versions.append(_entity("version", key, version_name, score, 1, 0, [item.observed_at], now))
    return sorted(versions, key=lambda item: item.canonical_name.casefold())


def _relationships(
    *,
    artists: list[CanonicalEntity],
    artist_lookup: dict[str, str],
    artist_aliases: dict[str, str],
    albums: list[CanonicalEntity],
    album_lookup: dict[str, str],
    tracks: list[CanonicalEntity],
    track_lookup: dict[str, str],
    track_groups: dict[str, list[TrackEvidence]],
    versions: list[CanonicalEntity],
    track_evidence: list[TrackEvidence],
    album_groups: list[dict[str, Any]],
    reliability_records: list[dict[str, Any]],
    now: str,
) -> list[EntityRelationship]:
    relationships: list[EntityRelationship] = []
    artist_by_id = {artist.canonical_id: artist for artist in artists}
    for source_norm, target_name in sorted(artist_aliases.items()):
        target_id = artist_lookup.get(_norm(target_name))
        if not target_id:
            continue
        relationships.append(
            _relationship(
                f"artist_alias:{source_norm}:{target_id}",
                f"artist_alias:{source_norm}",
                f"canonical_artists:{target_id}",
                "alias_of",
                0.9,
                1,
                0,
                f"approved review or normalization knowledge maps alias to {artist_by_id[target_id].canonical_name}",
                now,
            )
        )
    albums_by_name = {album.canonical_name.casefold(): album for album in albums}
    tracks_by_name = {track.canonical_name.casefold(): track for track in tracks}
    for group in album_groups:
        album = albums_by_name.get(str(group.get("album", "")).casefold())
        if album is None:
            continue
        for track in group.get("tracks", []):
            title = _base_title(str(track.get("title", "")))
            canonical_track = tracks_by_name.get(title.casefold())
            if canonical_track is None:
                continue
            relationships.append(
                _relationship(
                    f"belongs:{canonical_track.canonical_id}:{album.canonical_id}",
                    f"canonical_tracks:{canonical_track.canonical_id}",
                    f"canonical_albums:{album.canonical_id}",
                    "belongs_to_album",
                    float(group.get("cohesion_score") or 0.55),
                    int(group.get("track_count") or 1),
                    1 if group.get("classification") == "conflict" else 0,
                    "album cohesion evidence links track to canonical album",
                    now,
                )
            )
            if group.get("classification") == "single":
                relationships.append(
                    _relationship(
                        f"single:{canonical_track.canonical_id}:{album.canonical_id}",
                        f"canonical_tracks:{canonical_track.canonical_id}",
                        f"canonical_albums:{album.canonical_id}",
                        "probable_single",
                        min(0.64, float(group.get("cohesion_score") or 0.5)),
                        1,
                        0,
                        "album cohesion classified this one-track group as a probable single",
                        now,
                    )
                )
            if group.get("classification") == "compilation_mix":
                relationships.append(
                    _relationship(
                        f"compilation:{canonical_track.canonical_id}:{album.canonical_id}",
                        f"canonical_tracks:{canonical_track.canonical_id}",
                        f"canonical_albums:{album.canonical_id}",
                        "probable_compilation_member",
                        float(group.get("cohesion_score") or 0.5),
                        int(group.get("track_count") or 1),
                        0,
                        "album cohesion found multiple artists in the album group",
                        now,
                    )
                )
    for key, items in sorted(track_groups.items()):
        track_id = track_lookup.get(key)
        if not track_id:
            continue
        markers = defaultdict(int)
        for item in items:
            markers[_version_marker(item.title)] += 1
        if len(items) > 1:
            relationships.append(
                _relationship(
                    f"same_track:{track_id}",
                    f"canonical_tracks:{track_id}",
                    f"canonical_tracks:{track_id}",
                    "probable_same_track",
                    0.74 if len(items) > 2 else 0.66,
                    len(items),
                    0,
                    "repeated artist and normalized title co-occurrence",
                    now,
                )
            )
        if markers.get("live"):
            relationships.append(_relationship(f"live:{track_id}", f"canonical_tracks:{track_id}", f"canonical_tracks:{track_id}", "probable_live_version", 0.68, markers["live"], 0, "title evidence contains live version markers", now))
        if markers.get("remaster"):
            relationships.append(_relationship(f"remaster:{track_id}", f"canonical_tracks:{track_id}", f"canonical_tracks:{track_id}", "probable_remaster", 0.68, markers["remaster"], 0, "title evidence contains remaster markers", now))
    duplicate_candidates = [record for record in reliability_records if "duplicate" in " ".join(map(str, record.values())).casefold()]
    if duplicate_candidates:
        for track in tracks[: max(1, min(5, len(duplicate_candidates)))]:
            relationships.append(_relationship(f"duplicate:{track.canonical_id}", f"canonical_tracks:{track.canonical_id}", f"canonical_tracks:{track.canonical_id}", "probable_duplicate", 0.62, 1, 0, "duplicate-like evidence present in reliability records", now))
    return _dedupe_relationships(relationships)


def _classify_graph_candidates(
    *,
    track_evidence: list[TrackEvidence],
    reports_dir: str | Path,
    db_path: str | Path,
) -> dict[tuple[str, str, str], EntityClassification]:
    rows: list[dict[str, Any]] = []
    for item in track_evidence:
        metadata_tags = {"artist": item.artist, "title": item.title, "album": item.album}
        base = {
            "file_path": item.file_path,
            "folder_artist": item.source_folder,
            "filename_artist": item.filename_artist,
            "filename_title": item.filename_title,
            "metadata_tags": metadata_tags,
            "evidence_reliability_flags": [],
        }
        for field_name, value in (
            ("artist", item.artist),
            ("filename_artist", item.filename_artist),
            ("title", item.title),
            ("album", item.album),
        ):
            if value:
                rows.append({**base, "field_name": field_name, "value": value})
    contexts = build_candidate_contexts(rows, reports_dir=reports_dir, db_path=db_path)
    classifications: dict[tuple[str, str, str], EntityClassification] = {}
    for context in contexts:
        classification = classify_candidate(context)
        classifications[(context.field_name, context.file_path, _norm(context.candidate_value))] = classification
    return classifications


def _graph_role_records(track_evidence: list[TrackEvidence]) -> list[EntityRoleRecord]:
    rows: list[dict[str, Any]] = []
    for item in track_evidence:
        metadata_tags = {"artist": item.artist, "title": item.title, "album": item.album}
        base = {
            "file_path": item.file_path,
            "folder_artist": item.source_folder,
            "filename_artist": item.filename_artist,
            "filename_title": item.filename_title,
            "metadata_tags": metadata_tags,
        }
        for field_name, value in (
            ("artist", item.artist),
            ("filename_artist", item.filename_artist),
            ("title", item.title),
            ("album", item.album),
        ):
            if value:
                rows.append({**base, "field_name": field_name, "value": value})
    return aggregate_entity_roles(rows)


def _role_conflicts(role_records: list[EntityRoleRecord], now: str) -> list[UnresolvedConflict]:
    conflicts: list[UnresolvedConflict] = []
    for record in role_records:
        if record.role_status not in {"conflicted"} and record.entity_role != "ambiguous":
            continue
        conflicts.append(
            _conflict(
                record.entity_role,
                record.normalized_value,
                [record.entity_value],
                record.evidence_count,
                1,
                "role-aware classification left this contextual entity unresolved: "
                + " | ".join(record.rationale[:3]),
                now,
            )
        )
    return conflicts


def _classification_for(
    classifications: dict[tuple[str, str, str], EntityClassification],
    field_name: str,
    file_path: str,
    value: str,
) -> EntityClassification | None:
    return classifications.get((field_name, file_path, _norm(value)))


def _blocks_promotion(classification: EntityClassification | None) -> bool:
    if classification is None:
        return False
    return classification.proposed_entity_type in BLOCKING_TYPES or classification.proposed_entity_type == AMBIGUOUS_TYPE


def _classification_conflict(
    entity_type: str,
    value: str,
    classification: EntityClassification | None,
    now: str,
) -> UnresolvedConflict:
    proposed = classification.proposed_entity_type if classification else AMBIGUOUS_TYPE
    rationale = "classification blocked canonical promotion"
    if classification is not None:
        rationale = (
            f"classification blocked canonical promotion as {proposed}: "
            f"{' | '.join(classification.rationale[:3])}"
        )
    return _conflict(
        entity_type,
        _norm(value),
        [value],
        1,
        1,
        rationale,
        now,
    )


def _summary(
    *,
    artists: list[CanonicalEntity],
    albums: list[CanonicalEntity],
    tracks: list[CanonicalEntity],
    versions: list[CanonicalEntity],
    relationships: list[EntityRelationship],
    unresolved: list[UnresolvedConflict],
    reliability_summary: dict[str, Any],
    classification_summary: dict[str, Any],
    role_summary: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    entities = [*artists, *albums, *tracks, *versions]
    tiers = Counter(entity.confidence_tier for entity in entities)
    return {
        "created_at": now,
        "canonical_artist_count": len(artists),
        "canonical_album_count": len(albums),
        "canonical_track_count": len(tracks),
        "canonical_version_count": len(versions),
        "blocked_candidate_count": int(classification_summary.get("blocked_candidates", 0) or 0),
        "ambiguous_candidate_count": int(classification_summary.get("ambiguous_candidates", 0) or 0),
        "role_record_count": int(role_summary.get("total_role_records", 0) or 0),
        "multi_role_entities": int(role_summary.get("multi_role_entities", 0) or 0),
        "blocked_role_collisions": int(role_summary.get("blocked_role_collisions", 0) or 0),
        "alias_relationships": sum(1 for item in relationships if item.relationship_type == "alias_of"),
        "duplicate_relationships": sum(1 for item in relationships if item.relationship_type in {"probable_duplicate", "probable_same_track"}),
        "unresolved_conflicts": len(unresolved),
        "high_confidence_entities": tiers["high"],
        "medium_confidence_entities": tiers["medium"],
        "low_confidence_entities": tiers["low"],
        "canonical_reliability_matches": int(reliability_summary.get("canonical_matches", 0) or 0),
    }


def _write_reports(report_dir: Path, graph: CanonicalGraph) -> None:
    _write_csv(report_dir / "canonical_artists.csv", ENTITY_FIELDS, (asdict(item) for item in graph.artists))
    _write_csv(report_dir / "canonical_albums.csv", ENTITY_FIELDS, (asdict(item) for item in graph.albums))
    _write_csv(report_dir / "canonical_tracks.csv", ENTITY_FIELDS, (asdict(item) for item in graph.tracks))
    _write_csv(report_dir / "canonical_versions.csv", ENTITY_FIELDS, (asdict(item) for item in graph.versions))
    _write_csv(report_dir / "entity_relationships.csv", RELATIONSHIP_FIELDS, (asdict(item) for item in graph.relationships))
    _write_csv(report_dir / "unresolved_conflicts.csv", CONFLICT_FIELDS, (asdict(item) for item in graph.unresolved_conflicts))
    with (report_dir / "graph_summary.json").open("w", encoding="utf-8") as file_handle:
        json.dump(graph.summary, file_handle, indent=2, sort_keys=True)
        file_handle.write("\n")


def _insert_entities(connection: Any, table_name: str, entities: list[CanonicalEntity]) -> None:
    for entity in entities:
        connection.execute(
            f"""
            INSERT INTO {table_name} (
                canonical_id, canonical_name, confidence_score, confidence_tier,
                evidence_count, conflict_count, first_seen, last_seen, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(asdict(entity).values()),
        )


def _insert_relationships(connection: Any, relationships: list[EntityRelationship]) -> None:
    for relationship in relationships:
        connection.execute(
            """
            INSERT INTO entity_relationships (
                relationship_id, source_entity, target_entity, relationship_type,
                confidence_score, supporting_evidence_count,
                conflicting_evidence_count, rationale, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(asdict(relationship).values()),
        )


def _insert_conflicts(connection: Any, conflicts: list[UnresolvedConflict]) -> None:
    for conflict in conflicts:
        connection.execute(
            """
            INSERT INTO canonical_unresolved_conflicts (
                conflict_id, entity_type, entity_key, variants, evidence_count,
                conflict_count, rationale, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(asdict(conflict).values()),
        )


def _entity(entity_type: str, key: str, name: str, score: float, evidence_count: int, conflict_count: int, seen_values: list[str], now: str) -> CanonicalEntity:
    score = round(max(0.0, min(1.0, score)), 3)
    first_seen = min(seen_values) if seen_values else now
    last_seen = max(seen_values) if seen_values else now
    tier = _tier(score)
    lifecycle_state = graph_lifecycle_state(
        entity_type=entity_type,
        entity_key=key,
        entity_value=name or "Unknown",
        confidence_score=score,
        confidence_tier=tier,
        evidence_count=evidence_count,
        conflict_count=conflict_count,
        first_seen=first_seen,
        last_seen=last_seen,
        graph_relationships=1 if evidence_count >= 2 else 0,
    )
    return CanonicalEntity(
        canonical_id=_stable_id(entity_type, key),
        canonical_name=name or "Unknown",
        confidence_score=score,
        confidence_tier=tier,
        evidence_count=evidence_count,
        conflict_count=conflict_count,
        first_seen=first_seen,
        last_seen=last_seen,
        status=lifecycle_state,
    )


def _relationship(key: str, source: str, target: str, rel_type: str, score: float, support: int, conflict: int, rationale: str, now: str) -> EntityRelationship:
    return EntityRelationship(
        relationship_id=_stable_id("relationship", key),
        source_entity=source,
        target_entity=target,
        relationship_type=rel_type,
        confidence_score=round(max(0.0, min(1.0, score)), 3),
        supporting_evidence_count=support,
        conflicting_evidence_count=conflict,
        rationale=rationale,
        created_at=now,
    )


def _conflict(entity_type: str, key: str, variants: list[str], evidence_count: int, conflict_count: int, rationale: str, now: str) -> UnresolvedConflict:
    return UnresolvedConflict(
        conflict_id=_stable_id("conflict", f"{entity_type}:{key}"),
        entity_type=entity_type,
        entity_key=key,
        variants=" | ".join(variants),
        evidence_count=evidence_count,
        conflict_count=conflict_count,
        rationale=rationale,
        created_at=now,
    )


def _score_entity(
    *,
    entity_type: str,
    entity_value: str,
    evidence_count: int,
    conflict_count: int,
    average_reliability: float,
    approvals: int,
    seen_values: list[str],
    folder_agreement: bool = False,
    role_agreement: bool = False,
    album_cohesion_count: int = 0,
    weak_album_cohesion: bool = False,
) -> float:
    scored = score_canonical_entity(
        entity_type=entity_type,
        entity_key=_norm(entity_value),
        entity_value=entity_value,
        evidence_count=evidence_count,
        conflict_count=conflict_count,
        average_reliability=average_reliability,
        approvals=approvals,
        first_seen=min(seen_values) if seen_values else "",
        last_seen=max(seen_values) if seen_values else "",
        folder_agreement=folder_agreement,
        role_agreement=role_agreement,
        album_cohesion_count=album_cohesion_count,
        graph_reinforcement=evidence_count >= 2,
        weak_album_cohesion=weak_album_cohesion,
    )
    return scored.normalized_confidence


def _tier(score: float) -> str:
    return weighted_confidence_tier(score)


def _case_conflict_count(values: Iterable[str]) -> int:
    grouped: defaultdict[str, set[str]] = defaultdict(set)
    for value in values:
        if value:
            grouped[_norm(value)].add(value)
    return sum(max(0, len(items) - 1) for items in grouped.values())


def _best_name(values: Iterable[str], preferred: Iterable[str] = ()) -> str:
    preferred_list = [item for item in preferred if item]
    if preferred_list:
        return sorted(preferred_list, key=lambda item: (-len(item), item.casefold()))[0]
    counts = Counter(value for value in values if value)
    if not counts:
        return ""
    return sorted(counts, key=lambda item: (-counts[item], item.casefold()))[0]


def _base_title(value: str) -> str:
    value = _clean(value)
    value = re.sub(r"\s*[\[(](?:live|live at .+?|remaster(?:ed)?|[0-9]{4} remaster|radio edit|single version)[\])]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+-\s+(?:live|remaster(?:ed)?|radio edit|single version)\s*$", "", value, flags=re.IGNORECASE)
    return value.strip() or _clean(value)


def _version_marker(value: str) -> str:
    text = value.casefold()
    if "live" in text:
        return "live"
    if "remaster" in text:
        return "remaster"
    if "single version" in text or "radio edit" in text:
        return "single"
    return ""


def _dedupe_entities(entities: list[CanonicalEntity]) -> list[CanonicalEntity]:
    merged: dict[str, CanonicalEntity] = {}
    for entity in sorted(
        entities,
        key=lambda item: (
            item.canonical_id,
            item.first_seen,
            item.last_seen,
            item.canonical_name.casefold(),
            item.status.casefold(),
        ),
    ):
        existing = merged.get(entity.canonical_id)
        if existing is None:
            merged[entity.canonical_id] = entity
            continue
        score = max(existing.confidence_score, entity.confidence_score)
        evidence_count = existing.evidence_count + entity.evidence_count
        conflict_count = existing.conflict_count + entity.conflict_count
        canonical_name = _merged_name(existing.canonical_name, entity.canonical_name)
        merged[entity.canonical_id] = CanonicalEntity(
            canonical_id=entity.canonical_id,
            canonical_name=canonical_name,
            confidence_score=score,
            confidence_tier=_tier(score),
            evidence_count=evidence_count,
            conflict_count=conflict_count,
            first_seen=min(existing.first_seen, entity.first_seen),
            last_seen=max(existing.last_seen, entity.last_seen),
            status=_merged_status(existing.status, entity.status, conflict_count),
        )
    return sorted(merged.values(), key=lambda item: (item.canonical_name.casefold(), item.canonical_id))


def _dedupe_relationships(relationships: list[EntityRelationship]) -> list[EntityRelationship]:
    merged: dict[str, EntityRelationship] = {}
    for relationship in sorted(
        relationships,
        key=lambda item: (
            item.relationship_id,
            item.relationship_type,
            item.source_entity,
            item.target_entity,
            item.created_at,
            item.rationale,
        ),
    ):
        existing = merged.get(relationship.relationship_id)
        if existing is None:
            merged[relationship.relationship_id] = relationship
            continue
        merged[relationship.relationship_id] = EntityRelationship(
            relationship_id=relationship.relationship_id,
            source_entity=existing.source_entity or relationship.source_entity,
            target_entity=existing.target_entity or relationship.target_entity,
            relationship_type=existing.relationship_type or relationship.relationship_type,
            confidence_score=max(existing.confidence_score, relationship.confidence_score),
            supporting_evidence_count=existing.supporting_evidence_count + relationship.supporting_evidence_count,
            conflicting_evidence_count=existing.conflicting_evidence_count + relationship.conflicting_evidence_count,
            rationale=_merge_rationale(existing.rationale, relationship.rationale),
            created_at=min(existing.created_at, relationship.created_at),
        )
    return sorted(merged.values(), key=lambda item: (item.relationship_type, item.source_entity, item.target_entity, item.relationship_id))


def _merged_name(left: str, right: str) -> str:
    for name in (left, right):
        if name and _norm(name) != "unknown":
            return name
    return left or right or "Unknown"


def _merged_status(left: str, right: str, conflict_count: int) -> str:
    statuses = {left, right}
    if conflict_count or "conflicted" in statuses:
        return "conflicted"
    if "canonical" in statuses:
        return "canonical"
    if "probationary" in statuses:
        return "probationary"
    if "candidate" in statuses:
        return "candidate"
    if "active" in statuses:
        return "probationary"
    return sorted(status for status in statuses if status)[0] if any(statuses) else "active"


def _merge_rationale(left: str, right: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for rationale in (left, right):
        for part in [item.strip() for item in rationale.split(" | ") if item.strip()]:
            key = part.casefold()
            if key not in seen:
                parts.append(part)
                seen.add(key)
    return " | ".join(parts)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm(value: Any) -> str:
    text = _clean(value).casefold()
    text = re.sub(r"[\W_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _display_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _stable_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{key}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, str(path)
    try:
        with path.open(encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
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


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialized:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
