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
    assert summary["artist_credit_analysis_used"] is False
    assert summary["artist_credit_parsed_records"] == 0
    assert summary["artist_credit_unresolved_records"] == 0
    assert summary["artist_credit_high_confidence"] == 0
    assert summary["artist_credit_medium_confidence"] == 0
    assert summary["artist_credit_low_confidence"] == 0
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


def test_artist_credit_analysis_replaces_raw_collaboration_cohort(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "Alpha feat. Beta", "album": "Album", "title": "Song"},
            {"source_record_id": "2", "artist": "Gamma & Delta", "album": "Album", "title": "Song 2"},
            {"source_record_id": "3", "artist": "Uploader Channel", "album": "Album", "title": "Song 3"},
        ],
    )
    _write_artist_credit_analysis(
        tmp_path,
        "local_fixture",
        [
            _artist_credit_row(
                "1",
                raw_artist="Alpha feat. Beta",
                primary_artist="Alpha",
                featured_artists=["Beta"],
                credit_pattern="feat_artist",
                confidence_tier="high",
            ),
            _artist_credit_row(
                "2",
                raw_artist="Gamma & Delta",
                primary_artist="Gamma",
                collaborating_artists=["Delta"],
                credit_pattern="ampersand_collaboration",
                confidence_tier="medium",
            ),
            _artist_credit_row(
                "3",
                raw_artist="Uploader Channel",
                primary_artist="",
                credit_pattern="unknown_or_ambiguous",
                confidence_tier="low",
                parser_flags=["source_artifact"],
            ),
        ],
    )

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    report_dir = tmp_path / "reports" / "validation_benchmark"
    summary = json.loads((report_dir / "benchmark_summary.json").read_text(encoding="utf-8"))
    assert summary["artist_credit_analysis_used"] is True
    assert summary["artist_credit_parsed_records"] == 2
    assert summary["artist_credit_unresolved_records"] == 1
    assert summary["artist_credit_high_confidence"] == 1
    assert summary["artist_credit_medium_confidence"] == 1
    assert summary["artist_credit_low_confidence"] == 1
    assert summary["collaboration_string_candidates"] == 0

    cohorts = {
        row["cohort_type"]: row
        for row in _read_csv(report_dir / "cohort_distribution.csv")
    }
    assert "collaboration_string" not in cohorts
    assert cohorts["artist_credit_parsed_high_confidence"]["record_count"] == "1"
    assert cohorts["artist_credit_parsed_high_confidence"]["highest_severity"] == "low"
    assert cohorts["artist_credit_parsed_medium_confidence"]["record_count"] == "1"
    assert cohorts["artist_credit_unresolved"]["record_count"] == "1"
    assert cohorts["artist_credit_unresolved"]["highest_severity"] == "high"
    assert cohorts["artist_credit_featured"]["record_count"] == "1"
    assert cohorts["artist_credit_collaboration"]["record_count"] == "1"


def test_artist_credit_ambiguous_group_cohort(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Alpha, Beta & Company", "album": "Album", "title": "Track"}],
    )
    _write_artist_credit_analysis(
        tmp_path,
        "local_fixture",
        [
            _artist_credit_row(
                "1",
                raw_artist="Alpha, Beta & Company",
                primary_artist="Alpha, Beta & Company",
                credit_pattern="solo_artist",
                confidence_tier="medium",
                parser_flags=["possible_group_name", "ambiguous_separator"],
            )
        ],
        summary_overrides={
            "parsed_records": 1,
            "unresolved_count": 0,
            "high_confidence_count": 0,
            "medium_confidence_count": 1,
            "low_confidence_count": 0,
        },
    )

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    cohorts = {
        row["cohort_type"]: row
        for row in _read_csv(tmp_path / "reports" / "validation_benchmark" / "cohort_distribution.csv")
    }
    assert cohorts["artist_credit_ambiguous_group"]["record_count"] == "1"
    assert cohorts["artist_credit_ambiguous_group"]["highest_severity"] == "medium"


def test_artist_credit_cohort_ranking_is_deterministic(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "Alpha feat. Beta", "album": "Album", "title": "Track"},
            {"source_record_id": "2", "artist": "Gamma feat. Delta", "album": "Album", "title": "Track"},
        ],
    )
    _write_artist_credit_analysis(
        tmp_path,
        "local_fixture",
        [
            _artist_credit_row(
                "1",
                raw_artist="Alpha feat. Beta",
                primary_artist="Alpha",
                featured_artists=["Beta"],
                credit_pattern="feat_artist",
                confidence_tier="high",
            ),
            _artist_credit_row(
                "2",
                raw_artist="Gamma feat. Delta",
                primary_artist="Gamma",
                featured_artists=["Delta"],
                credit_pattern="feat_artist",
                confidence_tier="high",
            ),
        ],
        summary_overrides={
            "parsed_records": 2,
            "unresolved_count": 0,
            "high_confidence_count": 2,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
        },
    )

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    rows = _read_csv(tmp_path / "reports" / "validation_benchmark" / "top_failure_cohorts.csv")
    assert [row["cohort_type"] for row in rows[:2]] == [
        "artist_credit_featured",
        "artist_credit_parsed_high_confidence",
    ]


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
        "artist_credit_analysis_used",
        "artist_credit_high_confidence",
        "artist_credit_low_confidence",
        "artist_credit_medium_confidence",
        "artist_credit_parsed_records",
        "artist_credit_unresolved_records",
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


