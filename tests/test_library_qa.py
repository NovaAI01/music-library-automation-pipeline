import csv
import json
import os

from app import db
from app.library_qa import (
    ARTIST_HEADERS,
    FILE_HEALTH_HEADERS,
    GENRE_HEADERS,
    QUARANTINE_HEADERS,
    generate_library_qa_report,
)
from app.main import main


def test_counts_library_files(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    assert result.total_library_files == 4


def test_counts_quarantine_files(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    assert result.total_quarantine_files == 2


def test_counts_artists_from_folder_structure(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )
    artist_rows = _read_csv(tmp_path / "reports" / "library_qa" / "artists.csv")

    assert result.artist_count == 3
    assert {row["artist"] for row in artist_rows} == {
        "Deftones",
        "Nirvana",
        "Static-X",
    }


def test_counts_genres_and_subgenres_from_folder_structure(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    assert result.genre_count == 2
    assert result.subgenre_count == 3


def test_writes_json_summary(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )
    summary_path = tmp_path / "reports" / "library_qa" / "library_qa_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["library_root"] == str(library_root)
    assert summary["quarantine_root"] == str(quarantine_root)
    assert summary["total_library_files"] == 4
    assert summary["total_quarantine_files"] == 2
    assert summary["active_duplicate_group_count"] == 0
    assert summary["historical_duplicate_group_count"] == 0
    assert summary["quarantined_duplicate_file_count"] == 2
    assert summary["missing_file_count"] == 0
    assert summary["unresolved_missing_file_count"] == 0
    assert "created_at" in summary


def test_writes_csv_reports(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )
    report_dir = tmp_path / "reports" / "library_qa"

    assert _csv_headers(report_dir / "artists.csv") == list(ARTIST_HEADERS)
    assert _csv_headers(report_dir / "genres.csv") == list(GENRE_HEADERS)
    assert _csv_headers(report_dir / "quarantine_summary.csv") == list(
        QUARANTINE_HEADERS
    )
    assert _csv_headers(report_dir / "file_health.csv") == list(FILE_HEALTH_HEADERS)
    assert len(_read_csv(report_dir / "file_health.csv")) == 6


def test_does_not_mutate_files(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    tracked_files = [
        path
        for root in (library_root, quarantine_root)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    before = {
        path: (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in tracked_files
    }

    generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    after = {
        path: (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in tracked_files
    }
    assert after == before


def test_cli_works(tmp_path, capsys):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    out_dir = tmp_path / "reports"

    exit_code = main(
        [
            "--db",
            str(tmp_path / "missing.sqlite3"),
            "library-qa",
            "--library-root",
            str(library_root),
            "--quarantine-root",
            str(quarantine_root),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={out_dir / 'library_qa'}" in output
    assert "total_library_files=4" in output
    assert "total_quarantine_files=2" in output
    assert (out_dir / "library_qa" / "library_qa_summary.json").exists()


def test_quarantined_duplicate_files_do_not_count_as_unresolved_missing(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    db_path = tmp_path / "ledger.sqlite3"
    missing_destination = (
        library_root
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It duplicate.flac"
    )
    _write_file(
        quarantine_root / missing_destination.relative_to(library_root),
        b"quarantined duplicate",
    )
    _insert_placement_records(db_path, [missing_destination], library_root=library_root)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )
    summary = json.loads(
        (tmp_path / "reports" / "library_qa" / "library_qa_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.quarantined_duplicate_file_count == 3
    assert result.missing_file_count == 1
    assert result.unresolved_missing_file_count == 0
    assert summary["quarantined_duplicate_file_count"] == 3
    assert summary["missing_file_count"] == 1
    assert summary["unresolved_missing_file_count"] == 0


def test_active_duplicate_count_is_zero_after_quarantine(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    db_path = tmp_path / "ledger.sqlite3"
    keeper = (
        library_root
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It.flac"
    )
    quarantined = (
        library_root
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It duplicate.flac"
    )
    _write_file(quarantine_root / quarantined.relative_to(library_root), b"duplicate")
    _insert_duplicate_candidates(db_path, [keeper, quarantined], library_root=library_root)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.active_duplicate_group_count == 0
    assert result.historical_duplicate_group_count == 1


def test_historical_duplicate_count_is_preserved(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    db_path = tmp_path / "ledger.sqlite3"
    paths = [
        library_root
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It.flac",
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "Nirvana - Breed.wav",
    ]
    _insert_duplicate_candidates(db_path, paths, library_root=library_root)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.active_duplicate_group_count == 1
    assert result.historical_duplicate_group_count == 1


def test_cli_output_uses_active_duplicate_group_count(tmp_path, capsys):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    db_path = tmp_path / "ledger.sqlite3"
    _insert_duplicate_candidates(
        db_path,
        [
            library_root
            / "Alternative Metal"
            / "Nu Metal"
            / "Static-X"
            / "Static-X - Push It.flac",
            library_root
            / "Alternative Rock"
            / "Grunge"
            / "Nirvana"
            / "Nirvana - Breed.wav",
        ],
        library_root=library_root,
    )

    exit_code = main(
        [
            "--db",
            str(db_path),
            "library-qa",
            "--library-root",
            str(library_root),
            "--quarantine-root",
            str(quarantine_root),
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "active_duplicate_group_count=1" in output
    assert "historical_duplicate_group_count=1" in output
    assert "duplicate_group_count=" not in output.splitlines()


def _make_library_fixture(tmp_path):
    library_root = tmp_path / "Organised_Library"
    quarantine_root = tmp_path / "Quarantine_Duplicates"

    _write_file(
        library_root
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It.flac",
        b"static-x",
    )
    _write_file(
        library_root
        / "Alternative Metal"
        / "Shoegaze Metal"
        / "Deftones"
        / "Deftones - Change.mp3",
        b"deftones",
    )
    _write_file(
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "Nirvana - Breed.wav",
        b"nirvana",
    )
    _write_file(
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "Nirvana - Lounge Act.m4a",
        b"lounge",
    )
    _write_file(
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "cover.jpg",
        b"not audio",
    )
    _write_file(
        quarantine_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana - Breed duplicate.wav",
        b"quarantined",
    )
    _write_file(
        quarantine_root / "Loose" / "Deftones - Change duplicate.mp3",
        b"duplicate",
    )
    return library_root, quarantine_root


def _write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _csv_headers(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return next(csv.reader(file_handle))


def _insert_placement_records(db_path, destinations, *, library_root):
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        scan_run_id, execution_id = _insert_scan_and_execution(
            connection,
            library_root=library_root,
            total_files=len(destinations),
        )
        for index, destination in enumerate(destinations, start=1):
            _insert_placement_record(
                connection,
                scan_run_id=scan_run_id,
                execution_id=execution_id,
                index=index,
                destination=destination,
                library_root=library_root,
            )


def _insert_duplicate_candidates(db_path, paths, *, library_root):
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        scan_run_id, _execution_id = _insert_scan_and_execution(
            connection,
            library_root=library_root,
            total_files=len(paths),
        )
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
            VALUES (?, ?, '/reports/duplicates', ?, 0, 1, 0,
                '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id, str(library_root), len(paths)),
        ).lastrowid
        connection.executemany(
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
            VALUES (?, 'same_artist_title:static-x:push it',
                'same_artist_title', 'Static-X', 'push it', ?, 100, ?,
                'same_planned_artist_and_normalized_title',
                '2026-05-10T00:00:00+00:00')
            """,
            [
                (report_id, str(path), f"hash-{index}")
                for index, path in enumerate(paths, start=1)
            ],
        )


def _insert_scan_and_execution(connection, *, library_root, total_files):
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
        VALUES ('/intake', '2026-05-10T00:00:00+00:00', 'completed', ?, ?, 0)
        """,
        (total_files, total_files),
    ).lastrowid
    execution_id = connection.execute(
        """
        INSERT INTO placement_executions (
            scan_run_id,
            output_root,
            execution_status,
            total_planned,
            copied_count,
            skipped_count,
            failed_count,
            created_at,
            completed_at
        )
        VALUES (?, ?, 'completed', ?, ?, 0, 0,
            '2026-05-10T00:00:00+00:00',
            '2026-05-10T00:00:00+00:00')
        """,
        (scan_run_id, str(library_root), total_files, total_files),
    ).lastrowid
    return scan_run_id, execution_id


def _insert_placement_record(
    connection,
    *,
    scan_run_id,
    execution_id,
    index,
    destination,
    library_root,
):
    filename = destination.name
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
        VALUES (?, ?, ?, '', ?, '.flac', 100, ?, '2026-05-10T00:00:00+00:00')
        """,
        (scan_run_id, f"/intake/{filename}", filename, filename, f"hash-{index}"),
    ).lastrowid
    placement_plan_id = connection.execute(
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
        VALUES (?, ?, ?, ?, 'Static-X', 'Push It', 'Metal', 'Industrial Metal',
            0.95, 'planned', '{}', '2026-05-10T00:00:00+00:00')
        """,
        (
            observed_file_id,
            scan_run_id,
            f"/intake/{filename}",
            str(destination.relative_to(library_root)),
        ),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO placement_execution_files (
            execution_id,
            placement_plan_id,
            source_path,
            destination_path,
            file_status,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?, 'copied', NULL, '2026-05-10T00:00:00+00:00')
        """,
        (
            execution_id,
            placement_plan_id,
            f"/intake/{filename}",
            str(destination),
        ),
    )
