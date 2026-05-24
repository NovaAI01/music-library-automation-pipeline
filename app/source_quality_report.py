"""Source quality comparison reports from existing validation run outputs."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_DIRNAME = "source_quality"
SUMMARY_FILENAME = "source_quality_summary.json"
CSV_FILENAME = "source_quality_by_source.csv"

RUN_FIELDS = (
    "source_name",
    "run_label",
    "input_records",
    "accepted_records",
    "rejected_records",
    "missing_artist_count",
    "missing_album_count",
    "missing_title_count",
    "artist_credit_parsed_records",
    "artist_credit_unresolved_records",
    "release_identity_total_groups",
    "release_identity_possible_true_duplicates",
    "release_identity_duplicate_records_explained",
    "source_artifact_candidates",
    "total_cohorts",
    "total_conflicts",
    "safe_merge_candidates",
    "blocked_merges",
    "deferred_conflicts",
    "metadata_only",
    "audio_downloaded",
    "local_library_mutated",
    "canonical_graph_mutated",
)
NUMERIC_FIELDS = RUN_FIELDS[2:19]


@dataclass(frozen=True)
class SourceQualityReportResult:
    report_path: str
    output_json: str
    output_csv: str
    source_run_count: int
    sources: list[str]


class SourceQualityReportError(ValueError):
    """Raised when existing source-quality report inputs are invalid."""


def generate_source_quality_report(
    out_dir: str | Path = "reports",
) -> SourceQualityReportResult:
    """Summarize available validation run outputs without mutating source reports."""

    out_path = Path(out_dir)
    rows = [_source_run_row(run_dir) for run_dir in _iter_run_dirs(out_path)]
    report_dir = out_path / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)

    csv_path = report_dir / CSV_FILENAME
    summary_path = report_dir / SUMMARY_FILENAME
    _write_csv(csv_path, rows)
    sources = sorted({str(row["source_name"]) for row in rows})
    summary = {
        "generated_at": _utc_timestamp(),
        "source_run_count": len(rows),
        "sources": sources,
        "sources_included": sources,
        "aggregate_totals": _aggregate_totals(rows),
        "output_csv": str(csv_path),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return SourceQualityReportResult(
        report_path=str(report_dir),
        output_json=str(summary_path),
        output_csv=str(csv_path),
        source_run_count=len(rows),
        sources=summary["sources"],
    )


def _iter_run_dirs(out_path: Path) -> list[Path]:
    runs_dir = out_path / "runs"
    if not runs_dir.exists():
        return []
    return sorted(
        run_dir
        for source_dir in runs_dir.iterdir()
        if source_dir.is_dir()
        for run_dir in source_dir.iterdir()
        if run_dir.is_dir() and _has_valid_manifest(run_dir)
    )


def _source_run_row(run_dir: Path) -> dict[str, Any]:
    manifest = _read_required_manifest(run_dir / "run_manifest.json")
    ingestion = _read_optional_summary(
        run_dir / "external_metadata_ingestion" / "ingestion_summary.json"
    )
    artist_credit = _read_optional_summary(
        run_dir / "artist_credit_analysis" / "artist_credit_summary.json"
    )
    release_identity = _read_optional_summary(
        run_dir / "release_identity_analysis" / "release_identity_summary.json"
    )
    benchmark = _read_optional_summary(
        run_dir / "validation_benchmark" / "benchmark_summary.json"
    )

    row: dict[str, Any] = {
        "source_name": str(manifest.get("source_name") or run_dir.parent.name),
        "run_label": str(manifest.get("run_label") or run_dir.name),
        "input_records": _int_value(ingestion, "input_records"),
        "accepted_records": _int_value(ingestion, "accepted_records"),
        "rejected_records": _int_value(ingestion, "rejected_records"),
        "missing_artist_count": _int_value(ingestion, "missing_artist_count"),
        "missing_album_count": _int_value(ingestion, "missing_album_count"),
        "missing_title_count": _int_value(ingestion, "missing_title_count"),
        "artist_credit_parsed_records": _int_value(artist_credit, "parsed_records"),
        "artist_credit_unresolved_records": _int_value(
            artist_credit, "unresolved_count"
        ),
        "release_identity_total_groups": _int_value(
            release_identity, "total_identity_groups"
        ),
        "release_identity_possible_true_duplicates": _int_value(
            release_identity, "possible_true_duplicate_count"
        ),
        "release_identity_duplicate_records_explained": _int_value(
            release_identity, "duplicate_external_records_explained"
        ),
        "source_artifact_candidates": _int_value(
            benchmark, "source_artifact_candidates"
        ),
        "total_cohorts": _int_value(benchmark, "total_cohorts"),
        "total_conflicts": _int_value(benchmark, "total_conflicts"),
        "safe_merge_candidates": _int_value(benchmark, "safe_merge_candidates"),
        "blocked_merges": _int_value(benchmark, "blocked_merges"),
        "deferred_conflicts": _int_value(benchmark, "deferred_conflicts"),
        "metadata_only": _bool_or_none(manifest, "metadata_only"),
        "audio_downloaded": _bool_or_none(manifest, "audio_downloaded"),
        "local_library_mutated": _bool_or_none(manifest, "local_library_mutated"),
        "canonical_graph_mutated": _bool_or_none(manifest, "canonical_graph_mutated"),
    }
    return row


def _aggregate_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        field: sum(_coerce_int(row.get(field)) for row in rows)
        for field in NUMERIC_FIELDS
    }


def _has_valid_manifest(run_dir: Path) -> bool:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return False
    _read_required_manifest(manifest_path)
    return True


def _read_required_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SourceQualityReportError(f"Missing required run manifest: {path}")
    return _read_json_object(path)


def _read_optional_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json_object(path)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceQualityReportError(f"Malformed JSON in {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise SourceQualityReportError(f"JSON root must be an object in {path}")
    return data


def _int_value(payload: dict[str, Any], key: str) -> int:
    return _coerce_int(payload.get(key))


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bool_or_none(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: _csv_value(row.get(field)) for field in RUN_FIELDS}
            )


def _csv_value(value: Any) -> str | int:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return ""
    return value


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
