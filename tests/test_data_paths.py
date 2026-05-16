import csv
from pathlib import Path

import pytest

from app.data_paths import (
    cache_root,
    external_metadata_root,
    get_data_root,
    raw_dumps_root,
    reports_root,
    sanitize_source_name,
    source_external_tracks_csv,
    source_external_tracks_jsonl,
    source_metadata_dir,
)
from app.external_metadata import EXTERNAL_TRACK_FIELDS, import_external_metadata
from app.large_scale_validation import validate_external_metadata


def test_default_data_root(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSIC_INTELLIGENCE_DATA_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    assert get_data_root() == Path("data")
    assert (tmp_path / "data").is_dir()


def test_env_var_data_root(monkeypatch, tmp_path):
    data_root = tmp_path / "ssd" / "music-intelligence"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))

    assert get_data_root() == data_root
    assert data_root.is_dir()


def test_source_path_generation(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(tmp_path))

    assert source_metadata_dir("Local Fixture") == tmp_path / "external_metadata" / "local_fixture"
    assert source_external_tracks_csv("Local Fixture") == (
        tmp_path / "external_metadata" / "local_fixture" / "external_tracks.csv"
    )
    assert source_external_tracks_jsonl("Local Fixture") == (
        tmp_path / "external_metadata" / "local_fixture" / "external_tracks.jsonl"
    )


def test_directory_creation(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(tmp_path / "root"))

    assert external_metadata_root().is_dir()
    assert reports_root().is_dir()
    assert cache_root().is_dir()
    assert raw_dumps_root().is_dir()
    assert source_metadata_dir("discogs").is_dir()


def test_source_name_sanitization():
    assert sanitize_source_name(" Local Fixture! ") == "local_fixture"
    assert sanitize_source_name("YouTube-Metadata") == "youtube-metadata"


@pytest.mark.parametrize("source_name", ["../discogs", "discogs/2026", r"discogs\2026", ".", ".."])
def test_path_traversal_rejection(source_name):
    with pytest.raises(ValueError):
        source_metadata_dir(source_name)


def test_external_metadata_import_writes_to_configured_root(monkeypatch, tmp_path):
    data_root = tmp_path / "external-data"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))
    input_path = tmp_path / "external.csv"
    _write_import_csv(input_path, [{"source_record_id": "1", "artist": "Portishead"}])

    result = import_external_metadata(
        "local_fixture",
        input_path,
        out_dir=tmp_path / "reports",
    )

    expected_csv = data_root / "external_metadata" / "local_fixture" / "external_tracks.csv"
    assert result.output_csv == str(expected_csv)
    assert expected_csv.exists()
    assert not (tmp_path / "data" / "external_metadata").exists()


def test_validation_reads_from_configured_root(monkeypatch, tmp_path):
    data_root = tmp_path / "external-data"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))
    _write_external_tracks(
        data_root,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Massive Attack", "album": "Mezzanine", "title": "Angel"}],
    )

    result = validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
    )

    assert result.total_records == 1
    assert result.input_csv == str(
        data_root / "external_metadata" / "local_fixture" / "external_tracks.csv"
    )


def _write_import_csv(path, rows):
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


def _write_external_tracks(data_root, source_name, rows):
    path = data_root / "external_metadata" / source_name
    path.mkdir(parents=True, exist_ok=True)
    csv_path = path / "external_tracks.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXTERNAL_TRACK_FIELDS)
        writer.writeheader()
        for row in rows:
            complete = {field: "" for field in EXTERNAL_TRACK_FIELDS}
            complete.update(
                {
                    "source_name": source_name,
                    "raw_payload_json": "{}",
                    "ingested_at": "2026-05-15T00:00:00+00:00",
                }
            )
            complete.update(row)
            writer.writerow(complete)
