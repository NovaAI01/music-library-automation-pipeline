import csv
import json
import socket
from urllib.parse import parse_qs, urlparse

import pytest

from app.jamendo_metadata import (
    MISSING_CLIENT_ID_MESSAGE,
    OUTPUT_FIELDS,
    TRACKS_URL,
    JamendoCredentialError,
    build_tracks_url,
    fetch_jamendo_metadata,
    map_jamendo_record,
    resolve_client_id,
)
from app.main import main


def test_missing_client_id_fails_cleanly_without_partial_output(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)

    with pytest.raises(JamendoCredentialError, match=MISSING_CLIENT_ID_MESSAGE):
        fetch_jamendo_metadata(
            limit=1,
            out_dir=tmp_path / "reports",
            data_dir=tmp_path / "data",
            fetch_json=lambda _url, _timeout: {"results": [_track("1")]},
        )

    assert not (tmp_path / "data" / "external_metadata" / "jamendo").exists()
    assert not (tmp_path / "reports" / "jamendo_metadata").exists()
    output = capsys.readouterr()
    assert "fetching_jamendo_metadata" not in output.out
    assert "fetching_jamendo_metadata" not in output.err
    assert "jamendo_progress" not in output.out
    assert "jamendo_progress" not in output.err


def test_client_id_from_argument(monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "env-client")

    assert resolve_client_id("arg-client") == ("arg-client", "argument")


def test_client_id_from_environment(monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "env-client")

    assert resolve_client_id(None) == ("env-client", "environment")


def test_query_page_url_construction():
    url = build_tracks_url("client-123", offset=200, limit=50)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == TRACKS_URL
    assert params["client_id"] == ["client-123"]
    assert params["format"] == ["json"]
    assert params["limit"] == ["50"]
    assert params["offset"] == ["200"]
    assert params["order"] == ["id_asc"]


def test_pagination_and_limit_behavior(tmp_path, capsys):
    calls = []
    pages = [
        [_track("1"), _track("2")],
        [_track("3"), _track("4")],
    ]

    def fake_fetch(url, timeout):
        calls.append((url, timeout))
        return {"results": pages[len(calls) - 1]}

    result = fetch_jamendo_metadata(
        limit=3,
        page_size=2,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        client_id="client-123",
        timeout=9,
        fetch_json=fake_fetch,
    )

    assert result.fetched_records == 3
    assert result.accepted_records == 3
    assert len(calls) == 2
    assert parse_qs(urlparse(calls[0][0]).query)["limit"] == ["2"]
    assert parse_qs(urlparse(calls[1][0]).query)["offset"] == ["2"]
    assert calls[0][1] == 9
    assert capsys.readouterr().err.splitlines() == [
        "fetching_jamendo_metadata requested_limit=3 page_size=2",
        "jamendo_progress fetched=2 accepted=2 rejected=0 requested=3",
        "jamendo_progress fetched=3 accepted=3 rejected=0 requested=3",
    ]


def test_progress_reports_multipage_accepted_and_rejected_counts(tmp_path, capsys):
    pages = [
        [_track("1"), {"id": "rejected"}],
        [_track("3"), {"name": "missing id"}],
    ]
    calls = []

    def fake_fetch(url, _timeout):
        calls.append(url)
        return {"results": pages[len(calls) - 1]}

    result = fetch_jamendo_metadata(
        limit=4,
        page_size=2,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        client_id="client-123",
        fetch_json=fake_fetch,
    )

    assert result.fetched_records == 4
    assert result.accepted_records == 2
    assert result.rejected_records == 2
    assert capsys.readouterr().err.splitlines() == [
        "fetching_jamendo_metadata requested_limit=4 page_size=2",
        "jamendo_progress fetched=2 accepted=1 rejected=1 requested=4",
        "jamendo_progress fetched=4 accepted=2 rejected=2 requested=4",
    ]


