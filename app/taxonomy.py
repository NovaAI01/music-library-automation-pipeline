"""Controlled taxonomy for music-library classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PrimaryGenre = Literal[
    "Alternative Metal",
    "Nu Metal",
    "Post-Grunge",
    "Hard Rock",
    "Metalcore",
    "Progressive Metal",
    "Industrial Rock",
    "Grunge",
    "Alternative Rock",
]

Subgenre = Literal[
    "Shoegaze Metal",
    "Rap Metal",
    "Christian Rock",
    "Electronic Rock",
    "Modern Metalcore",
    "Post-Hardcore",
    "Industrial Metal",
    "Progressive Rock",
    "Grunge",
    "Alt-Metal",
    "Melodic Hard Rock",
]

EnergyLevel = Literal["medium", "high", "extreme"]

VocalStyle = Literal["clean", "mixed", "harsh", "rap_mixed"]

Mood = Literal[
    "dark",
    "aggressive",
    "melodic",
    "atmospheric",
    "emotional",
    "industrial",
]


PRIMARY_GENRES: frozenset[str] = frozenset(
    {
        "Alternative Metal",
        "Nu Metal",
        "Post-Grunge",
        "Hard Rock",
        "Metalcore",
        "Progressive Metal",
        "Industrial Rock",
        "Grunge",
        "Alternative Rock",
    }
)

SUBGENRES: frozenset[str] = frozenset(
    {
        "Shoegaze Metal",
        "Rap Metal",
        "Christian Rock",
        "Electronic Rock",
        "Modern Metalcore",
        "Post-Hardcore",
        "Industrial Metal",
        "Progressive Rock",
        "Grunge",
        "Alt-Metal",
        "Melodic Hard Rock",
    }
)

ENERGY_LEVELS: frozenset[str] = frozenset({"medium", "high", "extreme"})

VOCAL_STYLES: frozenset[str] = frozenset(
    {"clean", "mixed", "harsh", "rap_mixed"}
)

MOODS: frozenset[str] = frozenset(
    {
        "dark",
        "aggressive",
        "melodic",
        "atmospheric",
        "emotional",
        "industrial",
    }
)


@dataclass(frozen=True)
class ClassificationResult:
    """Classification output for a matched music-library entity."""

    artist: str
    primary_genre: PrimaryGenre
    subgenre: Subgenre
    energy_level: EnergyLevel
    vocal_style: VocalStyle
    mood: list[Mood]
    confidence: float
    evidence: list[str]


def validate_taxonomy_values(
    *,
    primary_genre: str,
    subgenre: str,
    energy_level: str,
    vocal_style: str,
    mood: list[str],
) -> None:
    """Raise ValueError when a classification uses uncontrolled taxonomy."""

    if primary_genre not in PRIMARY_GENRES:
        raise ValueError(f"Unknown primary_genre: {primary_genre}")
    if subgenre not in SUBGENRES:
        raise ValueError(f"Unknown subgenre: {subgenre}")
    if energy_level not in ENERGY_LEVELS:
        raise ValueError(f"Unknown energy_level: {energy_level}")
    if vocal_style not in VOCAL_STYLES:
        raise ValueError(f"Unknown vocal_style: {vocal_style}")

    unknown_moods = [value for value in mood if value not in MOODS]
    if unknown_moods:
        raise ValueError(f"Unknown mood values: {unknown_moods}")
