import csv
from pathlib import Path

import pytest

from app import db
from app.canonical_confidence import score_canonical_entity
from app.canonical_entity_classifier import (
    BLOCKING_TYPES,
    CandidateContext,
    classify_candidate,
)
from app.canonical_entity_graph import _base_title, build_canonical_graph
from app.entity_roles import aggregate_entity_roles
from app.promotion_lifecycle import evaluate_lifecycle
from app.review_decisions import record_review_decision, suggestion_key_for


GOLDEN_DIR = Path(__file__).parent / "golden_cases"
GOLDEN_FILES = (
    "uploader_artifacts.csv",
    "misclassified_titles.csv",
    "artist_aliases.csv",
    "album_pollution.csv",
    "feature_collisions.csv",
    "remaster_noise.csv",
    "blocked_promotions.csv",
    "canonical_merge_conflicts.csv",
)


def _read_rows(filename: str) -> list[dict[str, str]]:
    with (GOLDEN_DIR / filename).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("row", [row for filename in GOLDEN_FILES for row in _read_rows(filename)], ids=lambda row: row["case_id"])
def test_golden_cases_classify_confidence_and_lifecycle(row):
    classification = classify_candidate(_candidate_context(row))

    assert classification.proposed_entity_type == row["expected_proposed_entity_type"]
    assert classification.confidence_tier == row["expected_classifier_confidence_tier"]
    assert (classification.proposed_entity_type in BLOCKING_TYPES or classification.proposed_entity_type == "unknown_or_ambiguous") is _bool(row["expected_blocked"])

    scored = _score_profile(row)
    lifecycle = evaluate_lifecycle(
        scored,
        evidence_count=_lifecycle_evidence_count(row),
        conflict_count=_lifecycle_conflict_count(row),
        graph_relationships=_lifecycle_graph_relationships(row),
        role_conflict=row["scoring_profile"] in {"merge_conflict"},
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-03-15T00:00:00+00:00",
    )

    assert scored.confidence_tier == row["expected_weighted_confidence_tier"]
    assert lifecycle.lifecycle_state == row["expected_lifecycle_state"]


def test_album_pollution_preserves_independent_roles():
    rows = _read_rows("album_pollution.csv")
    records = aggregate_entity_roles(_role_rows(rows))
    roles_by_value = {
        record.entity_value: {
            role.entity_role: role.role_status
            for role in records
            if role.normalized_value == record.normalized_value
        }
        for record in records
    }

    for row in rows:
        expected_roles = _split(row["expected_roles"])
        if not expected_roles:
            continue
        actual_roles = roles_by_value[row["candidate_value"]]
        for expected_role in expected_roles:
            assert expected_role in actual_roles
            assert actual_roles[expected_role] in {"candidate", "probationary", "canonical", "conflicted"}
        assert actual_roles.get("artist") != "blocked"
        assert actual_roles.get("album") != "blocked"


def test_remaster_noise_preserves_base_track_identity():
    for row in _read_rows("remaster_noise.csv"):
        classification = classify_candidate(_candidate_context(row))

        assert classification.proposed_entity_type == "canonical_track"
        assert _base_title(row["candidate_value"]) == row["expected_base_title"]
        assert "artist" not in classification.proposed_entity_type
        assert "album" not in classification.proposed_entity_type


