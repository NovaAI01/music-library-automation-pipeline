"""Deterministic artist-credit parsing reports for external metadata."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.data_paths import source_external_tracks_csv
from app.external_metadata import validate_source_name


REPORT_DIRNAME = "artist_credit_analysis"
SUMMARY_FILENAME = "artist_credit_summary.json"
PARSED_FILENAME = "parsed_artist_credits.csv"
PATTERNS_FILENAME = "collaboration_patterns.csv"
UNRESOLVED_FILENAME = "unresolved_artist_credits.csv"
TOP_COLLABORATORS_FILENAME = "top_collaborators.csv"

PARSED_HEADERS = (
    "source_name",
    "source_record_id",
    "raw_artist",
    "primary_artist",
    "featured_artists_json",
    "collaborating_artists_json",
    "credit_pattern",
    "confidence_score",
    "confidence_tier",
    "parser_flags_json",
    "rationale",
    "source_title",
    "source_album",
)
PATTERN_HEADERS = (
    "credit_pattern",
    "record_count",
    "percentage",
    "confidence_default",
    "recommended_future_action",
)
TOP_COLLABORATOR_HEADERS = (
    "collaborator",
    "role",
    "record_count",
    "example_primary_artist",
    "example_title",
)

FEATURE_MARKER_RE = re.compile(r"\s+(feat\.?|ft\.?|featuring)(?=\s)", re.I)
WITH_MARKER_RE = re.compile(r"\s+with\s+", re.I)
VERSUS_MARKER_RE = re.compile(r"\s+(?:vs\.?|versus)(?=\s)", re.I)
X_MARKER_RE = re.compile(r"\s+x\s+", re.I)
AMPERSAND_RE = re.compile(r"\s+(?:&|and)\s+", re.I)
COMMA_RE = re.compile(r"\s*,\s*")
PROTECTED_GROUP_SUFFIX_RE = re.compile(
    r"\s+(?:&|and)\s+"
    r"(?:"
    r"(?:his|her|their)\s+"
    r"(?:(?:[\w'.-]+\s+){0,5}(?:band|choir|ensemble|orchestra)|"
    r"(?:band|choir|ensemble|orchestra)(?:\s+[\w'.-]+){0,5})|"
    r"the\s+(?:[\w'.-]+\s+){0,5}"
    r"(?:attractions|bad\s+seeds|band|banshees|choir|ensemble|flecktones|"
    r"heartbreakers|highlanders|metrosquad|orchestra|roadburners|wailers)|"
    r"his\s+lost\s+planet\s+airmen|"
    r"(?:company|family|friends)"
    r")\s*$",
    re.I,
)
SOURCE_ARTIFACT_RE = re.compile(
    r"\b(?:youtube|soundcloud|bandcamp|archive|uploader|uploads?|channel|topic|"
    r"vevo|auto-generated|provided to youtube|official channel|records?|"
    r"recordings|entertainment|label)\b",
    re.I,
)
TITLE_POLLUTION_RE = re.compile(
    r"\b(?:official\s+(?:audio|video|music video|visualizer)|music video|"
    r"lyric video|lyrics video|audio only|remaster(?:ed)?|radio edit|"
    r"explicit|clean|single version|album version|live version)\b",
    re.I,
)
BRACKET_RE = re.compile(r"[\[\](){}]")
COLLECTIVE_SUFFIXES = {
    "band",
    "brothers",
    "choir",
    "collective",
    "crew",
    "ensemble",
    "family",
    "friends",
    "gang",
    "heartbreakers",
    "orchestra",
    "quartet",
    "quintet",
    "sons",
    "trio",
    "wailers",
}

CREDIT_PATTERNS = (
    "solo_artist",
    "feat_artist",
    "ft_artist",
    "featuring_artist",
    "with_artist",
    "versus_artist",
    "x_collaboration",
    "ampersand_collaboration",
    "comma_collaboration",
    "multi_artist_credit",
    "unknown_or_ambiguous",
)


@dataclass(frozen=True)
class ArtistCreditInputRecord:
    source_name: str
    source_record_id: str
    artist: str
    album: str
    title: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ArtistCreditInputRecord":
        return cls(
            source_name=_clean_string(row.get("source_name")),
            source_record_id=_clean_string(row.get("source_record_id")),
            artist=_clean_string(row.get("artist")),
            album=_clean_string(row.get("album")),
            title=_clean_string(row.get("title")),
        )


@dataclass(frozen=True)
class ParsedArtistCredit:
    source_name: str
    source_record_id: str
    raw_artist: str
    primary_artist: str
    featured_artists: tuple[str, ...]
    collaborating_artists: tuple[str, ...]
    credit_pattern: str
    confidence_score: float
    confidence_tier: str
    parser_flags: tuple[str, ...]
    rationale: str
    source_title: str
    source_album: str

    def to_row(self) -> dict[str, str]:
        return {
            "source_name": self.source_name,
            "source_record_id": self.source_record_id,
            "raw_artist": self.raw_artist,
            "primary_artist": self.primary_artist,
            "featured_artists_json": _json_dumps(list(self.featured_artists)),
            "collaborating_artists_json": _json_dumps(list(self.collaborating_artists)),
            "credit_pattern": self.credit_pattern,
            "confidence_score": f"{self.confidence_score:.2f}",
            "confidence_tier": self.confidence_tier,
            "parser_flags_json": _json_dumps(list(self.parser_flags)),
            "rationale": self.rationale,
            "source_title": self.source_title,
            "source_album": self.source_album,
        }


@dataclass(frozen=True)
class ArtistCreditAnalysisResult:
    source_name: str
    total_records: int
    parsed_records: int
    solo_artist_count: int
    collaboration_count: int
    featured_artist_count: int
    unresolved_count: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    top_pattern: str
    report_path: str
    output_csv: str
    unresolved_csv: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "total_records": self.total_records,
            "parsed_records": self.parsed_records,
            "solo_artist_count": self.solo_artist_count,
            "collaboration_count": self.collaboration_count,
            "featured_artist_count": self.featured_artist_count,
            "unresolved_count": self.unresolved_count,
            "high_confidence_count": self.high_confidence_count,
            "medium_confidence_count": self.medium_confidence_count,
            "low_confidence_count": self.low_confidence_count,
            "top_pattern": self.top_pattern,
            "output_csv": self.output_csv,
            "unresolved_csv": self.unresolved_csv,
        }


def analyze_artist_credits(
    source_name: str,
    out_dir: str | Path = "reports",
    data_dir: str | Path | None = None,
    limit: int | None = None,
) -> ArtistCreditAnalysisResult:
    source_name = validate_source_name(source_name)
    out_dir = Path(out_dir)
    input_csv = source_external_tracks_csv(source_name, data_dir)
    records = _read_external_records(input_csv, limit=limit)
    parsed = [parse_artist_credit(record) for record in records]

    report_dir = out_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    parsed_path = report_dir / PARSED_FILENAME
    unresolved_path = report_dir / UNRESOLVED_FILENAME
    patterns_path = report_dir / PATTERNS_FILENAME
    top_collaborators_path = report_dir / TOP_COLLABORATORS_FILENAME

    unresolved = [row for row in parsed if _is_unresolved(row)]
    _write_parsed(parsed_path, parsed)
    _write_parsed(unresolved_path, unresolved)
    _write_patterns(patterns_path, parsed)
    _write_top_collaborators(top_collaborators_path, parsed)

    pattern_counts = Counter(row.credit_pattern for row in parsed)
    top_pattern = ""
    if pattern_counts:
        top_pattern = sorted(
            pattern_counts.items(),
            key=lambda item: (-item[1], CREDIT_PATTERNS.index(item[0])),
        )[0][0]
    result = ArtistCreditAnalysisResult(
        source_name=source_name,
        total_records=len(records),
        parsed_records=sum(1 for row in parsed if row.primary_artist),
        solo_artist_count=pattern_counts["solo_artist"],
        collaboration_count=sum(
            count
            for pattern, count in pattern_counts.items()
            if pattern
            in {
                "with_artist",
                "versus_artist",
                "x_collaboration",
                "ampersand_collaboration",
                "comma_collaboration",
                "multi_artist_credit",
            }
        ),
        featured_artist_count=sum(
            1 for row in parsed if row.credit_pattern in {"feat_artist", "ft_artist", "featuring_artist"}
        ),
        unresolved_count=len(unresolved),
        high_confidence_count=sum(1 for row in parsed if row.confidence_tier == "high"),
        medium_confidence_count=sum(1 for row in parsed if row.confidence_tier == "medium"),
        low_confidence_count=sum(1 for row in parsed if row.confidence_tier == "low"),
        top_pattern=top_pattern,
        report_path=str(report_dir),
        output_csv=str(parsed_path),
        unresolved_csv=str(unresolved_path),
    )
    (report_dir / SUMMARY_FILENAME).write_text(
        json.dumps(result.to_summary(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_artist_credit(record: ArtistCreditInputRecord) -> ParsedArtistCredit:
    raw_artist = _clean_string(record.artist)
    flags = _quality_flags(raw_artist, record.title, record.album)
    if not raw_artist:
        return _parsed(
            record,
            primary_artist="",
            featured_artists=(),
            collaborating_artists=(),
            credit_pattern="unknown_or_ambiguous",
            confidence_score=0.10,
            confidence_tier="low",
            parser_flags=flags + ("empty_artist",),
            rationale="Artist credit is empty.",
        )
    if flags:
        return _parsed(
            record,
            primary_artist="",
            featured_artists=(),
            collaborating_artists=(),
            credit_pattern="unknown_or_ambiguous",
            confidence_score=0.20,
            confidence_tier="low",
            parser_flags=flags,
            rationale="Artist credit contains source artifacts or title-like pollution.",
        )

    feature_match = FEATURE_MARKER_RE.search(raw_artist)
    if feature_match:
        left = raw_artist[: feature_match.start()]
        right = raw_artist[feature_match.end() :]
        primary, featured = _split_primary_and_others(left, right)
        marker = feature_match.group(1).casefold().rstrip(".")
        pattern = "featuring_artist" if marker == "featuring" else f"{marker}_artist"
        if primary and featured and _clean_names((primary, *featured)):
            return _parsed(
                record,
                primary_artist=primary,
                featured_artists=tuple(featured),
                collaborating_artists=(),
                credit_pattern=pattern,
                confidence_score=0.95,
                confidence_tier="high",
                parser_flags=("explicit_feature_marker",),
                rationale="Explicit feature marker separates a primary artist from featured artists.",
            )

    protected_group = _protected_group_name(record, raw_artist)
    if protected_group:
        return protected_group

    marker_specs = (
        (WITH_MARKER_RE, "with_artist", 0.72, "with marker separates collaborators"),
        (VERSUS_MARKER_RE, "versus_artist", 0.70, "versus marker separates collaborators"),
        (X_MARKER_RE, "x_collaboration", 0.68, "x marker separates collaborators"),
        (AMPERSAND_RE, "ampersand_collaboration", 0.65, "ampersand or and marker separates collaborators"),
    )
    for marker_re, pattern, score, rationale in marker_specs:
        parts = _split_on_regex(raw_artist, marker_re)
        if len(parts) > 1:
            if _looks_like_collective(raw_artist, parts) or not _clean_names(parts):
                return _ambiguous(
                    record,
                    "artist credit may be a collective or band name",
                    flags=("possible_group_name", "ambiguous_separator"),
                    score=0.35,
                    tier="low",
                )
            return _collaboration(record, parts, pattern, score, rationale)

    comma_parts = [part.strip() for part in COMMA_RE.split(raw_artist) if part.strip()]
    if len(comma_parts) > 1:
        if _looks_like_collective(raw_artist, comma_parts) or not _clean_names(comma_parts):
            return _ambiguous(
                record,
                "comma-separated artist credit may be a group name or multi-artist credit",
                flags=("possible_group_name", "ambiguous_separator"),
                score=0.45,
                tier="medium",
            )
        if len(comma_parts) > 2:
            return _collaboration(
                record,
                comma_parts,
                "multi_artist_credit",
                0.60,
                "multi-artist comma credit contains clean names",
            )
        return _collaboration(
            record,
            comma_parts,
            "comma_collaboration",
            0.62,
            "comma-separated artist credit contains clean names",
        )

    if _has_unhandled_separator(raw_artist):
        return _ambiguous(record, "artist credit contains an unsupported or unreliable separator")

    if not _is_clean_name(raw_artist):
        return _ambiguous(record, "artist credit is malformed or too sparse")

    return _parsed(
        record,
        primary_artist=raw_artist,
        featured_artists=(),
        collaborating_artists=(),
        credit_pattern="solo_artist",
        confidence_score=0.90,
        confidence_tier="high",
        parser_flags=(),
        rationale="No collaboration marker detected; clean artist name preserved as solo artist.",
    )


def _collaboration(
    record: ArtistCreditInputRecord,
    parts: list[str],
    pattern: str,
    score: float,
    rationale: str,
) -> ParsedArtistCredit:
    return _parsed(
        record,
        primary_artist=parts[0],
        featured_artists=(),
        collaborating_artists=tuple(parts[1:]),
        credit_pattern=pattern,
        confidence_score=score,
        confidence_tier="medium",
        parser_flags=("collaboration_marker",),
        rationale=rationale,
    )


def _ambiguous(
    record: ArtistCreditInputRecord,
    rationale: str,
    flags: tuple[str, ...] = (),
    score: float = 0.25,
    tier: str = "low",
) -> ParsedArtistCredit:
    return _parsed(
        record,
        primary_artist="",
        featured_artists=(),
        collaborating_artists=(),
        credit_pattern="unknown_or_ambiguous",
        confidence_score=score,
        confidence_tier=tier,
        parser_flags=("ambiguous_credit",) + flags,
        rationale=rationale,
    )


def _parsed(
    record: ArtistCreditInputRecord,
    primary_artist: str,
    featured_artists: tuple[str, ...],
    collaborating_artists: tuple[str, ...],
    credit_pattern: str,
    confidence_score: float,
    confidence_tier: str,
    parser_flags: tuple[str, ...],
    rationale: str,
) -> ParsedArtistCredit:
    return ParsedArtistCredit(
        source_name=record.source_name,
        source_record_id=record.source_record_id,
        raw_artist=record.artist,
        primary_artist=primary_artist,
        featured_artists=featured_artists,
        collaborating_artists=collaborating_artists,
        credit_pattern=credit_pattern,
        confidence_score=confidence_score,
        confidence_tier=confidence_tier,
        parser_flags=tuple(sorted(set(parser_flags))),
        rationale=rationale,
        source_title=record.title,
        source_album=record.album,
    )


def _split_primary_and_others(left: str, right: str) -> tuple[str, list[str]]:
    primary = left.strip()
    others = _split_secondary_names(right)
    return primary, others


def _split_secondary_names(value: str) -> list[str]:
    parts = COMMA_RE.split(value)
    expanded: list[str] = []
    for part in parts:
        expanded.extend(_split_on_regex(part, AMPERSAND_RE))
    return [part.strip() for part in expanded if part.strip()]


def _split_on_regex(value: str, pattern: re.Pattern[str]) -> list[str]:
    return [part.strip() for part in pattern.split(value) if part.strip()]


def _protected_group_name(
    record: ArtistCreditInputRecord,
    raw_artist: str,
) -> ParsedArtistCredit | None:
    if PROTECTED_GROUP_SUFFIX_RE.search(raw_artist):
        return _parsed(
            record,
            primary_artist=raw_artist,
            featured_artists=(),
            collaborating_artists=(),
            credit_pattern="solo_artist",
            confidence_score=0.88,
            confidence_tier="high",
            parser_flags=("protected_group_name",),
            rationale="Protected group-name suffix detected; artist credit preserved as a single group name.",
        )
    if _has_comma_and_ampersand_group_boundary(raw_artist):
        return _parsed(
            record,
            primary_artist=raw_artist,
            featured_artists=(),
            collaborating_artists=(),
            credit_pattern="solo_artist",
            confidence_score=0.55,
            confidence_tier="medium",
            parser_flags=("protected_group_name", "possible_group_name", "ambiguous_separator"),
            rationale="Comma plus ampersand boundary can be a canonical group name; preserved without collaborator splitting.",
        )
    return None


def _quality_flags(raw_artist: str, title: str, album: str) -> tuple[str, ...]:
    flags: list[str] = []
    combined = " ".join(part for part in (raw_artist, title, album) if part)
    if SOURCE_ARTIFACT_RE.search(raw_artist):
        flags.append("source_artifact")
    if TITLE_POLLUTION_RE.search(raw_artist):
        flags.append("title_like_pollution")
    if BRACKET_RE.search(raw_artist) and TITLE_POLLUTION_RE.search(combined):
        flags.append("punctuation_unreliable")
    return tuple(flags)


def _looks_like_collective(raw_artist: str, parts: list[str]) -> bool:
    lowered = [part.casefold().strip(" .") for part in parts]
    if "," in raw_artist and ("&" in raw_artist or " and " in raw_artist.casefold()):
        return True
    if len(parts) > 2 and ("&" in raw_artist or " and " in raw_artist.casefold()):
        return True
    last_tokens = lowered[-1].split()
    if lowered[-1] in COLLECTIVE_SUFFIXES or (
        last_tokens and last_tokens[-1] in COLLECTIVE_SUFFIXES
    ):
        return True
    if any(part.startswith("the ") and part.split()[-1] in COLLECTIVE_SUFFIXES for part in lowered):
        return True
    return False


def _has_comma_and_ampersand_group_boundary(raw_artist: str) -> bool:
    if "," not in raw_artist:
        return False
    if not ("&" in raw_artist or " and " in raw_artist.casefold()):
        return False
    parts = [part.strip() for part in COMMA_RE.split(raw_artist) if part.strip()]
    return len(parts) >= 2 and all(_is_clean_name(part) for part in parts)


def _clean_names(parts: Iterable[str]) -> bool:
    return all(_is_clean_name(part) for part in parts)


def _is_clean_name(value: str) -> bool:
    normalized = _clean_string(value)
    if not normalized:
        return False
    if len(normalized) == 1:
        return False
    if normalized.count("/") > 0 or normalized.count("\\") > 0:
        return False
    if TITLE_POLLUTION_RE.search(normalized) or SOURCE_ARTIFACT_RE.search(normalized):
        return False
    return True


def _has_unhandled_separator(value: str) -> bool:
    return bool(re.search(r"\s[/+]\s|;|\s\|\s", value))


def _is_unresolved(row: ParsedArtistCredit) -> bool:
    return row.credit_pattern == "unknown_or_ambiguous" or not row.primary_artist


def _read_external_records(
    input_csv: Path,
    limit: int | None = None,
) -> list[ArtistCreditInputRecord]:
    if not input_csv.exists():
        return []
    records: list[ArtistCreditInputRecord] = []
    with input_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            records.append(ArtistCreditInputRecord.from_row(row))
            if limit is not None and len(records) >= limit:
                break
    return records


def _write_parsed(path: Path, rows: Iterable[ParsedArtistCredit]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PARSED_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_row())


def _write_patterns(path: Path, rows: list[ParsedArtistCredit]) -> None:
    total = len(rows)
    counts = Counter(row.credit_pattern for row in rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PATTERN_HEADERS)
        writer.writeheader()
        for pattern in CREDIT_PATTERNS:
            count = counts[pattern]
            if count == 0:
                continue
            writer.writerow(
                {
                    "credit_pattern": pattern,
                    "record_count": str(count),
                    "percentage": f"{((count / total) * 100 if total else 0):.2f}",
                    "confidence_default": _default_confidence(pattern),
                    "recommended_future_action": _recommended_future_action(pattern),
                }
            )


def _write_top_collaborators(path: Path, rows: list[ParsedArtistCredit]) -> None:
    counts: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], tuple[str, str]] = {}
    for row in rows:
        for collaborator in row.featured_artists:
            key = (collaborator, "featured")
            counts[key] += 1
            examples.setdefault(key, (row.primary_artist, row.source_title))
        for collaborator in row.collaborating_artists:
            key = (collaborator, "collaborator")
            counts[key] += 1
            examples.setdefault(key, (row.primary_artist, row.source_title))

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0][1], item[0][0].casefold()))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TOP_COLLABORATOR_HEADERS)
        writer.writeheader()
        for (collaborator, role), count in ordered:
            example_primary, example_title = examples[(collaborator, role)]
            writer.writerow(
                {
                    "collaborator": collaborator,
                    "role": role,
                    "record_count": str(count),
                    "example_primary_artist": example_primary,
                    "example_title": example_title,
                }
            )


def _default_confidence(pattern: str) -> str:
    if pattern in {"solo_artist", "feat_artist", "ft_artist", "featuring_artist"}:
        return "high"
    if pattern in {
        "with_artist",
        "versus_artist",
        "x_collaboration",
        "ampersand_collaboration",
        "comma_collaboration",
        "multi_artist_credit",
    }:
        return "medium"
    return "low"


def _recommended_future_action(pattern: str) -> str:
    actions = {
        "solo_artist": "Keep as single artist evidence after normal canonical review.",
        "feat_artist": "Use as featured-artist role evidence after reviewed graph integration.",
        "ft_artist": "Use as featured-artist role evidence after reviewed graph integration.",
        "featuring_artist": "Use as featured-artist role evidence after reviewed graph integration.",
        "with_artist": "Review as collaboration role evidence before graph integration.",
        "versus_artist": "Review as collaboration role evidence before graph integration.",
        "x_collaboration": "Review as collaboration role evidence before graph integration.",
        "ampersand_collaboration": "Review for possible band-name ambiguity before graph integration.",
        "comma_collaboration": "Review for possible multi-artist credit before graph integration.",
        "multi_artist_credit": "Review as a multi-artist credit before graph integration.",
        "unknown_or_ambiguous": "Preserve unresolved until manual review or stronger source evidence exists.",
    }
    return actions[pattern]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
