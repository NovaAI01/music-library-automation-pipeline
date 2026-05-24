"""Filename evidence parser for observed audio files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FilenameObservation:
    cleaned_filename: str
    possible_artist: str | None
    possible_title: str | None
    possible_mix: str | None
    possible_track_number: str | None
    filename_pattern: str
    parser_confidence: float


TRACK_ARTIST_TITLE = re.compile(
    r"^(?P<track>\d{1,3})\s+-\s+(?P<artist>.+?)\s+-\s+(?P<title>.+)$"
)
TRACK_TITLE_DASH = re.compile(r"^(?P<track>\d{1,3})\s+-\s+(?P<title>.+)$")
TRACK_TITLE_DOT = re.compile(r"^(?P<track>\d{1,3})\.\s+(?P<title>.+)$")
TRACK_WORD_TITLE = re.compile(
    r"^Track\s+(?P<track>\d{1,3})\s+-\s+(?P<title>.+)$",
    re.IGNORECASE,
)
ARTIST_TITLE = re.compile(r"^(?P<artist>.+?)\s+-\s+(?P<title>.+)$")
TRACK_TITLE = re.compile(r"^(?P<track>\d{1,3})\s+(?P<title>.+)$")
MIX_SUFFIX = re.compile(r"^(?P<title>.+?)\s*\((?P<mix>[^)]+)\)$")


def parse_filename(value: str | Path) -> FilenameObservation:
    """Parse known filename patterns into conservative evidence fields."""

    cleaned = _clean_filename(value)

    match = TRACK_ARTIST_TITLE.match(cleaned)
    if match:
        title, mix = _split_mix(match.group("title"))
        return FilenameObservation(
            cleaned_filename=cleaned,
            possible_artist=match.group("artist").strip(),
            possible_title=title,
            possible_mix=mix,
            possible_track_number=match.group("track"),
            filename_pattern="track_artist_title",
            parser_confidence=0.9,
        )

    for pattern in (TRACK_TITLE_DASH, TRACK_TITLE_DOT, TRACK_WORD_TITLE):
        match = pattern.match(cleaned)
        if match:
            title, mix = _split_mix(match.group("title"))
            return FilenameObservation(
                cleaned_filename=cleaned,
                possible_artist=None,
                possible_title=title,
                possible_mix=mix,
                possible_track_number=match.group("track"),
                filename_pattern="track_title",
                parser_confidence=0.65,
            )

    match = ARTIST_TITLE.match(cleaned)
    if match:
        title, mix = _split_mix(match.group("title"))
        return FilenameObservation(
            cleaned_filename=cleaned,
            possible_artist=match.group("artist").strip(),
            possible_title=title,
            possible_mix=mix,
            possible_track_number=None,
            filename_pattern="artist_title_with_mix" if mix else "artist_title",
            parser_confidence=0.85 if mix else 0.8,
        )

    match = TRACK_TITLE.match(cleaned)
    if match:
        title, mix = _split_mix(match.group("title"))
        return FilenameObservation(
            cleaned_filename=cleaned,
            possible_artist=None,
            possible_title=title,
            possible_mix=mix,
            possible_track_number=match.group("track"),
            filename_pattern="track_title",
            parser_confidence=0.65,
        )

    return FilenameObservation(
        cleaned_filename=cleaned,
        possible_artist=None,
        possible_title=cleaned or None,
        possible_mix=None,
        possible_track_number=None,
        filename_pattern="unknown",
        parser_confidence=0.2,
    )


def _clean_filename(value: str | Path) -> str:
    path = Path(value)
    name = path.name if path.suffix else str(value)
    stem = Path(name).stem
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip()


def _split_mix(title: str) -> tuple[str, str | None]:
    match = MIX_SUFFIX.match(title.strip())
    if not match:
        return title.strip(), None
    return match.group("title").strip(), match.group("mix").strip()
