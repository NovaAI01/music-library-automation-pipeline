import csv
import json
import sqlite3

from app.external_metadata import EXTERNAL_TRACK_FIELDS
from app.large_scale_validation import validate_external_metadata
from app.main import main


def test_summary_generation(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "Deftones", "album": "", "title": "Change"},
            {"source_record_id": "2", "artist": "", "album": "Mezzanine", "title": "Angel"},
        ],
    )

    result = validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    summary = json.loads(
        (tmp_path / "reports" / "large_scale_validation" / "validation_summary.json")
        .read_text(encoding="utf-8")
    )
    assert result.total_records == 2
    assert summary["source_name"] == "local_fixture"
    assert summary["missing_artist_count"] == 1
    assert summary["missing_album_count"] == 1
    assert summary["missing_title_count"] == 0


def test_cohort_detection(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "low", "album": "Things We Lost", "title": "Sunflower"},
            {"source_record_id": "2", "artist": "Low", "album": "Things-We-Lost", "title": "Sun Flower"},
            {"source_record_id": "3", "artist": "Artist feat. Guest", "album": "Album", "title": "Song"},
            {"source_record_id": "4", "artist": "YouTube Topic", "album": "Official Audio", "title": "Song Remastered"},
            {"source_record_id": "5", "artist": "Only Artist", "album": "", "title": ""},
            {"source_record_id": "6", "artist": "Bad Year", "album": "Album", "title": "Title", "release_year": "20xx"},
        ],
    )

    validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    cohorts = _read_csv(tmp_path / "reports" / "large_scale_validation" / "validation_cohorts.csv")
    cohort_types = {row["cohort_type"] for row in cohorts}
    assert {
        "casing_alias_candidate",
        "album_title_punctuation_variant",
        "collaboration_string",
        "source_artifact_candidate",
        "official_audio_video_noise",
        "remaster_version_noise",
        "sparse_record",
        "malformed_year",
    }.issubset(cohort_types)


def test_severity_classification(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "YouTube Topic", "album": "Album", "title": "Song"},
            {"source_record_id": "2", "artist": "A feat. B", "album": "Album", "title": "Song"},
            {"source_record_id": "3", "artist": "Sparse", "album": "", "title": ""},
            {"source_record_id": "dup", "artist": "D", "album": "A", "title": "T"},
            {"source_record_id": "dup", "artist": "D", "album": "A", "title": "T"},
            {"source_record_id": "dup", "artist": "D", "album": "A", "title": "T"},
        ],
    )

    validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    cohorts = _read_csv(tmp_path / "reports" / "large_scale_validation" / "validation_cohorts.csv")
    severity_by_type = {row["cohort_type"]: row["severity"] for row in cohorts}
    assert severity_by_type["source_artifact_candidate"] == "high"
    assert severity_by_type["duplicate_external_record"] == "high"
    assert severity_by_type["collaboration_string"] == "medium"
    assert severity_by_type["sparse_record"] == "low"


def test_examples_output(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "YouTube Topic", "album": "Official Audio", "title": "Song"}],
    )

    validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    examples = _read_csv(tmp_path / "reports" / "large_scale_validation" / "cohort_examples.csv")
    assert examples
    assert {"cohort_key", "source_record_id", "artist", "album", "title", "label", "source_url", "rationale"} == set(examples[0])
    assert any(row["source_record_id"] == "1" for row in examples)


def test_no_mutation_of_input_file(tmp_path):
    input_path = _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Slowdive", "album": "Souvlaki", "title": "Alison"}],
    )
    before = input_path.read_bytes()

    validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    assert input_path.read_bytes() == before


def test_missing_source_path_handled_cleanly(tmp_path):
    result = validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    assert result.total_records == 0
    assert result.total_cohorts == 0
    assert _read_csv(tmp_path / "reports" / "large_scale_validation" / "validation_cohorts.csv") == []
    assert (tmp_path / "reports" / "large_scale_validation" / "validation_summary.json").exists()


def test_duplicate_record_detection(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "same", "artist": "A", "album": "B", "title": "C", "track_number": "1"},
            {"source_record_id": "same", "artist": "A", "album": "B", "title": "C", "track_number": "1"},
        ],
    )

    result = validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    cohorts = _read_csv(tmp_path / "reports" / "large_scale_validation" / "validation_cohorts.csv")
    assert result.duplicate_external_record_count == 4
    assert any(row["cohort_type"] == "duplicate_external_record" for row in cohorts)


def test_collaboration_source_artifact_and_title_pollution_detection(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "Blue Monday", "album": "Singles", "title": "Different"},
            {"source_record_id": "2", "artist": "New Order feat. Guest", "album": "Official Audio", "title": "Blue Monday"},
            {"source_record_id": "3", "artist": "Uploader Channel", "album": "Album", "title": "Track"},
        ],
    )

    result = validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    cohorts = _read_csv(tmp_path / "reports" / "large_scale_validation" / "validation_cohorts.csv")
    cohort_types = {row["cohort_type"] for row in cohorts}
    assert result.collaboration_string_count == 1
    assert "source_artifact_candidate" in cohort_types
    assert "official_audio_video_noise" in cohort_types
    assert "possible_track_as_artist" in cohort_types


def test_no_local_library_or_canonical_db_mutation(tmp_path):
    db_path = tmp_path / "music_library.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table canonical_entities (id integer primary key, name text)")
        conn.execute("insert into canonical_entities (name) values ('Existing')")
    before = db_path.read_bytes()
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Ride", "album": "Nowhere", "title": "Vapour Trail"}],
    )

    validate_external_metadata(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    assert db_path.read_bytes() == before


def test_cli_validate_external_metadata(tmp_path, monkeypatch, capsys):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Portishead", "album": "Dummy", "title": "Glory Box"}],
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "validate-external-metadata",
            "--source",
            "local_fixture",
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "source_name=local_fixture" in output
    assert "total_records=1" in output
    assert (tmp_path / "reports" / "large_scale_validation" / "source_quality_report.csv").exists()


def _write_external_tracks(tmp_path, source_name, rows):
    path = tmp_path / "data" / "external_metadata" / source_name
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
    return csv_path


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
