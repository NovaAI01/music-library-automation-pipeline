import csv
import json

from app.external_metadata import EXTERNAL_TRACK_FIELDS
from app.main import main
from app.validation_benchmark import (
    GOVERNANCE_STATUSES,
    benchmark_validation,
)


def test_benchmark_report_generation(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "low", "album": "Things We Lost", "title": "Sunflower"},
            {"source_record_id": "2", "artist": "Low", "album": "Things-We-Lost", "title": "Sun Flower"},
            {"source_record_id": "3", "artist": "Artist feat. Guest", "album": "Album", "title": "Song"},
            {"source_record_id": "4", "artist": "YouTube Topic", "album": "Official Audio", "title": "Song Remastered"},
            {"source_record_id": "dup", "artist": "D", "album": "A", "title": "T"},
            {"source_record_id": "dup", "artist": "D", "album": "A", "title": "T"},
            {"source_record_id": "6", "artist": "Bad Year", "album": "Album", "title": "Title", "release_year": "20xx"},
        ],
    )

    result = benchmark_validation(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    report_dir = tmp_path / "reports" / "validation_benchmark"
    summary = json.loads((report_dir / "benchmark_summary.json").read_text(encoding="utf-8"))
    assert result.total_records == 7
    assert summary["source_name"] == "local_fixture"
    assert summary["total_records"] == 7
    assert summary["total_cohorts"] > 0
    assert summary["duplicate_external_records"] > 0
    assert summary["source_artifact_candidates"] > 0
    assert summary["collaboration_string_candidates"] > 0
    assert summary["malformed_records"] == 1
    assert (report_dir / "cohort_distribution.csv").exists()
    assert (report_dir / "severity_distribution.csv").exists()
    assert (report_dir / "governance_distribution.csv").exists()
    assert (report_dir / "top_failure_cohorts.csv").exists()
    assert (report_dir / "benchmark_timing.json").exists()


def test_timing_report_generation(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Portishead", "album": "Dummy", "title": "Glory Box"}],
    )

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    timing = json.loads(
        (tmp_path / "reports" / "validation_benchmark" / "benchmark_timing.json")
        .read_text(encoding="utf-8")
    )
    assert set(timing) == {
        "ingestion_load_seconds",
        "cohort_analysis_seconds",
        "governance_analysis_seconds",
        "report_generation_seconds",
        "total_duration_seconds",
    }
    assert all(isinstance(value, float) for value in timing.values())
    assert timing["total_duration_seconds"] >= 0.0


def test_governance_distribution_generation(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "tool", "album": "Album", "title": "Track"},
            {"source_record_id": "2", "artist": "Tool", "album": "Album", "title": "Track"},
            {"source_record_id": "3", "artist": "YouTube Topic", "album": "Album", "title": "Track"},
            {"source_record_id": "4", "artist": "A feat. B", "album": "Album", "title": "Track"},
        ],
    )

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    rows = _read_csv(tmp_path / "reports" / "validation_benchmark" / "governance_distribution.csv")
    assert [row["conflict_status"] for row in rows] == list(GOVERNANCE_STATUSES)
    counts = {row["conflict_status"]: int(row["count"]) for row in rows}
    assert counts["safe_to_merge_candidate"] >= 1
    assert counts["blocked_merge"] >= 1
    assert counts["deferred"] >= 1
    assert counts["resolved"] == 0


def test_cohort_ranking_generation(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "", "album": "Album", "title": "Track"},
            {"source_record_id": "2", "artist": "", "album": "Album", "title": "Track 2"},
            {"source_record_id": "3", "artist": "YouTube Topic", "album": "Album", "title": "Track 3"},
        ],
    )

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    rows = _read_csv(tmp_path / "reports" / "validation_benchmark" / "top_failure_cohorts.csv")
    assert rows[0]["cohort_type"] == "missing_artist"
    assert rows[0]["record_count"] == "2"
    assert rows[0]["percentage_of_dataset"] == "66.67"
    assert {"cohort_type", "record_count", "percentage_of_dataset", "severity", "recommended_action"} == set(rows[0])


def test_empty_dataset_handling(tmp_path):
    result = benchmark_validation(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    report_dir = tmp_path / "reports" / "validation_benchmark"
    assert result.total_records == 0
    assert result.total_cohorts == 0
    assert _read_csv(report_dir / "cohort_distribution.csv") == []
    assert _read_csv(report_dir / "top_failure_cohorts.csv") == []
    governance = _read_csv(report_dir / "governance_distribution.csv")
    assert all(row["count"] == "0" for row in governance)


def test_deterministic_output_structure(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Ride", "album": "Nowhere", "title": "Vapour Trail"}],
    )

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    report_dir = tmp_path / "reports" / "validation_benchmark"
    summary = json.loads((report_dir / "benchmark_summary.json").read_text(encoding="utf-8"))
    assert list(summary) == [
        "benchmark_duration_seconds",
        "blocked_merges",
        "collaboration_string_candidates",
        "deferred_conflicts",
        "duplicate_external_records",
        "malformed_records",
        "safe_merge_candidates",
        "source_artifact_candidates",
        "source_name",
        "total_cohorts",
        "total_conflicts",
        "total_records",
    ]
    assert _read_csv_headers(report_dir / "severity_distribution.csv") == [
        "severity",
        "count",
        "percentage",
    ]
    assert _read_csv_headers(report_dir / "governance_distribution.csv") == [
        "conflict_status",
        "count",
        "percentage",
    ]


def test_no_mutation_of_source_dataset(tmp_path):
    source_path = _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Slowdive", "album": "Souvlaki", "title": "Alison"}],
    )
    before = source_path.read_bytes()

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    assert source_path.read_bytes() == before


def test_cli_benchmark_validation(tmp_path, monkeypatch, capsys):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Massive Attack", "album": "Mezzanine", "title": "Angel"}],
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "benchmark-validation",
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
    assert (tmp_path / "reports" / "validation_benchmark" / "benchmark_summary.json").exists()


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


def _read_csv_headers(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))