def test_metadata_only_boundary_and_no_audio_download(tmp_path):
    seen_urls = []

    def fake_fetch(url, _timeout):
        seen_urls.append(url)
        parsed = urlparse(url)
        assert parsed.netloc == "api.jamendo.com"
        assert parsed.path == "/v3.0/tracks/"
        assert "download" not in url
        assert "stream" not in url
        assert "audio" not in url
        return {"results": [_track("metadata-only")]}

    result = fetch_jamendo_metadata(
        limit=1,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        client_id="client-123",
        fetch_json=fake_fetch,
    )

    assert seen_urls
    assert result.metadata_only is True
    assert result.audio_download_allowed is False


def test_raw_payload_redacts_jamendo_media_urls_and_keeps_source_url():
    row, rejection = map_jamendo_record(
        {
            "id": "100",
            "name": "Fixture Title",
            "artist_name": "Fixture Artist",
            "album_name": "Fixture Album",
            "audio": "https://prod-1.storage.jamendo.com/?trackid=100&format=mp31",
            "audiodownload": (
                "https://prod-1.storage.jamendo.com/download/track/100/mp32"
            ),
            "audiodownload_allowed": True,
            "proaudio": "https://prod-1.storage.jamendo.com/pro/100",
            "audio_download": "https://prod-1.storage.jamendo.com/audio_download/100",
            "download": "https://prod-1.storage.jamendo.com/download/100",
            "waveform": "https://prod-1.storage.jamendo.com/waveform/100",
            "stream": "https://prod-1.storage.jamendo.com/stream/100",
            "album_image": "https://usercontent.jamendo.com?type=album",
            "image": "https://usercontent.jamendo.com?type=track",
            "shareurl": "https://www.jamendo.com/track/100/fixture-title",
            "shorturl": "https://jamen.do/t/100",
        }
    )

    raw_payload = json.loads(row["raw_payload_json"])
    raw_payload_text = row["raw_payload_json"]

    assert rejection is None
    assert "audio" not in raw_payload
    assert "audiodownload" not in raw_payload
    assert "audiodownload_allowed" not in raw_payload
    assert "proaudio" not in raw_payload
    assert "audio_download" not in raw_payload
    assert "download" not in raw_payload
    assert "waveform" not in raw_payload
    assert "stream" not in raw_payload
    assert "prod-1.storage.jamendo.com" not in raw_payload_text
    assert "format=mp3" not in raw_payload_text
    assert "mp31" not in raw_payload_text
    assert "mp32" not in raw_payload_text
    assert raw_payload["shareurl"] == "https://www.jamendo.com/track/100/fixture-title"
    assert raw_payload["shorturl"] == "https://jamen.do/t/100"
    assert row["source_url"] == "https://www.jamendo.com/track/100/fixture-title"


def test_record_mapping():
    row, rejection = map_jamendo_record(
        {
            "id": "100",
            "name": "Fixture Title",
            "artist_name": "Fixture Artist",
            "album_name": "Fixture Album",
            "position": "7",
            "releasedate": "2020-02-03",
            "duration": "123.9",
            "musicinfo": {"tags": {"genres": ["Rock", "Ambient"]}},
            "shareurl": "https://www.jamendo.com/track/100/fixture-title",
        }
    )

    assert rejection is None
    assert row["source_record_id"] == "100"
    assert row["artist"] == "Fixture Artist"
    assert row["album"] == "Fixture Album"
    assert row["title"] == "Fixture Title"
    assert row["track_number"] == "7"
    assert row["release_year"] == "2020"
    assert row["label"] == ""
    assert row["duration_seconds"] == "123"
    assert row["genre"] == "Ambient; Rock"
    assert row["source_url"] == "https://www.jamendo.com/track/100/fixture-title"


def test_missing_id_rejection_and_raw_payload_preservation():
    payload = {"name": "Has Title", "artist_name": "Artist"}
    row, rejection = map_jamendo_record(payload)

    assert rejection == "missing_track_id"
    assert row["source_record_id"] == ""
    assert json.loads(row["raw_payload_json"]) == payload


def test_rejects_records_without_title_artist_or_album():
    row, rejection = map_jamendo_record({"id": "empty-record"})

    assert rejection == "missing_title_artist_album"
    assert row["source_record_id"] == "empty-record"


