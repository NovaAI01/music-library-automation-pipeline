"""Deterministic promotion lifecycle for canonical entity hypotheses.

Lifecycle state is intentionally separate from confidence tier. Confidence is a
signal; promotion requires temporal persistence, low conflict pressure, and
graph/role reinforcement.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from app import db
from app.canonical_confidence import ScoredEntity, collect_scored_entities


REPORT_DIRNAME = "promotion_lifecycle"
SUMMARY_FILENAME = "lifecycle_summary.json"
ENTITIES_FILENAME = "lifecycle_entities.csv"
CANONICAL_FILENAME = "canonical_entities.csv"
PROBATIONARY_FILENAME = "probationary_entities.csv"
CONFLICTED_FILENAME = "conflicted_entities.csv"
DEPRECATED_FILENAME = "deprecated_entities.csv"

LIFECYCLE_STATES = {"candidate", "probationary", "canonical", "conflicted", "blocked", "deprecated"}

LIFECYCLE_HEADERS: tuple[str, ...] = (
    "entity_type",
    "entity_key",
    "entity_value",
    "lifecycle_state",
    "lifecycle_reason",
    "transition_source",
    "confidence_snapshot",
    "temporal_snapshot",
    "graph_snapshot",
)


@dataclass(frozen=True)
class LifecycleEntity:
    entity_type: str
    entity_key: str
    entity_value: str
    lifecycle_state: str
    lifecycle_reason: str
    transition_source: str
    confidence_snapshot: str
    temporal_snapshot: str
    graph_snapshot: str


@dataclass(frozen=True)
class PromotionLifecycleResult:
    report_path: str
    candidate_count: int
    probationary_count: int
    canonical_count: int
    conflicted_count: int
    blocked_count: int
    deprecated_count: int
    promoted_this_run: int
    demoted_this_run: int


def evaluate_lifecycle(
    scored: ScoredEntity,
    *,
    previous_state: str = "",
    evidence_count: int = 1,
    first_seen: str = "",
    last_seen: str = "",
    graph_relationships: int = 0,
    conflict_count: int = 0,
    role_conflict: bool = False,
) -> LifecycleEntity:
    previous_state = previous_state if previous_state in LIFECYCLE_STATES else ""
    temporal_days = _temporal_days(first_seen, last_seen)
    stable_temporal = temporal_days >= 30 or evidence_count >= 4
    graph_reinforced = graph_relationships > 0 or evidence_count >= 3
    confidence = scored.normalized_confidence
    positive = scored.raw_positive_score
    negative = scored.raw_negative_score
    reasons: list[str] = []

    if previous_state in {"canonical", "probationary"} and (
        scored.confidence_tier == "blocked" or confidence < 0.42 or negative > positive + 0.55
    ):
        state = "deprecated"
        reasons.append("previously promoted entity lost sufficient confidence")
    elif scored.confidence_tier == "blocked" and negative > positive + 0.34:
        state = "blocked"
        reasons.append("dominant negative evidence blocks promotion")
    elif conflict_count >= 1 or role_conflict or (positive >= 0.55 and negative >= 0.55):
        state = "conflicted"
        reasons.append("strong positive and negative evidence coexist")
    elif confidence >= 0.74 and stable_temporal and graph_reinforced and conflict_count == 0:
        state = "canonical"
        reasons.append("sustained high confidence with temporal and graph reinforcement")
    elif confidence >= 0.55 and stable_temporal and graph_reinforced and conflict_count == 0:
        state = "canonical"
        reasons.append("medium confidence stabilized by long-lived evidence")
    elif confidence >= 0.55 or (confidence >= 0.50 and conflict_count == 0 and evidence_count >= 2):
        state = "probationary"
        reasons.append("moderate confidence with evidence beginning to stabilize")
    else:
        state = "candidate"
        reasons.append("new or sparse evidence remains below promotion threshold")

    if state == "canonical" and evidence_count <= 1:
        state = "probationary"
        reasons.append("isolated evidence cannot canonicalize immediately")
    if state == "blocked" and negative <= positive + 0.34:
        state = "candidate"
        reasons.append("weak artifact signal cannot block by itself")

    transition = _transition_source(previous_state, state)
    return LifecycleEntity(
        entity_type=scored.entity_type,
        entity_key=scored.entity_key,
        entity_value=scored.entity_value,
        lifecycle_state=state,
        lifecycle_reason=" | ".join(dict.fromkeys(reasons)),
        transition_source=transition,
        confidence_snapshot=json.dumps(
            {
                "confidence_tier": scored.confidence_tier,
                "normalized_confidence": scored.normalized_confidence,
                "raw_positive_score": scored.raw_positive_score,
                "raw_negative_score": scored.raw_negative_score,
                "rationale": scored.rationale,
            },
            sort_keys=True,
        ),
        temporal_snapshot=json.dumps(
            {
                "first_seen": first_seen,
                "last_seen": last_seen,
                "temporal_days": temporal_days,
                "evidence_count": evidence_count,
                "stable_temporal": stable_temporal,
            },
            sort_keys=True,
        ),
        graph_snapshot=json.dumps(
            {
                "graph_relationships": graph_relationships,
                "conflict_count": conflict_count,
                "graph_reinforced": graph_reinforced,
                "role_conflict": role_conflict,
            },
            sort_keys=True,
        ),
    )


def generate_promotion_lifecycle_report(
    *,
    out_dir: str | Path = "reports",
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> PromotionLifecycleResult:
    reports_dir = Path(out_dir).expanduser()
    report_dir = reports_dir / REPORT_DIRNAME
    previous = _previous_states(report_dir / ENTITIES_FILENAME)
    report_dir.mkdir(parents=True, exist_ok=True)
    lifecycle = collect_lifecycle_entities(db_path=db_path, previous_states=previous)
    summary = lifecycle_summary(lifecycle, previous)
    summary["created_at"] = datetime.now().astimezone().isoformat()
    summary["report_file"] = str(report_dir / ENTITIES_FILENAME)

    _write_json(report_dir / SUMMARY_FILENAME, summary)
    _write_csv(report_dir / ENTITIES_FILENAME, LIFECYCLE_HEADERS, (_csv_row(item) for item in lifecycle))
    _write_csv(report_dir / CANONICAL_FILENAME, LIFECYCLE_HEADERS, (_csv_row(item) for item in lifecycle if item.lifecycle_state == "canonical"))
    _write_csv(report_dir / PROBATIONARY_FILENAME, LIFECYCLE_HEADERS, (_csv_row(item) for item in lifecycle if item.lifecycle_state == "probationary"))
    _write_csv(report_dir / CONFLICTED_FILENAME, LIFECYCLE_HEADERS, (_csv_row(item) for item in lifecycle if item.lifecycle_state == "conflicted"))
    _write_csv(report_dir / DEPRECATED_FILENAME, LIFECYCLE_HEADERS, (_csv_row(item) for item in lifecycle if item.lifecycle_state == "deprecated"))
    return PromotionLifecycleResult(report_path=str(report_dir), **_summary_result(summary))


def collect_lifecycle_entities(
    *,
    db_path: str | Path = db.DEFAULT_DB_PATH,
    previous_states: dict[tuple[str, str], str] | None = None,
) -> list[LifecycleEntity]:
    previous_states = previous_states or {}
    scored = collect_scored_entities(db_path=db_path)
    return [
        evaluate_lifecycle(
            item,
            previous_state=previous_states.get((item.entity_type, item.entity_key), ""),
            evidence_count=_evidence_count(item),
            first_seen="",
            last_seen="",
            graph_relationships=1 if item.raw_positive_score >= 0.8 else 0,
            conflict_count=1 if item.raw_negative_score >= 0.55 and item.raw_positive_score >= 0.55 else 0,
            role_conflict="conflicting_role_pattern" in item.negative_evidence_json,
        )
        for item in scored
    ]


def lifecycle_summary(
    lifecycle: Iterable[LifecycleEntity],
    previous_states: dict[tuple[str, str], str] | None = None,
) -> dict[str, int]:
    previous_states = previous_states or {}
    materialized = list(lifecycle)
    counts = Counter(item.lifecycle_state for item in materialized)
    promoted = 0
    demoted = 0
    rank = {"blocked": 0, "deprecated": 0, "conflicted": 1, "candidate": 2, "probationary": 3, "canonical": 4}
    for item in materialized:
        previous = previous_states.get((item.entity_type, item.entity_key))
        if not previous:
            continue
        if rank[item.lifecycle_state] > rank.get(previous, 2):
            promoted += 1
        elif rank[item.lifecycle_state] < rank.get(previous, 2):
            demoted += 1
    return {
        "candidate_count": counts["candidate"],
        "probationary_count": counts["probationary"],
        "canonical_count": counts["canonical"],
        "conflicted_count": counts["conflicted"],
        "blocked_count": counts["blocked"],
        "deprecated_count": counts["deprecated"],
        "promoted_this_run": promoted,
        "demoted_this_run": demoted,
    }


def graph_lifecycle_state(
    *,
    entity_type: str,
    entity_key: str,
    entity_value: str,
    confidence_score: float,
    confidence_tier: str,
    evidence_count: int,
    conflict_count: int,
    first_seen: str,
    last_seen: str,
    graph_relationships: int = 0,
) -> str:
    scored = ScoredEntity(
        entity_type=entity_type,
        entity_key=entity_key,
        entity_value=entity_value,
        positive_evidence_json="[]",
        negative_evidence_json="[]",
        weighted_score_breakdown_json="{}",
        raw_positive_score=confidence_score,
        raw_negative_score=0.0 if conflict_count == 0 else min(1.0, conflict_count * 0.34),
        normalized_confidence=confidence_score,
        confidence_tier=confidence_tier,
        rationale="graph confidence snapshot",
    )
    return evaluate_lifecycle(
        scored,
        evidence_count=evidence_count,
        first_seen=first_seen,
        last_seen=last_seen,
        graph_relationships=graph_relationships,
        conflict_count=conflict_count,
    ).lifecycle_state


def _evidence_count(item: ScoredEntity) -> int:
    try:
        positive = json.loads(item.positive_evidence_json)
        negative = json.loads(item.negative_evidence_json)
    except json.JSONDecodeError:
        return 1
    counts = [int(row.get("count", 1) or 1) for row in [*positive, *negative] if isinstance(row, dict)]
    return max(1, max(counts) if counts else 1)


def _transition_source(previous: str, current: str) -> str:
    if not previous:
        return "new_observation"
    if previous == current:
        return "state_retained"
    if current == "deprecated":
        return f"{previous}_deprecated"
    return f"{previous}_to_{current}"


def _temporal_days(first_seen: str, last_seen: str) -> int:
    first = _parse_datetime(first_seen)
    last = _parse_datetime(last_seen)
    if first is None or last is None:
        return 0
    return max(0, (last - first).days)


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _previous_states(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    try:
        with path.open(newline="", encoding="utf-8") as file_handle:
            rows = list(csv.DictReader(file_handle))
    except OSError:
        return {}
    return {
        (str(row.get("entity_type", "")), str(row.get("entity_key", ""))): str(row.get("lifecycle_state", ""))
        for row in rows
        if row.get("entity_type") and row.get("entity_key")
    }


def _summary_result(summary: dict[str, Any]) -> dict[str, int]:
    return {
        "candidate_count": int(summary["candidate_count"]),
        "probationary_count": int(summary["probationary_count"]),
        "canonical_count": int(summary["canonical_count"]),
        "conflicted_count": int(summary["conflicted_count"]),
        "blocked_count": int(summary["blocked_count"]),
        "deprecated_count": int(summary["deprecated_count"]),
        "promoted_this_run": int(summary["promoted_this_run"]),
        "demoted_this_run": int(summary["demoted_this_run"]),
    }


def _csv_row(item: LifecycleEntity) -> dict[str, Any]:
    return asdict(item)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in headers})
