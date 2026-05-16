"""Read-only validation benchmark reports for local external metadata datasets."""

from __future__ import annotations

import csv
import json
import re
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
ARTIST_CREDIT_REPORT_DIRNAME = "artist_credit_analysis"
ARTIST_CREDIT_SUMMARY_FILENAME = "artist_credit_summary.json"
ARTIST_CREDIT_PARSED_FILENAME = "parsed_artist_credits.csv"
RELEASE_IDENTITY_REPORT_DIRNAME = "release_identity_analysis"
RELEASE_IDENTITY_SUMMARY_FILENAME = "release_identity_summary.json"
RELEASE_IDENTITY_GROUPS_FILENAME = "identity_groups.csv"

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
ARTIST_CREDIT_COLLABORATION_RE = re.compile(
    r"(?:\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\bwith\b|\bversus\b|\bvs\.?\b|\sx\s|/|,|\s&\s|\sand\s)",
    re.I,
)
ARTIST_CREDIT_FEATURE_PATTERNS = {
    "feat_artist",
    "ft_artist",
    "featuring_artist",
}
ARTIST_CREDIT_COLLABORATION_PATTERNS = {
    "with_artist",
    "versus_artist",
    "x_collaboration",
    "ampersand_collaboration",
    "comma_collaboration",
    "multi_artist_credit",
}


@dataclass(frozen=True)
class ArtistCreditBenchmarkAnalysis:
    used: bool
    parsed_records: int = 0
    unresolved_records: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    cohorts: tuple[ValidationCohort, ...] = ()