def test_output_csv_jsonl_and_summary_generation(tmp_path):
    def fake_fetch(_url, _timeout):
        return {"results": [_track("accepted"), {"id": "rejected"}, {"name": "missing id"}]}

    result = fetch_jamendo_metadata(
        limit=3,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        client_id="client-123",
        fetch_json=fake_fetch,
    )

    output_csv = tmp_path / "data" / "external_metadata" / "jamendo" / "raw_jamendo.csv"
    output_jsonl = tmp_path / "data" / "external_metadata" / "jamendo" / "raw_jamendo.jsonl"
    report_dir = tmp_path / "reports" / "jamendo_metadata"
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
    assert rejected[0]["rejection_reason"] == "missing_title_artist_album"
    assert rejected[1]["rejection_reason"] == "missing_track_id"
    assert summary["source_name"] == "jamendo"
    assert summary["requested_limit"] == 3
    assert summary["fetched_records"] == 3
    assert summary["accepted_records"] == 1
    assert summary["rejected_records"] == 2
    assert summary["metadata_only"] is True
    assert summary["audio_download_allowed"] is False
    assert summary["client_id_source"] == "argument"
    assert summary["output_csv"] == result.output_csv
    assert summary["output_jsonl"] == result.output_jsonl


def test_data_root_output_path(monkeypatch, tmp_path):
    data_root = tmp_path / "configured_data"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))

    result = fetch_jamendo_metadata(
        limit=1,
        out_dir=tmp_path / "reports",
        client_id="client-123",
        fetch_json=lambda _url, _timeout: {"results": [_track("env-root")]},
    )

    assert result.output_csv == str(
        data_root / "external_metadata" / "jamendo" / "raw_jamendo.csv"
    )
    assert (data_root / "external_metadata" / "jamendo" / "raw_jamendo.jsonl").exists()


def test_malformed_response_handling(tmp_path):
    with pytest.raises(ValueError, match="results list"):
        fetch_jamendo_metadata(
            limit=1,
            out_dir=tmp_path / "reports",
            data_dir=tmp_path / "data",
            client_id="client-123",
            fetch_json=lambda _url, _timeout: {"unexpected": []},
        )
    with pytest.raises(ValueError, match="results must be JSON objects"):
        fetch_jamendo_metadata(
            limit=1,
            out_dir=tmp_path / "reports",
            data_dir=tmp_path / "data",
            client_id="client-123",
            fetch_json=lambda _url, _timeout: {"results": ["not an object"]},
        )


def test_no_live_network_required(monkeypatch, tmp_path):
    def fail_socket(*args, **kwargs):
        raise AssertionError("live network is not allowed")

    monkeypatch.setattr(socket, "socket", fail_socket)

    result = fetch_jamendo_metadata(
        limit=1,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        client_id="client-123",
        fetch_json=lambda _url, _timeout: {"results": [_track("mocked")]},
    )

    assert result.accepted_records == 1


def test_cli_missing_client_id_prints_required_message(tmp_path, monkeypatch, capsys):
    data_root = tmp_path / "data"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)

    exit_code = main(
        [
            "fetch-jamendo-metadata",
            "--limit",
            "5",
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert MISSING_CLIENT_ID_MESSAGE in output
    assert not (data_root / "external_metadata" / "jamendo").exists()


def test_cli_fetch_jamendo_metadata_dry_run_with_argument(tmp_path, monkeypatch, capsys):
    data_root = tmp_path / "data"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)

    exit_code = main(
        [
            "fetch-jamendo-metadata",
            "--limit",
            "5",
            "--out",
            str(tmp_path / "reports"),
            "--client-id",
            "client-123",
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "metadata_only=true" in output
    assert "audio_download_allowed=false" in output
    assert "client_id_source=argument" in output
    assert (data_root / "external_metadata" / "jamendo" / "raw_jamendo.csv").exists()


def _track(identifier):
    return {
        "id": identifier,
        "name": f"Title {identifier}",
        "artist_name": "Creator",
        "album_name": "Album",
        "tags": ["pop"],
    }


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
