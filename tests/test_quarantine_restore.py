import sqlite3

from app import db
from app.duplicate_quarantine import quarantine_duplicates
from app.main import main
from app.quarantine_restore import restore_quarantine


def test_dry_run_moves_nothing(tmp_path):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)

    result = restore_quarantine(
        quarantine_run_id=quarantine_run_id,
        dry_run=True,
        db_path=db_path,
    )

    assert result.total_restore_candidates == 1
    assert result.restored_count == 0
    assert not paths["restore"].exists()
    assert paths["quarantine"].exists()
    assert _restore_item_rows(db_path) == []


def test_restores_quarantined_file_to_original_source_path(tmp_path):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)

    result = restore_quarantine(quarantine_run_id=quarantine_run_id, db_path=db_path)

    row = _restore_item_rows(db_path)[0]
    assert result.restored_count == 1
    assert paths["restore"].read_text() == "remove"
    assert not paths["quarantine"].exists()
    assert row["item_status"] == "restored"
    assert row["restore_path"] == str(paths["restore"])


def test_skips_if_quarantine_file_missing(tmp_path):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)
    paths["quarantine"].unlink()

    result = restore_quarantine(quarantine_run_id=quarantine_run_id, db_path=db_path)

    row = _restore_item_rows(db_path)[0]
    assert result.skipped_count == 1
    assert not paths["restore"].exists()
    assert row["item_status"] == "skipped_missing_quarantine_file"
    assert row["reason"] == "quarantine_file_missing"


def test_skips_if_restore_target_already_exists(tmp_path):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)
    paths["restore"].parent.mkdir(parents=True, exist_ok=True)
    paths["restore"].write_text("existing")

    result = restore_quarantine(quarantine_run_id=quarantine_run_id, db_path=db_path)

    row = _restore_item_rows(db_path)[0]
    assert result.skipped_count == 1
    assert paths["restore"].read_text() == "existing"
    assert paths["quarantine"].read_text() == "remove"
    assert row["item_status"] == "skipped_restore_target_exists"


def test_does_not_overwrite_existing_library_file(tmp_path):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)
    paths["restore"].parent.mkdir(parents=True, exist_ok=True)
    paths["restore"].write_text("library")

    restore_quarantine(quarantine_run_id=quarantine_run_id, db_path=db_path)

    assert paths["restore"].read_text() == "library"
    assert paths["quarantine"].read_text() == "remove"


def test_repeated_run_is_safe(tmp_path):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)

    first = restore_quarantine(quarantine_run_id=quarantine_run_id, db_path=db_path)
    second = restore_quarantine(quarantine_run_id=quarantine_run_id, db_path=db_path)

    rows = _restore_item_rows(db_path)
    assert first.restored_count == 1
    assert second.skipped_count == 1
    assert paths["restore"].read_text() == "remove"
    assert rows[-1]["item_status"] == "skipped_missing_quarantine_file"


def test_validates_restore_path_boundary(tmp_path):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)
    outside_restore = tmp_path / "outside" / "Song (2).flac"
    _set_quarantine_item_source_path(db_path, outside_restore)

    result = restore_quarantine(quarantine_run_id=quarantine_run_id, db_path=db_path)

    row = _restore_item_rows(db_path)[0]
    assert result.failed_count == 1
    assert row["item_status"] == "failed"
    assert row["reason"] == "restore_path_outside_library_root"
    assert not outside_restore.exists()
    assert paths["quarantine"].exists()


def test_cli_dry_run_works(tmp_path, capsys):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "restore-quarantine",
            "--quarantine-run-id",
            str(quarantine_run_id),
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "restore_run_id=1" in output
    assert "total_restore_candidates=1" in output
    assert "restored=0" in output
    assert "failed=0" in output
    assert "dry_run=true" in output
    assert not paths["restore"].exists()
    assert paths["quarantine"].exists()


def test_cli_actual_restore_works(tmp_path, capsys):
    db_path, quarantine_run_id, paths = _quarantined_fixture(tmp_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "restore-quarantine",
            "--quarantine-run-id",
            str(quarantine_run_id),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "restore_run_id=1" in output
    assert "total_restore_candidates=1" in output
    assert "restored=1" in output
    assert "skipped=0" in output
    assert "failed=0" in output
    assert "dry_run=false" in output
    assert paths["restore"].read_text() == "remove"
    assert not paths["quarantine"].exists()


def _quarantined_fixture(tmp_path):
    db_path, review_plan_id, paths = _review_fixture(tmp_path)
    quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        db_path=db_path,
    )
    quarantine_run = _fetch_one(
        db_path,
        "SELECT id FROM duplicate_quarantine_runs ORDER BY id DESC LIMIT 1",
    )
    quarantine_path = tmp_path / "quarantine" / "Artist" / "Song (2).flac"
    return (
        db_path,
        quarantine_run["id"],
        {"restore": paths["remove"], "quarantine": quarantine_path},
    )


def _review_fixture(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    library_root = tmp_path / "library"
    keep = library_root / "Artist" / "Song.flac"
    remove = library_root / "Artist" / "Song (2).flac"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("keep")
    remove.write_text("remove")

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
            VALUES (?, '2026-05-10T00:00:00+00:00', 'completed', 2, 2, 0)
            """,
            (str(library_root),),
        ).lastrowid
        report_id = connection.execute(
            """
            INSERT INTO duplicate_reports (
                scan_run_id,
                library_root,
                report_path,
                total_files_checked,
                exact_hash_groups,
                same_artist_title_groups,
                variant_title_groups,
                created_at
            )
            VALUES (?, ?, '/reports/duplicates_scan_1', 2, 0, 1, 0,
                '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id, str(library_root)),
        ).lastrowid
        review_plan_id = connection.execute(
            """
            INSERT INTO duplicate_review_plans (
                duplicate_report_id,
                scan_run_id,
                plan_path,
                total_groups,
                total_files_reviewed,
                keeper_count,
                remove_candidate_count,
                created_at
            )
            VALUES (?, ?, '/reports/duplicate_review_scan_1', 1, 2, 1, 1,
                '2026-05-10T00:00:00+00:00')
            """,
            (report_id, scan_run_id),
        ).lastrowid
        for path, decision in (
            (keep, "keep_candidate"),
            (remove, "remove_candidate"),
        ):
            connection.execute(
                """
                INSERT INTO duplicate_review_items (
                    review_plan_id,
                    duplicate_group_key,
                    file_path,
                    decision,
                    reason,
                    created_at
                )
                VALUES (?, 'same_artist_title:artist:song', ?, ?, 'fixture',
                    '2026-05-10T00:00:00+00:00')
                """,
                (review_plan_id, str(path), decision),
            )
        connection.commit()
    finally:
        connection.close()

    return db_path, review_plan_id, {"keep": keep, "remove": remove}


def _set_quarantine_item_source_path(db_path, source_path):
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            UPDATE duplicate_quarantine_items
            SET source_path = ?
            """,
            (str(source_path),),
        )
        connection.commit()
    finally:
        connection.close()


def _restore_item_rows(db_path):
    return _fetch_all(
        db_path,
        """
        SELECT *
        FROM quarantine_restore_items
        ORDER BY id
        """,
    )


def _fetch_one(db_path, sql):
    rows = _fetch_all(db_path, sql)
    return rows[0]


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
