import csv
import json
import sqlite3

from app import db
from app.duplicate_review import generate_duplicate_review_plan
from app.main import main


def test_selects_no_numeric_suffix_as_keeper(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": "/library/Deftones - Change (2).flac", "size": 200},
                {"path": "/library/Deftones - Change.flac", "size": 100},
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(
        db_path,
        """
        SELECT file_path, decision
        FROM duplicate_review_items
        ORDER BY file_path
        """,
    )
    assert _decision_for(rows, "/library/Deftones - Change.flac") == "keep_candidate"
    assert (
        tmp_path
        / "reports"
        / f"duplicate_review_scan_{scan_run_id}"
        / "duplicate_review_plan.csv"
    ).exists()


def test_clean_filename_beats_trailing_dash_filename(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:falling in reverse:voices in my head": [
                {
                    "path": "/library/Falling in Reverse - Voices In My Head -.flac",
                    "size": 200,
                },
                {
                    "path": "/library/Falling in Reverse - Voices In My Head.flac",
                    "size": 100,
                },
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(db_path, "SELECT file_path, decision FROM duplicate_review_items")
    assert (
        _decision_for(rows, "/library/Falling in Reverse - Voices In My Head.flac")
        == "keep_candidate"
    )


def test_numeric_suffix_still_loses_to_clean_base_name(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": "/library/Deftones - Change (2).flac", "size": 300},
                {"path": "/library/Deftones - Change.flac", "size": 100},
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(db_path, "SELECT file_path, decision FROM duplicate_review_items")
    assert _decision_for(rows, "/library/Deftones - Change.flac") == "keep_candidate"


def test_larger_file_does_not_beat_dirty_trailing_dash(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:static x:push it": [
                {"path": "/library/Static-X - Push It-.flac", "size": 500},
                {"path": "/library/Static-X - Push It.flac", "size": 100},
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(db_path, "SELECT file_path, decision FROM duplicate_review_items")
    assert _decision_for(rows, "/library/Static-X - Push It.flac") == "keep_candidate"


def test_larger_file_wins_when_all_candidates_are_dirty(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:static x:push it": [
                {"path": "/library/Static-X - Push It-.flac", "size": 100},
                {"path": "/library/Static-X - Push It -.flac", "size": 500},
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(db_path, "SELECT file_path, decision FROM duplicate_review_items")
    assert _decision_for(rows, "/library/Static-X - Push It -.flac") == "keep_candidate"


def test_selects_larger_file_when_suffix_rule_ties(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": "/library/a.flac", "size": 100},
                {"path": "/library/b.flac", "size": 200},
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(db_path, "SELECT file_path, decision FROM duplicate_review_items")
    assert _decision_for(rows, "/library/b.flac") == "keep_candidate"


def test_marks_other_files_remove_candidate(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": "/library/Deftones - Change.flac", "size": 200},
                {"path": "/library/Deftones - Change Official Video.flac", "size": 100},
            ]
        },
    )

    result = generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(db_path, "SELECT file_path, decision FROM duplicate_review_items")
    assert result.keeper_count == 1
    assert result.remove_candidate_count == 1
    assert (
        _decision_for(rows, "/library/Deftones - Change Official Video.flac")
        == "remove_candidate"
    )


def test_handles_3_file_group(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "probable_variant:static x:push it": [
                {"path": "/library/Static-X - Push It.flac", "size": 200},
                {"path": "/library/Static-X - Push It Visualizer.flac", "size": 150},
                {"path": "/library/Static-X - Push It (2).flac", "size": 100},
            ]
        },
    )

    result = generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    rows = _fetch_all(db_path, "SELECT decision FROM duplicate_review_items")
    assert result.total_files_reviewed == 3
    assert [row["decision"] for row in rows].count("keep_candidate") == 1
    assert [row["decision"] for row in rows].count("remove_candidate") == 2


def test_writes_summary_json(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": "/library/a.flac", "size": 100},
                {"path": "/library/b.flac", "size": 200},
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )
    summary_path = (
        tmp_path
        / "reports"
        / f"duplicate_review_scan_{scan_run_id}"
        / "duplicate_review_summary.json"
    )

    summary = json.loads(summary_path.read_text())
    assert summary["duplicate_report_id"] == report_id
    assert summary["scan_run_id"] == scan_run_id
    assert summary["total_groups"] == 1
    assert summary["keeper_count"] == 1
    assert summary["remove_candidate_count"] == 1


def test_writes_csv(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": "/library/a.flac", "size": 100},
                {"path": "/library/b.flac", "size": 200},
            ]
        },
    )

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )
    csv_path = (
        tmp_path
        / "reports"
        / f"duplicate_review_scan_{scan_run_id}"
        / "duplicate_review_plan.csv"
    )

    rows = _read_csv(csv_path)
    assert list(rows[0].keys()) == [
        "duplicate_group_key",
        "file_path",
        "decision",
        "reason",
    ]
    assert len(rows) == 2


