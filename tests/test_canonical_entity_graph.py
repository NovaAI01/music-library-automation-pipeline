import csv
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.canonical_entity_graph import build_canonical_graph, generate_canonical_graph
from app.main import app, main
from app.review_decisions import record_review_decision, suggestion_key_for


def test_artist_alias_resolution_and_confidence_evolution(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    _insert_observation(db_path, "Static X", "Push It", "Wisconsin Death Trip", "Static X - Push It.flac")
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", "Static-X - Push It.flac")
    _approve_artist_alias(db_path, "Static X", "Static-X")

    graph = build_canonical_graph(db_path=db_path, reports_dir=tmp_path / "reports")

    assert len(graph.artists) == 1
    assert graph.artists[0].canonical_name == "Static-X"
    assert graph.artists[0].confidence_tier in {"medium", "high"}
    assert any(row.relationship_type == "alias_of" for row in graph.relationships)


def test_duplicate_track_and_alternate_version_relationships(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", "01 Push It.flac")
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", "02 Push It.flac")
    _insert_observation(db_path, "Static-X", "Push It (Live)", "Wisconsin Death Trip", "03 Push It Live.flac")
    _insert_observation(db_path, "Static-X", "Push It (Remaster)", "Wisconsin Death Trip", "04 Push It Remaster.flac")

    graph = build_canonical_graph(db_path=db_path, reports_dir=tmp_path / "reports")
    relationship_types = {row.relationship_type for row in graph.relationships}

    assert "probable_same_track" in relationship_types
    assert "probable_live_version" in relationship_types
    assert "probable_remaster" in relationship_types
    assert graph.summary["duplicate_relationships"] >= 1


def test_conflicting_artist_variants_remain_unresolved(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    _insert_observation(db_path, "Static X", "Push It", "", "a.flac")
    _insert_observation(db_path, "STATIC X", "Push It", "", "b.flac")

    graph = build_canonical_graph(db_path=db_path, reports_dir=tmp_path / "reports")

    assert graph.artists[0].status == "conflicted"
    assert graph.unresolved_conflicts
    assert "STATIC X" in graph.unresolved_conflicts[0].variants


def test_relationship_generation_from_album_cohesion(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", "01.flac")
    _write_album_cohesion(reports)

    graph = build_canonical_graph(db_path=db_path, reports_dir=reports)

    assert any(row.relationship_type == "belongs_to_album" for row in graph.relationships)


def test_graph_report_generation_and_persistence(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", "01.flac")

    result = generate_canonical_graph(out_dir=reports, db_path=db_path)
    report_dir = reports / "canonical_graph"

    assert result.report_path == str(report_dir)
    assert (report_dir / "canonical_artists.csv").exists()
    assert (report_dir / "canonical_albums.csv").exists()
    assert (report_dir / "canonical_tracks.csv").exists()
    assert (report_dir / "entity_relationships.csv").exists()
    assert (report_dir / "unresolved_conflicts.csv").exists()
    assert json.loads((report_dir / "graph_summary.json").read_text())["canonical_artist_count"] == 1
    with db.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM canonical_artists").fetchone()[0] == 1


def test_canonical_graph_ui_renders(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", "01.flac")
    generate_canonical_graph(out_dir=reports, db_path=db_path)
    app.state.reports_dir = reports
    app.state.db_path = db_path

    response = TestClient(app).get("/review/canonical-graph")

    assert response.status_code == 200
    assert "Canonical Graph" in response.text
    assert "Static-X" in response.text
    assert "observational" in response.text


def test_canonical_graph_cli(tmp_path, capsys):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", "01.flac")

    exit_code = main(["--db", str(db_path), "canonical-graph", "--out", str(reports)])

    assert exit_code == 0
    assert "canonical_artist_count=1" in capsys.readouterr().out


def test_no_mutation_behavior(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    media_file = tmp_path / "Static-X - Push It.flac"
    media_file.write_bytes(b"not real audio but still source bytes")
    before = media_file.read_bytes()
    _insert_observation(db_path, "Static-X", "Push It", "Wisconsin Death Trip", str(media_file))

    generate_canonical_graph(out_dir=tmp_path / "reports", db_path=db_path)

    assert media_file.read_bytes() == before


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
        reason="confirmed during review",
        db_path=db_path,
        suggestion={
            "file_path": "/music/a.flac",
            "field": "artist",
            "current_value": current,
            "proposed_value": proposed,
            "suggestion_type": "artist_casing",
            "confidence": "high",
            "source_evidence": ["test"],
        },
    )


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
            VALUES (?, ?, ?, '/music/Static-X', ?, '.flac', 10, ?, '2026-01-01T00:00:00+00:00')
            """,
            (scan_run_id, str(path), path.name, path.name, f"sha-{path.name}"),
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


def _write_album_cohesion(reports: Path) -> None:
    report_dir = reports / "album_cohesion"
    report_dir.mkdir(parents=True)
    (report_dir / "album_cohesion_summary.json").write_text(
        json.dumps({"created_at": "2026-01-01T00:00:00+00:00", "total_album_groups": 1}),
        encoding="utf-8",
    )
    (report_dir / "album_groups.json").write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "group_key": "static-x:wisconsin-death-trip",
                        "album": "Wisconsin Death Trip",
                        "artist": "Static-X",
                        "track_count": 1,
                        "cohesion_score": 0.76,
                        "confidence_tier": "high",
                        "classification": "album",
                        "rationale": ["repeated album folder structure"],
                        "tracks": [{"file_path": "01.flac", "title": "Push It"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    for name in ("album_conflicts.csv", "orphan_tracks.csv"):
        with (report_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["group_key"])
