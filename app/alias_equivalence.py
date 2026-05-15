"""Deterministic safe equivalence checks for artist and album names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


_OFFICIAL_SUFFIX_RE = re.compile(
    r"\b(?:official\s+(?:audio|video)|remaster(?:ed)?|live|acoustic|explicit|edit|"
    r"deluxe|special\s+edition|anniversary\s+edition)\b",
    re.I,
)
_COLLABORATION_RE = re.compile(r"(?:,|\b(?:ft\.?|feat\.?|featuring)\b)", re.I)
_ARTIFACT_MARKER_RE = re.compile(
    r"\b(?:uploader|uploads?|channel|topic|label|records?|recordings|vevo|"
    r"official\s+artist\s+channel|provided\s+to\s+youtube|auto-generated|youtube)\b",
    re.I,
)
_SOURCE_JOIN_RE = re.compile(r"\s+(?:-|--|/)\s+")
_SAFE_ALBUM_PUNCTUATION_RE = re.compile(r"^[\w\s:.'’`…-]+$", re.UNICODE)


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


def normalized_safe_album_title(value: Any) -> str:
    """Normalize album titles for safe punctuation-only equivalence checks."""

    text = str(value or "").casefold()
    text = text.replace("’", "'").replace("`", "'").replace("…", "")
    text = re.sub(r"\.{2,}", "", text)
    text = re.sub(r"[:.'\-\s]+", "", text)
    return "".join(char for char in text if char.isalnum())


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


def deterministic_album_title_equivalence(
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
    """Decide if an album membership conflict is a safe album-title candidate."""

    positive_types = set(positive_evidence_types)
    negative_types = set(negative_evidence_types)
    source = str(source_entity or "").strip()
    target = str(target_entity or "").strip()

    if conflict_type != "album_membership_conflict":
        return AliasEquivalenceDecision(False, "conflict type is not album_membership_conflict")
    if entity_role != "album":
        return AliasEquivalenceDecision(False, "entity role is not album")
    if not source or not target:
        return AliasEquivalenceDecision(False, "source or target album title is blank")
    if source == target:
        return AliasEquivalenceDecision(False, "album titles are already identical")
    if normalized_safe_album_title(source) != normalized_safe_album_title(target):
        return AliasEquivalenceDecision(False, "safe punctuation-normalized album titles differ")
    if not (_SAFE_ALBUM_PUNCTUATION_RE.match(source) and _SAFE_ALBUM_PUNCTUATION_RE.match(target)):
        return AliasEquivalenceDecision(False, "album title difference includes unsupported punctuation")
    if lifecycle_state in {"conflicted", "blocked", "deprecated"}:
        return AliasEquivalenceDecision(False, f"lifecycle state is {lifecycle_state}")
    if artifact_dominates:
        return AliasEquivalenceDecision(False, "dominant artifact evidence blocks merge")
    if confidence_tier not in {"medium", "high"}:
        return AliasEquivalenceDecision(False, "confidence tier is not medium or high")
    if not (positive_types & {"repeated_album_metadata", "canonical_role_agreement"}):
        return AliasEquivalenceDecision(
            False,
            "repeated album metadata or canonical role agreement evidence is required",
        )
    if "weak_album_cohesion" in negative_types:
        return AliasEquivalenceDecision(False, "weak album cohesion blocks deterministic equivalence")
    if "conflicting_role_pattern" in negative_types:
        return AliasEquivalenceDecision(False, "role collision evidence blocks merge")

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
    if _looks_like_artist_album_combined(source, target):
        return AliasEquivalenceDecision(False, "artist plus album combined form blocks deterministic equivalence")

    return AliasEquivalenceDecision(
        True,
        "deterministic album title equivalence: only spacing, apostrophe, hyphen, "
        "colon, ellipsis, or punctuation differs",
    )


def _looks_like_artist_album_combined(source: str, target: str) -> bool:
    for left, right in ((source, target), (target, source)):
        parts = _SOURCE_JOIN_RE.split(left, maxsplit=1)
        if len(parts) != 2:
            continue
        prefix, title = (part.strip() for part in parts)
        if len(prefix.split()) >= 2 and normalized_safe_album_title(title) == normalized_safe_album_title(right):
            return True
    return False
