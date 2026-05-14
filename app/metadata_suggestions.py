"""Review-only metadata cleanup suggestions from plan and audit evidence."""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from app.album_cohesion import album_cohesion_by_file
from app.evidence_reliability import score_evidence
from app.normalization_knowledge import influence_suggestion, rule_lookup_by_signature
from app.review_decisions import suggestion_key_for


SUGGESTION_HEADERS: tuple[str, ...] = (
    "suggestion_key",
    "file_path",
    "field",
    "current_value",
    "proposed_value",
    "suggestion_type",
    "confidence",
    "rationale",
    "reliability_score",
    "reliability_flags",
    "reliability_rationale",
    "requires_human_review",
    "source_evidence",
)
SUPPORTED_SUGGESTION_TYPES: tuple[str, ...] = (
    "title_cleanup",
    "artist_casing",
    "junk_suffix_removal",
    "separator_cleanup",
    "missing_album",
    "missing_album_artist",
    "duplicate_whitespace_cleanup",
)

_DUPLICATE_WHITESPACE_RE = re.compile(r"\s{2,}")
_JUNK_SUFFIX_RE = re.compile(
    r"\s*(?:"
    r"\[[A-Za-z0-9_-]{8,}\]"
    r"|\((?:official\s+(?:audio|video|visualizer)|audio|video|hd|4k|lyrics?|explicit)\)"
    r"|\[(?:official\s+(?:audio|video|visualizer)|audio|video|hd|4k|lyrics?|explicit)\]"
    r"|(?:official\s+(?:audio|video|visualizer)|audio|video|hd|4k)"
    r")\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MetadataSuggestion:
    suggestion_key: str
    file_path: str
    field: str
    current_value: str
    proposed_value: str
    suggestion_type: str
    confidence: str
    rationale: str
    requires_human_review: bool
    source_evidence: list[str]
    reliability_score: float = 0.0
    reliability_flags: list[str] | None = None
    reliability_rationale: list[str] | None = None


@dataclass(frozen=True)
class MetadataSuggestionResult:
    report_path: str
    total_suggestions: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    requires_human_review_count: int
    ai_enrichment_used: bool


def generate_metadata_suggestions(
    *,
    metadata_plan_path: str | Path,
    metadata_audit_dir: str | Path,
    out_dir: str | Path = "reports",
    db_path: str | Path | None = None,
) -> MetadataSuggestionResult:
    """Generate review-only metadata suggestions from existing report evidence."""

    plan_rows = _read_csv(_resolve_plan_path(Path(metadata_plan_path).expanduser()))
    audit_dir = Path(metadata_audit_dir).expanduser()
    audit_evidence = _read_audit_evidence(audit_dir)
    suggestions = _suggestions_from_rows(plan_rows, audit_evidence)
    suggestions = _with_normalization_knowledge(suggestions, db_path=db_path)
    suggestions = _with_album_cohesion_evidence(suggestions, reports_dir=audit_dir.parent)
    suggestions = _with_reliability_evidence(suggestions, reports_dir=audit_dir.parent)

    ai_enrichment_used = False
    if os.environ.get("OPENAI_API_KEY"):
        enriched = [_with_enriched_rationale(suggestion) for suggestion in suggestions]
        ai_enrichment_used = enriched != suggestions
        suggestions = enriched

    report_dir = Path(out_dir).expanduser() / "metadata_suggestions"
    report_dir.mkdir(parents=True, exist_ok=True)

    suggestion_dicts = [asdict(suggestion) for suggestion in suggestions]
    suggestion_csv_rows = [_suggestion_csv_payload(suggestion) for suggestion in suggestions]
    summary = _summary(suggestions, ai_enrichment_used=ai_enrichment_used)

    _write_json(report_dir / "metadata_suggestions.json", {"suggestions": suggestion_dicts})
    _write_csv(report_dir / "metadata_suggestions.csv", SUGGESTION_HEADERS, suggestion_csv_rows)
    _write_json(report_dir / "metadata_suggestion_summary.json", summary)

    return MetadataSuggestionResult(report_path=str(report_dir), **summary)


def _suggestions_from_rows(
    plan_rows: Iterable[dict[str, str]],
    audit_evidence: dict[tuple[str, str], list[dict[str, str]]],
) -> list[MetadataSuggestion]:
    suggestions: list[MetadataSuggestion] = []
    for row in plan_rows:
        path = row.get("path", "") or row.get("file_path", "")
        field = row.get("field", "")
        current_value = row.get("current_value", "")
        proposed_value = row.get("proposed_value", "")
        if not path or not field or proposed_value == "":
            continue

        evidence = audit_evidence.get((path, field), [])
        suggestion_type = _suggestion_type(field, current_value, proposed_value, evidence)
        if suggestion_type not in SUPPORTED_SUGGESTION_TYPES:
            continue

        source_evidence = _source_evidence(row, evidence)
        confidence = _confidence(current_value, proposed_value, evidence)
        suggestion_key = suggestion_key_for(
            file_path=path,
            field=field,
            current_value=current_value,
            proposed_value=proposed_value,
            suggestion_type=suggestion_type,
        )
        suggestions.append(
            MetadataSuggestion(
                suggestion_key=suggestion_key,
                file_path=path,
                field=field,
                current_value=current_value,
                proposed_value=proposed_value,
                suggestion_type=suggestion_type,
                confidence=confidence,
                rationale=_rationale(
                    suggestion_type=suggestion_type,
                    confidence=confidence,
                    plan_reason=row.get("reason", ""),
                    evidence=evidence,
                ),
                requires_human_review=True,
                source_evidence=source_evidence,
            )
        )
    return sorted(suggestions, key=lambda item: (item.file_path, item.field, item.suggestion_type))


def _suggestion_type(
    field: str,
    current_value: str,
    proposed_value: str,
    evidence: list[dict[str, str]],
) -> str | None:
    issue_types = {item.get("issue_type", "") for item in evidence}
    group_issues = " ".join(item.get("issue_types", "") for item in evidence)
    if field == "album" and not current_value:
        return "missing_album"
    if field == "album_artist" and not current_value:
        return "missing_album_artist"
    if "duplicate_whitespace" in issue_types or _DUPLICATE_WHITESPACE_RE.search(current_value):
        return "duplicate_whitespace_cleanup"
    if "probable_junk_suffix" in issue_types or _JUNK_SUFFIX_RE.search(current_value):
        return "junk_suffix_removal"
    if (
        "separator_symbol" in issue_types
        or "separator_inconsistency" in group_issues
        or _normalizes_separators(current_value, proposed_value)
    ):
        return "separator_cleanup"
    if field == "artist" and current_value.casefold() == proposed_value.casefold():
        return "artist_casing"
    if field == "title":
        return "title_cleanup"
    return None


def _confidence(
    current_value: str,
    proposed_value: str,
    evidence: list[dict[str, str]],
) -> str:
    issue_types = {item.get("issue_type", "") for item in evidence}
    has_conflict = any(item.get("source") in {"inconsistent_artists", "inconsistent_titles"} for item in evidence)
    exact_value_evidence = any(item.get("value", "") == current_value for item in evidence)
    if has_conflict:
        return "low"
    if exact_value_evidence or current_value == "":
        return "high"
    if (
        issue_types
        or current_value.casefold() == proposed_value.casefold()
        or _known_cleanup_pattern(current_value, proposed_value)
    ):
        return "medium"
    return "low"


def _known_cleanup_pattern(current_value: str, proposed_value: str) -> bool:
    current_cleaned = _JUNK_SUFFIX_RE.sub("", current_value).strip()
    current_cleaned = _DUPLICATE_WHITESPACE_RE.sub(" ", current_cleaned)
    current_cleaned = current_cleaned.replace("_", " ").replace(" -", "-").replace("- ", "-")
    return current_cleaned.casefold() == proposed_value.casefold()


def _normalizes_separators(current_value: str, proposed_value: str) -> bool:
    if not current_value:
        return False
    normalized = current_value.replace("_", " ").replace(" -", "-").replace("- ", "-")
    return normalized != current_value and normalized.casefold() == proposed_value.casefold()


def _rationale(
    *,
    suggestion_type: str,
    confidence: str,
    plan_reason: str,
    evidence: list[dict[str, str]],
) -> str:
    evidence_bits = sorted(
        {
            item.get("issue_type") or item.get("issue_types") or item.get("source", "")
            for item in evidence
            if item.get("issue_type") or item.get("issue_types") or item.get("source")
        }
    )
    reason = plan_reason or "metadata normalization plan"
    if evidence_bits:
        return (
            f"{suggestion_type} suggested from {reason}; audit evidence: "
            f"{', '.join(evidence_bits)}. Confidence: {confidence}."
        )
    return f"{suggestion_type} suggested from {reason}. Confidence: {confidence}."


def _with_enriched_rationale(suggestion: MetadataSuggestion) -> MetadataSuggestion:
    enriched = (
        f"{suggestion.rationale} AI-assisted rationale enrichment is limited to "
        "review wording; the proposed value remains deterministic."
    )
    return MetadataSuggestion(
        suggestion_key=suggestion.suggestion_key,
        file_path=suggestion.file_path,
        field=suggestion.field,
        current_value=suggestion.current_value,
        proposed_value=suggestion.proposed_value,
        suggestion_type=suggestion.suggestion_type,
        confidence=suggestion.confidence,
        rationale=enriched,
        requires_human_review=suggestion.requires_human_review,
        source_evidence=suggestion.source_evidence,
        reliability_score=suggestion.reliability_score,
        reliability_flags=suggestion.reliability_flags or [],
        reliability_rationale=suggestion.reliability_rationale or [],
    )


def _with_normalization_knowledge(
    suggestions: list[MetadataSuggestion],
    *,
    db_path: str | Path | None,
) -> list[MetadataSuggestion]:
    rules = rule_lookup_by_signature(db_path=db_path)
    if not rules:
        return suggestions
    influenced: list[MetadataSuggestion] = []
    for suggestion in suggestions:
        payload = influence_suggestion(asdict(suggestion), rules)
        influenced.append(MetadataSuggestion(**payload))
    return influenced


def _with_album_cohesion_evidence(
    suggestions: list[MetadataSuggestion],
    *,
    reports_dir: Path,
) -> list[MetadataSuggestion]:
    cohesion_by_file = album_cohesion_by_file(reports_dir)
    if not cohesion_by_file:
        return suggestions
    influenced: list[MetadataSuggestion] = []
    for suggestion in suggestions:
        group = cohesion_by_file.get(suggestion.file_path)
        if not group or suggestion.field != "album":
            influenced.append(suggestion)
            continue
        evidence = [
            *suggestion.source_evidence,
            f"album_cohesion:{group.get('group_key', '')}",
        ]
        rationale = list(group.get("rationale", []))
        for item in rationale[:2]:
            evidence.append(f"album_cohesion_rationale:{item}")
        influenced.append(
            MetadataSuggestion(
                suggestion_key=suggestion.suggestion_key,
                file_path=suggestion.file_path,
                field=suggestion.field,
                current_value=suggestion.current_value,
                proposed_value=suggestion.proposed_value,
                suggestion_type=suggestion.suggestion_type,
                confidence=suggestion.confidence,
                rationale=(
                    f"{suggestion.rationale} Album cohesion score "
                    f"{float(group.get('cohesion_score', 0.0) or 0.0):.3f}."
                ),
                requires_human_review=suggestion.requires_human_review,
                source_evidence=sorted(dict.fromkeys(evidence)),
                reliability_score=suggestion.reliability_score,
                reliability_flags=suggestion.reliability_flags or [],
                reliability_rationale=suggestion.reliability_rationale or [],
            )
        )
    return influenced


def _with_reliability_evidence(
    suggestions: list[MetadataSuggestion],
    *,
    reports_dir: Path,
) -> list[MetadataSuggestion]:
    cohesion_by_file = album_cohesion_by_file(reports_dir)
    influenced: list[MetadataSuggestion] = []
    for suggestion in suggestions:
        group = cohesion_by_file.get(suggestion.file_path, {})
        group_rationale = group.get("rationale", [])
        sequential = isinstance(group_rationale, list) and "sequential track numbering" in group_rationale
        cohesion_score = (
            float(group.get("cohesion_score", 0.0) or 0.0)
            if suggestion.field == "album" and group
            else None
        )
        reliability = score_evidence(
            suggestion.current_value or suggestion.proposed_value,
            field=suggestion.field,
            file_path=suggestion.file_path,
            album_cohesion_score=cohesion_score,
            sequential_tracks=sequential,
        )
        confidence = suggestion.confidence
        rationale = suggestion.rationale
        if reliability.reliability_tier == "low":
            confidence = _decrease_confidence(confidence)
            rationale = (
                f"{rationale} Evidence reliability is low "
                f"({reliability.reliability_score:.3f}): "
                f"{'; '.join(reliability.rationale[:2])}."
            )
        elif reliability.reliability_tier == "high":
            rationale = (
                f"{rationale} Evidence reliability is high "
                f"({reliability.reliability_score:.3f})."
            )
        influenced.append(
            MetadataSuggestion(
                suggestion_key=suggestion.suggestion_key,
                file_path=suggestion.file_path,
                field=suggestion.field,
                current_value=suggestion.current_value,
                proposed_value=suggestion.proposed_value,
                suggestion_type=suggestion.suggestion_type,
                confidence=confidence,
                rationale=rationale,
                requires_human_review=suggestion.requires_human_review,
                source_evidence=suggestion.source_evidence,
                reliability_score=reliability.reliability_score,
                reliability_flags=reliability.reliability_flags,
                reliability_rationale=reliability.rationale[:3],
            )
        )
    return influenced


def _decrease_confidence(confidence: str) -> str:
    if confidence == "high":
        return "medium"
    if confidence == "medium":
        return "low"
    return "low"


def _source_evidence(row: dict[str, str], evidence: list[dict[str, str]]) -> list[str]:
    sources = [f"metadata_plan:{row.get('reason', 'plan') or 'plan'}"]
    for item in evidence:
        source = item.get("source", "metadata_audit")
        issue = item.get("issue_type") or item.get("issue_types") or "row"
        sources.append(f"{source}:{issue}")
    return sorted(dict.fromkeys(sources))


def _read_audit_evidence(audit_dir: Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    evidence: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(audit_dir / "malformed_tags.csv"):
        row = {**row, "source": "malformed_tags"}
        evidence[(row.get("path", ""), row.get("field", ""))].append(row)
    for row in _read_csv(audit_dir / "missing_tags.csv"):
        row = {**row, "source": "missing_tags", "issue_type": "missing_tag", "value": ""}
        evidence[(row.get("path", ""), row.get("field", ""))].append(row)
    for source_name, field in (
        ("inconsistent_artists.csv", "artist"),
        ("inconsistent_titles.csv", "title"),
    ):
        for row in _read_csv(audit_dir / source_name):
            source = source_name.removesuffix(".csv")
            for path in _split_pipe_list(row.get("paths", "")):
                evidence[(path, field)].append({**row, "source": source, "field": field})
    return dict(evidence)


def _resolve_plan_path(path: Path) -> Path:
    if path.exists():
        return path
    if path.name == "metadata_plan.csv":
        legacy_path = path.with_name("tag_update_plan.csv")
        if legacy_path.exists():
            return legacy_path
    return path


def _split_pipe_list(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def _summary(
    suggestions: list[MetadataSuggestion],
    *,
    ai_enrichment_used: bool,
) -> dict[str, Any]:
    counts = Counter(suggestion.confidence for suggestion in suggestions)
    return {
        "total_suggestions": len(suggestions),
        "high_confidence_count": counts["high"],
        "medium_confidence_count": counts["medium"],
        "low_confidence_count": counts["low"],
        "requires_human_review_count": sum(
            1 for suggestion in suggestions if suggestion.requires_human_review
        ),
        "ai_enrichment_used": ai_enrichment_used,
    }


def _suggestion_csv_payload(suggestion: MetadataSuggestion) -> dict[str, Any]:
    payload = asdict(suggestion)
    payload["source_evidence"] = json.dumps(suggestion.source_evidence, sort_keys=True)
    payload["reliability_flags"] = json.dumps(suggestion.reliability_flags or [], sort_keys=True)
    payload["reliability_rationale"] = json.dumps(suggestion.reliability_rationale or [], sort_keys=True)
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, headers: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["requires_human_review"] = str(csv_row["requires_human_review"]).lower()
            writer.writerow(csv_row)
