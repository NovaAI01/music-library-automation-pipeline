import csv
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.canonical_entity_classifier import CandidateContext, classify_candidate
from app.canonical_entity_graph import build_canonical_graph
from app.entity_roles import aggregate_entity_roles, generate_entity_role_report
from app.main import app, main


def test_same_value_valid_as_artist_and_album():
    records = aggregate_entity_roles(
        [
            _row("Audioslave", "artist", "Audioslave - Cochise.flac", title="Cochise", album="Audioslave"),
            _row("Audioslave", "album", "Audioslave - Cochise.flac", artist="Audioslave", title="Cochise"),
            _row("Audioslave", "artist", "Audioslave - Show Me How To Live.flac", title="Show Me How To Live", album="Audioslave"),
        ]
    )

    roles = {(record.normalized_value, record.entity_role): record for record in records}
    assert roles[("audioslave", "artist")].role_status in {"probationary", "canonical"}
    assert roles[("audioslave", "album")].role_status in {"candidate", "probationary", "canonical"}
    assert "multi_role_entity" in roles[("audioslave", "artist")].flags


def test_artist_not_blocked_because_same_value_appears_as_album():
    result = classify_candidate(
        CandidateContext(
            candidate_value="Flyleaf",
            field_name="artist",
            folder_artist="/music/Flyleaf",
            metadata_tags={"album": "Flyleaf", "title": "I'm So Sick"},
            value_artist_count=3,
            value_album_count=2,
            role_evidence_count=3,
            role_status="canonical",
            active_roles=["album", "artist"],
            role_flags=["multi_role_entity"],
        )
    )

    assert result.proposed_entity_type == "canonical_artist"
    assert "multi_role_entity" in result.flags
    assert "cross_role_album_collision" in result.flags


def test_album_not_blocked_because_same_value_appears_as_artist():
    result = classify_candidate(
        CandidateContext(
            candidate_value="Alice in Chains",
            field_name="album",
            metadata_tags={"artist": "Alice in Chains", "album": "Alice in Chains", "title": "Grind"},
            value_artist_count=4,
            value_album_count=2,
            role_evidence_count=2,
            role_status="probationary",
            active_roles=["album", "artist"],
            role_flags=["multi_role_entity"],
        )
    )

    assert result.proposed_entity_type == "canonical_album"
    assert "cross_role_artist_collision" in result.flags


def test_source_artifact_still_blocked_when_artifact_evidence_dominates():
    result = classify_candidate(
        CandidateContext(
            candidate_value="Warner Records Vault",
            field_name="artist",
            folder_artist="/music/Static-X",
            value_artist_count=1,
            role_evidence_count=1,
            role_status="candidate",
            active_roles=["artist", "label_artifact"],
            role_flags=["multi_role_entity", "artifact_role"],
        )
    )

    assert result.proposed_entity_type in {"source_or_label_artifact", "uploader_channel_artifact"}
    assert result.confidence_tier == "high"


def test_multi_role_report_generation_and_blocked_collisions(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Audioslave", "Cochise", "Audioslave", "Audioslave - Cochise.flac")
    _insert_observation(db_path, "Audioslave", "Show Me How To Live", "Audioslave", "Audioslave - Show Me How To Live.flac")
    _insert_observation(db_path, "Warner Records Vault", "Push It", "Wisconsin Death Trip", "Static-X - Push It.flac")

    result = generate_entity_role_report(out_dir=reports, db_path=db_path)
    report_dir = reports / "entity_roles"
    summary = json.loads((report_dir / "entity_role_summary.json").read_text(encoding="utf-8"))
    multi_role = _read_csv(report_dir / "multi_role_entities.csv")
    blocked = _read_csv(report_dir / "blocked_role_collisions.csv")

    assert result.total_role_records >= 5
    assert summary["multi_role_entities"] >= 1
    assert any(row["entity_value"] == "Audioslave" and "artist" in row["active_roles"] and "album" in row["active_roles"] for row in multi_role)
    assert any(row["entity_value"] == "Warner Records Vault" and row["role_status"] == "blocked" for row in blocked)


def test_conflicted_role_detection():
    records = aggregate_entity_roles(
        [
            _row("Badmotorfinger", "artist", "Soundgarden - Badmotorfinger.flac", artist="Soundgarden", title="Badmotorfinger", folder="/music/Soundgarden"),
        ]
    )

    artist = next(record for record in records if record.entity_role == "artist")
    assert artist.role_status == "conflicted"
    assert "context_contradiction" in artist.flags


def test_canonical_graph_preserves_legitimate_multi_role_entities(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    _insert_observation(db_path, "Flyleaf", "I'm So Sick", "Flyleaf", "Flyleaf - I'm So Sick.flac")
    _insert_observation(db_path, "Flyleaf", "Fully Alive", "Flyleaf", "Flyleaf - Fully Alive.flac")
    _insert_observation(db_path, "Mudvayne", "Dig", "L.D. 50", "Mudvayne - Dig.flac")
    _insert_observation(db_path, "Soundgarden", "Rusty Cage", "Badmotorfinger", "Soundgarden - Rusty Cage.flac")

    graph = build_canonical_graph(db_path=db_path, reports_dir=tmp_path / "reports")

    artist_names = {artist.canonical_name for artist in graph.artists}
    album_names = {album.canonical_name for album in graph.albums}
    assert "Flyleaf" in artist_names
    assert "Flyleaf" in album_names
    assert "L.D. 50" in album_names
    assert "Badmotorfinger" in album_names
    assert graph.summary["multi_role_entities"] >= 1


def test_entity_roles_cli_and_ui(tmp_path, capsys):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Alice in Chains", "Grind", "Alice in Chains", "Alice in Chains - Grind.flac")

    exit_code = main(["--db", str(db_path), "entity-roles", "--out", str(reports)])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "total_role_records=" in output

    app.state.reports_dir = reports
    app.state.db_path = db_path
    response = TestClient(app).get("/review/entity-roles")

    assert response.status_code == 200
    assert "Entity Roles" in response.text
    assert "Alice in Chains" in response.text
    assert "read-only" in response.text


def _row(
    value: str,
    field_name: str,
    file_path: str,
    *,
    artist: str = "",
    title: str = "",
    album: str = "",
    folder: str = "/music/Audioslave",
) -> dict[str, object]:
    return {
        "value": value,
        "field_name": field_name,
        "file_path": file_path,
        "folder_artist": folder,
        "filename_artist": artist,
        "filename_title": title,
        "metadata_tags": {"artist": artist, "title": title, "album": album},
    }


def _insert_observation(db_path: Path, artist: str, title: str, album: str, filename: str) -> None:
    db.init_db(db_path)
    path = Path(filename)
    with db.connect(db_path) as connection:
        scan_run_id = connection.execute(
            """
            INSERT INTO scan_runs (
                source_path, started_at, completed_at, status,
                total_files_seen, audio_files_seen, files_failed
            )
            VALUES ('/music', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00',
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
            (scan_run_id, str(path), path.name, f"/music/{artist}", path.name, f"sha-{path.name}"),
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
        connection.execute(
            """
            INSERT INTO filename_observations (
                observed_file_id, cleaned_filename, possible_artist, possible_title,
                filename_pattern, parser_confidence
            )
            VALUES (?, ?, ?, ?, 'artist_title', 0.8)
            """,
            (observed_file_id, path.stem, artist, title),
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
