"""Deterministic safe alias equivalence checks for artist names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


_OFFICIAL_SUFFIX_RE = re.compile(
    r"\b(?:official\s+(?:audio|video)|remaster(?:ed)?|live|acoustic|explicit|edit)\b",
    re.I,
)
_COLLABORATION_RE = re.compile(r"(?:,|\b(?:ft\.?|feat\.?|featuring)\b)", re.I)
_ARTIFACT_MARKER_RE = re.compile(
    r"\b(?:uploader|uploads?|channel|topic|label|records?|recordings|vevo|"
    r"official\s+artist\s+channel|provided\s+to\s+youtube|auto-generated|youtube)\b",
    re.I,
)


@dataclass(frozen=True)
class AliasEquivalenceDecision:
    safe_to_merge_candidate: bool
    reason: str


def normalized_alnum_casefold(value: Any) -> str:
    """Normalize to alphanumeric casefolded text for deterministic alias comparison."""

    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def has_official_version_suffix(value: str) -> bool:
    return bool(_OFFICIAL_SUFFIX_RE.search(value))


def has_collaboration_marker(value: str) -> bool:
    return bool(_COLLABORATION_RE.search(value))


def has_artifact_marker(value: str) -> bool:
    return bool(_ARTIFACT_MARKER_RE.search(value))


def deterministic_artist_alias_equivalence(
    *,
    conflict_type: str,
    entity_role: str,
    source_entity: str,
    target_entity: str,
    positive_evidence_types: Iterable[str],
    negative_evidence_types: Iterable[str],
    confidence_tier: str,
    lifecycle_state: str,
    artifact_dominates: bool,
) -> AliasEquivalenceDecision:
    """Decide if an artist alias collision is a deterministic safe candidate.

    This is deliberately review-only. A safe candidate still requires the
    canonical alias workflow before any merge happens.
    """

    positive_types = set(positive_evidence_types)
    negative_types = set(negative_evidence_types)
    source = str(source_entity or "").strip()
    target = str(target_entity or "").strip()

    if conflict_type != "alias_collision":
        return AliasEquivalenceDecision(False, "conflict type is not alias_collision")
    if entity_role != "artist":
        return AliasEquivalenceDecision(False, "entity role is not artist")
    if not source or not target:
        return AliasEquivalenceDecision(False, "source or target alias is blank")
    if normalized_alnum_casefold(source) != normalized_alnum_casefold(target):
        return AliasEquivalenceDecision(False, "normalized alphanumeric values differ")
    if source == target:
        return AliasEquivalenceDecision(False, "aliases are already identical")
    if lifecycle_state in {"conflicted", "blocked", "deprecated"}:
        return AliasEquivalenceDecision(False, f"lifecycle state is {lifecycle_state}")
    if artifact_dominates:
        return AliasEquivalenceDecision(False, "dominant artifact evidence blocks merge")
    if "conflicting_role_pattern" in negative_types:
        return AliasEquivalenceDecision(False, "role collision evidence blocks merge")
    if "repeated_artist_metadata" not in positive_types:
        return AliasEquivalenceDecision(False, "repeated artist metadata evidence is required")
    if confidence_tier not in {"medium", "high"}:
        return AliasEquivalenceDecision(False, "confidence tier is not medium or high")

    joined = f"{source} {target}"
    if has_official_version_suffix(joined):
        return AliasEquivalenceDecision(False, "official/version suffix blocks deterministic equivalence")
    if has_collaboration_marker(joined):
        return AliasEquivalenceDecision(False, "collaboration marker blocks deterministic equivalence")
    if has_artifact_marker(joined):
        return AliasEquivalenceDecision(
            False,
            "uploader/channel/label artifact marker blocks deterministic equivalence",
        )

    return AliasEquivalenceDecision(
        True,
        "deterministic artist alias equivalence: only casing, spacing, apostrophe, "
        "hyphen, colon, or punctuation differs",
    )