def test_no_mutation_of_artist_credit_input_reports(tmp_path):
    source_path = _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Alpha feat. Beta", "album": "Album", "title": "Song"}],
    )
    parsed_path, summary_path = _write_artist_credit_analysis(
        tmp_path,
        "local_fixture",
        [
            _artist_credit_row(
                "1",
                raw_artist="Alpha feat. Beta",
                primary_artist="Alpha",
                featured_artists=["Beta"],
                credit_pattern="feat_artist",
                confidence_tier="high",
            )
        ],
    )
    before_source = source_path.read_bytes()
    before_parsed = parsed_path.read_bytes()
    before_summary = summary_path.read_bytes()

    benchmark_validation("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    assert source_path.read_bytes() == before_source
    assert parsed_path.read_bytes() == before_parsed
    assert summary_path.read_bytes() == before_summary


def test_cli_benchmark_validation(tmp_path, monkeypatch, capsys):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Massive Attack", "album": "Mezzanine", "title": "Angel"}],
    )
    monkeypatch.delenv("MUSIC_INTELLIGENCE_DATA_ROOT", raising=False)
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


def _write_artist_credit_analysis(
    tmp_path,
    source_name,
    rows,
    summary_overrides=None,
):
    report_dir = tmp_path / "reports" / "artist_credit_analysis"
    report_dir.mkdir(parents=True, exist_ok=True)
    parsed_path = report_dir / "parsed_artist_credits.csv"
    fieldnames = [
        "source_name",
        "source_record_id",
        "raw_artist",
        "primary_artist",
        "featured_artists_json",
        "collaborating_artists_json",
        "credit_pattern",
        "confidence_score",
        "confidence_tier",
        "parser_flags_json",
        "rationale",
        "source_title",
        "source_album",
    ]
    with parsed_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            complete = {field: "" for field in fieldnames}
            complete["source_name"] = source_name
            complete.update(row)
            writer.writerow(complete)

    summary = {
        "source_name": source_name,
        "total_records": len(rows),
        "parsed_records": sum(1 for row in rows if row.get("primary_artist")),
        "solo_artist_count": sum(1 for row in rows if row.get("credit_pattern") == "solo_artist"),
        "collaboration_count": sum(
            1
            for row in rows
            if row.get("credit_pattern")
            in {
                "with_artist",
                "versus_artist",
                "x_collaboration",
                "ampersand_collaboration",
                "comma_collaboration",
                "multi_artist_credit",
            }
        ),
        "featured_artist_count": sum(
            1
            for row in rows
            if row.get("credit_pattern") in {"feat_artist", "ft_artist", "featuring_artist"}
        ),
        "unresolved_count": sum(
            1
            for row in rows
            if row.get("credit_pattern") == "unknown_or_ambiguous" or not row.get("primary_artist")
        ),
        "high_confidence_count": sum(1 for row in rows if row.get("confidence_tier") == "high"),
        "medium_confidence_count": sum(1 for row in rows if row.get("confidence_tier") == "medium"),
        "low_confidence_count": sum(1 for row in rows if row.get("confidence_tier") == "low"),
        "top_pattern": "",
        "output_csv": str(parsed_path),
        "unresolved_csv": str(report_dir / "unresolved_artist_credits.csv"),
    }
    if summary_overrides:
        summary.update(summary_overrides)
    summary_path = report_dir / "artist_credit_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return parsed_path, summary_path


def _artist_credit_row(
    source_record_id,
    *,
    raw_artist,
    primary_artist,
    credit_pattern,
    confidence_tier,
    featured_artists=None,
    collaborating_artists=None,
    parser_flags=None,
):
    return {
        "source_record_id": source_record_id,
        "raw_artist": raw_artist,
        "primary_artist": primary_artist,
        "featured_artists_json": json.dumps(featured_artists or []),
        "collaborating_artists_json": json.dumps(collaborating_artists or []),
        "credit_pattern": credit_pattern,
        "confidence_score": {"high": "0.95", "medium": "0.65", "low": "0.20"}[confidence_tier],
        "confidence_tier": confidence_tier,
        "parser_flags_json": json.dumps(parser_flags or []),
        "rationale": "test fixture",
        "source_title": "Song",
        "source_album": "Album",
    }


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_csv_headers(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))
