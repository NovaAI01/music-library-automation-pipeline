import csv
import json
import socket
from urllib.parse import parse_qs, urlparse

import pytest

from app.internet_archive_metadata import (
    ADVANCED_SEARCH_URL,
    OUTPUT_FIELDS,
    build_search_url,
    fetch_internet_archive_metadata,
    map_internet_archive_record,
)
from app.main import main


def test_query_url_construction():
    url = build_search_url("collection:audio", page=2, rows=50)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == ADVANCED_SEARCH_URL
    assert params["q"] == ["collection:audio"]
    assert params["output"] == ["json"]
    assert params["page"] == ["2"]
    assert params["rows"] == ["50"]
    assert "identifier" in params["fl[]"]
    assert "title" in params["fl[]"]


def test_pagination_and_limit_behavior(tmp_path):
    calls = []
    pages = [
        [_doc("one"), _doc("two")],
        [_doc("three"), _doc("four")],
    ]

    def fake_fetch(url, timeout):
        calls.append((url, timeout))
        return {"response": {"docs": pages[len(calls) - 1]}}

    result = fetch_internet_archive_metadata(
        "collection:audio",
        limit=3,
        page_size=2,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        timeout=7,
        fetch_json=fake_fetch,
    )

    assert result.fetched_records == 3
    assert result.accepted_records == 3
    assert len(calls) == 2
    assert parse_qs(urlparse(calls[0][0]).query)["rows"] == ["2"]
    assert parse_qs(urlparse(calls[1][0]).query)["page"] == ["2"]
    assert calls[0][1] == 7


def test_metadata_only_boundary_and_no_audio_download(tmp_path):
    seen_urls = []

    def fake_fetch(url, _timeout):
        seen_urls.append(url)
        parsed = urlparse(url)
        assert parsed.netloc == "archive.org"
        assert parsed.path == "/advancedsearch.php"
        assert "/download/" not in url
        assert "/metadata/" not in url
        assert "/details/" not in url
        return {"response": {"docs": [_doc("metadata-only")]}}

    result = fetch_internet_archive_metadata(
        "collection:audio",
        limit=1,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        fetch_json=fake_fetch,
    )

    assert seen_urls
    assert result.metadata_only is True
    assert result.audio_download_allowed is False


def test_record_mapping():
    row, rejection = map_internet_archive_record(
        {
            "identifier": "fixture-id",
            "title": "Fixture Title",
            "creator": ["Beta", "Alpha"],
            "collection": ["opensource_audio", "audio"],
            "date": "1999-04-01",
            "subject": ["Noise", "Archive"],
            "label": "Fixture Label",
            "duration": "123.9",
        }
    )

    assert rejection is None
    assert row["source_record_id"] == "fixture-id"
    assert row["artist"] == "Alpha; Beta"
    assert row["album"] == "audio; opensource_audio"
    assert row["title"] == "Fixture Title"
    assert row["track_number"] == ""
    assert row["release_year"] == "1999"
    assert row["label"] == "Fixture Label"
    assert row["duration_seconds"] == "123"
    assert row["genre"] == "Archive; Noise"
    assert row["source_url"] == "https://archive.org/details/fixture-id"


def test_creator_maps_to_artist():
    row, rejection = map_internet_archive_record(
        {
            "identifier": "creator-artist",
            "title": "Creator Artist Title",
            "creator": ["Beta", "Alpha"],
        }
    )

    assert rejection is None
    assert row["artist"] == "Alpha; Beta"


def test_missing_creator_leaves_artist_blank():
    row, rejection = map_internet_archive_record(
        {
            "identifier": "missing-creator",
            "title": "Missing Creator Title",
            "collection": "opensource_audio",
            "subject": "Field recording",
        }
    )

    assert rejection is None
    assert row["artist"] == ""


def test_collection_does_not_populate_artist():
    row, rejection = map_internet_archive_record(
        {
            "identifier": "collection-not-artist",
            "title": "Collection Evidence",
            "collection": "not_an_artist_collection",
        }
    )

    assert rejection is None
    assert row["artist"] == ""
    assert row["album"] == "not_an_artist_collection"


def test_subject_does_not_populate_artist():
    row, rejection = map_internet_archive_record(
        {
            "identifier": "subject-not-artist",
            "title": "Subject Evidence",
            "subject": ["Example Artist", "Live Music"],
        }
    )

    assert rejection is None
    assert row["artist"] == ""
    assert row["genre"] == "Example Artist; Live Music"


def test_title_like_strings_do_not_parse_artist():
    row, rejection = map_internet_archive_record(
        {
            "identifier": "title-not-artist",
            "title": "Example Artist - Example Track",
        }
    )

    assert rejection is None
    assert row["artist"] == ""
    assert row["title"] == "Example Artist - Example Track"


def test_uploader_like_fields_do_not_populate_artist():
    payload = {
        "identifier": "uploader-not-artist",
        "title": "Uploader Evidence",
        "uploader": "Example Uploader",
        "uploader_email": "uploader@example.invalid",
        "contributor": "Example Contributor",
    }
    row, rejection = map_internet_archive_record(payload)

    assert rejection is None
    assert row["artist"] == ""
    assert json.loads(row["raw_payload_json"]) == payload


