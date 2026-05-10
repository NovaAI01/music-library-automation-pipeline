import json
import sqlite3

from app import db
from app.classifier import (
    REQUIRED_CLASSIFICATION_EVIDENCE_FIELDS,
    build_classification_evidence,
    calculate_classification_confidence,
    classify_by_artist_seed,
    classify_by_genre_tag,
    classify_track,
)
from app.main import main


def test_artist_seed_classification_wins():
    result = classify_track(probable_artist="Deftones", genre_tag="Pop")

    assert result.classification_status == "classified"
    assert result.classification_confidence == 0.95
    assert result.primary_genre == "Alternative Metal"
    assert result.subgenre == "Shoegaze Metal"
    assert "artist_seed_match" in result.evidence["evidence_items"]


def test_embedded_genre_tag_used_when_artist_unknown():
    result = classify_track(probable_artist="Unknown Artist", genre_tag="Hard Rock")

    assert result.classification_status == "inferred"
    assert result.classification_confidence == 0.75
    assert result.primary_genre == "Hard Rock"
    assert result.subgenre is None
    assert result.energy_level is None
    assert result.vocal_style is None
    assert result.mood == []
    assert "genre_tag" in result.evidence["evidence_items"]


def test_artist_seed_beats_conflicting_genre_tag():
    result = classify_track(probable_artist="System of a Down", genre_tag="Grunge")

    assert result.classification_status == "classified"
    assert result.primary_genre == "Nu Metal"
    assert result.subgenre == "Rap Metal"
    assert result.evidence["genre_tag"] == "Grunge"
    assert result.evidence["selected_source"] == "artist_seed"


def test_unknown_when_no_artist_or_genre_tag_exists():
    result = classify_track()

    assert result.classification_status == "unknown"
    assert result.classification_confidence == 0.20
    assert result.primary_genre is None
    assert result.subgenre is None


def test_mood_json_comes_from_artist_seed():
    result = classify_track(probable_artist="Deftones")

    assert result.mood == ["dark", "atmospheric", "melodic"]


def test_energy_level_comes_from_artist_seed():
    result = classify_track(probable_artist="Deftones")

    assert result.energy_level == "high"


def test_vocal_style_comes_from_artist_seed():
    result = classify_track(probable_artist="Deftones")

    assert result.vocal_style == "mixed"


def test_confidence_scoring_is_deterministic():
    assert (
        calculate_classification_confidence(
            classification_status="classified",
            selected_source="artist_seed",
        )
        == 0.95
    )
    assert (
        calculate_classification_confidence(
            classification_status="inferred",
            selected_source="genre_tag",
            normalized_genre="Hard Rock",
        )
        == 0.75
    )
    assert (
        calculate_classification_confidence(classification_status="uncertain")
        == 0.50
    )
    assert (
        calculate_classification_confidence(classification_status="unknown")
        == 0.20
    )


def test_evidence_json_contains_required_fields():
    evidence = build_classification_evidence(
        selected_source="artist_seed",
        probable_artist="Deftones",
        genre_tag="Pop",
        normalized_genre=None,
        artist_seed_matched="Deftones",
        evidence_items=["artist_seed_match"],
    )

    assert set(REQUIRED_CLASSIFICATION_EVIDENCE_FIELDS).issubset(evidence)
    assert json.loads(json.dumps(evidence)) == evidence


def test_genre_tag_variants():
    inferred = classify_by_genre_tag(
        probable_artist="Unknown Artist",
        genre_tag="alt rock",
    )
    uncertain = classify_by_genre_tag(
        probable_artist="Unknown Artist",
        genre_tag="space wizard rock",
    )

    assert inferred.primary_genre == "Alternative Rock"
    assert inferred.classification_status == "inferred"
    assert uncertain.primary_genre is None
    assert uncertain.classification_status == "uncertain"
    assert uncertain.classification_confidence == 0.50


def test_classify_by_artist_seed_returns_none_without_seed():
    assert classify_by_artist_seed(probable_artist="Unknown Artist") is None


def test_cli_writes_classification_rows_and_does_not_duplicate(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    db.init_db(db_path)
    scan_run_id = _insert_identified_track(
        db_path,
        probable_artist="Deftones",
        genre_tag="Pop",
    )

    assert (
        main(
            [
                "--db",
                str(db_path),
                "classify",
                "--scan-run-id",
                str(scan_run_id),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--db",
                str(db_path),
                "classify",
                "--scan-run-id",
                str(scan_run_id),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "total=1" in output
    assert "classified=1" in output

    rows = _fetch_all(db_path, "SELECT * FROM classification_results")
    assert len(rows) == 1
    assert rows[0]["primary_genre"] == "Alternative Metal"
    assert rows[0]["subgenre"] == "Shoegaze Metal"
    assert rows[0]["energy_level"] == "high"
    assert rows[0]["vocal_style"] == "mixed"
    assert json.loads(rows[0]["mood_json"]) == [
        "dark",
        "atmospheric",
        "melodic",
    ]
    assert rows[0]["classification_status"] == "classified"
    assert rows[0]["classification_confidence"] == 0.95
    evidence = json.loads(rows[0]["evidence_json"])
    assert set(REQUIRED_CLASSIFICATION_EVIDENCE_FIELDS).issubset(evidence)


def _insert_identified_track(db_path, *, probable_artist, genre_tag):
    connection = sqlite3.connect(db_path)
    try:
        scan_run_id = connection.execute(
            """
            INSERT INTO scan_runs (
                source_path,
                started_at,
                status,
                total_files_seen,
                audio_files_seen,
                files_failed
            )
            VALUES ('/music', '2026-05-10T00:00:00+00:00', 'completed', 1, 1, 0)
            """
        ).lastrowid
        observed_file_id = connection.execute(
            """
            INSERT INTO observed_files (
                scan_run_id,
                source_path,
                relative_path,
                parent_folder,
                filename,
                extension,
                file_size_bytes,
                sha256,
                created_at
            )
            VALUES (?, '/music', 'Deftones/Change.mp3', 'Deftones', 'Change.mp3',
                '.mp3', 10, 'abc', '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id,),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO tag_observations (
                observed_file_id,
                title,
                artist,
                album,
                album_artist,
                genre,
                date,
                track_number,
                disc_number,
                composer,
                comment,
                tag_status
            )
            VALUES (?, 'Change', ?, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, 'ok')
            """,
            (observed_file_id, probable_artist, genre_tag),
        )
        connection.execute(
            """
            INSERT INTO track_identity (
                observed_file_id,
                probable_artist,
                probable_title,
                probable_album,
                probable_year,
                probable_mix,
                identity_confidence,
                identity_status,
                evidence_json,
                created_at
            )
            VALUES (?, ?, 'Change', NULL, NULL, NULL, 0.95, 'identified', '{}',
                '2026-05-10T00:00:00+00:00')
            """,
            (observed_file_id, probable_artist),
        )
        connection.commit()
        return scan_run_id
    finally:
        connection.close()


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