@dataclass(frozen=True)
class ReleaseIdentityBenchmarkAnalysis:
    used: bool
    total_groups: int = 0
    legitimate_appearances: int = 0
    possible_true_duplicates: int = 0
    edition_or_reissue_clusters: int = 0
    compilation_or_multi_release: int = 0
    ambiguous_groups: int = 0
    duplicate_records_explained: int = 0
    duplicate_records_unresolved: int = 0
    cohorts: tuple[ValidationCohort, ...] = ()


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
    artist_credit_analysis_used: bool
    artist_credit_parsed_records: int
    artist_credit_unresolved_records: int
    artist_credit_high_confidence: int
    artist_credit_medium_confidence: int
    artist_credit_low_confidence: int
    release_identity_analysis_used: bool
    release_identity_total_groups: int
    release_identity_legitimate_appearances: int
    release_identity_possible_true_duplicates: int
    release_identity_edition_or_reissue_clusters: int
    release_identity_compilation_or_multi_release: int
    release_identity_ambiguous_groups: int
    release_identity_duplicate_records_explained: int
    release_identity_duplicate_records_unresolved: int
    benchmark_duration_seconds: float

    def to_summary(self) -> dict[str, Any]:
        return {
            "artist_credit_analysis_used": self.artist_credit_analysis_used,
            "artist_credit_high_confidence": self.artist_credit_high_confidence,
            "artist_credit_low_confidence": self.artist_credit_low_confidence,
            "artist_credit_medium_confidence": self.artist_credit_medium_confidence,
            "artist_credit_parsed_records": self.artist_credit_parsed_records,
            "artist_credit_unresolved_records": self.artist_credit_unresolved_records,
            "benchmark_duration_seconds": self.benchmark_duration_seconds,
            "blocked_merges": self.blocked_merges,
            "collaboration_string_candidates": self.collaboration_string_candidates,
            "deferred_conflicts": self.deferred_conflicts,
            "duplicate_external_records": self.duplicate_external_records,
            "malformed_records": self.malformed_records,
            "release_identity_ambiguous_groups": self.release_identity_ambiguous_groups,
            "release_identity_analysis_used": self.release_identity_analysis_used,
            "release_identity_compilation_or_multi_release": self.release_identity_compilation_or_multi_release,
            "release_identity_duplicate_records_explained": self.release_identity_duplicate_records_explained,
            "release_identity_duplicate_records_unresolved": self.release_identity_duplicate_records_unresolved,
            "release_identity_edition_or_reissue_clusters": self.release_identity_edition_or_reissue_clusters,
            "release_identity_legitimate_appearances": self.release_identity_legitimate_appearances,
            "release_identity_possible_true_duplicates": self.release_identity_possible_true_duplicates,
            "release_identity_total_groups": self.release_identity_total_groups,
            "safe_merge_candidates": self.safe_merge_candidates,
            "source_artifact_candidates": self.source_artifact_candidates,
            "source_name": self.source_name,
            "total_records": self.total_records,
            "total_cohorts": self.total_cohorts,
            "total_conflicts": self.total_conflicts,
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
    artist_credit_analysis = _load_artist_credit_analysis(source_name, out_dir)
    if artist_credit_analysis.used:
        cohorts = _with_artist_credit_cohorts(cohorts, artist_credit_analysis)
    release_identity_analysis = _load_release_identity_analysis(source_name, out_dir)
    if release_identity_analysis.used:
        cohorts = _with_release_identity_cohorts(cohorts, release_identity_analysis)
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
        artist_credit_analysis_used=artist_credit_analysis.used,
        artist_credit_parsed_records=artist_credit_analysis.parsed_records,
        artist_credit_unresolved_records=artist_credit_analysis.unresolved_records,
        artist_credit_high_confidence=artist_credit_analysis.high_confidence,
        artist_credit_medium_confidence=artist_credit_analysis.medium_confidence,
        artist_credit_low_confidence=artist_credit_analysis.low_confidence,
        release_identity_analysis_used=release_identity_analysis.used,
        release_identity_total_groups=release_identity_analysis.total_groups,
        release_identity_legitimate_appearances=release_identity_analysis.legitimate_appearances,
        release_identity_possible_true_duplicates=release_identity_analysis.possible_true_duplicates,
        release_identity_edition_or_reissue_clusters=release_identity_analysis.edition_or_reissue_clusters,
        release_identity_compilation_or_multi_release=release_identity_analysis.compilation_or_multi_release,
        release_identity_ambiguous_groups=release_identity_analysis.ambiguous_groups,
        release_identity_duplicate_records_explained=release_identity_analysis.duplicate_records_explained,
        release_identity_duplicate_records_unresolved=release_identity_analysis.duplicate_records_unresolved,
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


def _load_artist_credit_analysis(
    source_name: str,
    out_dir: Path,
) -> ArtistCreditBenchmarkAnalysis:
    report_dir = out_dir / ARTIST_CREDIT_REPORT_DIRNAME
    summary_path = report_dir / ARTIST_CREDIT_SUMMARY_FILENAME
    parsed_path = report_dir / ARTIST_CREDIT_PARSED_FILENAME
    if not summary_path.exists() or not parsed_path.exists():
        return ArtistCreditBenchmarkAnalysis(used=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("source_name") != source_name:
        return ArtistCreditBenchmarkAnalysis(used=False)

    with parsed_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    return ArtistCreditBenchmarkAnalysis(
        used=True,
        parsed_records=_summary_int(summary, "parsed_records"),
        unresolved_records=_summary_int(summary, "unresolved_count"),
        high_confidence=_summary_int(summary, "high_confidence_count"),
        medium_confidence=_summary_int(summary, "medium_confidence_count"),
        low_confidence=_summary_int(summary, "low_confidence_count"),
        cohorts=tuple(_artist_credit_cohorts(rows)),
    )


def _with_artist_credit_cohorts(
    cohorts: Iterable[ValidationCohort],
    artist_credit_analysis: ArtistCreditBenchmarkAnalysis,
) -> list[ValidationCohort]:
    return [
        cohort
        for cohort in cohorts
        if cohort.cohort_type != "collaboration_string"
    ] + list(artist_credit_analysis.cohorts)


def _artist_credit_cohorts(rows: list[dict[str, str]]) -> list[ValidationCohort]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        pattern = row.get("credit_pattern", "")
        confidence_tier = row.get("confidence_tier", "")
        flags = set(_json_list(row.get("parser_flags_json", "[]")))
        featured_artists = _json_list(row.get("featured_artists_json", "[]"))
        collaborating_artists = _json_list(row.get("collaborating_artists_json", "[]"))
        is_unresolved = pattern == "unknown_or_ambiguous" or not row.get("primary_artist", "")
        is_featured = pattern in ARTIST_CREDIT_FEATURE_PATTERNS or bool(featured_artists)
        is_collaboration = (
            pattern in ARTIST_CREDIT_COLLABORATION_PATTERNS
            or bool(collaborating_artists)
        )
        is_ambiguous_group = bool(flags & {"possible_group_name", "ambiguous_separator"})
        is_relevant = (
            is_unresolved
            or is_featured
            or is_collaboration
            or is_ambiguous_group
            or _artist_credit_has_collaboration_syntax(row)
        )

        if is_relevant and row.get("primary_artist", "") and confidence_tier == "high":
            counts[("artist_credit_parsed_high_confidence", "all", "low")] += 1
        if is_relevant and row.get("primary_artist", "") and confidence_tier == "medium":
            counts[("artist_credit_parsed_medium_confidence", "all", "medium")] += 1
        if is_unresolved:
            severity = "high" if confidence_tier == "low" else "medium"
            counts[("artist_credit_unresolved", confidence_tier or "unknown", severity)] += 1
        if is_featured:
            counts[("artist_credit_featured", "all", "medium")] += 1
        if is_collaboration:
            counts[("artist_credit_collaboration", "all", "medium")] += 1
        if is_ambiguous_group:
            counts[("artist_credit_ambiguous_group", "all", "medium")] += 1

    return [
        ValidationCohort(
            cohort_key=f"{cohort_type}:{cohort_key}",
            cohort_type=cohort_type,
            record_count=count,
            severity=severity,
            recommended_action=_artist_credit_recommended_action(cohort_type),
            rationale=_artist_credit_rationale(cohort_type),
        )
        for (cohort_type, cohort_key, severity), count in sorted(counts.items())
        if count
    ]


def _artist_credit_has_collaboration_syntax(row: dict[str, str]) -> bool:
    raw_artist = row.get("raw_artist", "")
    title = row.get("source_title", "")
    return bool(
        ARTIST_CREDIT_COLLABORATION_RE.search(raw_artist)
        or ARTIST_CREDIT_COLLABORATION_RE.search(title)
    )


def _artist_credit_recommended_action(cohort_type: str) -> str:
    actions = {
        "artist_credit_parsed_high_confidence": "Treat as parser-explained artist credit evidence; do not merge automatically.",
        "artist_credit_parsed_medium_confidence": "Review parsed collaboration evidence before graph integration.",
        "artist_credit_unresolved": "Keep blocked from canonical artist promotion until parser or human review resolves it.",
        "artist_credit_featured": "Review as featured-artist role evidence before graph integration.",
        "artist_credit_collaboration": "Review as collaboration role evidence before graph integration.",
        "artist_credit_ambiguous_group": "Review as possible group-name ambiguity before splitting artists.",
    }
    return actions[cohort_type]


def _artist_credit_rationale(cohort_type: str) -> str:
    rationales = {
        "artist_credit_parsed_high_confidence": "Artist-credit parser explained collaboration-like syntax with high confidence.",
        "artist_credit_parsed_medium_confidence": "Artist-credit parser explained collaboration-like syntax with medium confidence.",
        "artist_credit_unresolved": "Artist-credit parser could not safely identify primary and related artists.",
        "artist_credit_featured": "Artist credit contains explicit featured-artist role evidence.",
        "artist_credit_collaboration": "Artist credit contains parsed collaborator role evidence.",
        "artist_credit_ambiguous_group": "Artist credit may be a canonical group name rather than a collaboration.",
    }
    return rationales[cohort_type]


def _summary_int(summary: dict[str, Any], key: str) -> int:
    value = summary.get(key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _load_release_identity_analysis(
    source_name: str,
    out_dir: Path,
) -> ReleaseIdentityBenchmarkAnalysis:
    report_dir = out_dir / RELEASE_IDENTITY_REPORT_DIRNAME
    summary_path = report_dir / RELEASE_IDENTITY_SUMMARY_FILENAME
    groups_path = report_dir / RELEASE_IDENTITY_GROUPS_FILENAME
    if not summary_path.exists() or not groups_path.exists():
        return ReleaseIdentityBenchmarkAnalysis(used=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("source_name") != source_name:
        return ReleaseIdentityBenchmarkAnalysis(used=False)

    with groups_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    return ReleaseIdentityBenchmarkAnalysis(
        used=True,
        total_groups=_summary_int(summary, "total_identity_groups"),
        legitimate_appearances=_summary_int(summary, "legitimate_release_appearance_count"),
        possible_true_duplicates=_summary_int(summary, "possible_true_duplicate_count"),
        edition_or_reissue_clusters=_summary_int(summary, "edition_or_reissue_cluster_count"),
        compilation_or_multi_release=_summary_int(summary, "compilation_or_multi_release_appearance_count"),
        ambiguous_groups=_summary_int(summary, "ambiguous_identity_group_count"),
        duplicate_records_explained=_summary_int(summary, "duplicate_external_records_explained"),
        duplicate_records_unresolved=_summary_int(summary, "duplicate_external_records_unresolved"),
        cohorts=tuple(_release_identity_cohorts(rows, summary)),
    )


def _with_release_identity_cohorts(
    cohorts: Iterable[ValidationCohort],
    release_identity_analysis: ReleaseIdentityBenchmarkAnalysis,
) -> list[ValidationCohort]:
    return [
        cohort
        for cohort in cohorts
        if cohort.cohort_type != "duplicate_external_record"
    ] + list(release_identity_analysis.cohorts)


def _release_identity_cohorts(
    rows: list[dict[str, str]],
    summary: dict[str, Any],
) -> list[ValidationCohort]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        classification = row.get("classification", "")
        record_count = _row_int(row, "record_count")
        if record_count <= 1:
            continue
        cohort_type = _release_identity_cohort_type(classification)
        if not cohort_type:
            continue
        counts[(cohort_type, "all", _release_identity_severity(cohort_type))] += record_count

    unresolved_count = _summary_int(summary, "duplicate_external_records_unresolved")
    ambiguous_count = sum(
        count
        for (cohort_type, _cohort_key, _severity), count in counts.items()
        if cohort_type == "release_identity_ambiguous"
    )
    unresolved_remainder = max(0, unresolved_count - ambiguous_count)
    if unresolved_remainder:
        counts[("release_identity_unresolved_duplicate_like", "all", "high")] += unresolved_remainder

    return [
        ValidationCohort(
            cohort_key=f"{cohort_type}:{cohort_key}",
            cohort_type=cohort_type,
            record_count=count,
            severity=severity,
            recommended_action=_release_identity_recommended_action(cohort_type),
            rationale=_release_identity_rationale(cohort_type),
        )
        for (cohort_type, cohort_key, severity), count in sorted(counts.items())
        if count
    ]


def _release_identity_cohort_type(classification: str) -> str:
    mapping = {
        "legitimate_release_appearance": "release_identity_legitimate_appearance",
        "possible_true_duplicate": "release_identity_possible_true_duplicate",
        "edition_or_reissue_cluster": "release_identity_edition_or_reissue",
        "compilation_or_multi_release_appearance": "release_identity_compilation_or_multi_release",
        "ambiguous_identity_cluster": "release_identity_ambiguous",
    }
    return mapping.get(classification, "")


def _release_identity_severity(cohort_type: str) -> str:
    if cohort_type == "release_identity_legitimate_appearance":
        return "low"
    if cohort_type in {
        "release_identity_edition_or_reissue",
        "release_identity_compilation_or_multi_release",
    }:
        return "medium"
    return "high"


def _release_identity_recommended_action(cohort_type: str) -> str:
    actions = {
        "release_identity_legitimate_appearance": "Treat as release-aware duplicate evidence; do not remove or merge automatically.",
        "release_identity_possible_true_duplicate": "Review as possible true duplicate metadata before any remediation.",
        "release_identity_edition_or_reissue": "Preserve edition or reissue context before duplicate interpretation.",
        "release_identity_compilation_or_multi_release": "Preserve compilation or multi-release context before duplicate interpretation.",
        "release_identity_ambiguous": "Keep blocked from duplicate remediation until identity ambiguity is resolved.",
        "release_identity_unresolved_duplicate_like": "Keep unresolved duplicate-like evidence visible for manual review.",
    }
    return actions[cohort_type]


def _release_identity_rationale(cohort_type: str) -> str:
    rationales = {
        "release_identity_legitimate_appearance": "Release identity analysis explained duplicate-like rows as the same recording across releases.",
        "release_identity_possible_true_duplicate": "Release identity analysis found duplicate-like rows without clear different release evidence.",
        "release_identity_edition_or_reissue": "Release identity analysis found edition, remaster, deluxe, or reissue appearances.",
        "release_identity_compilation_or_multi_release": "Release identity analysis found compilation, collection, soundtrack, or many-release appearances.",
        "release_identity_ambiguous": "Release identity analysis found weak or conflicting identity evidence.",
        "release_identity_unresolved_duplicate_like": "Duplicate-like records remain unresolved after release identity analysis.",
    }
    return rationales[cohort_type]


def _row_int(row: dict[str, Any], key: str) -> int:
    value = row.get(key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
