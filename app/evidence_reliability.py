"""Reusable metadata evidence reliability scoring.

The engine is intentionally read-only. It scores observed strings and report
evidence so downstream review features can discount polluted metadata without
rewriting tags or deleting evidence.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.normalization_knowledge import derive_normalization_rules
from app.review_decisions import list_review_decisions


REPORT_DIRNAME = "evidence_reliability"
SUMMARY_FILENAME = "evidence_reliability_summary.json"
UNRELIABLE_CSV_FILENAME = "unreliable_evidence.csv"
RELIABLE_CSV_FILENAME = "reliable_patterns.csv"
GROUPS_JSON_FILENAME = "reliability_groups.json"

UNRELIABLE_HEADERS: tuple[str, ...] = (
    "record_key",
    "file_path",
    "field",
    "value",
    "source",
    "reliability_score",
    "reliability_tier",
    "reliability_flags",
    "rationale",
)
RELIABLE_HEADERS: tuple[str, ...] = (
    "pattern_key",
    "field",
    "value",
    "source_count",
    "reliability_score",
    "reliability_tier",
    "reliability_flags",
    "rationale",
)

_OFFICIAL_RE = re.compile(r"\b(?:official\s+(?:audio|video|visualizer|music\s+video)|lyric\s+video)\b", re.I)
_REMASTER_RE = re.compile(r"\b(?:remaster(?:ed)?|remastered\s+\d{4}|\d{4}\s+remaster|anniversary\s+edition|deluxe\s+edition)\b", re.I)
_PLATFORM_RE = re.compile(r"\b(?:youtube|vevo|topic|provided\s+to\s+youtube|auto-generated|soundcloud|bandcamp)\b", re.I)
_LABEL_CHANNEL_RE = re.compile(r"\b(?:records|recordings|music|official|entertainment)\s+(?:channel|official)\b", re.I)
_UPLOAD_RE = re.compile(r"\b(?:uploaded\s+by|subscribe|channel|topic|vevo|provided\s+to\s+youtube|auto-generated)\b", re.I)
_NON_MUSICAL_TOKEN_RE = re.compile(r"\b(?:official|audio|video|lyrics?|hd|4k|remaster(?:ed)?|subscribe|channel|topic|vevo)\b", re.I)
_SOURCE_NOISE_RE = re.compile(r"\b(?:track\s+\d+|unknown\s+(?:artist|album)|untitled|audio\s+track|new\s+folder|copy\s+of)\b", re.I)
_SEPARATOR_RE = re.compile(r"[-_|:/\\]{2,}|(?:\s+-\s+){2,}")
_BRACKET_RE = re.compile(r"[\[(](.*?)[\])]")


@dataclass(frozen=True)
class EvidenceReliability:
    reliability_score: float
    reliability_tier: str
    reliability_flags: list[str]
    rationale: list[str]


@dataclass(frozen=True)
class EvidenceRecord:
    record_key: str
    file_path: str
    field: str
    value: str
    source: str
    reliability_score: float
    reliability_tier: str
    reliability_flags: list[str]
    rationale: list[str]


@dataclass(frozen=True)
class EvidenceReliabilityResult:
    report_path: str
    total_records: int
    high_reliability: int
    medium_reliability: int
    low_reliability: int
    uploader_artifacts_detected: int
    noisy_titles_detected: int
    conflicting_artist_patterns: int
    canonical_matches: int


def score_evidence(
    value: str,
    *,
    field: str = "",
    file_path: str = "",
    folder_value: str = "",
    canonical_values: Iterable[str] = (),
    repeated_count: int = 1,
    album_cohesion_score: float | None = None,
    sequential_tracks: bool = False,
    prior_approvals: int = 0,
    prior_rejections: int = 0,
    conflict_count: int = 0,
) -> EvidenceReliability:
    """Score a single metadata value from 0.0 to 1.0."""

    text = _clean(value)
    normalized = _norm(text)
    score = 0.56 if text else 0.18
    flags: list[str] = []
    rationale: list[str] = []

    if not text:
        flags.append("empty_value")
        rationale.append("empty evidence value")
    if _UPLOAD_RE.search(text):
        score -= 0.30
        flags.append("uploader_or_channel_signature")
        rationale.append("uploader or channel wording detected")
    if _LABEL_CHANNEL_RE.search(text):
        score -= 0.18
        flags.append("label_channel_signature")
        rationale.append("label/channel signature detected")
    if _OFFICIAL_RE.search(text):
        score -= 0.18
        flags.append("official_media_suffix")
        rationale.append("official audio/video wording detected")
    if _REMASTER_RE.search(text):
        score -= 0.12
        flags.append("remaster_noise")
        rationale.append("remaster or edition wording may be release-note noise")
    if _PLATFORM_RE.search(text):
        score -= 0.20
        flags.append("platform_branding")
        rationale.append("embedded platform branding detected")
    if _SEPARATOR_RE.search(text) or text.count(" - ") >= 2:
        score -= 0.13
        flags.append("excessive_separators")
        rationale.append("excessive separators detected")
    if _all_caps_anomaly(text):
        score -= 0.10
        flags.append("all_caps_anomaly")
        rationale.append("non-canonical all-caps casing")
    if _mixed_artist_name(text):
        score -= 0.12
        flags.append("mixed_artist_naming")
        rationale.append("mixed artist naming pattern detected")
    if _repeated_non_musical_tokens(text):
        score -= 0.15
        flags.append("repeated_non_musical_tokens")
        rationale.append("repeated non-musical tokens detected")
    if _suspicious_suffix_repetition(text):
        score -= 0.11
        flags.append("suspicious_suffix_repetition")
        rationale.append("repeated bracketed or suffix noise detected")
    if field in {"title", "album"} and _SOURCE_NOISE_RE.search(text):
        score -= 0.16
        flags.append("autogenerated_name_noise")
        rationale.append("autogenerated or placeholder source text detected")
    if field == "artist" and folder_value and not _compatible_artist(text, folder_value):
        score -= 0.18
        flags.append("artist_folder_mismatch")
        rationale.append("artist evidence conflicts with folder context")
    if field in {"title", "album"} and any(flag in flags for flag in ("official_media_suffix", "platform_branding", "remaster_noise")):
        flags.append("noisy_title_or_album")

    canonical_norms = {_norm(item) for item in canonical_values if item}
    if normalized and normalized in canonical_norms:
        score += 0.22
        flags.append("canonical_match")
        rationale.append("normalization knowledge supports value")
    if repeated_count >= 2:
        score += min(0.18, 0.07 + (repeated_count - 2) * 0.03)
        flags.append("repeated_canonical_agreement")
        rationale.append("repeated canonical agreement exists")
    if album_cohesion_score is not None and album_cohesion_score >= 0.72:
        score += 0.12
        flags.append("album_cohesion_support")
        rationale.append("album cohesion supports value")
    elif album_cohesion_score is not None and album_cohesion_score < 0.45:
        score -= 0.08
        flags.append("weak_album_cohesion")
        rationale.append("album cohesion evidence is weak")
    if sequential_tracks:
        score += 0.08
        flags.append("sequential_track_support")
        rationale.append("sequential tracks support this evidence")
    if prior_approvals:
        score += min(0.16, 0.08 + prior_approvals * 0.03)
        flags.append("prior_approval_support")
        rationale.append("prior approvals support this value")
    if prior_rejections:
        score -= min(0.18, 0.08 + prior_rejections * 0.04)
        flags.append("prior_rejection_conflict")
        rationale.append("prior rejected decisions conflict with this pattern")
    if conflict_count == 0 and text:
        score += 0.04
        flags.append("low_conflict_rate")
        rationale.append("low conflict rate observed")
    elif conflict_count:
        score -= min(0.20, conflict_count * 0.06)
        flags.append("conflicting_pattern")
        rationale.append("conflicting evidence pattern observed")

    score = round(max(0.0, min(1.0, score)), 3)
    return EvidenceReliability(
        reliability_score=score,
        reliability_tier=reliability_tier(score),
        reliability_flags=sorted(dict.fromkeys(flags)),
        rationale=rationale or ["limited reliability evidence"],
    )


def reliability_tier(score: float) -> str:
    if score >= 0.72:
        return "high"
    if score >= 0.42:
        return "medium"
    return "low"


def generate_evidence_reliability_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> EvidenceReliabilityResult:
    reports_dir = Path(out_dir).expanduser()
    report_dir = reports_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)

    records = collect_evidence_records(reports_dir=reports_dir, db_path=db_path)
    summary = evidence_reliability_summary(records)
    summary["created_at"] = datetime.now(UTC).isoformat()
    summary["report_file"] = str(report_dir / GROUPS_JSON_FILENAME)

    grouped = _group_records(records)
    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_csv(
        report_dir / UNRELIABLE_CSV_FILENAME,
        UNRELIABLE_HEADERS,
        (_record_csv_row(record) for record in records if record.reliability_tier == "low"),
    )
    _write_csv(
        report_dir / RELIABLE_CSV_FILENAME,
        RELIABLE_HEADERS,
        _reliable_rows(grouped),
    )
    _write_json(
        report_dir / GROUPS_JSON_FILENAME,
        {
            "records": [asdict(record) for record in records],
            "groups": grouped,
        },
    )
    return EvidenceReliabilityResult(report_path=str(report_dir), **_summary_ints(summary))


def collect_evidence_records(
    *,
    reports_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[EvidenceRecord]:
    reports_path = Path(reports_dir).expanduser()
    canonical_values = _canonical_values(db_path)
    approvals, rejections = _decision_counts(db_path)
    suggestions = _read_json(reports_path / "metadata_suggestions" / "metadata_suggestions.json").get("suggestions", [])
    cohesion = _read_json(reports_path / "album_cohesion" / "album_groups.json")
    groups = cohesion.get("groups", []) if isinstance(cohesion, dict) else []
    source_rows: list[dict[str, Any]] = []

    if isinstance(suggestions, list):
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            source_rows.append(
                {
                    "file_path": str(item.get("file_path", "")),
                    "field": str(item.get("field", "")),
                    "value": str(item.get("current_value", "")),
                    "source": "metadata_suggestion_current",
                }
            )
            proposed = str(item.get("proposed_value", ""))
            if proposed:
                source_rows.append(
                    {
                        "file_path": str(item.get("file_path", "")),
                        "field": str(item.get("field", "")),
                        "value": proposed,
                        "source": "metadata_suggestion_proposed",
                    }
                )

    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_score = float(group.get("cohesion_score", 0.0) or 0.0)
            rationale = group.get("rationale", [])
            sequential = isinstance(rationale, list) and "sequential track numbering" in rationale
            for field in ("album", "artist"):
                value = str(group.get(field, ""))
                if value:
                    source_rows.append(
                        {
                            "file_path": "",
                            "field": field,
                            "value": value,
                            "source": "album_cohesion_group",
                            "album_cohesion_score": group_score,
                            "sequential_tracks": sequential,
                        }
                    )
            for track in group.get("tracks", []) if isinstance(group.get("tracks"), list) else []:
                if not isinstance(track, dict):
                    continue
                for field, key in (("artist", "artist"), ("title", "title"), ("album", "album_tag")):
                    value = str(track.get(key, ""))
                    if value:
                        source_rows.append(
                            {
                                "file_path": str(track.get("file_path", "")),
                                "field": field,
                                "value": value,
                                "source": "album_cohesion_track",
                                "folder_value": str(track.get("source_folder", "")),
                                "album_cohesion_score": group_score,
                                "sequential_tracks": sequential,
                            }
                        )

    value_counts = Counter((_norm(row["field"]), _norm(row["value"])) for row in source_rows if row.get("value"))
    conflicts = _conflicts_by_field(source_rows)
    records: list[EvidenceRecord] = []
    for index, row in enumerate(source_rows):
        field = str(row.get("field", ""))
        value = str(row.get("value", ""))
        signature = (_norm(field), _norm(value))
        score = score_evidence(
            value,
            field=field,
            file_path=str(row.get("file_path", "")),
            folder_value=str(row.get("folder_value", "")),
            canonical_values=canonical_values.get(field, set()),
            repeated_count=value_counts[signature],
            album_cohesion_score=row.get("album_cohesion_score"),
            sequential_tracks=bool(row.get("sequential_tracks")),
            prior_approvals=approvals.get(signature, 0),
            prior_rejections=rejections.get(signature, 0),
            conflict_count=conflicts.get(field, 0),
        )
        records.append(
            EvidenceRecord(
                record_key=f"evidence-{index + 1:06d}",
                file_path=str(row.get("file_path", "")),
                field=field,
                value=value,
                source=str(row.get("source", "")),
                reliability_score=score.reliability_score,
                reliability_tier=score.reliability_tier,
                reliability_flags=score.reliability_flags,
                rationale=score.rationale,
            )
        )
    return sorted(records, key=lambda item: (item.reliability_tier, item.field, item.value.casefold(), item.file_path))


def evidence_reliability_summary(records: Iterable[EvidenceRecord]) -> dict[str, int]:
    materialized = list(records)
    counts = Counter(record.reliability_tier for record in materialized)
    return {
        "total_records": len(materialized),
        "high_reliability": counts["high"],
        "medium_reliability": counts["medium"],
        "low_reliability": counts["low"],
        "uploader_artifacts_detected": _flag_count(materialized, {"uploader_or_channel_signature", "label_channel_signature"}),
        "noisy_titles_detected": _flag_count(materialized, {"noisy_title_or_album", "autogenerated_name_noise"}),
        "conflicting_artist_patterns": sum(1 for record in materialized if record.field == "artist" and "conflicting_pattern" in record.reliability_flags),
        "canonical_matches": _flag_count(materialized, {"canonical_match", "repeated_canonical_agreement"}),
    }


def read_evidence_reliability_report(reports_dir: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]], list[str]]:
    report_dir = Path(reports_dir).expanduser() / REPORT_DIRNAME
    summary, missing_summary = _read_json_with_missing(report_dir / SUMMARY_FILENAME)
    groups, missing_groups = _read_json_with_missing(report_dir / GROUPS_JSON_FILENAME)
    unreliable, missing_unreliable = _read_csv(report_dir / UNRELIABLE_CSV_FILENAME)
    reliable, missing_reliable = _read_csv(report_dir / RELIABLE_CSV_FILENAME)
    records = groups.get("records", []) if isinstance(groups, dict) else []
    if not isinstance(records, list):
        records = []
    return (
        summary,
        [_normalize_record(record) for record in records if isinstance(record, dict)],
        unreliable,
        reliable,
        [label for label in (missing_summary, missing_groups, missing_unreliable, missing_reliable) if label],
    )


def _canonical_values(db_path: str | Path) -> dict[str, set[str]]:
    values: defaultdict[str, set[str]] = defaultdict(set)
    for rule in derive_normalization_rules(db_path=db_path):
        if rule.confidence == "rejected_pattern":
            continue
        if rule.rule_type == "artist_alias":
            values["artist"].add(rule.target_value)
        elif rule.rule_type == "title_cleanup":
            values["title"].add(rule.target_value)
        elif rule.rule_type == "album_artist_default":
            values["album_artist"].add(rule.target_value)
    return values


def _decision_counts(db_path: str | Path) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]]]:
    approvals: Counter[tuple[str, str]] = Counter()
    rejections: Counter[tuple[str, str]] = Counter()
    for row in list_review_decisions(db_path):
        signature = (_norm(str(row.get("field", ""))), _norm(str(row.get("proposed_value", ""))))
        if row.get("decision") == "approved":
            approvals[signature] += 1
        elif row.get("decision") == "rejected":
            rejections[signature] += 1
    return approvals, rejections


def _conflicts_by_field(rows: list[dict[str, Any]]) -> dict[str, int]:
    values: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("value"):
            values[str(row.get("field", ""))].add(_norm(str(row.get("value", ""))))
    return {field: max(0, len(field_values) - 1) for field, field_values in values.items()}


def _group_records(records: list[EvidenceRecord]) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, str], list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.field, _norm(record.value))].append(record)
    payload = []
    for (field, _), items in grouped.items():
        scores = [item.reliability_score for item in items]
        flags = sorted({flag for item in items for flag in item.reliability_flags})
        payload.append(
            {
                "field": field,
                "value": items[0].value,
                "source_count": len(items),
                "average_reliability_score": round(sum(scores) / len(scores), 3),
                "reliability_tier": reliability_tier(sum(scores) / len(scores)),
                "reliability_flags": flags,
                "rationale": sorted({reason for item in items for reason in item.rationale})[:8],
                "records": [item.record_key for item in items],
            }
        )
    return sorted(payload, key=lambda item: (-item["average_reliability_score"], item["field"], item["value"].casefold()))


def _reliable_rows(groups: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for group in groups:
        if group["reliability_tier"] != "high":
            continue
        yield {
            "pattern_key": f"{group['field']}:{_norm(group['value'])}",
            "field": group["field"],
            "value": group["value"],
            "source_count": group["source_count"],
            "reliability_score": group["average_reliability_score"],
            "reliability_tier": group["reliability_tier"],
            "reliability_flags": json.dumps(group["reliability_flags"], sort_keys=True),
            "rationale": " | ".join(group["rationale"]),
        }


def _record_csv_row(record: EvidenceRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["reliability_flags"] = json.dumps(record.reliability_flags, sort_keys=True)
    payload["rationale"] = " | ".join(record.rationale)
    return payload


def _flag_count(records: list[EvidenceRecord], flags: set[str]) -> int:
    return sum(1 for record in records if flags.intersection(record.reliability_flags))


def _summary_ints(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "total_records": int(summary["total_records"]),
        "high_reliability": int(summary["high_reliability"]),
        "medium_reliability": int(summary["medium_reliability"]),
        "low_reliability": int(summary["low_reliability"]),
        "uploader_artifacts_detected": int(summary["uploader_artifacts_detected"]),
        "noisy_titles_detected": int(summary["noisy_titles_detected"]),
        "conflicting_artist_patterns": int(summary["conflicting_artist_patterns"]),
        "canonical_matches": int(summary["canonical_matches"]),
    }


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    flags = record.get("reliability_flags", [])
    rationale = record.get("rationale", [])
    return {
        **record,
        "reliability_score": float(record.get("reliability_score", 0.0) or 0.0),
        "reliability_tier": str(record.get("reliability_tier", "low") or "low"),
        "reliability_flags": [str(item) for item in flags] if isinstance(flags, list) else [str(flags)],
        "rationale": [str(item) for item in rationale] if isinstance(rationale, list) else [str(rationale)],
    }


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).casefold())


def _all_caps_anomaly(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return len(letters) >= 6 and sum(1 for char in letters if char.isupper()) / len(letters) > 0.82


def _mixed_artist_name(value: str) -> bool:
    return bool(re.search(r"\b(?:feat\.?|ft\.?|with|x|vs\.?)\b", value, re.I) and re.search(r"\s[-/&]\s|,\s*", value))


def _repeated_non_musical_tokens(value: str) -> bool:
    tokens = [match.group(0).casefold() for match in _NON_MUSICAL_TOKEN_RE.finditer(value)]
    return bool(tokens and max(Counter(tokens).values()) >= 2)


def _suspicious_suffix_repetition(value: str) -> bool:
    bracketed = [part.casefold().strip() for part in _BRACKET_RE.findall(value) if part.strip()]
    return len(bracketed) != len(set(bracketed)) or len(bracketed) >= 3


def _compatible_artist(value: str, folder_value: str) -> bool:
    value_norm = _norm(value)
    folder_norm = _norm(Path(folder_value).name)
    return not value_norm or not folder_norm or value_norm in folder_norm or folder_norm in value_norm


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json_with_missing(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, str(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, str(path)
    return (payload if isinstance(payload, dict) else {}), ""


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], str(path)
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle)), ""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
