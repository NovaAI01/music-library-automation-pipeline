"""Plan-first acquisition reports for external metadata-only datasets."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.data_paths import (
    DATA_ROOT_ENV_VAR,
    cache_root,
    raw_dumps_root,
    source_metadata_dir,
)


SUPPORTED_ACQUISITION_SOURCES = (
    "musicbrainz",
    "discogs",
    "internet_archive",
    "jamendo",
    "youtube_metadata",
)

REPORT_DIRNAME = "metadata_acquisition"
PLAN_FILENAME = "acquisition_plan.json"
STEPS_FILENAME = "acquisition_steps.csv"
RISK_FILENAME = "source_risk_assessment.json"

STEP_FIELDS = (
    "step_number",
    "source_name",
    "phase",
    "action",
    "target_path",
    "command",
    "safety_boundary",
)


@dataclass(frozen=True)
class MetadataAcquisitionResult:
    source_name: str
    report_path: str
    acquisition_plan_path: str
    acquisition_steps_path: str
    source_risk_assessment_path: str
    storage_target: str
    raw_dump_target: str
    cache_target: str
    risk_level: str


def plan_metadata_acquisition(
    source_name: str,
    out_dir: str | Path = "reports",
    data_root: str | Path | None = None,
) -> MetadataAcquisitionResult:
    """Write deterministic metadata-only acquisition planning reports."""

    source_name = validate_acquisition_source(source_name)
    profile = _source_profiles()[source_name]

    raw_dump_target = raw_dumps_root(data_root) / source_name
    storage_target = source_metadata_dir(source_name, data_root)
    source_cache_target = cache_root(data_root) / source_name
    raw_dump_target.mkdir(parents=True, exist_ok=True)
    storage_target.mkdir(parents=True, exist_ok=True)
    source_cache_target.mkdir(parents=True, exist_ok=True)

    plan = _build_plan(
        source_name=source_name,
        profile=profile,
        raw_dump_target=raw_dump_target,
        storage_target=storage_target,
        cache_target=source_cache_target,
        use_env_var_command=data_root is None and bool(os.environ.get(DATA_ROOT_ENV_VAR)),
    )
    steps = _build_steps(plan, profile)
    risk_assessment = _build_risk_assessment(plan, profile)

    report_dir = Path(out_dir) / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    plan_path = report_dir / PLAN_FILENAME
    steps_path = report_dir / STEPS_FILENAME
    risk_path = report_dir / RISK_FILENAME

    _write_json(plan_path, plan)
    _write_csv(steps_path, STEP_FIELDS, steps)
    _write_json(risk_path, risk_assessment)

    return MetadataAcquisitionResult(
        source_name=source_name,
        report_path=str(report_dir),
        acquisition_plan_path=str(plan_path),
        acquisition_steps_path=str(steps_path),
        source_risk_assessment_path=str(risk_path),
        storage_target=plan["storage_target"],
        raw_dump_target=plan["raw_dump_target"],
        cache_target=plan["cache_target"],
        risk_level=plan["risk_level"],
    )


def validate_acquisition_source(source_name: str) -> str:
    normalized = str(source_name or "").strip().casefold()
    if normalized not in SUPPORTED_ACQUISITION_SOURCES:
        supported = ", ".join(SUPPORTED_ACQUISITION_SOURCES)
        raise ValueError(
            f"unsupported metadata acquisition source: {normalized}. Supported: {supported}"
        )
    return normalized


def _build_plan(
    *,
    source_name: str,
    profile: dict[str, Any],
    raw_dump_target: Path,
    storage_target: Path,
    cache_target: Path,
    use_env_var_command: bool,
) -> dict[str, Any]:
    normalized_input = storage_target / profile["normalized_filename"]
    command_input = _command_input_path(
        source_name,
        profile["normalized_filename"],
        normalized_input,
        use_env_var_command=use_env_var_command,
    )
    import_command = (
        "python -m app.main import-external-metadata "
        f"--source {source_name} "
        f"--input {command_input} "
        "--out reports"
    )
    benchmark_command = (
        "python -m app.main benchmark-validation "
        f"--source {source_name} "
        "--out reports"
    )

    plan = {
        "source_name": source_name,
        "acquisition_type": profile["acquisition_type"],
        "metadata_only": True,
        "audio_download_allowed": False,
        "requires_credentials": profile["requires_credentials"],
        "expected_format": profile["expected_format"],
        "expected_scale": profile["expected_scale"],
        "legal_boundary": profile["legal_boundary"],
        "storage_target": str(storage_target),
        "raw_dump_target": str(raw_dump_target),
        "cache_target": str(cache_target),
        "expected_normalized_input": str(normalized_input),
        "import_command": import_command,
        "benchmark_command": benchmark_command,
        "risk_level": profile["risk_level"],
        "risk_notes": profile["risk_notes"],
    }
    if profile.get("preferred_first_source"):
        plan["preferred_first_source"] = True
    return plan


def _build_steps(
    plan: dict[str, Any],
    profile: dict[str, Any],
) -> list[dict[str, str]]:
    source_name = plan["source_name"]
    return [
        {
            "step_number": "1",
            "source_name": source_name,
            "phase": "prepare",
            "action": profile["preparation_step"],
            "target_path": plan["raw_dump_target"],
            "command": "",
            "safety_boundary": "Manual metadata-only preparation; no audio download, API call, credentials, or library DB mutation.",
        },
        {
            "step_number": "2",
            "source_name": source_name,
            "phase": "normalize",
            "action": profile["normalization_step"],
            "target_path": plan["expected_normalized_input"],
            "command": "",
            "safety_boundary": "Preprocess outside planner v1 into the documented ingestion schema before import.",
        },
        {
            "step_number": "3",
            "source_name": source_name,
            "phase": "import",
            "action": "Import the prepared metadata file with the existing metadata-only ingestion command.",
            "target_path": plan["storage_target"],
            "command": plan["import_command"],
            "safety_boundary": "Imports external metadata records only; does not download audio or mutate the local library DB.",
        },
        {
            "step_number": "4",
            "source_name": source_name,
            "phase": "benchmark",
            "action": "Run the existing read-only validation benchmark for the imported source.",
            "target_path": "reports/validation_benchmark",
            "command": plan["benchmark_command"],
            "safety_boundary": "Benchmarking reads local external metadata and writes reports only.",
        },
    ]


def _build_risk_assessment(
    plan: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_name": plan["source_name"],
        "risk_level": plan["risk_level"],
        "metadata_only": plan["metadata_only"],
        "audio_download_allowed": plan["audio_download_allowed"],
        "requires_credentials": plan["requires_credentials"],
        "primary_risks": profile["primary_risks"],
        "risk_notes": plan["risk_notes"],
        "legal_boundary": plan["legal_boundary"],
        "mitigations": profile["mitigations"],
    }


def _source_profiles() -> dict[str, dict[str, Any]]:
    return {
        "musicbrainz": {
            "acquisition_type": "metadata dump or metadata CSV preparation",
            "requires_credentials": False,
            "expected_format": "MusicBrainz metadata dump prepared as CSV",
            "expected_scale": "large open metadata catalog",
            "legal_boundary": "Use MusicBrainz metadata dumps or prepared metadata CSV only; no audio files.",
            "normalized_filename": "raw_musicbrainz.csv",
            "risk_level": "low",
            "risk_notes": "Preferred first source because it is metadata-centric, broadly reusable, and has low product risk when handled as local dumps.",
            "preferred_first_source": True,
            "preparation_step": "Place MusicBrainz metadata dump exports or manually prepared metadata CSV files under raw_dumps/musicbrainz/.",
            "normalization_step": "Prepare external_metadata/musicbrainz/raw_musicbrainz.csv for the existing importer.",
            "primary_risks": ["schema mapping drift", "large local files"],
            "mitigations": ["keep dumps outside the repository", "normalize to the existing external metadata schema"],
        },
        "discogs": {
            "acquisition_type": "metadata dump only",
            "requires_credentials": False,
            "expected_format": "Discogs XML dump preprocessed to CSV outside app v1",
            "expected_scale": "large release and artist metadata dump",
            "legal_boundary": "Use metadata dumps only; no audio, marketplace, purchase, scraping, or checkout workflow.",
            "normalized_filename": "raw_discogs.csv",
            "risk_level": "medium",
            "risk_notes": "Medium risk because XML dump preprocessing and marketplace-adjacent identifiers need clear separation from purchase workflows.",
            "preparation_step": "Place Discogs metadata dump files under raw_dumps/discogs/ without marketplace or purchase artifacts.",
            "normalization_step": "Preprocess XML/CSV outside app v1 into external_metadata/discogs/raw_discogs.csv.",
            "primary_risks": ["dump license constraints", "marketplace workflow confusion", "large XML preprocessing"],
            "mitigations": ["metadata dump only", "no marketplace actions", "preprocess outside planner v1"],
        },
        "internet_archive": {
            "acquisition_type": "metadata API/export plan only",
            "requires_credentials": False,
            "expected_format": "Internet Archive item metadata export prepared as CSV",
            "expected_scale": "large item metadata export",
            "legal_boundary": "Use metadata exports only; do not download files, audio, derivatives, or media assets.",
            "normalized_filename": "raw_internet_archive.csv",
            "risk_level": "medium",
            "risk_notes": "Medium risk because item metadata can point at downloadable media; planner v1 must preserve a no-file-download boundary.",
            "preparation_step": "Place manually acquired Internet Archive metadata exports under raw_dumps/internet_archive/.",
            "normalization_step": "Prepare external_metadata/internet_archive/raw_internet_archive.csv from metadata fields only.",
            "primary_risks": ["metadata records can reference files", "collection-specific rights variance"],
            "mitigations": ["metadata API/export only", "no file or audio download", "retain rights notes in raw payloads"],
        },
        "jamendo": {
            "acquisition_type": "metadata API plan only",
            "requires_credentials": False,
            "expected_format": "Jamendo metadata export prepared as CSV",
            "expected_scale": "medium to large catalog metadata export",
            "legal_boundary": "Plan for metadata fields only; credentials may be optional or future, and audio download is not allowed.",
            "normalized_filename": "raw_jamendo.csv",
            "risk_level": "low-to-medium",
            "risk_notes": "Low-to-medium risk because the source is music-focused but planner v1 avoids API calls, credentials, and audio download.",
            "preparation_step": "Place manually prepared Jamendo metadata exports under raw_dumps/jamendo/.",
            "normalization_step": "Prepare external_metadata/jamendo/raw_jamendo.csv from metadata fields only.",
            "primary_risks": ["future credential handling", "license interpretation drift"],
            "mitigations": ["no credentials required in v1", "metadata-only plan", "no audio download"],
        },
        "youtube_metadata": {
            "acquisition_type": "metadata-only export plan with skip-download boundary",
            "requires_credentials": False,
            "expected_format": "YouTube metadata JSON/CSV export prepared as CSV",
            "expected_scale": "large channel, playlist, or search metadata export",
            "legal_boundary": "Metadata-only with explicit skip-download style operation; this is not a downloader and must not fetch audio, video, thumbnails, or media streams.",
            "normalized_filename": "raw_youtube_metadata.csv",
            "risk_level": "high",
            "risk_notes": "Highest identity and product risk because uploader names, unofficial uploads, covers, and platform metadata can be mistaken for canonical artist or release facts.",
            "preparation_step": "Place metadata-only YouTube exports under raw_dumps/youtube_metadata/ with skip-download style provenance notes.",
            "normalization_step": "Prepare external_metadata/youtube_metadata/raw_youtube_metadata.csv without media paths or downloader outputs.",
            "primary_risks": ["uploader identity pollution", "unofficial upload metadata", "product boundary drift toward downloader behavior"],
            "mitigations": ["explicitly not a downloader", "skip-download style boundary", "no media files, thumbnails, or stream URLs"],
        },
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, str]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _command_input_path(
    source_name: str,
    normalized_filename: str,
    fallback_path: Path,
    *,
    use_env_var_command: bool,
) -> str:
    if use_env_var_command:
        return (
            f"${DATA_ROOT_ENV_VAR}/external_metadata/{source_name}/"
            f"{normalized_filename}"
        )
    return str(fallback_path)
