"""Read-only validation benchmark reports for local external metadata datasets."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from app.data_paths import source_external_tracks_csv
from app.external_metadata import validate_source_name
from app.large_scale_validation import (
    ExternalValidationRecord,
    ValidationCohort,
    analyze_external_metadata_records,
)


REPORT_DIRNAME = "validation_benchmark"
SUMMARY_FILENAME = "benchmark_summary.json"
COHORT_DISTRIBUTION_FILENAME = "cohort_distribution.csv"
SEVERITY_DISTRIBUTION_FILENAME = "severity_distribution.csv"
GOVERNANCE_DISTRIBUTION_FILENAME = "governance_distribution.csv"
TOP_FAILURE_COHORTS_FILENAME = "top_failure_cohorts.csv"
TIMING_FILENAME = "benchmark_timing.json"

GOVERNANCE_STATUSES = (
    "safe_to_merge_candidate",
    "blocked_merge",
    "deferred",
    "resolved",
    "none",
)
SEVERITIES = ("high", "medium", "low")
COHORT_DISTRIBUTION_FIELDS = (
    "cohort_type",
    "cohort_count",
    "record_count",
    "percentage_of_dataset",
    "highest_severity",
)
SEVERITY_DISTRIBUTION_FIELDS = ("severity", "count", "percentage")
GOVERNANCE_DISTRIBUTION_FIELDS = ("conflict_status", "count", "percentage")
TOP_FAILURE_FIELDS = (
    "cohort_type",
    "record_count",
    "percentage_of_dataset",
    "severity",
    "recommended_action",
)


@dataclass(frozen=True)
class ValidationBenchmarkResult:
    report_path: str
    source_name: str
    total_records: int
    total_cohorts: int
    total_conflicts: int
    safe_merge_candidates: int
    blocked_merges: int
    deferred_conflicts: int
    duplicate_external_records: int
    source_artifact_candidates: int
    collaboration_string_candidates: int
    malformed_records: int
    benchmark_duration_seconds: float

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "total_records": self.total_records,
            "total_cohorts": self.total_cohorts,
            "total_conflicts": self.total_conflicts,
            "safe_merge_candidates": self.safe_merge_candidates,
            "blocked_merges": self.blocked_merges,
            "deferred_conflicts": self.deferred_conflicts,
            "duplicate_external_records": self.duplicate_external_records,
            "source_artifact_candidates": self.source_artifact_candidates,
            "collaboration_string_candidates": self.collaboration_string_candidates,
            "malformed_records": self.malformed_records,
            "benchmark_duration_seconds": self.benchmark_duration_seconds,
        }


def benchmark_validation(
    source_name: str,
    out_dir: str | Path = "reports",
    data_dir: str | Path | None = None,
) -> ValidationBenchmarkResult:
    """Generate read-only benchmark reports for one local external dataset."""

    source_name = validate_source_name(source_name)
    out_dir = Path(out_dir)
    input_csv = source_external_tracks_csv(source_name, data_dir)
    report_dir = out_dir / REPORT_DIRNAME

    total_start = perf_counter()
    phase_start = perf_counter()
    records = _read_external_records(input_csv)
    ingestion_load_seconds = _elapsed(phase_start)

    phase_start = perf_counter()
    cohorts, _examples = analyze_external_metadata_records(records)
    cohort_analysis_seconds = _elapsed(phase_start)

    phase_start = perf_counter()
    governance_counts = governance_distribution_counts(cohorts, total_records=len(records))
    severity_counts = Counter(cohort.severity for cohort in cohorts)
    governance_analysis_seconds = _elapsed(phase_start)

    phase_start = perf_counter()
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        report_dir / COHORT_DISTRIBUTION_FILENAME,
        COHORT_DISTRIBUTION_FIELDS,
        cohort_distribution_rows(cohorts, total_records=len(records)),
    )
    _write_csv(
        report_dir / SEVERITY_DISTRIBUTION_FILENAME,
        SEVERITY_DISTRIBUTION_FIELDS,
        severity_distribution_rows(severity_counts, total_cohorts=len(cohorts)),
    )
    _write_csv(
        report_dir / GOVERNANCE_DISTRIBUTION_FILENAME,
        GOVERNANCE_DISTRIBUTION_FIELDS,
        governance_distribution_rows(governance_counts),
    )
    _write_csv(
        report_dir / TOP_FAILURE_COHORTS_FILENAME,
        TOP_FAILURE_FIELDS,
        top_failure_cohort_rows(cohorts, total_records=len(records)),
    )
    report_generation_seconds = _elapsed(phase_start)
    total_duration_seconds = _elapsed(total_start)

    timing = {
        "ingestion_load_seconds": ingestion_load_seconds,
        "cohort_analysis_seconds": cohort_analysis_seconds,
        "governance_analysis_seconds": governance_analysis_seconds,
        "report_generation_seconds": report_generation_seconds,
        "total_duration_seconds": total_duration_seconds,
    }
    _write_json(report_dir / TIMING_FILENAME, timing)

    benchmark_counts = _benchmark_counts(cohorts)
    result = ValidationBenchmarkResult(
        report_path=str(report_dir),
        source_name=source_name,
        total_records=len(records),
        total_cohorts=len(cohorts),
        total_conflicts=sum(
            governance_counts[status]
            for status in GOVERNANCE_STATUSES
            if status != "none"
        ),
        safe_merge_candidates=governance_counts["safe_to_merge_candidate"],
        blocked_merges=governance_counts["blocked_merge"],
        deferred_conflicts=governance_counts["deferred"],
        benchmark_duration_seconds=total_duration_seconds,
        **benchmark_counts,
    )
    _write_json(report_dir / SUMMARY_FILENAME, result.to_summary())
    return result


def cohort_distribution_rows(
    cohorts: Iterable[ValidationCohort],
    *,
    total_records: int,
) -> list[dict[str, str]]:
    by_type: dict[str, list[ValidationCohort]] = {}
    for cohort in cohorts:
        by_type.setdefault(cohort.cohort_type, []).append(cohort)
    rows = []
    for cohort_type in sorted(by_type):
        items = by_type[cohort_type]
        record_count = sum(item.record_count for item in items)
        rows.append(
            {
                "cohort_type": cohort_type,
                "cohort_count": str(len(items)),
                "record_count": str(record_count),
                "percentage_of_dataset": _percentage(record_count, total_records),
                "highest_severity": _highest_severity(item.severity for item in items),
            }
        )
    return rows


def severity_distribution_rows(
    severity_counts: Counter[str],
    *,
    total_cohorts: int,
) -> list[dict[str, str]]:
    return [
        {
            "severity": severity,
            "count": str(severity_counts[severity]),
            "percentage": _percentage(severity_counts[severity], total_cohorts),
        }
        for severity in SEVERITIES
    ]


def governance_distribution_counts(
    cohorts: Iterable[ValidationCohort],
    *,
    total_records: int,
) -> Counter[str]:
    counts: Counter[str] = Counter({status: 0 for status in GOVERNANCE_STATUSES})
    cohort_count = 0
    for cohort in cohorts:
        cohort_count += 1
        counts[_governance_status_for(cohort)] += 1
    if cohort_count == 0 and total_records:
        counts["none"] = total_records
    return counts


def governance_distribution_rows(counts: Counter[str]) -> list[dict[str, str]]:
    denominator = sum(counts[status] for status in GOVERNANCE_STATUSES)
    return [
        {
            "conflict_status": status,
            "count": str(counts[status]),
            "percentage": _percentage(counts[status], denominator),
        }
        for status in GOVERNANCE_STATUSES
    ]


def top_failure_cohort_rows(
    cohorts: Iterable[ValidationCohort],
    *,
    total_records: int,
    limit: int = 20,
) -> list[dict[str, str]]:
    ranked = sorted(
        cohorts,
        key=lambda item: (
            -item.record_count,
            _severity_rank(item.severity),
            item.cohort_type,
            item.cohort_key,
        ),
    )
    return [
        {
            "cohort_type": cohort.cohort_type,
            "record_count": str(cohort.record_count),
            "percentage_of_dataset": _percentage(cohort.record_count, total_records),
            "severity": cohort.severity,
            "recommended_action": cohort.recommended_action,
        }
        for cohort in ranked[:limit]
    ]


def _read_external_records(input_csv: Path) -> list[ExternalValidationRecord]:
    if not input_csv.exists():
        return []
    with input_csv.open(newline="", encoding="utf-8") as handle:
        return [
            ExternalValidationRecord.from_row(row)
            for row in csv.DictReader(handle)
        ]


def _benchmark_counts(cohorts: Iterable[ValidationCohort]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for cohort in cohorts:
        counts[cohort.cohort_type] += cohort.record_count
    return {
        "duplicate_external_records": counts["duplicate_external_record"],
        "source_artifact_candidates": counts["source_artifact_candidate"],
        "collaboration_string_candidates": counts["collaboration_string"],
        "malformed_records": counts["malformed_duration"] + counts["malformed_year"],
    }


def _governance_status_for(cohort: ValidationCohort) -> str:
    if cohort.cohort_type in {
        "casing_alias_candidate",
        "album_title_punctuation_variant",
    }:
        return "safe_to_merge_candidate"
    if cohort.severity == "high":
        return "blocked_merge"
    if cohort.severity in {"medium", "low"}:
        return "deferred"
    return "none"


def _highest_severity(severities: Iterable[str]) -> str:
    ordered = sorted(severities, key=_severity_rank)
    return ordered[0] if ordered else "low"


def _severity_rank(severity: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)


def _percentage(count: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.00"
    return f"{(count / denominator) * 100:.2f}"


def _elapsed(start: float) -> float:
    return round(perf_counter() - start, 6)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: Iterable[dict[str, Any]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
