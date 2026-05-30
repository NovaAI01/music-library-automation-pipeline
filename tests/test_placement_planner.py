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
    scan_run_id = _insert_track(
        db_path,
        album="White Pony",
        year="2000",
        track_number="04",
    )

    summary = plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert summary.planned == 1
    assert row["placement_status"] == "planned"
    assert row["planned_relative_path"] == (
        "OrganizedLibrary/Music/Artists/Deftones/Albums/[2000] White Pony/"
        "04 - Change.mp3"
    )
    assert row["planned_album"] == "White Pony"


def test_null_subgenre_becomes_unsorted(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(db_path, subgenre=None)

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT planned_relative_path, planned_subgenre FROM placement_plans")[0]

    assert row["planned_subgenre"] == "_Unsorted"
    assert row["planned_relative_path"].startswith("OrganizedLibrary/Music/Artists/")


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
    assert row["planned_relative_path"] == (
        "OrganizedLibrary/_Review/identity/Deftones/Change.mp3"
    )


def test_partial_identity_routes_to_identity_review(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(
        db_path,
        identity_status="partial",
        artist=None,
        title="Change",
    )

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert row["placement_status"] == "blocked_unknown_identity"
    assert row["planned_relative_path"] == (
        "OrganizedLibrary/_Review/identity/Deftones/Change.mp3"
    )


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
    assert row["planned_relative_path"] == (
        "OrganizedLibrary/_Review/classification/Deftones/Change.mp3"
    )


def test_conflicting_identity_creates_conflict_status(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_track(db_path, identity_status="conflicting")

    plan_scan_run_placements(scan_run_id, db_path)
    row = _fetch_all(db_path, "SELECT * FROM placement_plans")[0]

    assert row["placement_status"] == "conflict"
    assert row["planned_relative_path"] == (
        "OrganizedLibrary/_Review/identity/Deftones/Change.mp3"
    )
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
    assert row["planned_relative_path"] == (
        "OrganizedLibrary/_Review/classification/Deftones/Change.mp3"
    )


def test_no_usable_identity_or_original_path_routes_to_unresolved_unknown():
    plan = create_placement_plan(
        observed_file_id=1,
        scan_run_id=1,
        source_path="",
        original_relative_path=None,
        extension=".mp3",
        identity_status="unknown",
        identity_confidence=0.1,
        probable_artist=None,
        probable_title=None,
        classification_status="unknown",
        classification_confidence=0.1,
        primary_genre=None,
        subgenre=None,
    )

    assert plan.placement_status == "blocked_unknown_identity"
    assert plan.planned_relative_path == "OrganizedLibrary/_Unresolved/unknown/_Unknown.mp3"


def test_path_components_are_sanitized():
    assert sanitize_path_component('Deftones: Live/Set*?') == "Deftones Live Set"


def test_planned_relative_path_is_never_absolute():
    path = build_planned_relative_path(
        artist="/Deftones",
        album="/White Pony",
        title="/Change",
        extension=".mp3",
        year="2000",
        track_number="04",
    )

    assert not path.startswith("/")
    assert path.startswith("OrganizedLibrary/Music/Artists/")


def test_ep_path_uses_ep_bucket():
    path = build_planned_relative_path(
        artist="Deftones",
        album="B-Sides EP",
        title="Knife Prty",
        extension=".flac",
        year="2001",
        track_number="02",
    )

    assert path == (
        "OrganizedLibrary/Music/Artists/Deftones/EPs/[2001] B-Sides EP/"
        "02 - Knife Prty.flac"
    )


def test_single_path_uses_singles_bucket():
    path = build_planned_relative_path(
        artist="Deftones",
        album=None,
        title="Change",
        extension=".mp3",
        year="2000",
    )

    assert path == "OrganizedLibrary/Music/Artists/Deftones/Singles/[2000] Change.mp3"


def test_live_path_uses_live_bucket():
    path = build_planned_relative_path(
        artist="Deftones",
        album="Live at Dynamo",
        title="Change",
        extension=".mp3",
        year="1998",
        track_number="03",
    )

    assert path == (
        "OrganizedLibrary/Music/Artists/Deftones/Live/[1998] Live at Dynamo/"
        "03 - Change.mp3"
    )


def test_various_artists_compilation_path_includes_track_artist():
    path = build_planned_relative_path(
        artist="Deftones",
        album_artist="Various Artists",
        album="Soundtrack Album",
        title="Change",
        extension=".mp3",
        year="2002",
        track_number="07",
    )

    assert path == (
        "OrganizedLibrary/Music/Compilations/Various Artists/"
        "[2002] Soundtrack Album/07 - Deftones - Change.mp3"
    )


def test_single_artist_compilation_path_uses_compilation_bucket():
    path = build_planned_relative_path(
        artist="Deftones",
        album_artist="Deftones",
        album="Greatest Hits",
        title="Change",
        extension=".mp3",
        year="2010",
        track_number="01",
    )

    assert path == (
        "OrganizedLibrary/Music/Compilations/Single Artist/"
        "[2010] Deftones - Greatest Hits/01 - Change.mp3"
    )


def test_placement_uses_clean_album_folder_for_planned_path():
    plan = create_placement_plan(
        observed_file_id=1,
        scan_run_id=1,
        source_path="/downloads/Uploader Channel/Artist Name - Album Name [Full Album]/01 Track Name.ext",
        original_relative_path="Uploader Channel/Artist Name - Album Name [Full Album]/01 Track Name.ext",
        extension=".ext",
        identity_status="identified",
        identity_confidence=0.95,
        probable_artist="Artist Name",
        probable_title="Track Name",
        probable_album=None,
        tag_album=None,
        parent_folder="Uploader Channel/Artist Name - Album Name [Full Album]",
        filename="01 Track Name.ext",
        classification_status="classified",
        classification_confidence=0.95,
        primary_genre="Test Genre",
        subgenre=None,
    )

    assert plan.planned_artist == "Artist Name"
    assert plan.planned_album == "Album Name"
    assert plan.planned_relative_path == (
        "OrganizedLibrary/Music/Artists/Artist Name/Albums/Album Name/"
        "01 - Track Name.ext"
    )
    assert "Uploader Channel" not in plan.planned_relative_path


def test_unsplit_full_album_single_file_routes_to_placement_review_tool():
    plan = create_placement_plan(
        observed_file_id=1,
        scan_run_id=1,
        source_path=(
            "/music/Anticyclone/TOOL - Lateralus (Full Album HQ)./"
            " TOOL - Lateralus (Full Album HQ)..flac"
        ),
        original_relative_path=(
            "Anticyclone/TOOL - Lateralus (Full Album HQ)./"
            " TOOL - Lateralus (Full Album HQ)..flac"
        ),
        extension=".flac",
        identity_status="identified",
        identity_confidence=0.95,
        probable_artist="Tool",
        probable_title="Lateralus (Full Album HQ)",
        probable_album="Lateralus (Full Album HQ)",
        tag_album=None,
        parent_folder="Anticyclone/TOOL - Lateralus (Full Album HQ).",
        filename=" TOOL - Lateralus (Full Album HQ)..flac",
        classification_status="classified",
        classification_confidence=0.95,
        primary_genre="Progressive Metal",
        subgenre=None,
    )

    assert plan.placement_status == "needs_review"
    assert plan.planned_relative_path == (
        "OrganizedLibrary/_Review/placement/Anticyclone/"
        "TOOL - Lateralus (Full Album HQ)/TOOL - Lateralus (Full Album HQ)flac"
    )
    assert "unsplit_full_album" in plan.reason["reasons"]


def test_unsplit_full_album_single_file_routes_to_placement_review_motionless():
    plan = create_placement_plan(
        observed_file_id=1,
        scan_run_id=1,
        source_path=(
            "/music/Motionless In White - Disguise (Full Album)/"
            " Motionless In White - Disguise (Full Album).flac"
        ),
        original_relative_path=(
            "Motionless In White - Disguise (Full Album)/"
            " Motionless In White - Disguise (Full Album).flac"
        ),
        extension=".flac",
        identity_status="identified",
        identity_confidence=0.95,
        probable_artist="Motionless in White",
        probable_title="Disguise (Full Album)",
        probable_album="Disguise",
        tag_album=None,
        parent_folder="Motionless In White - Disguise (Full Album)",
        filename=" Motionless In White - Disguise (Full Album).flac",
        classification_status="classified",
        classification_confidence=0.95,
        primary_genre="Metalcore",
        subgenre=None,
    )

    assert plan.placement_status == "needs_review"
    assert plan.planned_relative_path == (
        "OrganizedLibrary/_Review/placement/"
        "Motionless In White - Disguise (Full Album)/"
        "Motionless In White - Disguise (Full Album).flac"
    )
    assert "unsplit_full_album" in plan.reason["reasons"]


def test_chapter_split_full_album_track_stays_clean_planned_path():
    plan = create_placement_plan(
        observed_file_id=1,
        scan_run_id=1,
        source_path=(
            "/music/Warner Records Vault/Deftones - Around The Fur (Full Album)/"
            "01 My Own Summer (Shove It).flac"
        ),
        original_relative_path=(
            "Warner Records Vault/Deftones - Around The Fur (Full Album)/"
            "01 My Own Summer (Shove It).flac"
        ),
        extension=".flac",
        identity_status="identified",
        identity_confidence=0.95,
        probable_artist="Deftones",
        probable_title="My Own Summer (Shove It)",
        probable_album="Around the Fur",
        tag_album=None,
        filename_track_number="01",
        parent_folder="Warner Records Vault/Deftones - Around The Fur (Full Album)",
        filename="01 My Own Summer (Shove It).flac",
        classification_status="classified",
        classification_confidence=0.95,
        primary_genre="Alternative Metal",
        subgenre=None,
    )

    assert plan.placement_status == "planned"
    assert plan.planned_relative_path == (
        "OrganizedLibrary/Music/Artists/Deftones/Albums/Around The Fur/"
        "01 - My Own Summer (Shove It).flac"
    )
    assert "unsplit_full_album" not in plan.reason["reasons"]


def test_legitimate_standalone_single_stays_clean_planned_path():
    plan = create_placement_plan(
        observed_file_id=1,
        scan_run_id=1,
        source_path="/music/NOTHING MORE - FREEFALL.flac",
        original_relative_path="NOTHING MORE - FREEFALL.flac",
        extension=".flac",
        identity_status="identified",
        identity_confidence=0.95,
        probable_artist="Nothing More",
        probable_title="FREEFALL",
        probable_album=None,
        tag_album=None,
        parent_folder="",
        filename="NOTHING MORE - FREEFALL.flac",
        classification_status="classified",
        classification_confidence=0.95,
        primary_genre="Alternative Rock",
        subgenre=None,
    )

    assert plan.placement_status == "planned"
    assert plan.planned_relative_path == (
        "OrganizedLibrary/Music/Artists/Nothing More/Singles/FREEFALL.flac"
    )
    assert "unsplit_full_album" not in plan.reason["reasons"]


def test_path_traversal_is_stripped():
    path = build_planned_relative_path(
        artist="../Deftones",
        album="../White Pony",
        title="../Change",
        extension=".mp3",
        year="2000",
        track_number="04",
    )

    assert ".." not in path


def test_collision_appends_numeric_suffix():
    existing = {
        "OrganizedLibrary/Music/Artists/Deftones/Singles/Change.mp3"
    }

    result = detect_planned_path_collision(
        "OrganizedLibrary/Music/Artists/Deftones/Singles/Change.mp3",
        existing,
    )

    assert result == "OrganizedLibrary/Music/Artists/Deftones/Singles/Change (2).mp3"


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
        original_relative_path="one.mp3",
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
        original_relative_path="two.mp3",
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

    assert first.planned_relative_path.endswith("Change.mp3")
    assert second.planned_relative_path.endswith("Change (2).mp3")
    assert first.planned_album is None


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
    album=None,
    year=None,
    album_artist=None,
    track_number=None,
    disc_number=None,
    relative_path="Deftones/Change.mp3",
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
            VALUES (?, '/music', ?, 'Deftones', 'Change.mp3',
                '.mp3', 10, 'abc', '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id, relative_path),
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
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, '{}',
                '2026-05-10T00:00:00+00:00')
            """,
            (
                observed_file_id,
                artist,
                title,
                album,
                year,
                identity_confidence,
                identity_status,
            ),
        )
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
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL, 'ok')
            """,
            (
                observed_file_id,
                title,
                artist,
                album,
                album_artist,
                year,
                track_number,
                disc_number,
            ),
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
            VALUES (?, 'Change', NULL, ?, NULL, ?, 'track_title', 0.65)
            """,
            (observed_file_id, title, track_number),
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
