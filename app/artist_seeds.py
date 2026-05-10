"""Controlled artist seed library for artist-first track classification."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.taxonomy import (
    ClassificationResult,
    EnergyLevel,
    Mood,
    PrimaryGenre,
    Subgenre,
    VocalStyle,
    validate_taxonomy_values,
)


@dataclass(frozen=True)
class ArtistSeed:
    """Canonical artist classification seed."""

    artist: str
    primary_genre: PrimaryGenre
    subgenre: Subgenre
    energy_level: EnergyLevel
    vocal_style: VocalStyle
    mood: list[Mood]


def normalize_artist_name(value: str) -> str:
    """Normalize artist text for case- and punctuation-insensitive matching."""

    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _seed(
    artist: str,
    primary_genre: PrimaryGenre,
    subgenre: Subgenre,
    energy_level: EnergyLevel,
    vocal_style: VocalStyle,
    mood: list[Mood],
) -> ArtistSeed:
    validate_taxonomy_values(
        primary_genre=primary_genre,
        subgenre=subgenre,
        energy_level=energy_level,
        vocal_style=vocal_style,
        mood=mood,
    )
    return ArtistSeed(
        artist=artist,
        primary_genre=primary_genre,
        subgenre=subgenre,
        energy_level=energy_level,
        vocal_style=vocal_style,
        mood=mood,
    )


_SEED_ARTISTS: tuple[ArtistSeed, ...] = (
    _seed(
        "Deftones",
        "Alternative Metal",
        "Shoegaze Metal",
        "high",
        "mixed",
        ["dark", "atmospheric", "melodic"],
    ),
    _seed(
        "System of a Down",
        "Nu Metal",
        "Rap Metal",
        "extreme",
        "mixed",
        ["aggressive", "dark"],
    ),
    _seed(
        "Nothing More",
        "Hard Rock",
        "Melodic Hard Rock",
        "high",
        "mixed",
        ["emotional", "aggressive", "melodic"],
    ),
    _seed(
        "Flyleaf",
        "Alternative Rock",
        "Christian Rock",
        "high",
        "mixed",
        ["emotional", "melodic"],
    ),
    _seed(
        "The Pretty Reckless",
        "Hard Rock",
        "Melodic Hard Rock",
        "high",
        "clean",
        ["dark", "melodic"],
    ),
    _seed(
        "Halestorm",
        "Hard Rock",
        "Melodic Hard Rock",
        "high",
        "clean",
        ["aggressive", "melodic"],
    ),
    _seed(
        "Breaking Benjamin",
        "Post-Grunge",
        "Melodic Hard Rock",
        "high",
        "mixed",
        ["dark", "emotional", "melodic"],
    ),
    _seed(
        "Three Days Grace",
        "Post-Grunge",
        "Melodic Hard Rock",
        "high",
        "mixed",
        ["aggressive", "emotional", "melodic"],
    ),
    _seed(
        "Chevelle",
        "Alternative Metal",
        "Alt-Metal",
        "high",
        "mixed",
        ["dark", "melodic"],
    ),
    _seed(
        "Seether",
        "Post-Grunge",
        "Melodic Hard Rock",
        "high",
        "mixed",
        ["dark", "emotional", "melodic"],
    ),
    _seed(
        "Starset",
        "Alternative Rock",
        "Electronic Rock",
        "high",
        "mixed",
        ["atmospheric", "melodic", "emotional"],
    ),
    _seed(
        "Bad Omens",
        "Metalcore",
        "Modern Metalcore",
        "high",
        "mixed",
        ["dark", "atmospheric", "melodic"],
    ),
    _seed(
        "Spiritbox",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "mixed",
        ["dark", "atmospheric", "aggressive"],
    ),
    _seed(
        "Sleep Token",
        "Progressive Metal",
        "Progressive Rock",
        "high",
        "mixed",
        ["dark", "atmospheric", "emotional"],
    ),
    _seed(
        "Loathe",
        "Metalcore",
        "Shoegaze Metal",
        "extreme",
        "mixed",
        ["dark", "atmospheric", "aggressive"],
    ),
    _seed(
        "Architects",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "harsh",
        ["aggressive", "dark", "emotional"],
    ),
    _seed(
        "Bring Me the Horizon",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "mixed",
        ["aggressive", "dark", "melodic"],
    ),
    _seed(
        "I Prevail",
        "Metalcore",
        "Modern Metalcore",
        "high",
        "mixed",
        ["aggressive", "emotional", "melodic"],
    ),
    _seed(
        "Beartooth",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "harsh",
        ["aggressive", "emotional"],
    ),
    _seed(
        "Motionless in White",
        "Metalcore",
        "Industrial Metal",
        "extreme",
        "mixed",
        ["dark", "industrial", "aggressive"],
    ),
    _seed(
        "Falling in Reverse",
        "Metalcore",
        "Modern Metalcore",
        "high",
        "rap_mixed",
        ["aggressive", "melodic", "dark"],
    ),
    _seed(
        "From Ashes to New",
        "Nu Metal",
        "Rap Metal",
        "high",
        "rap_mixed",
        ["aggressive", "emotional", "melodic"],
    ),
    _seed(
        "Evans Blue",
        "Post-Grunge",
        "Melodic Hard Rock",
        "medium",
        "clean",
        ["emotional", "melodic", "dark"],
    ),
    _seed(
        "Red",
        "Alternative Rock",
        "Christian Rock",
        "high",
        "mixed",
        ["emotional", "dark", "melodic"],
    ),
    _seed(
        "Crossfade",
        "Post-Grunge",
        "Melodic Hard Rock",
        "high",
        "mixed",
        ["emotional", "dark", "melodic"],
    ),
    _seed(
        "10 Years",
        "Alternative Metal",
        "Alt-Metal",
        "medium",
        "clean",
        ["atmospheric", "emotional", "melodic"],
    ),
    _seed(
        "Cold",
        "Post-Grunge",
        "Melodic Hard Rock",
        "medium",
        "clean",
        ["dark", "emotional", "melodic"],
    ),
    _seed(
        "Korn",
        "Nu Metal",
        "Alt-Metal",
        "extreme",
        "mixed",
        ["dark", "aggressive"],
    ),
    _seed(
        "Slipknot",
        "Nu Metal",
        "Industrial Metal",
        "extreme",
        "harsh",
        ["aggressive", "dark", "industrial"],
    ),
    _seed(
        "Linkin Park",
        "Nu Metal",
        "Rap Metal",
        "high",
        "rap_mixed",
        ["emotional", "melodic", "aggressive"],
    ),
    _seed(
        "Papa Roach",
        "Nu Metal",
        "Rap Metal",
        "high",
        "rap_mixed",
        ["aggressive", "emotional", "melodic"],
    ),
    _seed(
        "Mudvayne",
        "Nu Metal",
        "Alt-Metal",
        "extreme",
        "mixed",
        ["aggressive", "dark"],
    ),
    _seed(
        "Static-X",
        "Industrial Rock",
        "Industrial Metal",
        "extreme",
        "harsh",
        ["industrial", "aggressive", "dark"],
    ),
    _seed(
        "P.O.D.",
        "Nu Metal",
        "Christian Rock",
        "high",
        "rap_mixed",
        ["aggressive", "melodic"],
    ),
    _seed(
        "Tool",
        "Progressive Metal",
        "Progressive Rock",
        "high",
        "mixed",
        ["dark", "atmospheric"],
    ),
    _seed(
        "A Perfect Circle",
        "Alternative Rock",
        "Progressive Rock",
        "medium",
        "clean",
        ["dark", "atmospheric", "melodic"],
    ),
    _seed(
        "Alice in Chains",
        "Grunge",
        "Grunge",
        "high",
        "mixed",
        ["dark", "melodic"],
    ),
    _seed(
        "Soundgarden",
        "Grunge",
        "Grunge",
        "high",
        "mixed",
        ["dark", "melodic"],
    ),
    _seed(
        "Stone Temple Pilots",
        "Grunge",
        "Grunge",
        "medium",
        "clean",
        ["melodic", "dark"],
    ),
    _seed(
        "Audioslave",
        "Alternative Rock",
        "Melodic Hard Rock",
        "high",
        "clean",
        ["melodic", "emotional"],
    ),
    _seed(
        "Rage Against the Machine",
        "Alternative Metal",
        "Rap Metal",
        "extreme",
        "rap_mixed",
        ["aggressive"],
    ),
    _seed(
        "Nine Inch Nails",
        "Industrial Rock",
        "Industrial Metal",
        "high",
        "mixed",
        ["industrial", "dark", "aggressive"],
    ),
    _seed(
        "Dayseeker",
        "Metalcore",
        "Post-Hardcore",
        "high",
        "mixed",
        ["emotional", "atmospheric", "melodic"],
    ),
    _seed(
        "Holding Absence",
        "Alternative Rock",
        "Post-Hardcore",
        "high",
        "mixed",
        ["emotional", "atmospheric", "melodic"],
    ),
    _seed(
        "Thornhill",
        "Metalcore",
        "Modern Metalcore",
        "high",
        "mixed",
        ["atmospheric", "dark", "melodic"],
    ),
    _seed(
        "Northlane",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "mixed",
        ["aggressive", "atmospheric", "industrial"],
    ),
    _seed(
        "Polaris",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "mixed",
        ["aggressive", "emotional", "melodic"],
    ),
    _seed(
        "ERRA",
        "Progressive Metal",
        "Modern Metalcore",
        "extreme",
        "mixed",
        ["atmospheric", "melodic", "aggressive"],
    ),
    _seed(
        "Currents",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "mixed",
        ["dark", "emotional", "aggressive"],
    ),
    _seed(
        "Fit for a King",
        "Metalcore",
        "Modern Metalcore",
        "extreme",
        "harsh",
        ["aggressive", "dark", "emotional"],
    ),
)

_ALIASES: dict[str, str] = {
    normalize_artist_name("SOAD"): "System of a Down",
    normalize_artist_name("NIN"): "Nine Inch Nails",
    normalize_artist_name("BMTH"): "Bring Me the Horizon",
    normalize_artist_name("RATM"): "Rage Against the Machine",
    normalize_artist_name("APC"): "A Perfect Circle",
}

_SEEDS_BY_ARTIST: dict[str, ArtistSeed] = {
    seed.artist: seed for seed in _SEED_ARTISTS
}

_SEEDS_BY_NORMALIZED_NAME: dict[str, ArtistSeed] = {
    normalize_artist_name(seed.artist): seed for seed in _SEED_ARTISTS
}

_SEEDS_BY_NORMALIZED_NAME.update(
    {
        normalized_alias: _SEEDS_BY_ARTIST[artist]
        for normalized_alias, artist in _ALIASES.items()
    }
)


def match_seed_artist(value: str) -> ArtistSeed | None:
    """Return the canonical seed artist for a normalized artist string."""

    return _SEEDS_BY_NORMALIZED_NAME.get(normalize_artist_name(value))


def classify_by_artist(value: str) -> ClassificationResult | None:
    """Classify a track from artist evidence when it matches a seed artist."""

    seed = match_seed_artist(value)
    if seed is None:
        return None

    return ClassificationResult(
        artist=seed.artist,
        primary_genre=seed.primary_genre,
        subgenre=seed.subgenre,
        energy_level=seed.energy_level,
        vocal_style=seed.vocal_style,
        mood=list(seed.mood),
        confidence=0.95,
        evidence=["artist_seed_match"],
    )


def list_seed_artists() -> list[ArtistSeed]:
    """Return all controlled artist seeds in canonical order."""

    return list(_SEED_ARTISTS)
