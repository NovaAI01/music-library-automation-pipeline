"""Reusable normalization knowledge derived from human review decisions."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import db
from app.review_decisions import list_review_decisions


RULE_HEADERS: tuple[str, ...] = (
    "rule_key",
    "rule_type",
    "source_value",
    "target_value",
    "evidence_count",
    "approved_count",
    "rejected_count",
    "confidence",
    "confidence_reason",
    "first_seen",
    "last_seen",
    "examples_json",
)
RULE_TYPES: tuple[str, ...] = (
    "artist_alias",
    "title_cleanup",
    "album_artist_default",
    "junk_suffix_cleanup",
    "separator_cleanup",
    "rejected_pattern",
)
CONFIDENCE_LEVELS: tuple[str, ...] = ("high", "medium", "low", "rejected_pattern")
TEMPLATE_DIR = Path(__file__).parent / "templates"

router = APIRouter(prefix="/review/knowledge", tags=["normalization-knowledge"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@dataclass(frozen=True)
class NormalizationRule:
    rule_key: str
    rule_type: str
    source_value: str
    target_value: str
    evidence_count: int
    approved_count: int
    rejected_count: int
    confidence: str
    confidence_reason: str
    first_seen: str
    last_seen: str
    examples_json: str


@dataclass(frozen=True)
class NormalizationKnowledgeResult:
    report_path: str
    total_rules: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    rejected_pattern_count: int


def build_normalization_knowledge(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> NormalizationKnowledgeResult:
    rules = derive_normalization_rules(db_path=db_path)
    report_dir = Path(out_dir).expanduser() / "normalization_knowledge"
    report_dir.mkdir(parents=True, exist_ok=True)
    summary = normalization_knowledge_summary(rules)

    _write_json(
        report_dir / "normalization_knowledge_rules.json",
        {"rules": [asdict(rule) for rule in rules]},
    )
    _write_csv(
        report_dir / "normalization_knowledge_rules.csv",
        RULE_HEADERS,
        (asdict(rule) for rule in rules),
    )
    _write_json(report_dir / "normalization_knowledge_summary.json", summary)

    return NormalizationKnowledgeResult(report_path=str(report_dir), **summary)


def derive_normalization_rules(
    *,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> list[NormalizationRule]:
    rows = [
        row
        for row in list_review_decisions(db_path)
        if row["decision"] in {"approved", "rejected"} and _base_rule_type(row)
    ]
    grouped: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        base_type = _base_rule_type(row)
        if base_type:
            grouped[(base_type, row["current_value"], row["proposed_value"])].append(row)

    rules = [_rule_from_rows(key, group_rows) for key, group_rows in grouped.items()]
    return sorted(rules, key=lambda rule: (rule.rule_type, rule.source_value.casefold(), rule.target_value.casefold()))


def normalization_knowledge_summary(rules: Iterable[NormalizationRule]) -> dict[str, int]:
    materialized = list(rules)
    counts = Counter(rule.confidence for rule in materialized)
    return {
        "total_rules": len(materialized),
        "high_confidence_count": counts["high"],
        "medium_confidence_count": counts["medium"],
        "low_confidence_count": counts["low"],
        "rejected_pattern_count": counts["rejected_pattern"],
    }


def rule_lookup_by_signature(
    *,
    db_path: str | Path | None,
) -> dict[tuple[str, str, str], NormalizationRule]:
    if db_path is None:
        return {}
    return {
        (rule.rule_type, rule.source_value, rule.target_value): rule
        for rule in derive_normalization_rules(db_path=db_path)
        if rule.approved_count > 0 and rule.confidence != "rejected_pattern"
    }


def influence_suggestion(
    suggestion: dict[str, Any],
    rules: dict[tuple[str, str, str], NormalizationRule],
) -> dict[str, Any]:
    rule_type = _rule_type_for_suggestion(
        str(suggestion.get("field", "")),
        str(suggestion.get("suggestion_type", "")),
    )
    if not rule_type:
        return suggestion
    rule = rules.get(
        (
            rule_type,
            str(suggestion.get("current_value", "")),
            str(suggestion.get("proposed_value", "")),
        )
    )
    if rule is None:
        return suggestion

    source_evidence = list(suggestion.get("source_evidence", []))
    source_evidence.append(f"normalization_knowledge:{rule.rule_key}")
    return {
        **suggestion,
        "confidence": _increase_confidence(str(suggestion.get("confidence", "low"))),
        "rationale": (
            f"{suggestion.get('rationale', '')} Approved prior decision evidence "
            f"supports this normalization ({rule.approved_count} approved, "
            f"{rule.rejected_count} rejected)."
        ).strip(),
        "source_evidence": sorted(dict.fromkeys(source_evidence)),
        "requires_human_review": True,
    }


@router.get("")
def knowledge_review(request: Request):
    rules = _read_rules(_reports_dir(request))
    confidence_counts = Counter({level: 0 for level in CONFIDENCE_LEVELS})
    type_counts = Counter({rule_type: 0 for rule_type in RULE_TYPES})
    for rule in rules:
        confidence_counts[rule["confidence"]] += 1
        type_counts[rule["rule_type"]] += 1
    return templates.TemplateResponse(
        name="normalization_knowledge/review.html",
        request=request,
        context={
            "request": request,
            "title": "Normalization Knowledge",
            "nav_items": _nav_items(),
            "rules": rules,
            "cards": [
                ("Total rules", len(rules)),
                ("High confidence", confidence_counts["high"]),
                ("Medium confidence", confidence_counts["medium"]),
                ("Rejected patterns", confidence_counts["rejected_pattern"]),
            ],
            "rule_type_counts": dict(type_counts),
            "confidence_counts": dict(confidence_counts),
            "empty_message": "No normalization knowledge rules available.",
        },
    )


def _rule_from_rows(
    key: tuple[str, str, str],
    rows: list[dict[str, Any]],
) -> NormalizationRule:
    base_type, source_value, target_value = key
    approved_count = sum(1 for row in rows if row["decision"] == "approved")
    rejected_count = sum(1 for row in rows if row["decision"] == "rejected")
    confidence = _confidence(approved_count, rejected_count)
    rule_type = "rejected_pattern" if confidence == "rejected_pattern" else base_type
    examples = [
        {
            "suggestion_key": row["suggestion_key"],
            "file_path": row["file_path"],
            "field": row["field"],
            "decision": row["decision"],
            "decided_at": row["decided_at"],
        }
        for row in sorted(rows, key=lambda item: item["decided_at"])
    ]
    return NormalizationRule(
        rule_key=_rule_key(rule_type, source_value, target_value),
        rule_type=rule_type,
        source_value=source_value,
        target_value=target_value,
        evidence_count=len(rows),
        approved_count=approved_count,
        rejected_count=rejected_count,
        confidence=confidence,
        confidence_reason=_confidence_reason(approved_count, rejected_count, confidence),
        first_seen=min(str(row["decided_at"]) for row in rows),
        last_seen=max(str(row["decided_at"]) for row in rows),
        examples_json=json.dumps(examples, sort_keys=True),
    )


def _base_rule_type(row: dict[str, Any]) -> str | None:
    return _rule_type_for_suggestion(str(row["field"]), str(row["suggestion_type"]))


def _rule_type_for_suggestion(field: str, suggestion_type: str) -> str | None:
    if field == "artist" and suggestion_type == "artist_casing":
        return "artist_alias"
    if field == "album_artist":
        return "album_artist_default"
    if suggestion_type == "junk_suffix_removal":
        return "junk_suffix_cleanup"
    if suggestion_type == "separator_cleanup":
        return "separator_cleanup"
    if field == "title" and suggestion_type in {"title_cleanup", "duplicate_whitespace_cleanup"}:
        return "title_cleanup"
    return None


def _confidence(approved_count: int, rejected_count: int) -> str:
    if rejected_count > approved_count:
        return "rejected_pattern"
    if approved_count >= 3 and rejected_count == 0:
        return "high"
    if approved_count >= 1 and rejected_count == 0:
        return "medium"
    if approved_count > 0 and rejected_count > 0:
        return "low"
    return "rejected_pattern"


def _confidence_reason(approved_count: int, rejected_count: int, confidence: str) -> str:
    if confidence == "high":
        return "at least three approvals and no rejections"
    if confidence == "medium":
        return "at least one approval and no rejections"
    if confidence == "low":
        return "approved and rejected decisions both exist"
    return "rejections outnumber approvals"


def _increase_confidence(confidence: str) -> str:
    if confidence == "low":
        return "medium"
    if confidence == "medium":
        return "high"
    return "high"


def _rule_key(rule_type: str, source_value: str, target_value: str) -> str:
    canonical = json.dumps(
        {
            "rule_type": rule_type,
            "source_value": source_value,
            "target_value": target_value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _read_rules(reports_dir: Path) -> list[dict[str, Any]]:
    path = reports_dir / "normalization_knowledge" / "normalization_knowledge_rules.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("rules", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return [_normalize_rule(row) for row in rows if isinstance(row, dict)]


def _normalize_rule(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_key": str(row.get("rule_key", "")),
        "rule_type": str(row.get("rule_type", "")),
        "source_value": str(row.get("source_value", "")),
        "target_value": str(row.get("target_value", "")),
        "evidence_count": int(row.get("evidence_count", 0) or 0),
        "approved_count": int(row.get("approved_count", 0) or 0),
        "rejected_count": int(row.get("rejected_count", 0) or 0),
        "confidence": str(row.get("confidence", "")),
        "confidence_reason": str(row.get("confidence_reason", "")),
        "first_seen": str(row.get("first_seen", "")),
        "last_seen": str(row.get("last_seen", "")),
    }


def _reports_dir(request: Request) -> Path:
    configured = getattr(request.app.state, "reports_dir", Path("reports"))
    return Path(configured).expanduser()


def _nav_items() -> list[tuple[str, str]]:
    return [
        ("/", "Dashboard"),
        ("/import", "Import"),
        ("/library", "Library"),
        ("/library/artists", "Artists"),
        ("/library/albums", "Albums"),
        ("/library/genres", "Genres"),
        ("/library/tracks", "Tracks"),
        ("/review", "Review"),
        ("/review/duplicates", "Duplicates"),
        ("/review/metadata", "Metadata"),
        ("/review/knowledge", "Knowledge"),
        ("/player", "Player"),
        ("/settings", "Settings"),
    ]


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
            writer.writerow({header: row.get(header, "") for header in headers})
