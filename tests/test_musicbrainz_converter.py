import csv
import json
import socket
from pathlib import Path

import pytest

from app.main import main
from app.musicbrainz_converter import OUTPUT_FIELDS, convert_musicbrainz_dump


FIXTURE_DUMP = Path(__file__).parent / "fixtures" / "musicbrainz_dump"


def test_musicbrainz_dump_mapping_and_contract(tmp_path):
    output_csv = tmp_path / "external_metadata" / "musicbrainz" / "raw_musicbrainz.csv"

    result = convert_musicbrainz_dump(FIXTURE_DUMP, output_csv, reports_dir=tmp_path)

    rows = _read_csv(output_csv)
    rejected = _read_csv(output_csv.with_name("raw_musicbrainz_rejected.csv"))
    summary = json.loads(
        (tmp_path / "musicbrainz_conversion" / "conversion_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert list(rows[0].keys()) == list(OUTPUT_FIELDS)
    assert result.input_tracks_seen == 3
    assert result.accepted_records == 2
    assert result.rejected_records == 1
    assert summary["accepted_records"] == 2
    assert summary["rejected_csv"] == str(
        output_csv.with_name("raw_musicbrainz_rejected.csv")
    )

    first = rows[0]
    assert first["source_record_id"] == "musicbrainz:track-gid-1"
    assert first["artist"] == "Artist A & Artist B"
    assert first["album"] == "Fixture Album"
    assert first["title"] == "Recording Title"
    assert first["track_number"] == "1"
    assert first["duration_seconds"] == "245"
    assert first["release_year"] == ""
    assert first["label"] == ""
    assert first["genre"] == ""
    assert first["source_url"] == "https://musicbrainz.org/recording/recording-gid-10"

    payload = json.loads(first["raw_payload_json"])
    assert payload == {
        "track_id": "1",
        "track_gid": "track-gid-1",
        "recording_id": "10",
        "recording_gid": "recording-gid-10",
        "medium_id": "100",
        "release_id": "500",
        "release_gid": "release-gid-500",
        "artist_credit_id": "4000",
    }

    fallback = rows[1]
    assert fallback["artist"] == "Release Artist"
    assert fallback["title"] == "Fallback Title"
    assert fallback["track_number"] == "A2"
    assert fallback["duration_seconds"] == "61"

    assert rejected[0]["source_record_id"] == "musicbrainz:3:30:300"
    assert rejected[0]["rejection_reason"] == "missing_album"
    rejected_payload = json.loads(rejected[0]["raw_payload_json"])
    assert rejected_payload["track_id"] == "3"
    assert rejected_payload["release_id"] == "999"


def test_limit_behavior_reads_only_bounded_track_rows(tmp_path):
    output_csv = tmp_path / "raw_musicbrainz.csv"

    result = convert_musicbrainz_dump(
        FIXTURE_DUMP, output_csv, limit=1, reports_dir=tmp_path
    )

    rows = _read_csv(output_csv)
    rejected = _read_csv(output_csv.with_name("raw_musicbrainz_rejected.csv"))

    assert result.input_tracks_seen == 1
    assert result.limit_applied == 1
    assert len(rows) == 1
    assert rows[0]["source_record_id"] == "musicbrainz:track-gid-1"
    assert rejected == []


def test_no_network_calls(monkeypatch, tmp_path):
    def fail_socket(*args, **kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", fail_socket)

    result = convert_musicbrainz_dump(
        FIXTURE_DUMP, tmp_path / "raw_musicbrainz.csv", limit=2, reports_dir=tmp_path
    )

    assert result.accepted_records == 2


def test_cli_convert_musicbrainz_dump(tmp_path):
    output_csv = tmp_path / "raw_musicbrainz.csv"

    exit_code = main(
        [
            "convert-musicbrainz-dump",
            "--dump-dir",
            str(FIXTURE_DUMP),
            "--out",
            str(output_csv),
            "--limit",
            "2",
        ]
    )

    assert exit_code == 0
    rows = _read_csv(output_csv)
    assert len(rows) == 2


def test_invalid_limit_rejected(tmp_path):
    with pytest.raises(ValueError, match="positive integer"):
        convert_musicbrainz_dump(
            FIXTURE_DUMP, tmp_path / "raw_musicbrainz.csv", limit=0
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
