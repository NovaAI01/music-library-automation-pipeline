import csv
import json
import sqlite3

from app import db
from app.duplicate_report import generate_duplicate_report
from app.main import main


def test_detects_exact_hash_duplicates(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Static-X", "title": "Push It", "sha256": "same-hash"},
            {"artist": "Static-X", "title": "Push It Live", "sha256": "same-hash"},
        ],
    )

    result = generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=tmp_path / "library",
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.exact_hash_groups == 1
    exact_rows = _fetch_all(
        db_path,
        "SELECT * FROM duplicate_candidates WHERE duplicate_type = 'exact_hash'",
    )
    assert len(exact_rows) == 2
    assert exact_rows[0]["duplicate_group_key"] == "exact_hash:same-hash"


def test_detects_same_artist_title_duplicates(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Deftones", "title": "Change", "sha256": "hash-1"},
            {"artist": "Deftones", "title": "Change", "sha256": "hash-2"},
        ],
    )

    result = generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=tmp_path / "library",
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.same_artist_title_groups == 1
    rows = _fetch_all(
        db_path,
        "SELECT * FROM duplicate_candidates WHERE duplicate_type = 'same_artist_title'",
    )
    assert len(rows) == 2
    assert rows[0]["normalized_title"] == "change"


def test_detects_numeric_suffix_duplicates(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Deftones", "title": "Change", "sha256": "hash-1"},
            {"artist": "Deftones", "title": "Change (2)", "sha256": "hash-2"},
        ],
    )

    result = generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=tmp_path / "library",
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.variant_title_groups == 1
    rows = _read_csv(
        tmp_path
        / "reports"
        / f"duplicates_scan_{scan_run_id}"
        / "probable_variants.csv"
    )
    assert len(rows) == 2
    assert {row["normalized_title"] for row in rows} == {"change"}


def test_detects_official_video_audio_variant_duplicates(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {
                "artist": "Static-X",
                "title": "Push It [ubimQkYukxc] Official Video",
                "sha256": "hash-1",
            },
            {
                "artist": "Static-X",
                "title": "Push It Official Audio",
                "sha256": "hash-2",
            },
        ],
    )

    result = generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=tmp_path / "library",
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.variant_title_groups == 1
    rows = _fetch_all(
        db_path,
        "SELECT * FROM duplicate_candidates WHERE duplicate_type = 'probable_variant'",
    )
    assert len(rows) == 2
    assert {row["normalized_title"] for row in rows} == {"push it"}


def test_ignores_different_artists_with_same_title(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Deftones", "title": "Change", "sha256": "hash-1"},
            {"artist": "Static-X", "title": "Change", "sha256": "hash-2"},
        ],
    )

    result = generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=tmp_path / "library",
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    assert result.same_artist_title_groups == 0
    assert result.variant_title_groups == 0


def test_writes_summary_json(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Deftones", "title": "Change", "sha256": "hash-1"},
            {"artist": "Deftones", "title": "Change", "sha256": "hash-2"},
        ],
    )

    generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=tmp_path / "library",
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )
    summary_path = (
        tmp_path
        / "reports"
        / f"duplicates_scan_{scan_run_id}"
        / "duplicate_summary.json"
    )

    summary = json.loads(summary_path.read_text())
    assert summary["scan_run_id"] == scan_run_id
    assert summary["total_files_checked"] == 2
    assert summary["same_artist_title_groups"] == 1


def test_writes_csv_files(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Deftones", "title": "Change", "sha256": "same-hash"},
            {"artist": "Deftones", "title": "Change (2)", "sha256": "same-hash"},
        ],
    )

    generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=tmp_path / "library",
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )
    report_dir = tmp_path / "reports" / f"duplicates_scan_{scan_run_id}"

    assert (report_dir / "exact_hash_duplicates.csv").exists()
    assert (report_dir / "same_artist_title_duplicates.csv").exists()
    assert (report_dir / "probable_variants.csv").exists()
    assert _read_csv(report_dir / "exact_hash_duplicates.csv")[0][
        "duplicate_type"
    ] == "exact_hash"


def test_does_not_delete_or_move_files(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    library_root = tmp_path / "library"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Deftones", "title": "Change", "sha256": "hash-1"},
            {"artist": "Deftones", "title": "Change", "sha256": "hash-2"},
        ],
        library_root=library_root,
        create_files=True,
    )
    before = {
        path.relative_to(library_root): path.read_bytes()
        for path in sorted(library_root.rglob("*.flac"))
    }

    generate_duplicate_report(
        scan_run_id=scan_run_id,
        library_root=library_root,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )

    after = {
        path.relative_to(library_root): path.read_bytes()
        for path in sorted(library_root.rglob("*.flac"))
    }
    assert after == before


def test_cli_creates_report(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    library_root = tmp_path / "library"
    scan_run_id = _insert_duplicate_fixture(
        db_path,
        [
            {"artist": "Deftones", "title": "Change", "sha256": "hash-1"},
            {"artist": "Deftones", "title": "Change", "sha256": "hash-2"},
        ],
        library_root=library_root,
    )
    out_dir = tmp_path / "reports"

    exit_code = main(
        [
            "--db",
            str(db_path),
            "duplicate-report",
            "--scan-run-id",
            str(scan_run_id),
            "--library-root",
            str(library_root),
            "--out",
            str(out_dir),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"report_path={out_dir / f'duplicates_scan_{scan_run_id}'}" in output
    assert "total_files_checked=2" in output
    assert "same_artist_title_groups=1" in output
    assert (out_dir / f"duplicates_scan_{scan_run_id}" / "duplicate_summary.json").exists()


def _insert_duplicate_fixture(
    db_path,
    tracks,
    *,
    library_root=None,
    create_files=False,
):
    db.init_db(db_path)
    library_root = library_root or db_path.parent / "library"
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
            VALUES ('/intake', '2026-05-10T00:00:00+00:00', 'completed', ?, ?, 0)
            """,
            (len(tracks), len(tracks)),
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
            (scan_run_id, str(library_root), len(tracks), len(tracks)),
        ).lastrowid

        for index, track in enumerate(tracks, start=1):
            _insert_track(
                connection,
                scan_run_id=scan_run_id,
                execution_id=execution_id,
                index=index,
                library_root=library_root,
                artist=track["artist"],
                title=track["title"],
                sha256=track["sha256"],
                create_file=create_files,
            )
        connection.commit()
        return scan_run_id
    finally:
        connection.close()


def _insert_track(
    connection,
    *,
    scan_run_id,
    execution_id,
    index,
    library_root,
    artist,
    title,
    sha256,
    create_file,
):
    filename = f"{artist} - {title} - {index}.flac"
    destination_path = library_root / artist / filename
    if create_file:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(f"audio-{index}".encode())

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
        VALUES (?, ?, ?, ?, ?, '.flac', ?, ?, '2026-05-10T00:00:00+00:00')
        """,
        (
            scan_run_id,
            f"/intake/{filename}",
            filename,
            "",
            filename,
            100 + index,
            sha256,
        ),
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
        VALUES (?, ?, ?, ?, ?, ?, 'Metal', 'Industrial Metal',
            0.95, 'planned', '{}', '2026-05-10T00:00:00+00:00')
        """,
        (
            observed_file_id,
            scan_run_id,
            f"/intake/{filename}",
            str(destination_path.relative_to(library_root)),
            artist,
            title,
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
            str(destination_path),
        ),
    )


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
