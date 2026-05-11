import sqlite3

from app import db
from app.main import main
from app.placement_executor import execute_placement


def test_copies_planned_file_to_destination(tmp_path):
    db_path, scan_run_id, source = _fixture(tmp_path)

    result = execute_placement(scan_run_id, tmp_path / "out", db_path)

    destination = tmp_path / "out" / "Rock/Alt/Artist/Artist - Song.mp3"
    assert result.copied_count == 1
    assert destination.read_text() == "audio"
    assert _file_rows(db_path)[0]["file_status"] == "copied"


def test_creates_nested_folders(tmp_path):
    db_path, scan_run_id, _source = _fixture(
        tmp_path,
        planned_relative_path="Rock/Alt/Deep/Artist - Song.mp3",
    )

    execute_placement(scan_run_id, tmp_path / "out", db_path)

    assert (tmp_path / "out" / "Rock/Alt/Deep/Artist - Song.mp3").exists()


def test_does_not_move_or_delete_source(tmp_path):
    db_path, scan_run_id, source = _fixture(tmp_path)

    execute_placement(scan_run_id, tmp_path / "out", db_path)

    assert source.exists()
    assert source.read_text() == "audio"


def test_skips_conflict_plan(tmp_path):
    db_path, scan_run_id, _source = _fixture(tmp_path, placement_status="conflict")

    result = execute_placement(scan_run_id, tmp_path / "out", db_path)

    row = _file_rows(db_path)[0]
    assert result.copied_count == 0
    assert row["file_status"] == "skipped_not_planned"
    assert not (tmp_path / "out" / "Rock/Alt/Artist/Artist - Song.mp3").exists()


def test_skips_blocked_plan(tmp_path):
    db_path, scan_run_id, _source = _fixture(
        tmp_path,
        placement_status="blocked_unknown_identity",
        planned_relative_path=None,
    )

    result = execute_placement(scan_run_id, tmp_path / "out", db_path)

    row = _file_rows(db_path)[0]
    assert result.copied_count == 0
    assert row["file_status"] == "skipped_not_planned"


def test_prevents_overwrite(tmp_path):
    db_path, scan_run_id, _source = _fixture(tmp_path)
    destination = tmp_path / "out" / "Rock/Alt/Artist/Artist - Song.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_text("existing")

    result = execute_placement(scan_run_id, tmp_path / "out", db_path)

    assert result.skipped_count == 1
    assert destination.read_text() == "existing"
    assert _file_rows(db_path)[0]["file_status"] == "skipped_exists"


def test_prevents_path_traversal(tmp_path):
    db_path, scan_run_id, _source = _fixture(
        tmp_path,
        planned_relative_path="../escape.mp3",
    )

    result = execute_placement(scan_run_id, tmp_path / "out", db_path)

    row = _file_rows(db_path)[0]
    assert result.failed_count == 1
    assert row["file_status"] == "failed"
    assert row["reason"] == "invalid_planned_relative_path"
    assert not (tmp_path / "escape.mp3").exists()


def test_prevents_absolute_planned_path(tmp_path):
    db_path, scan_run_id, _source = _fixture(
        tmp_path,
        planned_relative_path="/absolute.mp3",
    )

    result = execute_placement(scan_run_id, tmp_path / "out", db_path)

    assert result.failed_count == 1
    assert _file_rows(db_path)[0]["file_status"] == "failed"


def test_repeated_run_does_not_duplicate_copies(tmp_path):
    db_path, scan_run_id, _source = _fixture(tmp_path)

    first = execute_placement(scan_run_id, tmp_path / "out", db_path)
    second = execute_placement(scan_run_id, tmp_path / "out", db_path)

    destination = tmp_path / "out" / "Rock/Alt/Artist/Artist - Song.mp3"
    assert first.copied_count == 1
    assert second.copied_count == 0
    assert second.skipped_count == 1
    assert destination.read_text() == "audio"
    assert len(_execution_rows(db_path)) == 2


def test_cli_executes_planned_rows(tmp_path, capsys):
    db_path, scan_run_id, _source = _fixture(tmp_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "execute-placement",
            "--scan-run-id",
            str(scan_run_id),
            "--dest",
            str(tmp_path / "out"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "execution_id=1" in output
    assert "total_planned=1" in output
    assert "copied=1" in output
    assert (tmp_path / "out" / "Rock/Alt/Artist/Artist - Song.mp3").exists()


def _fixture(
    tmp_path,
    *,
    placement_status="planned",
    planned_relative_path="Rock/Alt/Artist/Artist - Song.mp3",
):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source" / "song.mp3"
    source.parent.mkdir()
    source.write_text("audio")
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
            VALUES (?, '2026-05-10T00:00:00+00:00', 'completed', 1, 1, 0)
            """,
            (str(source.parent),),
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
            VALUES (?, ?, 'song.mp3', 'source', 'song.mp3',
                '.mp3', 5, 'abc', '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id, str(source.parent)),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO placement_plans (
                observed_file_id,
                scan_run_id,
                source_path,
                planned_relative_path,
                planned_artist,
                planned_title,
                planned_primary_genre,
                planned_subgenre,
                placement_confidence,
                placement_status,
                reason_json,
                created_at
            )
            VALUES (?, ?, ?, ?, 'Artist', 'Song', 'Rock', 'Alt',
                0.95, ?, '{}', '2026-05-10T00:00:00+00:00')
            """,
            (
                observed_file_id,
                scan_run_id,
                str(source),
                planned_relative_path,
                placement_status,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return db_path, scan_run_id, source


def _file_rows(db_path):
    return _fetch_all(db_path, "SELECT * FROM placement_execution_files ORDER BY id")


def _execution_rows(db_path):
    return _fetch_all(db_path, "SELECT * FROM placement_executions ORDER BY id")


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
