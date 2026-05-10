import json
import sqlite3

from app import db
from app.identity_engine import (
    REQUIRED_EVIDENCE_FIELDS,
    build_identity_evidence,
    calculate_identity_confidence,
    identify_scan_run,
    resolve_identity,
)
from app.main import main


def test_complete_tag_identity():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        tag_album="White Pony",
        tag_date="2000-06-20",
        filename_artist="Deftones",
        filename_title="Change",
    )

    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Change"
    assert result.probable_album == "White Pony"
    assert result.probable_year == "2000"
    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.95
    assert result.evidence["selected_artist_source"] == "tag"
    assert result.evidence["selected_title_source"] == "tag"


def test_filename_only_identity():
    result = resolve_identity(
        filename_artist="Unknown Band",
        filename_title="Unknown Song",
    )

    assert result.probable_artist == "Unknown Band"
    assert result.probable_title == "Unknown Song"
    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.75


def test_artist_seed_normalization():
    result = resolve_identity(filename_artist="NIN", filename_title="Closer")

    assert result.probable_artist == "Nine Inch Nails"
    assert result.probable_title == "Closer"
    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.evidence["artist_seed_matched"] == "Nine Inch Nails"


def test_conflicting_artist_detection():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        filename_artist="Korn",
        filename_title="Change",
    )

    assert result.identity_status == "conflicting"
    assert result.identity_confidence == 0.40
    assert result.probable_artist == "Deftones"
    assert "tag_artist_conflicts_with_filename_artist" in result.evidence[
        "conflict_reasons"
    ]


def test_conflicting_title_detection():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        filename_artist="Deftones",
        filename_title="Digital Bath",
    )

    assert result.identity_status == "conflicting"
    assert result.identity_confidence == 0.40
    assert result.probable_title == "Change"
    assert "tag_title_conflicts_with_filename_title" in result.evidence[
        "conflict_reasons"
    ]


