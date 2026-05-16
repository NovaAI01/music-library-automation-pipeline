import json
import sqlite3

from app import db
from app.main import main
from app.placement_planner import (
    build_planned_relative_path,
    create_placement_plan,
    detect_planned_path_collision,
    plan_scan_run_placements,
    sanitize_path_component,
)


def test_classified_identified_track_creates_planned_path(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(db_path)

    summary = plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert summary.planned == 1
    assert row["placement_status"] == "planned"
    assert row["planned_relative_path"] == (
        "Alternative Metal/Deftones/Unknown Album/Deftones - Change.mp3"
    )
    assert row["planned_album"] == "Unknown Album"


def test_null_subgenre_becomes_unsorted(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(db_path, subgenre=None)

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT planned_relative_path, planned_subgenre FROM placement_plans")[0]

    assert row["planned_subgenre"] == "_Unsorted"
    assert row["planned_relative_path"] == (
        "Alternative Metal/Deftones/Unknown Album/Deftones - Change.mp3"
    )


def test_unknown_identity_blocks_placement(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(
        db_path,
        identity_status="unknown",
        artist=None,
        title=None,
    )

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert row["placement_status"] == "blocked_unknown_identity"
    assert row["planned_relative_path"] is None


def test_unknown_classification_blocks_placement(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(
        db_path,
        classification_status="unknown",
        primary_genre=None,
        subgenre=None,
    )

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert row["placement_status"] == "blocked_unknown_classification"
    assert row["planned_relative_path"] is None


def test_conflicting_identity_creates_conflict_status(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(db_path, identity_status="conflicting")

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert row["placement_status"] == "conflict"
    assert json.loads(row["reason_json"])["reasons"] == ["identity_conflicting"]


def test_uncertain_classification_creates_needs_review_status(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(
        db_path,
        classification_status="uncertain",
        primary_genre="Alternative Rock",
        subgenre=None,
        classification_confidence=0.5,
    )

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert row["placement_status"] == "needs_review"
    assert row["placement_confidence"] == 0.5


def test_path_components_are_sanitized():
    assert sanitize_path_component('Deftones: Live/Set*?') == "Deftones Live Set"


def test_planned_relative_path_is_never_absolute():
    path = build_planned_relative_path(
        primary_genre="/Alternative Metal",
        subgenre="/Shoegaze Metal",
        artist="/Deftones",
        album="/White Pony",
        title="/Change",
        extension=".mp3",
    )

    assert not path.startswith("/")


def test_path_traversal_is_stripped():
    path = build_planned_relative_path(
        primary_genre="../Alternative Metal",
        subgenre="../../Shoegaze Metal",
        artist="../Deftones",
        album="../White Pony",
        title="../Change",
        extension=".mp3",
    )

    assert ".." not in path


def test_collision_appends_numeric_suffix():
    existing = {
        "Alternative Metal/Deftones/Unknown Album/Deftones - Change.mp3"
    }

    result = detect_planned_path_collision(
        "Alternative Metal/Deftones/Unknown Album/Deftones - Change.mp3",
        existing,
    )

    assert result == "Alternative Metal/Deftones/Unknown Album/Deftones - Change (2).mp3"


def test_repeated_planner_run_does_not_duplicate_rows(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(db_path)

    plan_scan_run_placements(scan_run_id, db_path)
    plan_scan_run_placements(scan_run_id, db_path)

    assert len(_fetch_all(db_path, "SELECT * FROM placement_plans")) == 1


def test_cli_writes_placement_plan_rows(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(db_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "plan-placement",
            "--scan-run-id",
            str(scan_run_id),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "total=1" in output
    assert "planned=1" in output
    assert len(_fetch_all(db_path, "SELECT * FROM placement_plans")) == 1


def test_create_placement_plan_collision_within_batch():
    existing = set()
    first = create_placement_plan(
        observed_file_id=1,
        scan_run_id=1,
        source_path="/music/one.mp3",
        extension=".mp3",
        identity_status="identified",
        identity_confidence=0.95,
        probable_artist="Deftones",
        probable_title="Change",
        classification_status="classified",
        classification_confidence=0.95,
        primary_genre="Alternative Metal",
        subgenre="Shoegaze Metal",
        existing_paths=existing,
    )
    second = create_placement_plan(
        observed_file_id=2,
        scan_run_id=1,
        source_path="/music/two.mp3",
        extension=".mp3",
        identity_status="identified",
        identity_confidence=0.95,
        probable_artist="Deftones",
        probable_title="Change",
        classification_status="classified",
        classification_confidence=0.95,
        primary_genre="Alternative Metal",
        subgenre="Shoegaze Metal",
        existing_paths=existing,
    )

    assert first.planned_relative_path.endswith("Deftones - Change.mp3")
    assert second.planned_relative_path.endswith("Deftones - Change (2).mp3")
    assert first.planned_album == "Unknown Album"


def _insert_track(
    db_path,
    *,
    artist="Deftones",
    title="Change",
    identity_status="identified",
    identity_confidence=0.95,
    classification_status="classified",
    classification_confidence=0.95,
    primary_genre="Alternative Metal",
    subgenre="Shoegaze Metal",
):
    db.init_db(db_path)
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
            VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, '{}',
                '2026-05-10T00:00:00+00:00')
            """,
            (observed_file_id, artist, title, identity_confidence, identity_status),
        )
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
            VALUES (?, ?, ?, NULL, NULL, '[]', ?, ?, '{}',
                '2026-05-10T00:00:00+00:00')
            """,
            (
                observed_file_id,
                primary_genre,
                subgenre,
                classification_confidence,
                classification_status,
            ),
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
