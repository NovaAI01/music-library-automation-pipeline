import csv
import json
import sqlite3

import pytest

from app.external_metadata import (
    SUPPORTED_SOURCE_NAMES,
    generate_deterministic_source_record_id,
    get_source_adapter,
    import_external_metadata,
    validate_source_name,
)
from app.main import main


def test_valid_csv_ingestion(tmp_path):
    input_path = tmp_path / "external.csv"
    _write_csv(
        input_path,
        [
            {
                "source_record_id": "mb-1",
                "artist": "  Deftones ",
                "album": "White Pony",
                "title": " Change ",
                "track_number": " 11 ",
                "release_year": "2000",
                "duration_seconds": "301",
                "raw_payload_json": '{"id":"mb-1"}',
            }
        ],
    )

    result = import_external_metadata(
        "local_fixture",
        input_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    rows = _read_csv(
        tmp_path
        / "data"
        / "external_metadata"
        / "local_fixture"
        / "external_tracks.csv"
    )
    assert result.accepted_records == 1
    assert result.rejected_records == 0
    assert rows[0]["artist"] == "Deftones"
    assert rows[0]["title"] == "Change"
    assert rows[0]["release_year"] == "2000"
    assert rows[0]["duration_seconds"] == "301"


def test_valid_jsonl_ingestion_preserves_full_payload_when_raw_missing(tmp_path):
    input_path = tmp_path / "external.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "source_record_id": "discogs-1",
                "artist": "Massive Attack",
                "album": "Mezzanine",
                "title": "Angel",
                "extra": {"country": "UK"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import_external_metadata(
        "discogs",
        input_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    records = _read_jsonl(
        tmp_path / "data" / "external_metadata" / "discogs" / "external_tracks.jsonl"
    )
    raw_payload = json.loads(records[0]["raw_payload_json"])
    assert raw_payload["extra"] == {"country": "UK"}
    assert raw_payload["source_record_id"] == "discogs-1"


def test_generated_deterministic_ids(tmp_path):
    input_path = tmp_path / "external.csv"
    _write_csv(
        input_path,
        [
            {
                "artist": "Aphex Twin",
                "album": "",
                "title": "Xtal",
                "track_number": "1",
            }
        ],
    )

    result = import_external_metadata(
        "jamendo",
        input_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    rows = _read_csv(
        tmp_path / "data" / "external_metadata" / "jamendo" / "external_tracks.csv"
    )
    expected = generate_deterministic_source_record_id(
        "jamendo", "Aphex Twin", "", "Xtal", "1"
    )
    assert result.generated_id_count == 1
    assert rows[0]["source_record_id"] == expected


def test_invalid_row_rejection(tmp_path):
    input_path = tmp_path / "external.csv"
    _write_csv(input_path, [{"source_record_id": "bad-1", "raw_payload_json": "{}"}])

    result = import_external_metadata(
        "musicbrainz",
        input_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    rejected = _read_csv(
        tmp_path / "reports" / "external_metadata_ingestion" / "rejected_records.csv"
    )
    assert result.accepted_records == 0
    assert result.rejected_records == 1
    assert "at least one of artist" in rejected[0]["error"]


def test_invalid_raw_payload_rejected(tmp_path):
    input_path = tmp_path / "external.csv"
    _write_csv(
        input_path,
        [
            {
                "source_record_id": "bad-raw",
                "artist": "Bark Psychosis",
                "raw_payload_json": "{bad json",
            }
        ],
    )

    result = import_external_metadata(
        "internet_archive",
        input_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    rejected = _read_csv(
        tmp_path / "reports" / "external_metadata_ingestion" / "rejected_records.csv"
    )
    assert result.rejected_records == 1
    assert "raw_payload_json must be valid JSON" in rejected[0]["error"]


def test_raw_payload_preservation(tmp_path):
    input_path = tmp_path / "external.csv"
    raw_payload_json = '{"source":"yt-dlp","webpage_url":"https://example.test/watch"}'
    _write_csv(
        input_path,
        [
            {
                "source_record_id": "yt-1",
                "title": "Fixture Upload",
                "raw_payload_json": raw_payload_json,
            }
        ],
    )

    import_external_metadata(
        "youtube_metadata",
        input_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    rows = _read_csv(
        tmp_path
        / "data"
        / "external_metadata"
        / "youtube_metadata"
        / "external_tracks.csv"
    )
    assert rows[0]["raw_payload_json"] == raw_payload_json


def test_source_isolation(tmp_path):
    csv_path = tmp_path / "external.csv"
    _write_csv(csv_path, [{"source_record_id": "1", "artist": "Low"}])
    import_external_metadata(
        "musicbrainz", csv_path, out_dir=tmp_path / "reports", data_dir=tmp_path / "data"
    )
    import_external_metadata(
        "discogs", csv_path, out_dir=tmp_path / "reports", data_dir=tmp_path / "data"
    )

    assert (
        tmp_path / "data" / "external_metadata" / "musicbrainz" / "external_tracks.csv"
    ).exists()
    assert (
        tmp_path / "data" / "external_metadata" / "discogs" / "external_tracks.csv"
    ).exists()


def test_no_audio_paths_required(tmp_path):
    csv_path = tmp_path / "metadata_only.csv"
    _write_csv(csv_path, [{"source_record_id": "meta-1", "title": "No File"}])

    result = import_external_metadata(
        "local_fixture",
        csv_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    assert result.accepted_records == 1
    rows = _read_csv(
        tmp_path
        / "data"
        / "external_metadata"
        / "local_fixture"
        / "external_tracks.csv"
    )
    assert "path" not in rows[0]


def test_no_local_library_mutation(tmp_path):
    library_root = tmp_path / "library"
    library_root.mkdir()
    audio_file = library_root / "track.flac"
    audio_file.write_bytes(b"audio")
    before = (audio_file.read_bytes(), audio_file.stat().st_mtime_ns)
    csv_path = tmp_path / "external.csv"
    _write_csv(csv_path, [{"source_record_id": "meta-1", "artist": "Slowdive"}])

    import_external_metadata(
        "local_fixture",
        csv_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    after = (audio_file.read_bytes(), audio_file.stat().st_mtime_ns)
    assert after == before


def test_no_local_library_db_mutation(tmp_path):
    db_path = tmp_path / "music_library.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table local_tracks (id integer primary key, title text)")
        conn.execute("insert into local_tracks (title) values ('Existing')")
    before = db_path.read_bytes()
    csv_path = tmp_path / "external.csv"
    _write_csv(csv_path, [{"source_record_id": "meta-1", "artist": "Ride"}])

    import_external_metadata(
        "local_fixture",
        csv_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    assert db_path.read_bytes() == before


def test_report_generation(tmp_path):
    csv_path = tmp_path / "external.csv"
    _write_csv(
        csv_path,
        [
            {"source_record_id": "1", "album": "Dummy"},
            {"source_record_id": "2"},
        ],
    )

    result = import_external_metadata(
        "local_fixture",
        csv_path,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    report_dir = tmp_path / "reports" / "external_metadata_ingestion"
    summary = json.loads((report_dir / "ingestion_summary.json").read_text())
    assert summary["input_records"] == 2
    assert summary["accepted_records"] == 1
    assert summary["rejected_records"] == 1
    assert summary["missing_artist_count"] == 1
    assert summary["missing_title_count"] == 1
    assert summary["output_csv"] == result.output_csv
    assert (report_dir / "external_tracks_sample.csv").exists()
    assert (report_dir / "rejected_records.csv").exists()


def test_supported_source_validation():
    assert validate_source_name("musicbrainz") == "musicbrainz"
    for source_name in SUPPORTED_SOURCE_NAMES:
        adapter = get_source_adapter(source_name)
        with pytest.raises(NotImplementedError, match="local CSV and JSONL"):
            adapter.fetch()
    with pytest.raises(ValueError, match="unsupported external metadata source"):
        validate_source_name("spotify")


def test_cli_import_external_metadata(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "external.csv"
    _write_csv(csv_path, [{"source_record_id": "1", "artist": "Portishead"}])
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "import-external-metadata",
            "--source",
            "local_fixture",
            "--input",
            str(csv_path),
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "accepted_records=1" in output
    assert (
        tmp_path
        / "data"
        / "external_metadata"
        / "local_fixture"
        / "external_tracks.jsonl"
    ).exists()


def _write_csv(path, rows):
    fieldnames = [
        "artist",
        "album",
        "title",
        "track_number",
        "release_year",
        "label",
        "duration_seconds",
        "genre",
        "source_url",
        "raw_payload_json",
        "source_record_id",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
