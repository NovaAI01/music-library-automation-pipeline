import csv
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.canonical_entity_classifier import (
    CandidateContext,
    classify_candidate,
    generate_canonical_entity_classification_report,
)
from app.canonical_entity_graph import generate_canonical_graph
from app.main import app, main
from app.review_decisions import record_review_decision, suggestion_key_for


def test_track_title_as_artist_detection_examples():
    examples = [
        "6. 3 Libras",
        "A Place For My Head",
        "Heavy Is the Crown (Official Audio)",
        "Last Resort (explicit)",
        "Lying From You",
    ]

    for value in examples:
        result = classify_candidate(
            CandidateContext(
                candidate_value=value,
                field_name="artist",
                folder_artist="Linkin Park",
                filename_title=value,
                metadata_tags={"title": value},
                value_artist_count=1,
                value_title_count=1,
            )
        )

        assert result.proposed_entity_type == "track_title_misclassified_as_artist"
        assert result.confidence_tier == "high"


def test_uploader_and_source_artifact_detection_examples():
    examples = [
        "Warner Records Vault",
        "David Rolfe's Rock & Metal Channel",
        "UNFD",
        "BEARTOOTHband",
        "The Korn Projekt",
        "Lagu Pre Studio",
        "MrKculnalyd",
    ]

    for value in examples:
        result = classify_candidate(
            CandidateContext(
                candidate_value=value,
                field_name="artist",
                folder_artist="Beartooth",
                value_artist_count=1,
            )
        )

        assert result.proposed_entity_type in {"source_or_label_artifact", "uploader_channel_artifact"}
        assert result.confidence_tier == "high"


def test_valid_artist_confidence_from_repetition_review_and_knowledge(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    _approve_artist_alias(db_path, "Static X", "Static-X")

    result = classify_candidate(
        CandidateContext(
            candidate_value="Static-X",
            field_name="artist",
            folder_artist="Static-X",
            value_artist_count=8,
            approved_review_support=True,
            normalization_knowledge_support=True,
        )
    )

    assert result.proposed_entity_type == "canonical_artist"
    assert result.confidence_score >= 0.9
    assert "folder_artist_match" in result.flags
    assert "approved_review_support" in result.flags


def test_ambiguous_candidate_handling():
    result = classify_candidate(
        CandidateContext(
            candidate_value="A Different Name",
            field_name="artist",
            folder_artist="Static-X",
            value_artist_count=1,
        )
    )

    assert result.proposed_entity_type == "unknown_or_ambiguous"
    assert result.confidence_tier == "low"
    assert "single_artist_folder_disagreement" in result.flags


def test_report_generation_and_no_mutation(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    media_file = tmp_path / "Heavy Is the Crown.flac"
    media_file.write_bytes(b"unchanged")
    before = (media_file.read_bytes(), os.stat(media_file).st_mtime_ns)
    _insert_observation(
        db_path,
        artist="Heavy Is the Crown (Official Audio)",
        title="Heavy Is the Crown (Official Audio)",
        album="From Zero",
        filename=str(media_file),
        folder="/music/Linkin Park",
    )
    _insert_observation(
        db_path,
        artist="Linkin Park",
        title="Lying From You",
        album="Meteora",
        filename="Linkin Park - Lying From You.flac",
        folder="/music/Linkin Park",
    )

    result = generate_canonical_entity_classification_report(out_dir=reports, db_path=db_path)
    report_dir = reports / "canonical_entity_classification"
    summary = json.loads((report_dir / "entity_classification_summary.json").read_text(encoding="utf-8"))
    blocked = _read_csv(report_dir / "blocked_entity_candidates.csv")
    ambiguous = _read_csv(report_dir / "ambiguous_entity_candidates.csv")

    assert result.total_candidates >= 6
    assert summary["misclassified_track_titles"] >= 1
    assert blocked
    assert (report_dir / "entity_classifications.csv").exists()
    assert (report_dir / "ambiguous_entity_candidates.csv").exists()
    assert ambiguous == [] or isinstance(ambiguous, list)
    assert (media_file.read_bytes(), os.stat(media_file).st_mtime_ns) == before


def test_classifier_cli(tmp_path, capsys):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(
        db_path,
        artist="Warner Records Vault",
        title="Push It",
        album="Wisconsin Death Trip",
        filename="Static-X - Push It.flac",
        folder="/music/Static-X",
    )

    exit_code = main(["--db", str(db_path), "classify-canonical-entities", "--out", str(reports)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "total_candidates=" in output
    assert "blocked_candidates=" in output


def test_graph_integration_blocks_polluted_artist(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(
        db_path,
        artist="A Place For My Head",
        title="A Place For My Head",
        album="Hybrid Theory",
        filename="Linkin Park - A Place For My Head.flac",
        folder="/music/Linkin Park",
    )
    _insert_observation(
        db_path,
        artist="Linkin Park",
        title="Papercut",
        album="Hybrid Theory",
        filename="Linkin Park - Papercut.flac",
        folder="/music/Linkin Park",
    )

    result = generate_canonical_graph(out_dir=reports, db_path=db_path)

    with db.connect(db_path) as connection:
        artist_names = [row["canonical_name"] for row in connection.execute("SELECT canonical_name FROM canonical_artists")]
        conflicts = [row["rationale"] for row in connection.execute("SELECT rationale FROM canonical_unresolved_conflicts")]
    assert "A Place For My Head" not in artist_names
    assert "Linkin Park" in artist_names
    assert result.blocked_candidate_count >= 1
    assert any("classification blocked canonical promotion" in rationale for rationale in conflicts)


def test_entity_classification_ui_route_rendering(tmp_path):
    reports = tmp_path / "reports"
    db_path = tmp_path / "music.sqlite3"
    _insert_observation(
        db_path,
        artist="David Rolfe's Rock & Metal Channel",
        title="Push It",
        album="Wisconsin Death Trip",
        filename="Static-X - Push It.flac",
        folder="/music/Static-X",
    )
    generate_canonical_entity_classification_report(out_dir=reports, db_path=db_path)
    app.state.reports_dir = reports
    app.state.db_path = db_path

    response = TestClient(app).get("/review/entity-classification")

    assert response.status_code == 200
    assert "Entity Classification" in response.text
    assert "David Rolfe" in response.text
    assert "read-only" in response.text


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


def _insert_observation(
    db_path: Path,
    *,
    artist: str,
    title: str,
    album: str,
    filename: str,
    folder: str,
) -> None:
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