def test_uploader_tag_artist_with_filename_seed_artist_resolves_identified():
    result = resolve_identity(
        tag_artist="David Rolfe's Rock & Metal Channel.",
        tag_title="I'm So Sick",
        filename_artist="Flyleaf",
        filename_title="I'm So Sick",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Flyleaf"
    assert result.probable_title == "I'm So Sick"
    assert result.evidence["selected_artist_source"] == "filename"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["deprioritized_reason"] == "uploader_or_label_metadata"


def test_label_tag_artist_with_filename_seed_artist_resolves_identified():
    result = resolve_identity(
        tag_artist="Roadrunner Records",
        tag_title="Digital Bath",
        filename_artist="Deftones",
        filename_title="Digital Bath",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Digital Bath"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["deprioritized_reason"] == "uploader_or_label_metadata"


def test_tag_artist_seed_match_remains_preferred():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        filename_artist="Deftones",
        filename_title="Change",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.95
    assert result.probable_artist == "Deftones"
    assert result.evidence["selected_artist_source"] == "tag"
    assert "tag_artist_deprioritized" not in result.evidence


def test_different_valid_seed_artists_still_conflict():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        filename_artist="Nothing More",
        filename_title="Change",
    )

    assert result.identity_status == "conflicting"
    assert result.identity_confidence == 0.40
    assert result.probable_artist == "Deftones"
    assert "tag_artist_conflicts_with_filename_artist" in result.evidence[
        "conflict_reasons"
    ]


def test_youtube_title_suffixes_are_removed():
    result = resolve_identity(
        filename_artist="Deftones",
        filename_title="Be Quiet and Drive (Official Music Video) [HD Remaster]",
    )

    assert result.probable_title == "Be Quiet and Drive"
    assert result.identity_status == "identified"


def test_better_noise_music_nothing_more_resolves_nothing_more():
    result = resolve_identity(
        tag_artist="Better Noise Music",
        tag_title="Jenny",
        filename_artist="NOTHING MORE",
        filename_title="Jenny (Official Video)",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Nothing More"
    assert result.probable_title == "Jenny"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["deprioritized_reason"] == "uploader_or_label_metadata"


def test_deftones_filename_remains_deftones_and_title_cleans():
    result = resolve_identity(
        tag_artist="Warner Records",
        tag_title="My Own Summer",
        filename_artist="Deftones",
        filename_title="My Own Summer [Official Music Video] [4K]",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "My Own Summer"
    assert result.evidence["selected_artist_source"] == "filename"
    assert result.evidence["selected_title_source"] == "filename"


def test_parent_folder_treated_as_weak_evidence():
    result = resolve_identity(parent_folder="Deftones")

    assert result.probable_artist == "Deftones"
    assert result.probable_title is None
    assert result.identity_status == "partial"
    assert result.identity_confidence == 0.60
    assert result.evidence["selected_artist_source"] == "parent_folder"


def test_partial_artist_only():
    result = resolve_identity(tag_artist="Deftones")

    assert result.probable_artist == "Deftones"
    assert result.probable_title is None
    assert result.identity_status == "partial"
    assert result.identity_confidence == 0.60


def test_partial_title_only():
    result = resolve_identity(filename_title="Change")

    assert result.probable_artist is None
    assert result.probable_title == "Change"
    assert result.identity_status == "partial"
    assert result.identity_confidence == 0.60


def test_unknown_identity():
    result = resolve_identity()

    assert result.probable_artist is None
    assert result.probable_title is None
    assert result.identity_status == "unknown"
    assert result.identity_confidence == 0.10


def test_deterministic_confidence_scoring():
    assert (
        calculate_identity_confidence(
            identity_status="identified",
            selected_artist_source="tag",
            selected_title_source="tag",
            tag_artist="Deftones",
            tag_title="Change",
        )
        == 0.95
    )
    assert (
        calculate_identity_confidence(
            identity_status="identified",
            selected_artist_source="filename",
            selected_title_source="filename",
            filename_artist="Deftones",
            filename_title="Change",
            artist_seed_matched="Deftones",
        )
        == 0.85
    )
    assert calculate_identity_confidence(identity_status="partial") == 0.60
    assert calculate_identity_confidence(identity_status="conflicting") == 0.40
    assert calculate_identity_confidence(identity_status="unknown") == 0.10


def test_evidence_json_contains_required_fields():
    evidence = build_identity_evidence(
        selected_artist_source="filename",
        selected_title_source="filename",
        tag_artist=None,
        tag_title=None,
        filename_artist="Deftones",
        filename_title="Change",
        parent_folder="Deftones",
        artist_seed_matched="Deftones",
        conflict_reasons=[],
    )

    assert set(REQUIRED_EVIDENCE_FIELDS).issubset(evidence)
    assert json.loads(json.dumps(evidence)) == evidence


def test_cli_writes_identity_rows(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    db.init_db(db_path)

    scan_run_id = _insert_observed_track(
        db_path,
        tag_artist=None,
        tag_title=None,
        filename_artist="Deftones",
        filename_title="Change",
        parent_folder="Albums/Deftones",
    )

    exit_code = main(
        [
            "--db",
            str(db_path),
            "identify",
            "--scan-run-id",
            str(scan_run_id),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "total=1" in output
    assert "identified=1" in output

    rows = _fetch_all(db_path, "SELECT * FROM track_identity")
    assert len(rows) == 1
    assert rows[0]["probable_artist"] == "Deftones"
    assert rows[0]["probable_title"] == "Change"
    assert rows[0]["identity_status"] == "identified"
    assert rows[0]["identity_confidence"] == 0.85
    evidence = json.loads(rows[0]["evidence_json"])
    assert set(REQUIRED_EVIDENCE_FIELDS).issubset(evidence)


def _insert_observed_track(
    db_path,
    *,
    tag_artist,
    tag_title,
    filename_artist,
    filename_title,
    parent_folder,
):
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
            VALUES (?, '/music', 'Albums/Deftones/Change.mp3', ?, 'Change.mp3',
                '.mp3', 10, 'abc', '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id, parent_folder),
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
            VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'ok')
            """,
            (observed_file_id, tag_title, tag_artist),
        )
        connection.execute(
            """
            INSERT INTO filename_observations (
                observed_file_id,
                cleaned_filename,
                possible_artist,
                possible_title,
                possible_mix,
                possible_track_number,
                filename_pattern,
                parser_confidence
            )
            VALUES (?, 'Deftones - Change', ?, ?, NULL, NULL, 'artist_title', 0.8)
            """,
            (observed_file_id, filename_artist, filename_title),
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
