import csv
import json
import subprocess
from pathlib import Path

from app.external_metadata import INPUT_FIELDS, import_external_metadata
from app.main import main


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "examples" / "fixture_library"
FIXTURE_CSV = FIXTURE_DIR / "external_metadata_fixture.csv"
DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "public-fixture-validation.md"


def test_public_fixture_csv_exists_and_has_external_track_columns():
    assert FIXTURE_CSV.exists()
    rows = _read_fixture_rows()
    assert 50 <= len(rows) <= 100
    assert set(INPUT_FIELDS).issubset(rows[0].keys())


def test_public_fixture_contains_required_cohort_patterns():
    rows = _read_fixture_rows()
    text = "\n".join(
        " ".join(row.get(field, "") for field in ("artist", "album", "title", "label", "raw_payload_json"))
        for row in rows
    ).casefold()

    assert "north harbor" in text and "north harbor".upper().casefold() in text
    assert "signal-fires" in text or "transit-lines" in text
    assert "feat." in text and "featuring" in text
    assert " with " in text and " x " in text and " vs." in text
    assert "roadburners" in text
    assert "remastered" in text and "deluxe edition" in text
    assert "explicit" in text and "clean" in text and "radio edit" in text
    assert "uploader channel" in text and "topic" in text
    assert "possible_true_duplicate" in text and "legitimate_release_appearance" in text
    assert "rejected_bad_year" in text and "rejected_bad_duration" in text and "{bad json" in text


def test_public_fixture_import_accepts_and_rejects_expected_rows(tmp_path):
    result = import_external_metadata(
        "local_fixture",
        FIXTURE_CSV,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    assert result.input_records == len(_read_fixture_rows())
    assert result.accepted_records > 0
    assert result.rejected_records >= 4
    assert result.missing_artist_count > 0
    assert result.missing_album_count > 0
    rejected = _read_csv(tmp_path / "reports" / "external_metadata_ingestion" / "rejected_records.csv")
    errors = "\n".join(row["error"] for row in rejected)
    assert "at least one of artist" in errors
    assert "release_year must be an integer or empty" in errors
    assert "duration_seconds must be an integer or empty" in errors
    assert "raw_payload_json must be valid JSON" in errors


def test_public_fixture_validation_docs_reference_valid_commands():
    doc = DOC_PATH.read_text(encoding="utf-8")
    expected_commands = [
        "python -m app.main import-external-metadata",
        "--input examples/fixture_library/external_metadata_fixture.csv",
        "python -m app.main analyze-artist-credits",
        "python -m app.main analyze-release-identity",
        "python -m app.main benchmark-validation",
        "--source local_fixture",
        "--run-label public_fixture",
        "reports/runs/local_fixture/public_fixture/",
    ]
    for command in expected_commands:
        assert command in doc
    assert "download audio" in doc
    assert "API credentials" in doc


def test_no_audio_or_media_files_exist_under_public_fixture():
    forbidden_suffixes = {
        ".aac",
        ".aiff",
        ".alac",
        ".flac",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
        ".wma",
    }
    media_files = [
        path
        for path in FIXTURE_DIR.rglob("*")
        if path.is_file() and path.suffix.casefold() in forbidden_suffixes
    ]
    assert media_files == []


def test_generated_public_fixture_run_path_is_ignored_or_not_tracked():
    run_path = "reports/runs/local_fixture/public_fixture/run_manifest.json"
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", run_path],
        cwd=FIXTURE_DIR.parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", run_path],
        cwd=FIXTURE_DIR.parents[1],
        check=False,
    )

    assert tracked.returncode != 0 or ignored.returncode == 0


def test_public_fixture_command_sequence_with_temp_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(FIXTURE_DIR.parents[1])
    monkeypatch.setenv("MUSIC_INTELLIGENCE_DATA_ROOT", str(tmp_path / "data"))
    out_dir = tmp_path / "reports"
    commands = [
        [
            "import-external-metadata",
            "--source",
            "local_fixture",
            "--input",
            str(FIXTURE_CSV),
            "--out",
            str(out_dir),
            "--run-label",
            "public_fixture",
        ],
        [
            "analyze-artist-credits",
            "--source",
            "local_fixture",
            "--out",
            str(out_dir),
            "--run-label",
            "public_fixture",
        ],
        [
            "analyze-release-identity",
            "--source",
            "local_fixture",
            "--out",
            str(out_dir),
            "--run-label",
            "public_fixture",
        ],
        [
            "benchmark-validation",
            "--source",
            "local_fixture",
            "--out",
            str(out_dir),
            "--run-label",
            "public_fixture",
        ],
    ]

    for command in commands:
        assert main(command) == 0

    run_root = out_dir / "runs" / "local_fixture" / "public_fixture"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    ingestion = json.loads((run_root / "external_metadata_ingestion" / "ingestion_summary.json").read_text())
    benchmark = json.loads((run_root / "validation_benchmark" / "benchmark_summary.json").read_text())

    assert manifest["metadata_only"] is True
    assert manifest["audio_downloaded"] is False
    assert manifest["local_library_mutated"] is False
    assert manifest["canonical_graph_mutated"] is False
    assert ingestion["accepted_records"] > 0
    assert ingestion["rejected_records"] > 0
    assert benchmark["artist_credit_analysis_used"] is True
    assert benchmark["release_identity_analysis_used"] is True
    assert benchmark["safe_merge_candidates"] > 0
    assert benchmark["blocked_merges"] > 0
    assert benchmark["deferred_conflicts"] > 0


def _read_fixture_rows():
    return _read_csv(FIXTURE_CSV)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
