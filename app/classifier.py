"""Deterministic classification engine for identified tracks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import db
from app.artist_seeds import match_seed_artist
from app.taxonomy import PRIMARY_GENRES, SUBGENRES


CLASSIFICATION_STATUSES: frozenset[str] = frozenset(
    {"classified", "inferred", "uncertain", "unknown"}
)

REQUIRED_CLASSIFICATION_EVIDENCE_FIELDS: tuple[str, ...] = (
    "selected_source",
    "probable_artist",
    "genre_tag",
    "normalized_genre",
    "artist_seed_matched",
    "evidence_items",
)

SUBGENRE_TO_PRIMARY_GENRE: dict[str, str] = {
    "Shoegaze Metal": "Alternative Metal",
    "Rap Metal": "Nu Metal",
    "Christian Rock": "Alternative Rock",
    "Electronic Rock": "Alternative Rock",
    "Modern Metalcore": "Metalcore",
    "Post-Hardcore": "Alternative Rock",
    "Industrial Metal": "Industrial Rock",
    "Progressive Rock": "Progressive Metal",
    "Grunge": "Grunge",
    "Alt-Metal": "Alternative Metal",
    "Melodic Hard Rock": "Hard Rock",
}


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


GENRE_ALIASES: dict[str, str] = {
    "altmetal": "Alternative Metal",
    "alternativemetal": "Alternative Metal",
    "numetal": "Nu Metal",
    "postgrunge": "Post-Grunge",
    "hardrock": "Hard Rock",
    "metalcore": "Metalcore",
    "progressivemetal": "Progressive Metal",
    "industrialrock": "Industrial Rock",
    "grunge": "Grunge",
    "alternativerock": "Alternative Rock",
    "altrock": "Alternative Rock",
}

for genre in PRIMARY_GENRES:
    GENRE_ALIASES.setdefault(_normalize_key(genre), genre)
for genre in SUBGENRES:
    GENRE_ALIASES.setdefault(_normalize_key(genre), genre)


@dataclass(frozen=True)
class TrackClassification:
    observed_file_id: int | None
    primary_genre: str | None
    subgenre: str | None
    energy_level: str | None
    vocal_style: str | None
    mood: list[str]
    classification_confidence: float
    classification_status: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class ClassifySummary:
    total: int
    classified: int
    inferred: int
    uncertain: int
    unknown: int


def classify_track(
    *,
    observed_file_id: int | None = None,
    probable_artist: str | None = None,
    genre_tag: str | None = None,
) -> TrackClassification:
    """Classify a track from identity artist first, then embedded genre tag."""

    probable_artist = _clean(probable_artist)
    genre_tag = _clean(genre_tag)

    artist_classification = classify_by_artist_seed(
        observed_file_id=observed_file_id,
        probable_artist=probable_artist,
        genre_tag=genre_tag,
    )
    if artist_classification is not None:
        return artist_classification

    genre_classification = classify_by_genre_tag(
        observed_file_id=observed_file_id,
        probable_artist=probable_artist,
        genre_tag=genre_tag,
    )
    if genre_classification is not None:
        return genre_classification

    evidence = build_classification_evidence(
        selected_source=None,
        probable_artist=probable_artist,
        genre_tag=genre_tag,
        normalized_genre=None,
        artist_seed_matched=None,
        evidence_items=[],
    )
    return TrackClassification(
        observed_file_id=observed_file_id,
        primary_genre=None,
        subgenre=None,
        energy_level=None,
        vocal_style=None,
        mood=[],
        classification_confidence=calculate_classification_confidence(
            classification_status="unknown"
        ),
        classification_status="unknown",
        evidence=evidence,
    )


def classify_by_artist_seed(
    *,
    observed_file_id: int | None = None,
    probable_artist: str | None,
    genre_tag: str | None = None,
) -> TrackClassification | None:
    """Classify from a controlled artist seed when the identity artist matches."""

    if probable_artist is None:
        return None

    seed = match_seed_artist(probable_artist)
    if seed is None:
        return None

    evidence = build_classification_evidence(
        selected_source="artist_seed",
        probable_artist=probable_artist,
        genre_tag=genre_tag,
        normalized_genre=None,
        artist_seed_matched=seed.artist,
        evidence_items=["artist_seed_match"],
    )
    return TrackClassification(
        observed_file_id=observed_file_id,
        primary_genre=seed.primary_genre,
        subgenre=seed.subgenre,
        energy_level=seed.energy_level,
        vocal_style=seed.vocal_style,
        mood=list(seed.mood),
        classification_confidence=calculate_classification_confidence(
            classification_status="classified",
            selected_source="artist_seed",
        ),
        classification_status="classified",
        evidence=evidence,
    )


def classify_by_genre_tag(
    *,
    observed_file_id: int | None = None,
    probable_artist: str | None = None,
    genre_tag: str | None,
) -> TrackClassification | None:
    """Classify from embedded genre metadata when no artist seed matched."""

    if genre_tag is None:
        return None

    normalized_genre = _normalize_genre_tag(genre_tag)
    if normalized_genre is None:
        status = "uncertain"
        primary_genre = None
        subgenre = None
    elif normalized_genre in PRIMARY_GENRES:
        status = "inferred"
        primary_genre = normalized_genre
        subgenre = normalized_genre if normalized_genre in SUBGENRES else None
    else:
        status = "inferred"
        primary_genre = SUBGENRE_TO_PRIMARY_GENRE.get(normalized_genre)
        subgenre = normalized_genre

    evidence = build_classification_evidence(
        selected_source="genre_tag",
        probable_artist=probable_artist,
        genre_tag=genre_tag,
        normalized_genre=normalized_genre,
        artist_seed_matched=None,
        evidence_items=["genre_tag"],
    )
    return TrackClassification(
        observed_file_id=observed_file_id,
        primary_genre=primary_genre,
        subgenre=subgenre,
        energy_level=None,
        vocal_style=None,
        mood=[],
        classification_confidence=calculate_classification_confidence(
            classification_status=status,
            selected_source="genre_tag",
            normalized_genre=normalized_genre,
        ),
        classification_status=status,
        evidence=evidence,
    )


def calculate_classification_confidence(
    *,
    classification_status: str,
    selected_source: str | None = None,
    normalized_genre: str | None = None,
) -> float:
    """Return deterministic confidence for a classification result."""

    if classification_status == "classified" and selected_source == "artist_seed":
        return 0.95
    if (
        classification_status == "inferred"
        and selected_source == "genre_tag"
        and normalized_genre is not None
    ):
        return 0.75
    if classification_status == "uncertain":
        return 0.50
    if classification_status == "unknown":
        return 0.20
    raise ValueError(f"Unknown classification state: {classification_status}")


def build_classification_evidence(
    *,
    selected_source: str | None,
    probable_artist: str | None,
    genre_tag: str | None,
    normalized_genre: str | None,
    artist_seed_matched: str | None,
    evidence_items: list[str],
) -> dict[str, Any]:
    """Build the required deterministic classification evidence payload."""

    return {
        "selected_source": selected_source,
        "probable_artist": probable_artist,
        "genre_tag": genre_tag,
        "normalized_genre": normalized_genre,
        "artist_seed_matched": artist_seed_matched,
        "evidence_items": list(evidence_items),
    }


def classify_scan_run(
    scan_run_id: int, db_path: str | Path = db.DEFAULT_DB_PATH
) -> ClassifySummary:
    """Classify tracks with existing identity rows for a scan run."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                observed_files.id AS observed_file_id,
                track_identity.probable_artist,
                tag_observations.genre AS genre_tag
            FROM observed_files
            INNER JOIN track_identity
                ON track_identity.observed_file_id = observed_files.id
            LEFT JOIN tag_observations
                ON tag_observations.observed_file_id = observed_files.id
            WHERE observed_files.scan_run_id = ?
            ORDER BY observed_files.id
            """,
            (scan_run_id,),
        ).fetchall()

        observed_file_ids = [row["observed_file_id"] for row in rows]
        if observed_file_ids:
            placeholders = ",".join("?" for _ in observed_file_ids)
            connection.execute(
                f"""
                DELETE FROM classification_results
                WHERE observed_file_id IN ({placeholders})
                """,
                observed_file_ids,
            )

        counts = {"classified": 0, "inferred": 0, "uncertain": 0, "unknown": 0}
        for row in rows:
            classification = classify_track(
                observed_file_id=row["observed_file_id"],
                probable_artist=row["probable_artist"],
                genre_tag=row["genre_tag"],
            )
            _insert_classification(connection, classification)
            counts[classification.classification_status] += 1

    return ClassifySummary(
        total=len(rows),
        classified=counts["classified"],
        inferred=counts["inferred"],
        uncertain=counts["uncertain"],
        unknown=counts["unknown"],
    )


def _insert_classification(
    connection, classification: TrackClassification
) -> None:
    connection.execute(
        """
        INSERT INTO classification_results (
            observed_file_id,
            primary_genre,
            subgenre,
            energy_level,
            vocal_style,
            mood_json,
            classification_confidence,
            classification_status,
            evidence_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            classification.observed_file_id,
            classification.primary_genre,
            classification.subgenre,
            classification.energy_level,
            classification.vocal_style,
            json.dumps(classification.mood),
            classification.classification_confidence,
            classification.classification_status,
            json.dumps(classification.evidence, sort_keys=True),
            datetime.now(UTC).isoformat(),
        ),
    )


def _normalize_genre_tag(value: str) -> str | None:
    return GENRE_ALIASES.get(_normalize_key(value))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None
