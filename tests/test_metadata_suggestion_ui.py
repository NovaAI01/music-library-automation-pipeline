import json

from fastapi.testclient import TestClient

from app.main import app
from app.ui_screenshot_capture import screenshot_targets


def test_metadata_suggestions_route_renders_review_fields(tmp_path):
    client = _client(tmp_path)
    _write_suggestions_fixture(tmp_path)

    response = client.get("/review/metadata-suggestions")

    assert response.status_code == 200
    assert "Suggestions are review-only." in response.text
    assert "No metadata is modified by this workflow." in response.text
    assert "Human approval required before future execution." in response.text
    assert "Alternative Metal/Static-X/Push It.flac" in response.text
    assert "album_artist" in response.text
    assert "Static-X" in response.text
    assert "metadata_plan:album_artist should equal artist" in response.text
    assert "True" in response.text


def test_metadata_suggestions_summary_counts(tmp_path):
    client = _client(tmp_path)
    _write_suggestions_fixture(tmp_path)

    response = client.get("/review/metadata-suggestions")

    assert response.status_code == 200
    assert "Total suggestions" in response.text
    assert "Requires human review" in response.text
    assert "missing_album_artist" in response.text
    assert "separator_cleanup" in response.text
    assert "artist_casing" in response.text


def test_metadata_suggestions_filtering_behavior(tmp_path):
    client = _client(tmp_path)
    _write_suggestions_fixture(tmp_path)

    high = client.get("/review/metadata-suggestions/high")
    medium = client.get("/review/metadata-suggestions/medium")
    low = client.get("/review/metadata-suggestions/low")

    assert high.status_code == 200
    assert "Push It.flac" in high.text
    assert "Wisconsin Death Trip.flac" not in high.text
    assert "Spineshank.flac" not in high.text
    assert medium.status_code == 200
    assert "Wisconsin Death Trip.flac" in medium.text
    assert "Push It.flac" not in medium.text
    assert low.status_code == 200
    assert "Spineshank.flac" in low.text
    assert "Push It.flac" not in low.text


def test_metadata_suggestions_empty_state(tmp_path):
    client = _client(tmp_path)
    suggestions_dir = tmp_path / "reports" / "metadata_suggestions"
    suggestions_dir.mkdir(parents=True)
    _write_json(suggestions_dir / "metadata_suggestions.json", {"suggestions": []})

    response = client.get("/review/metadata-suggestions")

    assert response.status_code == 200
    assert "No metadata suggestions available." in response.text
    assert "Missing report data" not in response.text


def test_metadata_suggestions_missing_report_state(tmp_path):
    client = _client(tmp_path)

    response = client.get("/review/metadata-suggestions")

    assert response.status_code == 200
    assert "Missing report data" in response.text
    assert "No metadata suggestion report data is available." in response.text


def test_metadata_suggestion_screenshot_route_is_registered():
    assert (
        "/review",
        "03_review_hub.png",
    ) in [(target.route, target.filename) for target in screenshot_targets()]


def test_metadata_suggestion_review_does_not_mutate_report_file(tmp_path):
    client = _client(tmp_path)
    report_path = _write_suggestions_fixture(tmp_path)
    before = report_path.read_bytes()

    response = client.get("/review/metadata-suggestions/low")

    assert response.status_code == 200
    assert report_path.read_bytes() == before


def _client(tmp_path):
    app.state.reports_dir = tmp_path / "reports"
    return TestClient(app)


def _write_suggestions_fixture(tmp_path):
    suggestions_dir = tmp_path / "reports" / "metadata_suggestions"
    suggestions_dir.mkdir(parents=True)
    path = suggestions_dir / "metadata_suggestions.json"
    _write_json(
        path,
        {
            "suggestions": [
                {
                    "file_path": "Alternative Metal/Static-X/Push It.flac",
                    "field": "album_artist",
                    "current_value": "",
                    "proposed_value": "Static-X",
                    "confidence": "high",
                    "suggestion_type": "missing_album_artist",
                    "rationale": "missing_album_artist suggested from album_artist should equal artist.",
                    "source_evidence": [
                        "metadata_plan:album_artist should equal artist",
                        "missing_tags:missing_tag",
                    ],
                    "requires_human_review": True,
                },
                {
                    "file_path": "Alternative Metal/Static-X/Wisconsin Death Trip.flac",
                    "field": "title",
                    "current_value": "Static-X - Wisconsin Death Trip",
                    "proposed_value": "Wisconsin Death Trip",
                    "confidence": "medium",
                    "suggestion_type": "separator_cleanup",
                    "rationale": "separator_cleanup suggested from filename.",
                    "source_evidence": ["metadata_plan:filename"],
                    "requires_human_review": True,
                },
                {
                    "file_path": "Alternative Metal/Spineshank/Spineshank.flac",
                    "field": "artist",
                    "current_value": "spineshank",
                    "proposed_value": "Spineshank",
                    "confidence": "low",
                    "suggestion_type": "artist_casing",
                    "rationale": "artist_casing suggested from inconsistent artist evidence.",
                    "source_evidence": ["inconsistent_artists:artist_case"],
                    "requires_human_review": True,
                },
            ]
        },
    )
    return path


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