def test_malformed_optional_fields_are_blank():
    row, rejection = map_internet_archive_record(
        {
            "identifier": "bad-fields",
            "title": "Bad Fields",
            "date": "not-a-date",
            "duration": "1:23",
        }
    )

    assert rejection is None
    assert row["release_year"] == ""
    assert row["duration_seconds"] == ""


def test_missing_identifier_rejection_and_raw_payload_preservation():
    payload = {"title": "Has Title", "creator": "Artist"}
    row, rejection = map_internet_archive_record(payload)

    assert rejection == "missing_identifier"
    assert row["source_record_id"] == ""
    assert json.loads(row["raw_payload_json"]) == payload


def test_rejects_records_without_metadata_evidence():
    row, rejection = map_internet_archive_record({"identifier": "empty-record"})

    assert rejection == "missing_title_creator_collection_subject_evidence"
    assert row["title"] == "empty-record"


def test_output_csv_jsonl_and_summary_generation(tmp_path):
    def fake_fetch(_url, _timeout):
        return {
            "response": {
                "docs": [
                    _doc("accepted"),
                    {"identifier": "rejected"},
                    {"title": "missing id"},
                ]
            }
        }

    result = fetch_internet_archive_metadata(
        "collection:audio",
        limit=3,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        fetch_json=fake_fetch,
    )

    output_csv = tmp_path / "data" / "external_metadata" / "internet_archive" / "raw_internet_archive.csv"
    output_jsonl = tmp_path / "data" / "external_metadata" / "internet_archive" / "raw_internet_archive.jsonl"
    report_dir = tmp_path / "reports" / "internet_archive_metadata"
    rows = _read_csv(output_csv)
    rejected = _read_csv(report_dir / "rejected_records.csv")
    sample = _read_csv(report_dir / "sample_records.csv")
    jsonl_rows = [
        json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads((report_dir / "acquisition_summary.json").read_text())

    assert list(rows[0].keys()) == list(OUTPUT_FIELDS)
    assert len(rows) == 1
    assert len(jsonl_rows) == 1
    assert len(sample) == 1
    assert rejected[0]["rejection_reason"] == "missing_title_creator_collection_subject_evidence"
    assert rejected[1]["rejection_reason"] == "missing_identifier"
    assert summary["source_name"] == "internet_archive"
    assert summary["requested_limit"] == 3
    assert summary["fetched_records"] == 3
    assert summary["accepted_records"] == 1
    assert summary["rejected_records"] == 2
    assert summary["metadata_only"] is True
    assert summary["audio_download_allowed"] is False
    assert summary["output_csv"] == result.output_csv
    assert summary["output_jsonl"] == result.output_jsonl


def test_data_root_output_path(monkeypatch, tmp_path):
    data_root = tmp_path / "configured_data"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))

    result = fetch_internet_archive_metadata(
        "collection:audio",
        limit=1,
        out_dir=tmp_path / "reports",
        fetch_json=lambda _url, _timeout: {"response": {"docs": [_doc("env-root")]}},
    )

    assert result.output_csv == str(
        data_root / "external_metadata" / "internet_archive" / "raw_internet_archive.csv"
    )
    assert (data_root / "external_metadata" / "internet_archive" / "raw_internet_archive.jsonl").exists()


def test_unsupported_malformed_response_handling(tmp_path):
    with pytest.raises(ValueError, match="response object"):
        fetch_internet_archive_metadata(
            "collection:audio",
            limit=1,
            out_dir=tmp_path / "reports",
            data_dir=tmp_path / "data",
            fetch_json=lambda _url, _timeout: {"unexpected": {}},
        )
    with pytest.raises(ValueError, match="docs list"):
        fetch_internet_archive_metadata(
            "collection:audio",
            limit=1,
            out_dir=tmp_path / "reports",
            data_dir=tmp_path / "data",
            fetch_json=lambda _url, _timeout: {"response": {"docs": {}}},
        )


def test_no_live_network_required(monkeypatch, tmp_path):
    def fail_socket(*args, **kwargs):
        raise AssertionError("live network is not allowed")

    monkeypatch.setattr(socket, "socket", fail_socket)

    result = fetch_internet_archive_metadata(
        "collection:audio",
        limit=1,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        fetch_json=lambda _url, _timeout: {"response": {"docs": [_doc("mocked")]}},
    )

    assert result.accepted_records == 1


def test_cli_fetch_internet_archive_metadata_dry_run(tmp_path, monkeypatch, capsys):
    data_root = tmp_path / "data"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))

    exit_code = main(
        [
            "fetch-internet-archive-metadata",
            "--query",
            "collection:audio",
            "--limit",
            "5",
            "--out",
            str(tmp_path / "reports"),
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "metadata_only=true" in output
    assert "audio_download_allowed=false" in output
    assert (
        data_root
        / "external_metadata"
        / "internet_archive"
        / "raw_internet_archive.csv"
    ).exists()


def _doc(identifier):
    return {
        "identifier": identifier,
        "title": f"Title {identifier}",
        "creator": "Creator",
        "collection": "audio",
        "subject": ["subject"],
    }


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
