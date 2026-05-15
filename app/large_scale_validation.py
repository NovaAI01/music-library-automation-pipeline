"""Read-only cohort validation for ingested external metadata."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.external_metadata import EXTERNAL_TRACK_FIELDS, validate_source_name


REPORT_DIRNAME = "large_scale_validation"
SUMMARY_FILENAME = "validation_summary.json"
COHORTS_FILENAME = "validation_cohorts.csv"
EXAMPLES_FILENAME = "cohort_examples.csv"
HIGH_PRIORITY_FILENAME = "high_priority_cohorts.csv"
SOURCE_QUALITY_FILENAME = "source_quality_report.csv"

COHORT_TYPES = (
    "missing_artist",
    "missing_album",
    "missing_title",
    "casing_alias_candidate",
    "album_title_punctuation_variant",
    "collaboration_string",
    "source_artifact_candidate",
    "official_audio_video_noise",
    "remaster_version_noise",
    "explicit_clean_radio_edit_noise",
    "possible_track_as_artist",
    "possible_album_as_artist",
    "sparse_record",
    "duplicate_external_record",
    "malformed_duration",
    "malformed_year",
)

COHORT_HEADERS = (
    "cohort_key",
    "cohort_type",
    "record_count",
    "severity",
    "recommended_action",
    "rationale",
)
EXAMPLE_HEADERS = (
    "cohort_key",
    "source_record_id",
    "artist",
    "album",
    "title",
    "label",
    "source_url",
    "rationale",
)
QUALITY_HEADERS = ("metric", "value")

_COLLABORATION_RE = re.compile(
    r"(?:\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\bwith\b|\sx\s|/|,|\s&\s)",
    re.I,
)
_SOURCE_ARTIFACT_RE = re.compile(
    r"\b(?:youtube|soundcloud|bandcamp|archive|uploader|uploads?|channel|topic|"
    r"vevo|auto-generated|provided to youtube|official channel|records?|"
    r"recordings|entertainment|label)\b",
    re.I,
)
_OFFICIAL_AUDIO_VIDEO_RE = re.compile(
    r"\b(?:official\s+(?:audio|video|music video|visualizer)|music video|"
    r"lyric video|lyrics video|audio only)\b",
    re.I,
)
_REMASTER_RE = re.compile(
    r"\b(?:remaster(?:ed)?|anniversary|deluxe|expanded edition|bonus track|"
    r"single version|album version|live version|version)\b",
    re.I,
)
_EXPLICIT_CLEAN_RE = re.compile(
    r"\b(?:explicit|clean|radio edit|edited version|censored)\b",
    re.I,
)
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class ExternalValidationRecord:
    source_name: str
    source_record_id: str
    artist: str
    album: str
    title: str
    track_number: str
    release_year: str
    label: str
    duration_seconds: str
    genre: str
    source_url: str
    raw_payload_json: str
    ingested_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ExternalValidationRecord":
        values = {field: _clean_string(row.get(field)) for field in EXTERNAL_TRACK_FIELDS}
        return cls(**values)

    def to_example(self, cohort_key: str, rationale: str) -> dict[str, str]:
        return {
            "cohort_key": cohort_key,
            "source_record_id": self.source_record_id,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "label": self.label,
            "source_url": self.source_url,
            "rationale": rationale,
        }


@dataclass(frozen=True)
class ValidationCohort:
    cohort_key: str
    cohort_type: str
    record_count: int
    severity: str
    recommended_action: str
    rationale: str

    def to_row(self) -> dict[str, str]:
        return {
            "cohort_key": self.cohort_key,
            "cohort_type": self.cohort_type,
            "record_count": str(self.record_count),
            "severity": self.severity,
            "recommended_action": self.recommended_action,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class LargeScaleValidationResult:
    source_name: str
    total_records: int
    total_cohorts: int
    high_priority_cohorts: int
    missing_artist_count: int
    missing_album_count: int
    missing_title_count: int
    collaboration_string_count: int
    source_artifact_candidate_count: int
    official_audio_video_noise_count: int
    remaster_version_noise_count: int
    duplicate_external_record_count: int
    malformed_record_count: int
    report_path: str
    input_csv: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "total_records": self.total_records,
            "total_cohorts": self.total_cohorts,
            "high_priority_cohorts": self.high_priority_cohorts,
            "missing_artist_count": self.missing_artist_count,
            "missing_album_count": self.missing_album_count,
            "missing_title_count": self.missing_title_count,
            "collaboration_string_count": self.collaboration_string_count,
            "source_artifact_candidate_count": self.source_artifact_candidate_count,
            "official_audio_video_noise_count": self.official_audio_video_noise_count,
            "remaster_version_noise_count": self.remaster_version_noise_count,
            "duplicate_external_record_count": self.duplicate_external_record_count,
            "malformed_record_count": self.malformed_record_count,
            "input_csv": self.input_csv,
        }


def validate_external_metadata(
    source_name: str,
    out_dir: str | Path = "reports",
    data_dir: str | Path = "data",
) -> LargeScaleValidationResult:
    source_name = validate_source_name(source_name)
    out_dir = Path(out_dir)
    data_dir = Path(data_dir)
    input_csv = data_dir / "external_metadata" / source_name / "external_tracks.csv"
    records = _read_external_records(input_csv)
    cohorts, examples = analyze_external_metadata_records(records)

    report_dir = out_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_cohorts(report_dir / COHORTS_FILENAME, cohorts)
    _write_cohorts(
        report_dir / HIGH_PRIORITY_FILENAME,
        [cohort for cohort in cohorts if cohort.severity == "high"],
    )
    _write_examples(report_dir / EXAMPLES_FILENAME, examples)

    counts = _summary_counts(records, cohorts)
    result = LargeScaleValidationResult(
        source_name=source_name,
        total_records=len(records),
        total_cohorts=len(cohorts),
        high_priority_cohorts=sum(1 for cohort in cohorts if cohort.severity == "high"),
        report_path=str(report_dir),
        input_csv=str(input_csv),
        **counts,
    )
    summary = result.to_summary()
    (report_dir / SUMMARY_FILENAME).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_source_quality_report(report_dir / SOURCE_QUALITY_FILENAME, summary)
    return result


def analyze_external_metadata_records(
    records: list[ExternalValidationRecord],
) -> tuple[list[ValidationCohort], list[dict[str, str]]]:
    groups: dict[str, list[tuple[ExternalValidationRecord, str]]] = defaultdict(list)

    _add_simple_quality_groups(records, groups)
    _add_pattern_groups(records, groups)
    _add_variant_groups(records, groups)
    _add_cross_field_groups(records, groups)
    _add_duplicate_groups(records, groups)

    cohorts: list[ValidationCohort] = []
    examples: list[dict[str, str]] = []
    for cohort_key in sorted(groups):
        records_with_rationale = groups[cohort_key]
        cohort_type = cohort_key.split(":", 1)[0]
        cohort = ValidationCohort(
            cohort_key=cohort_key,
            cohort_type=cohort_type,
            record_count=len(records_with_rationale),
            severity=_severity_for(cohort_type, len(records_with_rationale)),
            recommended_action=_recommended_action_for(cohort_type),
            rationale=_rationale_for(cohort_type),
        )
        cohorts.append(cohort)
        for record, rationale in records_with_rationale[:5]:
            examples.append(record.to_example(cohort_key, rationale))

    return cohorts, examples


def _add_simple_quality_groups(
    records: list[ExternalValidationRecord],
    groups: dict[str, list[tuple[ExternalValidationRecord, str]]],
) -> None:
    for record in records:
        if not record.artist:
            groups["missing_artist"].append((record, "artist is empty"))
        if not record.album:
            groups["missing_album"].append((record, "album is empty"))
        if not record.title:
            groups["missing_title"].append((record, "title is empty"))
        if _is_sparse(record):
            groups["sparse_record"].append((record, "record has limited identifying metadata"))
        if record.duration_seconds and not _is_int(record.duration_seconds):
            groups["malformed_duration"].append((record, "duration_seconds is not an integer"))
        if record.release_year and not _is_int(record.release_year):
            groups["malformed_year"].append((record, "release_year is not an integer"))


def _add_pattern_groups(
    records: list[ExternalValidationRecord],
    groups: dict[str, list[tuple[ExternalValidationRecord, str]]],
) -> None:
    for record in records:
        artist_album = " ".join([record.artist, record.album]).strip()
        all_text = " ".join([record.artist, record.album, record.title]).strip()
        if _COLLABORATION_RE.search(record.artist) or _COLLABORATION_RE.search(record.title):
            groups["collaboration_string"].append((record, "artist or title contains collaboration syntax"))
        if _SOURCE_ARTIFACT_RE.search(all_text):
            groups["source_artifact_candidate"].append((record, "metadata contains platform, channel, label, or source artifact terms"))
        if _OFFICIAL_AUDIO_VIDEO_RE.search(artist_album):
            groups["official_audio_video_noise"].append((record, "artist or album contains official audio/video wording"))
        if _REMASTER_RE.search(all_text):
            groups["remaster_version_noise"].append((record, "metadata contains version or remaster wording"))
        if _EXPLICIT_CLEAN_RE.search(all_text):
            groups["explicit_clean_radio_edit_noise"].append((record, "metadata contains explicit, clean, or radio edit wording"))


def _add_variant_groups(
    records: list[ExternalValidationRecord],
    groups: dict[str, list[tuple[ExternalValidationRecord, str]]],
) -> None:
    artist_by_casefold: dict[str, list[ExternalValidationRecord]] = defaultdict(list)
    album_title_by_punctuation: dict[str, list[tuple[ExternalValidationRecord, str]]] = defaultdict(list)
    for record in records:
        if record.artist:
            artist_by_casefold[record.artist.casefold()].append(record)
        for field_name, value in (("album", record.album), ("title", record.title)):
            normalized = _punctuation_key(value)
            if normalized:
                album_title_by_punctuation[f"{field_name}:{normalized}"].append((record, value))

    for normalized, candidates in artist_by_casefold.items():
        variants = {record.artist for record in candidates}
        if len(variants) > 1:
            cohort_key = f"casing_alias_candidate:{normalized}"
            for record in candidates:
                groups[cohort_key].append((record, "artist differs only by casing from another record"))

    for normalized, candidates in album_title_by_punctuation.items():
        variants = {value for _record, value in candidates}
        if len(variants) > 1:
            cohort_key = f"album_title_punctuation_variant:{normalized}"
            for record, _value in candidates:
                groups[cohort_key].append((record, "album or title differs only by punctuation from another record"))


def _add_cross_field_groups(
    records: list[ExternalValidationRecord],
    groups: dict[str, list[tuple[ExternalValidationRecord, str]]],
) -> None:
    titles = {_identity_key(record.title) for record in records if record.title}
    albums = {_identity_key(record.album) for record in records if record.album}
    for record in records:
        artist_key = _identity_key(record.artist)
        if artist_key and artist_key in titles:
            groups[f"possible_track_as_artist:{artist_key}"].append((record, "artist matches a track title in the same source"))
        if artist_key and artist_key in albums:
            groups[f"possible_album_as_artist:{artist_key}"].append((record, "artist matches an album title in the same source"))


def _add_duplicate_groups(
    records: list[ExternalValidationRecord],
    groups: dict[str, list[tuple[ExternalValidationRecord, str]]],
) -> None:
    by_source_record_id: dict[str, list[ExternalValidationRecord]] = defaultdict(list)
    by_identity: dict[str, list[ExternalValidationRecord]] = defaultdict(list)
    for record in records:
        if record.source_record_id:
            by_source_record_id[record.source_record_id].append(record)
        identity = "\x1f".join(
            [
                _identity_key(record.artist),
                _identity_key(record.album),
                _identity_key(record.title),
                _identity_key(record.track_number),
            ]
        )
        if identity.strip("\x1f"):
            by_identity[identity].append(record)

    for source_record_id, candidates in by_source_record_id.items():
        if len(candidates) > 1:
            cohort_key = f"duplicate_external_record:source_record_id:{source_record_id}"
            for record in candidates:
                groups[cohort_key].append((record, "source_record_id appears more than once"))
    for identity, candidates in by_identity.items():
        if len(candidates) > 1:
            cohort_key = f"duplicate_external_record:identity:{identity}"
            for record in candidates:
                groups[cohort_key].append((record, "artist, album, title, and track number duplicate another record"))


def _summary_counts(
    records: list[ExternalValidationRecord],
    cohorts: list[ValidationCohort],
) -> dict[str, int]:
    counts = {cohort_type: 0 for cohort_type in COHORT_TYPES}
    for cohort in cohorts:
        counts[cohort.cohort_type] += cohort.record_count
    return {
        "missing_artist_count": counts["missing_artist"],
        "missing_album_count": counts["missing_album"],
        "missing_title_count": counts["missing_title"],
        "collaboration_string_count": counts["collaboration_string"],
        "source_artifact_candidate_count": counts["source_artifact_candidate"],
        "official_audio_video_noise_count": counts["official_audio_video_noise"],
        "remaster_version_noise_count": counts["remaster_version_noise"],
        "duplicate_external_record_count": counts["duplicate_external_record"],
        "malformed_record_count": counts["malformed_duration"] + counts["malformed_year"],
    }


def _read_external_records(input_csv: Path) -> list[ExternalValidationRecord]:
    if not input_csv.exists():
        return []
    with input_csv.open(newline="", encoding="utf-8") as handle:
        return [
            ExternalValidationRecord.from_row(row)
            for row in csv.DictReader(handle)
        ]


def _write_cohorts(path: Path, cohorts: Iterable[ValidationCohort]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COHORT_HEADERS)
        writer.writeheader()
        for cohort in cohorts:
            writer.writerow(cohort.to_row())


def _write_examples(path: Path, examples: Iterable[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXAMPLE_HEADERS)
        writer.writeheader()
        for example in examples:
            writer.writerow(example)


def _write_source_quality_report(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUALITY_HEADERS)
        writer.writeheader()
        for key in sorted(summary):
            writer.writerow({"metric": key, "value": summary[key]})


def _severity_for(cohort_type: str, record_count: int) -> str:
    if cohort_type in {
        "source_artifact_candidate",
        "official_audio_video_noise",
        "possible_track_as_artist",
        "possible_album_as_artist",
    }:
        return "high"
    if cohort_type == "duplicate_external_record" and record_count >= 3:
        return "high"
    if cohort_type in {
        "collaboration_string",
        "remaster_version_noise",
        "album_title_punctuation_variant",
        "malformed_duration",
        "malformed_year",
        "explicit_clean_radio_edit_noise",
        "duplicate_external_record",
    }:
        return "medium"
    return "low"


def _recommended_action_for(cohort_type: str) -> str:
    actions = {
        "missing_artist": "Quantify source completeness before using artist evidence.",
        "missing_album": "Use as weak album evidence unless corroborated.",
        "missing_title": "Exclude from track-level validation until title is present.",
        "casing_alias_candidate": "Propose casing normalization only after source comparison.",
        "album_title_punctuation_variant": "Review punctuation-insensitive album/title normalization.",
        "collaboration_string": "Route through role-aware artist parsing proposals.",
        "source_artifact_candidate": "Block from canonical promotion proposals until reviewed.",
        "official_audio_video_noise": "Strip only through reviewed cleanup rules.",
        "remaster_version_noise": "Separate version descriptors from canonical titles.",
        "explicit_clean_radio_edit_noise": "Treat as version metadata, not canonical title text.",
        "possible_track_as_artist": "Investigate track-title-as-artist misclassification.",
        "possible_album_as_artist": "Investigate album-title-as-artist misclassification.",
        "sparse_record": "Use only for cohort-level completeness metrics.",
        "duplicate_external_record": "Deduplicate external evidence before scoring.",
        "malformed_duration": "Reject duration from numeric scoring.",
        "malformed_year": "Reject year from release-date scoring.",
    }
    return actions[cohort_type]


def _rationale_for(cohort_type: str) -> str:
    rationales = {
        "missing_artist": "Missing artist values reduce identity confidence.",
        "missing_album": "Missing album values limit release-level validation.",
        "missing_title": "Missing titles cannot support track-level comparison.",
        "casing_alias_candidate": "Case-only variants often indicate normalization opportunities.",
        "album_title_punctuation_variant": "Punctuation variants can inflate distinct album/title counts.",
        "collaboration_string": "Collaborations need role-aware parsing instead of direct artist merging.",
        "source_artifact_candidate": "Source, channel, label, or platform artifacts pollute entity evidence.",
        "official_audio_video_noise": "Official video/audio wording is usually delivery metadata.",
        "remaster_version_noise": "Version descriptors should not become base canonical names.",
        "explicit_clean_radio_edit_noise": "Edit descriptors are version evidence, not base identity.",
        "possible_track_as_artist": "A track title appearing as an artist is likely field pollution.",
        "possible_album_as_artist": "An album title appearing as an artist is likely field pollution.",
        "sparse_record": "Sparse records are weak standalone evidence.",
        "duplicate_external_record": "Duplicates can overweight one external source.",
        "malformed_duration": "Malformed durations cannot be compared numerically.",
        "malformed_year": "Malformed years cannot support release chronology.",
    }
    return rationales[cohort_type]


def _is_sparse(record: ExternalValidationRecord) -> bool:
    populated_identity = sum(bool(value) for value in (record.artist, record.album, record.title))
    populated_all = sum(
        bool(value)
        for value in (
            record.artist,
            record.album,
            record.title,
            record.track_number,
            record.release_year,
            record.label,
            record.duration_seconds,
            record.genre,
            record.source_url,
        )
    )
    return populated_identity <= 1 or populated_all <= 2


def _is_int(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True


def _identity_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _punctuation_key(value: str) -> str:
    without_punctuation = _PUNCTUATION_RE.sub(" ", value)
    return " ".join(without_punctuation.casefold().split())


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
