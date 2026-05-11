import csv
import json

from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_route_returns_200(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports")

    assert response.status_code == 200
    assert "Total library files" in response.text
    assert "4" in response.text


def test_artists_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/artists")

    assert response.status_code == 200
    assert "Static-X" in response.text


def test_genres_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/genres")

    assert response.status_code == 200
    assert "Alternative Metal" in response.text


def test_quarantine_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/quarantine")

    assert response.status_code == 200
    assert "duplicate.flac" in response.text


def test_duplicate_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/duplicates")

    assert response.status_code == 200
    assert "Historical Duplicate Groups" in response.text
    assert "same_artist_title:static-x:push it" in response.text


def test_missing_report_files_are_handled_gracefully(tmp_path):
    client = _client(tmp_path)

    response = client.get("/reports")

    assert response.status_code == 200
    assert "Missing report data" in response.text
    assert "Total library files" in response.text


def test_file_health_search_filters_rows(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/file-health?q=quarantine")

    assert response.status_code == 200
    assert "duplicate.flac" in response.text
    assert "Push It.flac" not in response.text


def _client(tmp_path):
    app.state.reports_dir = tmp_path / "reports"
    return TestClient(app)


def _write_report_fixture(tmp_path):
    reports_dir = tmp_path / "reports"
    qa_dir = reports_dir / "library_qa"
    duplicate_dir = reports_dir / "duplicates_scan_1"
    qa_dir.mkdir(parents=True)
    duplicate_dir.mkdir(parents=True)

    _write_json(
        qa_dir / "library_qa_summary.json",
        {
            "total_library_files": 4,
            "total_quarantine_files": 1,
            "artist_count": 2,
            "genre_count": 2,
            "active_duplicate_group_count": 1,
            "unresolved_missing_file_count": 0,
            "created_at": "2026-05-10T00:00:00+00:00",
        },
    )
    _write_csv(
        qa_dir / "artists.csv",
        ["artist", "genre", "subgenre", "file_count"],
        [
            {
                "artist": "Static-X",
                "genre": "Alternative Metal",
                "subgenre": "Nu Metal",
                "file_count": "2",
            },
            {
                "artist": "Nirvana",
                "genre": "Alternative Rock",
                "subgenre": "Grunge",
                "file_count": "2",
            },
        ],
    )
    _write_csv(
        qa_dir / "genres.csv",
        ["genre", "subgenre", "artist_count", "file_count"],
        [
            {
                "genre": "Alternative Metal",
                "subgenre": "Nu Metal",
                "artist_count": "1",
                "file_count": "2",
            },
            {
                "genre": "Alternative Rock",
                "subgenre": "Grunge",
                "artist_count": "1",
                "file_count": "2",
            },
        ],
    )
    _write_csv(
        qa_dir / "quarantine_summary.csv",
        ["extension", "file_count", "size_bytes"],
        [{"extension": ".flac", "file_count": "1", "size_bytes": "100"}],
    )
    library_file = (
        tmp_path
        / "library"
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It.flac"
    )
    duplicate_file = (
        tmp_path
        / "library"
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It duplicate.flac"
    )
    quarantine_file = tmp_path / "quarantine" / "duplicate.flac"
    for path in (library_file, duplicate_file, quarantine_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
    _write_csv(
        qa_dir / "file_health.csv",
        ["path", "size_bytes", "extension", "status"],
        [
            {
                "path": str(library_file),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "library_present",
            },
            {
                "path": str(duplicate_file),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "library_present",
            },
            {
                "path": str(quarantine_file),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "quarantine_present",
            },
        ],
    )
    _write_json(
        duplicate_dir / "duplicate_summary.json",
        {
            "scan_run_id": 1,
            "total_files_checked": 2,
            "same_artist_title_groups": 1,
        },
    )
    _write_csv(
        duplicate_dir / "exact_hash_duplicates.csv",
        [
            "duplicate_group_key",
            "duplicate_type",
            "artist",
            "normalized_title",
            "file_path",
            "file_size_bytes",
            "sha256",
            "reason",
        ],
        [],
    )
    _write_csv(
        duplicate_dir / "same_artist_title_duplicates.csv",
        [
            "duplicate_group_key",
            "duplicate_type",
            "artist",
            "normalized_title",
            "file_path",
            "file_size_bytes",
            "sha256",
            "reason",
        ],
        [
            {
                "duplicate_group_key": "same_artist_title:static-x:push it",
                "duplicate_type": "same_artist_title",
                "artist": "Static-X",
                "normalized_title": "push it",
                "file_path": str(library_file),
                "file_size_bytes": "100",
                "sha256": "hash-1",
                "reason": "same_planned_artist_and_normalized_title",
            },
            {
                "duplicate_group_key": "same_artist_title:static-x:push it",
                "duplicate_type": "same_artist_title",
                "artist": "Static-X",
                "normalized_title": "push it",
                "file_path": str(duplicate_file),
                "file_size_bytes": "100",
                "sha256": "hash-2",
                "reason": "same_planned_artist_and_normalized_title",
            },
        ],
    )
    _write_csv(
        duplicate_dir / "probable_variants.csv",
        [
            "duplicate_group_key",
            "duplicate_type",
            "artist",
            "normalized_title",
            "file_path",
            "file_size_bytes",
            "sha256",
            "reason",
        ],
        [],
    )


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