def test_artist_alias_golden_cases_create_explainable_graph_relationships(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    for row in _read_rows("artist_aliases.csv"):
        _insert_observation(
            db_path,
            artist=row["candidate_value"],
            title=f"{row['expected_alias_target']} track",
            album=f"{row['expected_alias_target']} album",
            filename=f"{row['candidate_value']} - {row['expected_alias_target']} track.flac",
            folder=f"/music/{row['expected_alias_target']}",
        )
        _approve_artist_alias(db_path, row["candidate_value"], row["expected_alias_target"])

    graph = build_canonical_graph(db_path=db_path, reports_dir=tmp_path / "reports")
    artist_names = {artist.canonical_name for artist in graph.artists}
    alias_relationships = [relationship for relationship in graph.relationships if relationship.relationship_type == "alias_of"]

    assert {"Chevelle", "Korn", "Bring Me the Horizon"} <= artist_names
    assert len(alias_relationships) == 3
    assert all("approved review or normalization knowledge" in relationship.rationale for relationship in alias_relationships)


def test_mini_graph_fixture_blocks_pollution_preserves_roles_and_conflicts(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, artist="Warner Records Vault", title="Push It", album="Wisconsin Death Trip", filename="Static-X - Push It.flac", folder="/music/Static-X")
    _insert_observation(db_path, artist="Static-X", title="Push It", album="Wisconsin Death Trip", filename="Static-X - Push It alternate.flac", folder="/music/Static-X")
    _insert_observation(db_path, artist="Audioslave", title="Cochise", album="Audioslave", filename="Audioslave - Cochise.flac", folder="/music/Audioslave")
    _insert_observation(db_path, artist="Audioslave", title="Show Me How to Live", album="Audioslave", filename="Audioslave - Show Me How to Live.flac", folder="/music/Audioslave")
    _insert_observation(db_path, artist="Soundgarden", title="Rusty Cage", album="Badmotorfinger", filename="Soundgarden - Rusty Cage.flac", folder="/music/Soundgarden")
    _insert_observation(db_path, artist="Loathe & Teenage Wrist", title="Is It Really You?", album="Single", filename="Loathe - Is It Really You.flac", folder="/music/Loathe")
    _insert_observation(db_path, artist="Deftones", title="My Own Summer", album="Around the Fur", filename="Deftones - My Own Summer.flac", folder="/music/Deftones")
    _insert_observation(db_path, artist="Deftone", title="Independent Evidence", album="No Alias", filename="Deftone - Independent Evidence.flac", folder="/music/Deftone")

    graph = build_canonical_graph(db_path=db_path, reports_dir=reports)
    canonical_artists = {artist.canonical_name: artist for artist in graph.artists}
    canonical_albums = {album.canonical_name: album for album in graph.albums}
    conflict_text = " | ".join(conflict.variants + " " + conflict.rationale for conflict in graph.unresolved_conflicts)

    assert "Warner Records Vault" not in canonical_artists
    assert "Loathe & Teenage Wrist" not in canonical_artists
    assert {"Static-X", "Audioslave", "Soundgarden"} <= set(canonical_artists)
    assert "Audioslave" in canonical_albums
    assert "Badmotorfinger" in canonical_albums
    assert "Deftones" in canonical_artists
    assert "Deftone" in canonical_artists
    assert "Loathe & Teenage Wrist" in conflict_text
    assert graph.summary["blocked_candidate_count"] >= 1
    assert graph.summary["ambiguous_candidate_count"] >= 1
    assert graph.summary["multi_role_entities"] >= 1


def _candidate_context(row: dict[str, str]) -> CandidateContext:
    return CandidateContext(
        candidate_value=row["candidate_value"],
        field_name=row["field_name"],
        folder_artist=row["folder_artist"],
        filename_artist=row["filename_artist"],
        filename_title=row["filename_title"],
        metadata_tags={
            "title": row["tag_title"],
            "album": row["tag_album"],
            "artist": row["candidate_value"] if row["field_name"] == "artist" else row["folder_artist"],
        },
        value_artist_count=_int(row["value_artist_count"]),
        value_album_count=_int(row["value_album_count"]),
        value_title_count=_int(row["value_title_count"]),
        other_title_count=_int(row["other_title_count"]),
        role_status=row["role_status"],
        role_evidence_count=_int(row["role_evidence_count"]),
        active_roles=_split(row["active_roles"]),
        role_flags=_split(row["role_flags"]),
        approved_review_support=_bool(row["approved_review_support"]),
        normalization_knowledge_support=_bool(row["normalization_knowledge_support"]),
    )


def _score_profile(row: dict[str, str]):
    profile = row["scoring_profile"]
    common = {
        "entity_type": "artist",
        "entity_key": row["case_id"],
        "entity_value": row["candidate_value"],
    }
    if profile == "artifact":
        return score_canonical_entity(**common, evidence_count=1, average_reliability=0.3, artifact_flags=["source_artifact_pattern", "uploader_signature"])
    if profile == "title_artifact":
        return score_canonical_entity(**common, evidence_count=1, average_reliability=0.5, title_like_artist=True)
    if profile == "canonical_artist":
        return score_canonical_entity(**common, evidence_count=4, average_reliability=0.86, approvals=1, folder_agreement=True, role_agreement=True, first_seen="2026-01-01T00:00:00+00:00", last_seen="2026-03-15T00:00:00+00:00")
    if profile == "canonical_album":
        return score_canonical_entity(entity_type="album", entity_key=row["case_id"], entity_value=row["candidate_value"], evidence_count=3, average_reliability=0.72, role_agreement=True, album_cohesion_count=2, first_seen="2026-01-01T00:00:00+00:00", last_seen="2026-03-15T00:00:00+00:00")
    if profile == "track_version":
        return score_canonical_entity(entity_type="track", entity_key=row["case_id"], entity_value=row["candidate_value"], evidence_count=2, average_reliability=0.68, role_agreement=True)
    if profile == "merge_conflict":
        return score_canonical_entity(**common, evidence_count=2, conflict_count=1, average_reliability=0.65, role_agreement=True)
    raise AssertionError(f"unknown scoring_profile={profile}")


def _role_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    role_rows = []
    for row in rows:
        role_rows.append(
            {
                "value": row["candidate_value"],
                "field_name": row["field_name"],
                "file_path": f"/golden/{row['case_id']}.flac",
                "folder_artist": row["folder_artist"],
                "filename_artist": row["filename_artist"],
                "filename_title": row["filename_title"],
                "metadata_tags": {"title": row["tag_title"], "album": row["tag_album"]},
            }
        )
    return role_rows


def _lifecycle_evidence_count(row: dict[str, str]) -> int:
    if row["scoring_profile"] in {"canonical_artist"}:
        return 4
    if row["scoring_profile"] in {"canonical_album"}:
        return 3
    if row["scoring_profile"] in {"track_version", "merge_conflict"}:
        return 2
    return 1


def _lifecycle_conflict_count(row: dict[str, str]) -> int:
    return 1 if row["scoring_profile"] in {"artifact", "title_artifact", "merge_conflict"} else 0


def _lifecycle_graph_relationships(row: dict[str, str]) -> int:
    return 1 if row["scoring_profile"] in {"canonical_artist", "canonical_album", "track_version", "merge_conflict"} else 0


def _insert_observation(db_path: Path, *, artist: str, title: str, album: str, filename: str, folder: str) -> None:
    db.init_db(db_path)
    path = Path(filename)
    with db.connect(db_path) as connection:
        scan_run_id = connection.execute(
            """
            INSERT INTO scan_runs (
                source_path, started_at, completed_at, status,
                total_files_seen, audio_files_seen, files_failed
            )
            VALUES ('/music', '2026-01-01T00:00:00+00:00', '2026-03-15T00:00:01+00:00',
                    'completed', 1, 1, 0)
            """
        ).lastrowid
        observed_file_id = connection.execute(
            """
            INSERT INTO observed_files (
                scan_run_id, source_path, relative_path, parent_folder, filename,
                extension, file_size_bytes, sha256, created_at
            )
            VALUES (?, ?, ?, ?, ?, '.flac', 10, ?, '2026-01-01T00:00:00+00:00')
            """,
            (scan_run_id, str(path), path.name, folder, path.name, f"sha-{path.name}"),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO tag_observations (
                observed_file_id, title, artist, album, album_artist, tag_status
            )
            VALUES (?, ?, ?, ?, ?, 'read')
            """,
            (observed_file_id, title, artist, album, artist),
        )
        parsed_artist = artist if " - " not in path.stem else path.stem.split(" - ", 1)[0]
        parsed_title = title if " - " not in path.stem else path.stem.split(" - ", 1)[1]
        connection.execute(
            """
            INSERT INTO filename_observations (
                observed_file_id, cleaned_filename, possible_artist, possible_title,
                filename_pattern, parser_confidence
            )
            VALUES (?, ?, ?, ?, 'artist_title', 0.8)
            """,
            (observed_file_id, path.stem, parsed_artist, parsed_title),
        )


def _approve_artist_alias(db_path: Path, current: str, proposed: str) -> None:
    key = suggestion_key_for(
        file_path="/music/a.flac",
        field="artist",
        current_value=current,
        proposed_value=proposed,
        suggestion_type="artist_casing",
    )
    record_review_decision(
        suggestion_key=key,
        decision="approved",
        reason="golden alias fixture",
        db_path=db_path,
        suggestion={
            "file_path": "/music/a.flac",
            "field": "artist",
            "current_value": current,
            "proposed_value": proposed,
            "suggestion_type": "artist_casing",
            "confidence": "high",
            "source_evidence": ["golden"],
        },
    )


def _split(value: str) -> list[str]:
    return [part for part in value.split("|") if part]


def _bool(value: str) -> bool:
    return value.strip().casefold() == "true"


def _int(value: str) -> int:
    return int(value or 0)
