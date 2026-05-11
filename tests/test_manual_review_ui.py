import csv
import json

from fastapi.testclient import TestClient

from app.main import app


def test_review_returns_200(tmp_path):
    client = _client(tmp_path)
    _write_review_fixture(tmp_path)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Quarantined duplicate files" in response.text
    assert "Blocked classification" in response.text


def test_review_quarantine_returns_200(tmp_path):
    client = _client(tmp_path)
    _write_review_fixture(tmp_path)

    response = client.get("/review/quarantine")

    assert response.status_code == 200
    assert "duplicate.flac" in response.text
    assert "Artist / Path" in response.text


def test_review_conflicts_returns_200(tmp_path):
    client = _client(tmp_path)
    _write_review_fixture(tmp_path)

    response = client.get("/review/conflicts")

    assert response.status_code == 200
    assert "conflict.flac" in response.text


def test_review_blocked_returns_200(tmp_path):
    client = _client(tmp_path)
    _write_review_fixture(tmp_path)

    response = client.get("/review/blocked")

    assert response.status_code == 200
    assert "blocked.flac" in response.text


def test_missing_review_report_files_are_handled_gracefully(tmp_path):
    client = _client(tmp_path)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Missing report data" in response.text
    assert "Quarantined duplicate files" in response.text


def _client(tmp_path):
    app.state.reports_dir = tmp_path / "reports"
    return TestClient(app)


def _write_review_fixture(tmp_path):
    reports_dir = tmp_path / "reports"
    qa_dir = reports_dir / "library_qa"
    scan_dir = reports_dir / "scan_1"
    qa_dir.mkdir(parents=True)
    scan_dir.mkdir(parents=True)

    _write_json(
        qa_dir / "library_qa_summary.json",
        {
            "quarantined_duplicate_file_count": 1,
            "unresolved_missing_file_count": 1,
        },
    )
    _write_csv(
        qa_dir / "file_health.csv",
        ["path", "size_bytes", "extension", "status"],
        [
            {
                "path": str(tmp_path / "quarantine" / "Static-X" / "duplicate.flac"),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "quarantine_present",
            },
            {
                "path": str(tmp_path / "library" / "missing.flac"),
                "size_bytes": "0",
                "extension": ".flac",
                "status": "missing_placement_file",
            },
        ],
    )
    _write_csv(
        scan_dir / "conflicts.csv",
        [
            "observed_file_id",
            "source_path",
            "planned_artist",
            "planned_title",
            "reason_json",
        ],
        [
            {
                "observed_file_id": "1",
                "source_path": str(tmp_path / "incoming" / "conflict.flac"),
                "planned_artist": "Static-X",
                "planned_title": "Push It",
                "reason_json": "{}",
            }
        ],
    )
    _write_csv(
        scan_dir / "blocked_items.csv",
        ["observed_file_id", "source_path", "placement_status", "reason_json"],
        [
            {
                "observed_file_id": "2",
                "source_path": str(tmp_path / "incoming" / "blocked.flac"),
                "placement_status": "blocked_unknown_classification",
                "reason_json": "{}",
            }
        ],
    )


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
