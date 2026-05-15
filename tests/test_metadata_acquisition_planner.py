import csv
import json

import pytest

from app.metadata_acquisition_planner import (
    SUPPORTED_ACQUISITION_SOURCES,
    plan_metadata_acquisition,
    validate_acquisition_source,
)
from app.main import main


def test_every_supported_source_generates_metadata_only_plan(tmp_path):
    for source_name in SUPPORTED_ACQUISITION_SOURCES:
        result = plan_metadata_acquisition(
            source_name,
            out_dir=tmp_path / source_name / "reports",
            data_root=tmp_path / source_name / "data",
        )
        plan = _read_json(result.acquisition_plan_path)

        assert plan["source_name"] == source_name
        assert plan["metadata_only"] is True
        assert plan["audio_download_allowed"] is False
        assert plan["raw_dump_target"].endswith(f"raw_dumps/{source_name}")
        assert plan["storage_target"].endswith(f"external_metadata/{source_name}")
        assert plan["cache_target"].endswith(f"cache/{source_name}")


def test_unsupported_source_fails_cleanly():
    with pytest.raises(ValueError, match="unsupported metadata acquisition source"):
        validate_acquisition_source("spotify")


def test_youtube_metadata_is_high_risk(tmp_path):
    result = plan_metadata_acquisition(
        "youtube_metadata",
        out_dir=tmp_path / "reports",
        data_root=tmp_path / "data",
    )
    plan = _read_json(result.acquisition_plan_path)
    risk = _read_json(result.source_risk_assessment_path)

    assert plan["risk_level"] == "high"
    assert risk["risk_level"] == "high"
    assert "not a downloader" in plan["legal_boundary"]
    assert "skip-download" in plan["legal_boundary"]


def test_musicbrainz_is_preferred_first_source(tmp_path):
    result = plan_metadata_acquisition(
        "musicbrainz",
        out_dir=tmp_path / "reports",
        data_root=tmp_path / "data",
    )
    plan = _read_json(result.acquisition_plan_path)

    assert plan["preferred_first_source"] is True
    assert plan["risk_level"] == "low"
    assert plan["expected_normalized_input"].endswith(
        "external_metadata/musicbrainz/raw_musicbrainz.csv"
    )


def test_storage_targets_use_configured_env_root(monkeypatch, tmp_path):
    data_root = tmp_path / "ssd-data-root"
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(data_root))

    result = plan_metadata_acquisition("musicbrainz", out_dir=tmp_path / "reports")
    plan = _read_json(result.acquisition_plan_path)

    assert plan["raw_dump_target"] == str(data_root / "raw_dumps" / "musicbrainz")
    assert plan["storage_target"] == str(
        data_root / "external_metadata" / "musicbrainz"
    )
    assert plan["cache_target"] == str(data_root / "cache" / "musicbrainz")


def test_import_and_benchmark_commands_target_existing_commands(tmp_path):
    result = plan_metadata_acquisition(
        "musicbrainz",
        out_dir=tmp_path / "reports",
        data_root=tmp_path / "data",
    )
    plan = _read_json(result.acquisition_plan_path)

    assert plan["import_command"].startswith(
        "python -m app.main import-external-metadata --source musicbrainz"
    )
    assert "--input" in plan["import_command"]
    assert "raw_musicbrainz.csv" in plan["import_command"]
    assert plan["benchmark_command"] == (
        "python -m app.main benchmark-validation --source musicbrainz --out reports"
    )


def test_reports_are_generated_deterministically(tmp_path):
    kwargs = {
        "source_name": "discogs",
        "out_dir": tmp_path / "reports",
        "data_root": tmp_path / "data",
    }
    first = plan_metadata_acquisition(**kwargs)
    first_plan = _read_text(first.acquisition_plan_path)
    first_steps = _read_text(first.acquisition_steps_path)
    first_risk = _read_text(first.source_risk_assessment_path)

    second = plan_metadata_acquisition(**kwargs)

    assert _read_text(second.acquisition_plan_path) == first_plan
    assert _read_text(second.acquisition_steps_path) == first_steps
    assert _read_text(second.source_risk_assessment_path) == first_risk


def test_cli_writes_expected_report_files(tmp_path):
    exit_code = main(
        [
            "plan-metadata-acquisition",
            "--source",
            "musicbrainz",
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    report_dir = tmp_path / "reports" / "metadata_acquisition"
    assert exit_code == 0
    assert (report_dir / "acquisition_plan.json").exists()
    assert (report_dir / "acquisition_steps.csv").exists()
    assert (report_dir / "source_risk_assessment.json").exists()

    rows = _read_csv(report_dir / "acquisition_steps.csv")
    assert [row["step_number"] for row in rows] == ["1", "2", "3", "4"]


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