def test_does_not_delete_files(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    library_root = tmp_path / "library"
    keeper = library_root / "Deftones - Change.flac"
    duplicate = library_root / "Deftones - Change (2).flac"
    keeper.parent.mkdir(parents=True)
    keeper.write_bytes(b"keeper-audio")
    duplicate.write_bytes(b"duplicate-audio")
    report_id, _scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": str(keeper), "size": keeper.stat().st_size},
                {"path": str(duplicate), "size": duplicate.stat().st_size},
            ]
        },
    )
    before = {path: path.read_bytes() for path in (keeper, duplicate)}

    generate_duplicate_review_plan(
        duplicate_report_id=report_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    after = {path: path.read_bytes() for path in (keeper, duplicate)}
    assert after == before


def test_cli_creates_review_plan(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    report_id, scan_run_id = _insert_review_fixture(
        db_path,
        {
            "same_artist_title:deftones:change": [
                {"path": "/library/a.flac", "size": 100},
                {"path": "/library/b.flac", "size": 200},
            ]
        },
    )
    out_dir = tmp_path / "reports"

    exit_code = main(
        [
            "--db",
            str(db_path),
            "duplicate-review",
            "--duplicate-report-id",
            str(report_id),
            "--out",
            str(out_dir),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"plan_path={out_dir / f'duplicate_review_scan_{scan_run_id}'}" in output
    assert "total_groups=1" in output
    assert "files_reviewed=2" in output
    assert "keeper_count=1" in output
    assert "remove_candidate_count=1" in output


def _insert_review_fixture(db_path, groups):
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
            VALUES ('/intake', '2026-05-10T00:00:00+00:00', 'completed', 0, 0, 0)
            """
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
            VALUES (?, '/library', '/reports/duplicates_scan_1', 0, 0, 0, 0,
                '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id,),
        ).lastrowid
        for group_key, candidates in groups.items():
            for index, candidate in enumerate(candidates, start=1):
                connection.execute(
                    """
                    INSERT INTO duplicate_candidates (
                        report_id,
                        duplicate_group_key,
                        duplicate_type,
                        artist,
                        normalized_title,
                        file_path,
                        file_size_bytes,
                        sha256,
                        reason,
                        created_at
                    )
                    VALUES (?, ?, 'same_artist_title', 'Artist', 'title',
                        ?, ?, ?, 'fixture',
                        '2026-05-10T00:00:00+00:00')
                    """,
                    (
                        report_id,
                        group_key,
                        candidate["path"],
                        candidate["size"],
                        f"hash-{index}",
                    ),
                )
        connection.commit()
        return report_id, scan_run_id
    finally:
        connection.close()


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _fetch_all(db_path, query):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def _decision_for(rows, file_path):
    return next(row["decision"] for row in rows if row["file_path"] == file_path)
