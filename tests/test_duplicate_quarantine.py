import sqlite3

from app import db
from app.duplicate_quarantine import quarantine_duplicates
from app.main import main


def test_dry_run_moves_nothing(tmp_path):
    db_path, review_plan_id, paths = _fixture(tmp_path)

    result = quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        dry_run=True,
        db_path=db_path,
    )

    assert result.total_remove_candidates == 1
    assert result.moved_count == 0
    assert paths["remove"].exists()
    assert not (tmp_path / "quarantine" / "Artist" / "Song (2).flac").exists()
    assert _item_rows(db_path) == []


def test_moves_remove_candidate_only(tmp_path):
    db_path, review_plan_id, paths = _fixture(tmp_path)

    result = quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        db_path=db_path,
    )

    quarantine_path = tmp_path / "quarantine" / "Artist" / "Song (2).flac"
    assert result.moved_count == 1
    assert not paths["remove"].exists()
    assert quarantine_path.read_text() == "remove"
    assert _item_rows(db_path)[0]["item_status"] == "moved"


def test_does_not_move_keep_candidate(tmp_path):
    db_path, review_plan_id, paths = _fixture(tmp_path)

    quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        db_path=db_path,
    )

    assert paths["keep"].exists()
    assert paths["keep"].read_text() == "keep"


def test_does_not_move_manual_review(tmp_path):
    db_path, review_plan_id, paths = _fixture(tmp_path)

    quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        db_path=db_path,
    )

    assert paths["manual"].exists()
    assert paths["manual"].read_text() == "manual"


def test_preserves_relative_structure(tmp_path):
    db_path, review_plan_id, _paths = _fixture(
        tmp_path,
        remove_relative_path="Artist/Album/Disc 1/Song (2).flac",
    )

    quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        db_path=db_path,
    )

    assert (
        tmp_path / "quarantine" / "Artist" / "Album" / "Disc 1" / "Song (2).flac"
    ).read_text() == "remove"


def test_skips_missing_files(tmp_path):
    db_path, review_plan_id, paths = _fixture(tmp_path)
    paths["remove"].unlink()

    result = quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        db_path=db_path,
    )

    row = _item_rows(db_path)[0]
    assert result.skipped_count == 1
    assert row["item_status"] == "skipped_missing"
    assert row["reason"] == "source_missing"


def test_skips_existing_quarantine_destination(tmp_path):
    db_path, review_plan_id, paths = _fixture(tmp_path)
    destination = tmp_path / "quarantine" / "Artist" / "Song (2).flac"
    destination.parent.mkdir(parents=True)
    destination.write_text("existing")

    result = quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=tmp_path / "quarantine",
        db_path=db_path,
    )

    row = _item_rows(db_path)[0]
    assert result.skipped_count == 1
    assert paths["remove"].exists()
    assert destination.read_text() == "existing"
    assert row["item_status"] == "skipped_exists"


def test_prevents_path_traversal(tmp_path):
    db_path, review_plan_id, paths = _fixture(
        tmp_path,
        remove_relative_path="Link/Song (2).flac",
    )
    quarantine_root = tmp_path / "quarantine"
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    quarantine_root.mkdir()
    (quarantine_root / "Link").symlink_to(outside_root, target_is_directory=True)

    result = quarantine_duplicates(
        review_plan_id=review_plan_id,
        quarantine_root=quarantine_root,
        db_path=db_path,
    )

    row = _item_rows(db_path)[0]
    assert result.failed_count == 1
    assert row["item_status"] == "failed"
    assert row["reason"] == "invalid_quarantine_path"
    assert paths["remove"].exists()
    assert not (outside_root / "Song (2).flac").exists()


def test_cli_dry_run_works(tmp_path, capsys):
    db_path, review_plan_id, paths = _fixture(tmp_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "quarantine-duplicates",
            "--review-plan-id",
            str(review_plan_id),
            "--quarantine-root",
            str(tmp_path / "quarantine"),
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "quarantine_run_id=1" in output
    assert "total_remove_candidates=1" in output
    assert "moved=0" in output
    assert "failed=0" in output
    assert "dry_run=true" in output
    assert paths["remove"].exists()


def test_cli_actual_run_works(tmp_path, capsys):
    db_path, review_plan_id, paths = _fixture(tmp_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "quarantine-duplicates",
            "--review-plan-id",
            str(review_plan_id),
            "--quarantine-root",
            str(tmp_path / "quarantine"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "quarantine_run_id=1" in output
    assert "total_remove_candidates=1" in output
    assert "moved=1" in output
    assert "skipped=0" in output
    assert "failed=0" in output
    assert "dry_run=false" in output
    assert not paths["remove"].exists()
    assert (tmp_path / "quarantine" / "Artist" / "Song (2).flac").exists()


def _fixture(tmp_path, *, remove_relative_path="Artist/Song (2).flac"):
    db_path = tmp_path / "ledger.sqlite3"
    library_root = tmp_path / "library"
    keep = library_root / "Artist" / "Song.flac"
    remove = library_root / remove_relative_path
    manual = library_root / "Artist" / "Song Live.flac"
    keep.parent.mkdir(parents=True, exist_ok=True)
    remove.parent.mkdir(parents=True, exist_ok=True)
    manual.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("keep")
    remove.write_text("remove")
    manual.write_text("manual")

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
            VALUES (?, '2026-05-10T00:00:00+00:00', 'completed', 3, 3, 0)
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
            VALUES (?, ?, '/reports/duplicates_scan_1', 3, 0, 1, 0,
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
            VALUES (?, ?, '/reports/duplicate_review_scan_1', 1, 3, 1, 1,
                '2026-05-10T00:00:00+00:00')
            """,
            (report_id, scan_run_id),
        ).lastrowid
        for path, decision in (
            (keep, "keep_candidate"),
            (remove, "remove_candidate"),
            (manual, "manual_review"),
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

    return db_path, review_plan_id, {"keep": keep, "remove": remove, "manual": manual}


def _item_rows(db_path):
    return _fetch_all(
        db_path,
        """
        SELECT *
        FROM duplicate_quarantine_items
        ORDER BY id
        """,
    )


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
