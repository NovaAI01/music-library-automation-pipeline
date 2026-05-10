import csv
import json
import sqlite3

from app import db
from app.main import main
from app.review_report import (
    BLOCKED_HEADERS,
    CONFLICT_HEADERS,
    PLACEMENT_REVIEW_HEADERS,
    generate_review_report,
)


def test_summary_json_generated(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"

    generate_review_report(scan_run_id=scan_run_id, out_dir=out_dir, db_path=db_path)
    summary_path = out_dir / f"scan_{scan_run_id}" / "placement_summary.json"

    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["scan_run_id"] == scan_run_id
    assert summary["total_plans"] == 4


def test_placement_review_csv_generated(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"

    generate_review_report(scan_run_id=scan_run_id, out_dir=out_dir, db_path=db_path)
    rows = _read_csv(out_dir / f"scan_{scan_run_id}" / "placement_review.csv")

    assert len(rows) == 4
    assert rows[0]["placement_status"] == "planned"


def test_blocked_items_csv_generated(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"

    generate_review_report(scan_run_id=scan_run_id, out_dir=out_dir, db_path=db_path)
    rows = _read_csv(out_dir / f"scan_{scan_run_id}" / "blocked_items.csv")

    assert len(rows) == 1
    assert rows[0]["placement_status"] == "blocked_unknown_identity"


def test_conflicts_csv_generated(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"

    generate_review_report(scan_run_id=scan_run_id, out_dir=out_dir, db_path=db_path)
    rows = _read_csv(out_dir / f"scan_{scan_run_id}" / "conflicts.csv")

    assert len(rows) == 1
    assert rows[0]["planned_artist"] == "Deftones"


def test_report_counts_match_database_rows(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)

    result = generate_review_report(
        scan_run_id=scan_run_id,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.total_plans == 4
    assert result.planned_count == 1
    assert result.needs_review_count == 1
    assert result.blocked_count == 1
    assert result.conflict_count == 1


def test_csv_headers_are_stable(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"

    generate_review_report(scan_run_id=scan_run_id, out_dir=out_dir, db_path=db_path)

    assert _csv_headers(out_dir / f"scan_{scan_run_id}" / "placement_review.csv") == list(
        PLACEMENT_REVIEW_HEADERS
    )
    assert _csv_headers(out_dir / f"scan_{scan_run_id}" / "blocked_items.csv") == list(
        BLOCKED_HEADERS
    )
    assert _csv_headers(out_dir / f"scan_{scan_run_id}" / "conflicts.csv") == list(
        CONFLICT_HEADERS
    )


def test_repeated_report_generation_overwrites_reports_safely(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"
    report_dir = out_dir / f"scan_{scan_run_id}"

    generate_review_report(scan_run_id=scan_run_id, out_dir=out_dir, db_path=db_path)
    stale = report_dir / "stale.txt"
    stale.write_text("remove me")
    generate_review_report(scan_run_id=scan_run_id, out_dir=out_dir, db_path=db_path)

    assert not stale.exists()
    assert (report_dir / "placement_summary.json").exists()


def test_review_reports_table_records_generated_report(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"

    result = generate_review_report(
        scan_run_id=scan_run_id,
        out_dir=out_dir,
        db_path=db_path,
    )
    rows = _fetch_all(db_path, "SELECT * FROM review_reports")

    assert len(rows) == 1
    assert rows[0]["report_path"] == result.report_path
    assert rows[0]["total_plans"] == 4
    assert rows[0]["blocked_count"] == 1


def test_cli_prints_report_path_and_counts(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_report_fixture(db_path)
    out_dir = tmp_path / "reports"

    exit_code = main(
        [
            "--db",
            str(db_path),
            "review-report",
            "--scan-run-id",
            str(scan_run_id),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={out_dir / f'scan_{scan_run_id}'}" in output
    assert "total_plans=4" in output
    assert "planned=1" in output
    assert "needs_review=1" in output
    assert "blocked=1" in output
    assert "conflicts=1" in output


def _insert_report_fixture(db_path):
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
            VALUES ('/music', '2026-05-10T00:00:00+00:00', 'completed', 4, 4, 0)
            """
        ).lastrowid
        _insert_plan(
            connection,
            scan_run_id,
            observed_file_id=1,
            placement_status="planned",
            planned_relative_path="Alternative Metal/Shoegaze Metal/Deftones/Deftones - Change.mp3",
        )
        _insert_plan(
            connection,
            scan_run_id,
            observed_file_id=2,
            placement_status="needs_review",
            planned_relative_path="Alternative Rock/_Unsorted/Unknown/Unknown - Track.mp3",
        )
        _insert_plan(
            connection,
            scan_run_id,
            observed_file_id=3,
            placement_status="blocked_unknown_identity",
            planned_relative_path=None,
        )
        _insert_plan(
            connection,
            scan_run_id,
            observed_file_id=4,
            placement_status="conflict",
            planned_relative_path=None,
        )
        connection.commit()
        return scan_run_id
    finally:
        connection.close()


def _insert_plan(
    connection,
    scan_run_id,
    *,
    observed_file_id,
    placement_status,
    planned_relative_path,
):
    connection.execute(
        """
        INSERT INTO observed_files (
            id,
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
        VALUES (?, ?, '/music', ?, '', ?, '.mp3', 10, ?, '2026-05-10T00:00:00+00:00')
        """,
        (
            observed_file_id,
            scan_run_id,
            f"track-{observed_file_id}.mp3",
            f"track-{observed_file_id}.mp3",
            f"sha-{observed_file_id}",
        ),
    )
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
        VALUES (?, ?, ?, ?, 'Deftones', 'Change', 'Alternative Metal',
            'Shoegaze Metal', 0.95, ?, ?, '2026-05-10T00:00:00+00:00')
        """,
        (
            observed_file_id,
            scan_run_id,
            f"/music/track-{observed_file_id}.mp3",
            planned_relative_path,
            placement_status,
            json.dumps({"reason": placement_status}, sort_keys=True),
        ),
    )


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _csv_headers(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return next(csv.reader(file_handle))


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
