import csv
import hashlib
import json
from pathlib import Path

from app.external_metadata import EXTERNAL_TRACK_FIELDS
from app.main import main
from app.report_runs import create_report_run, resolve_report_out_dir


def test_run_label_path_generation(tmp_path):
    run = create_report_run(
        tmp_path / "reports",
        source_name="MusicBrainz",
        run_label="MusicBrainz 50k",
    )

    assert run.run_root == tmp_path / "reports" / "runs" / "musicbrainz" / "musicbrainz_50k"
    assert run.command_dir("benchmark-validation") == run.run_root / "validation_benchmark"
    assert resolve_report_out_dir(tmp_path / "reports", source_name="local_fixture") == tmp_path / "reports"


def test_cli_without_run_label_preserves_existing_report_path(tmp_path, monkeypatch):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [{"source_record_id": "1", "artist": "Portishead", "album": "Dummy", "title": "Roads"}],
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MUSIC_INTELLIGENCE_DATA_ROOT", raising=False)

    exit_code = main(
        [
            "benchmark-validation",
            "--source",
            "local_fixture",
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "reports" / "validation_benchmark" / "benchmark_summary.json").exists()
    assert not (tmp_path / "reports" / "runs").exists()


def test_run_manifest_accumulates_labeled_validation_commands(tmp_path, monkeypatch):
    input_csv = tmp_path / "input.csv"
    _write_input_csv(
        input_csv,
        [{"source_record_id": "1", "artist": "Massive Attack feat. Horace Andy", "album": "Mezzanine", "title": "Angel"}],
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MUSIC_INTELLIGENCE_DATA_ROOT", raising=False)

    commands = [
        [
            "import-external-metadata",
            "--source",
            "local_fixture",
            "--input",
            str(input_csv),
            "--out",
            str(tmp_path / "reports"),
            "--run-label",
            "local_fixture_smoke",
        ],
        [
            "analyze-artist-credits",
            "--source",
            "local_fixture",
            "--out",
            str(tmp_path / "reports"),
            "--run-label",
            "local_fixture_smoke",
        ],
        [
            "analyze-release-identity",
            "--source",
            "local_fixture",
            "--out",
            str(tmp_path / "reports"),
            "--run-label",
            "local_fixture_smoke",
        ],
        [
            "benchmark-validation",
            "--source",
            "local_fixture",
            "--out",
            str(tmp_path / "reports"),
            "--run-label",
            "local_fixture_smoke",
        ],
    ]

    for command in commands:
        assert main(command) == 0

    run_root = tmp_path / "reports" / "runs" / "local_fixture" / "local_fixture_smoke"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))

    assert manifest["source_name"] == "local_fixture"
    assert manifest["run_label"] == "local_fixture_smoke"
    assert manifest["commands_run"] == [
        "import-external-metadata",
        "analyze-artist-credits",
        "analyze-release-identity",
        "benchmark-validation",
    ]
    assert manifest["report_paths"] == {
        "import-external-metadata": str(run_root / "external_metadata_ingestion"),
        "analyze-artist-credits": str(run_root / "artist_credit_analysis"),
        "analyze-release-identity": str(run_root / "release_identity_analysis"),
        "benchmark-validation": str(run_root / "validation_benchmark"),
    }
    assert manifest["data_root"] == "data"
    assert manifest["metadata_only"] is True
    assert manifest["audio_downloaded"] is False
    assert manifest["local_library_mutated"] is False
    assert manifest["canonical_graph_mutated"] is False


def test_run_label_does_not_change_benchmark_metrics_or_source_data(tmp_path, monkeypatch):
    source_csv = _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            {"source_record_id": "1", "artist": "Portishead", "album": "Dummy", "title": "Roads"},
            {"source_record_id": "2", "artist": "", "album": "", "title": ""},
        ],
    )
    before_hash = _sha256(source_csv)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MUSIC_INTELLIGENCE_DATA_ROOT", raising=False)

    assert main(["benchmark-validation", "--source", "local_fixture", "--out", str(tmp_path / "reports")]) == 0
    assert (
        main(
            [
                "benchmark-validation",
                "--source",
                "local_fixture",
                "--out",
                str(tmp_path / "reports"),
                "--run-label",
                "local_fixture_smoke",
            ]
        )
        == 0
    )

    legacy_summary = _metric_summary(tmp_path / "reports" / "validation_benchmark" / "benchmark_summary.json")
    isolated_summary = _metric_summary(
        tmp_path
        / "reports"
        / "runs"
        / "local_fixture"
        / "local_fixture_smoke"
        / "validation_benchmark"
        / "benchmark_summary.json"
    )

    assert isolated_summary == legacy_summary
    assert _sha256(source_csv) == before_hash


def test_convert_musicbrainz_dump_run_label_writes_isolated_outputs(tmp_path, monkeypatch):
    fixture_dump = Path(__file__).parent / "fixtures" / "musicbrainz_dump"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "convert-musicbrainz-dump",
            "--dump-dir",
            str(fixture_dump),
            "--out",
            str(tmp_path / "reports"),
            "--limit",
            "2",
            "--run-label",
            "musicbrainz_50k",
        ]
    )

    run_root = tmp_path / "reports" / "runs" / "musicbrainz" / "musicbrainz_50k"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert (run_root / "musicbrainz_conversion" / "external_tracks.csv").exists()
    assert (run_root / "musicbrainz_conversion" / "conversion_summary.json").exists()
    assert manifest["report_paths"]["convert-musicbrainz-dump"] == str(run_root / "musicbrainz_conversion")


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


def _write_input_csv(path, rows):
    fieldnames = ["source_record_id", "artist", "album", "title"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _metric_summary(path):
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary.pop("benchmark_duration_seconds", None)
    return summary


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
