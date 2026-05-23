import csv
import hashlib
import json
from pathlib import Path

from app.main import main
from app.source_quality_report import generate_source_quality_report


def test_source_quality_report_reads_multiple_runs_and_writes_json_csv(tmp_path):
    reports = tmp_path / "reports"
    _write_run(
        reports,
        source_name="jamendo",
        run_label="jamendo_1k",
        ingestion={
            "input_records": 1000,
            "accepted_records": 1000,
            "rejected_records": 0,
            "missing_artist_count": 0,
            "missing_album_count": 7,
            "missing_title_count": 0,
        },
        artist_credit={"parsed_records": 983, "unresolved_count": 17},
        release_identity={
            "total_identity_groups": 1000,
            "possible_true_duplicate_count": 0,
            "duplicate_external_records_explained": 0,
        },
        benchmark={
            "source_artifact_candidates": 2,
            "total_cohorts": 15,
            "total_conflicts": 15,
            "safe_merge_candidates": 2,
            "blocked_merges": 9,
            "deferred_conflicts": 4,
        },
        manifest={
            "metadata_only": True,
            "audio_downloaded": False,
            "local_library_mutated": False,
            "canonical_graph_mutated": False,
        },
    )
    _write_run(
        reports,
        source_name="internet_archive",
        run_label="internet_archive_1k",
        ingestion={
            "input_records": 1000,
            "accepted_records": 1000,
            "rejected_records": 0,
            "missing_artist_count": 763,
            "missing_album_count": 0,
            "missing_title_count": 0,
        },
        artist_credit={"parsed_records": 228, "unresolved_count": 772},
        release_identity={
            "total_identity_groups": 906,
            "possible_true_duplicate_count": 89,
            "duplicate_external_records_explained": 0,
        },
        benchmark={
            "source_artifact_candidates": 5,
            "total_cohorts": 23,
            "total_conflicts": 23,
            "safe_merge_candidates": 1,
            "blocked_merges": 15,
            "deferred_conflicts": 7,
        },
        manifest={
            "metadata_only": True,
            "audio_downloaded": False,
            "local_library_mutated": False,
            "canonical_graph_mutated": False,
        },
    )

    result = generate_source_quality_report(reports)

    summary = json.loads(Path(result.output_json).read_text(encoding="utf-8"))
    rows = _read_csv(Path(result.output_csv))
    assert result.source_run_count == 2
    assert summary["source_run_count"] == 2
    assert summary["sources"] == ["internet_archive", "jamendo"]
    assert summary["sources_included"] == ["internet_archive", "jamendo"]
    assert summary["output_csv"] == str(
        reports / "source_quality" / "source_quality_by_source.csv"
    )
    assert summary["aggregate_totals"]["input_records"] == 2000
    assert summary["aggregate_totals"]["missing_artist_count"] == 763
    assert summary["aggregate_totals"]["total_conflicts"] == 38
    assert {row["source_name"] for row in rows} == {"jamendo", "internet_archive"}
    jamendo = next(row for row in rows if row["source_name"] == "jamendo")
    assert jamendo["run_label"] == "jamendo_1k"
    assert jamendo["artist_credit_parsed_records"] == "983"
    assert jamendo["release_identity_total_groups"] == "1000"
    assert jamendo["metadata_only"] == "true"
    assert jamendo["audio_downloaded"] == "false"
    assert jamendo["local_library_mutated"] == "false"
    assert jamendo["canonical_graph_mutated"] == "false"


def test_source_quality_report_tolerates_missing_optional_summaries(tmp_path):
    reports = tmp_path / "reports"
    _write_run(
        reports,
        source_name="local_fixture",
        run_label="public_fixture",
        ingestion={
            "input_records": 65,
            "accepted_records": 60,
            "rejected_records": 5,
        },
        manifest={"metadata_only": True},
    )

    result = generate_source_quality_report(reports)

    row = _read_csv(Path(result.output_csv))[0]
    assert row["source_name"] == "local_fixture"
    assert row["run_label"] == "public_fixture"
    assert row["input_records"] == "65"
    assert row["artist_credit_parsed_records"] == "0"
    assert row["release_identity_total_groups"] == "0"
    assert row["total_cohorts"] == "0"
    assert row["metadata_only"] == "true"
    assert row["audio_downloaded"] == ""


def test_source_quality_report_does_not_mutate_source_reports(tmp_path):
    reports = tmp_path / "reports"
    run_dir = _write_run(
        reports,
        source_name="jamendo",
        run_label="jamendo_100",
        ingestion={
            "input_records": 100,
            "accepted_records": 100,
            "rejected_records": 0,
        },
        artist_credit={"parsed_records": 95, "unresolved_count": 5},
        release_identity={"total_identity_groups": 100},
        benchmark={"total_cohorts": 3, "total_conflicts": 3},
        manifest={"metadata_only": True, "audio_downloaded": False},
    )
    before = _file_hashes(run_dir)

    generate_source_quality_report(reports)

    assert _file_hashes(run_dir) == before


def test_source_quality_report_cli_command_is_registered(tmp_path):
    reports = tmp_path / "reports"
    _write_run(
        reports,
        source_name="internet_archive",
        run_label="internet_archive_100",
        ingestion={
            "input_records": 100,
            "accepted_records": 100,
            "rejected_records": 0,
        },
        manifest={
            "metadata_only": True,
            "audio_downloaded": False,
            "local_library_mutated": False,
            "canonical_graph_mutated": False,
        },
    )

    exit_code = main(["source-quality-report", "--out", str(reports)])

    assert exit_code == 0
    assert (reports / "source_quality" / "source_quality_summary.json").exists()
    assert (reports / "source_quality" / "source_quality_by_source.csv").exists()


def _write_run(
    reports: Path,
    *,
    source_name: str,
    run_label: str,
    ingestion: dict | None = None,
    artist_credit: dict | None = None,
    release_identity: dict | None = None,
    benchmark: dict | None = None,
    manifest: dict | None = None,
) -> Path:
    run_dir = reports / "runs" / source_name / run_label
    _write_json(
        run_dir / "run_manifest.json",
        {"source_name": source_name, "run_label": run_label, **(manifest or {})},
    )
    if ingestion is not None:
        _write_json(
            run_dir / "external_metadata_ingestion" / "ingestion_summary.json",
            ingestion,
        )
    if artist_credit is not None:
        _write_json(
            run_dir / "artist_credit_analysis" / "artist_credit_summary.json",
            artist_credit,
        )
    if release_identity is not None:
        _write_json(
            run_dir / "release_identity_analysis" / "release_identity_summary.json",
            release_identity,
        )
    if benchmark is not None:
        _write_json(run_dir / "validation_benchmark" / "benchmark_summary.json", benchmark)
    return run_dir


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _file_hashes(path: Path) -> dict[str, str]:
    return {
        str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }
