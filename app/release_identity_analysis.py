"""Read-only release-aware identity analysis for external metadata."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.data_paths import source_external_tracks_csv
from app.external_metadata import EXTERNAL_TRACK_FIELDS, validate_source_name


REPORT_DIRNAME = "release_identity_analysis"
SUMMARY_FILENAME = "release_identity_summary.json"
IDENTITY_GROUPS_FILENAME = "identity_groups.csv"
RELEASE_APPEARANCES_FILENAME = "release_appearances.csv"
POSSIBLE_TRUE_DUPLICATES_FILENAME = "possible_true_duplicates.csv"
LEGITIMATE_RELEASE_APPEARANCES_FILENAME = "legitimate_release_appearances.csv"
AMBIGUOUS_IDENTITY_GROUPS_FILENAME = "ambiguous_identity_groups.csv"

CLASSIFICATIONS = (
    "single_record_identity",
    "legitimate_release_appearance",
    "possible_true_duplicate",
    "edition_or_reissue_cluster",
    "compilation_or_multi_release_appearance",
    "ambiguous_identity_cluster",
)
IDENTITY_GROUP_FIELDS = (
    "identity_key",
    "classification",
    "record_count",
    "artist",
    "title",
    "duration_seconds",
    "distinct_album_count",
    "distinct_release_count",
    "distinct_source_record_count",
    "confidence_tier",
    "rationale",
)
RELEASE_APPEARANCE_FIELDS = (
    "identity_key",
    "source_record_id",
    "artist",
    "album",
    "title",
    "track_number",
    "release_year",
    "duration_seconds",
    "source_url",
    "release_id",
    "release_gid",
    "recording_id",
    "recording_gid",
)
POSSIBLE_TRUE_DUPLICATE_FIELDS = (
    "identity_key",
    "record_count",
    "duplicate_reason",
    "representative_artist",
    "representative_album",
    "representative_title",
    "source_record_ids_json",
)
LEGITIMATE_RELEASE_APPEARANCE_FIELDS = (
    "identity_key",
    "record_count",
    "release_count",
    "representative_artist",
    "representative_title",
    "albums_json",
    "rationale",
)
AMBIGUOUS_IDENTITY_GROUP_FIELDS = (
    "identity_key",
    "record_count",
    "ambiguity_reason",
    "representative_artist",
    "representative_title",
    "conflicting_values_json",
)

EDITION_RE = re.compile(
    r"\b(?:anniversary|bonus|deluxe|edition|expanded|reissue|remaster(?:ed)?|"
    r"special|version)\b",
    re.I,
)
COMPILATION_RE = re.compile(
    r"\b(?:antholog(?:y|ies)|best\s+of|collection|compilation|essential|"
    r"greatest\s+hits|hits|soundtrack|the\s+very\s+best|tribute|various\s+artists)\b",
    re.I,
)
PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class ReleaseIdentityRecord:
    source_name: str
    source_record_id: str
    artist: str
    album: str
    title: str
    track_number: str
    release_year: str
    duration_seconds: str
    source_url: str
    release_id: str
    release_gid: str
    recording_id: str
    recording_gid: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ReleaseIdentityRecord":
        payload = _parse_payload(row.get("raw_payload_json"))
        return cls(
            source_name=_clean_string(row.get("source_name")),
            source_record_id=_clean_string(row.get("source_record_id")),
            artist=_clean_string(row.get("artist")),
            album=_clean_string(row.get("album")),
            title=_clean_string(row.get("title")),
            track_number=_clean_string(row.get("track_number")),
            release_year=_clean_string(row.get("release_year")),
            duration_seconds=_clean_string(row.get("duration_seconds")),
            source_url=_clean_string(row.get("source_url")),
            release_id=_clean_string(payload.get("release_id")),
            release_gid=_clean_string(payload.get("release_gid")),
            recording_id=_clean_string(payload.get("recording_id")),
            recording_gid=_clean_string(payload.get("recording_gid")),
        )

    def appearance_row(self, identity_key: str) -> dict[str, str]:
        return {
            "identity_key": identity_key,
            "source_record_id": self.source_record_id,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "track_number": self.track_number,
            "release_year": self.release_year,
            "duration_seconds": self.duration_seconds,
            "source_url": self.source_url,
            "release_id": self.release_id,
            "release_gid": self.release_gid,
            "recording_id": self.recording_id,
            "recording_gid": self.recording_gid,
        }


@dataclass(frozen=True)
class ReleaseIdentityGroup:
    identity_key: str
    records: tuple[ReleaseIdentityRecord, ...]
    classification: str
    confidence_tier: str
    rationale: str
    duplicate_reason: str = ""
    ambiguity_reason: str = ""

    def to_identity_row(self) -> dict[str, str]:
        representative = self.records[0]
        return {
            "identity_key": self.identity_key,
            "classification": self.classification,
            "record_count": str(len(self.records)),
            "artist": representative.artist,
            "title": representative.title,
            "duration_seconds": _representative_value(record.duration_seconds for record in self.records),
            "distinct_album_count": str(len(_distinct(record.album for record in self.records))),
            "distinct_release_count": str(len(_release_keys(self.records))),
            "distinct_source_record_count": str(len(_distinct(record.source_record_id for record in self.records))),
            "confidence_tier": self.confidence_tier,
            "rationale": self.rationale,
        }

    def to_possible_duplicate_row(self) -> dict[str, str]:
        representative = self.records[0]
        return {
            "identity_key": self.identity_key,
            "record_count": str(len(self.records)),
            "duplicate_reason": self.duplicate_reason,
            "representative_artist": representative.artist,
            "representative_album": representative.album,
            "representative_title": representative.title,
            "source_record_ids_json": _json_dumps(_distinct(record.source_record_id for record in self.records)),
        }

    def to_legitimate_release_row(self) -> dict[str, str]:
        representative = self.records[0]
        albums = _distinct(record.album for record in self.records)
        return {
            "identity_key": self.identity_key,
            "record_count": str(len(self.records)),
            "release_count": str(len(_release_keys(self.records))),
            "representative_artist": representative.artist,
            "representative_title": representative.title,
            "albums_json": _json_dumps(albums),
            "rationale": self.rationale,
        }

    def to_ambiguous_row(self) -> dict[str, str]:
        representative = self.records[0]
        conflicting = {
            "duration_seconds": _distinct(record.duration_seconds for record in self.records),
            "artist": _distinct(record.artist for record in self.records),
            "title": _distinct(record.title for record in self.records),
            "recording_ids": _distinct(record.recording_id for record in self.records),
            "recording_gids": _distinct(record.recording_gid for record in self.records),
        }
        return {
            "identity_key": self.identity_key,
            "record_count": str(len(self.records)),
            "ambiguity_reason": self.ambiguity_reason,
            "representative_artist": representative.artist,
            "representative_title": representative.title,
            "conflicting_values_json": _json_dumps(conflicting),
        }


@dataclass(frozen=True)
class ReleaseIdentityAnalysisResult:
    source_name: str
    total_records: int
    total_identity_groups: int
    single_record_identity_count: int
    legitimate_release_appearance_count: int
    possible_true_duplicate_count: int
    edition_or_reissue_cluster_count: int
    compilation_or_multi_release_appearance_count: int
    ambiguous_identity_group_count: int
    duplicate_external_records_explained: int
    duplicate_external_records_unresolved: int
    report_path: str
    output_files: dict[str, str]

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "total_records": self.total_records,
            "total_identity_groups": self.total_identity_groups,
            "single_record_identity_count": self.single_record_identity_count,
            "legitimate_release_appearance_count": self.legitimate_release_appearance_count,
            "possible_true_duplicate_count": self.possible_true_duplicate_count,
            "edition_or_reissue_cluster_count": self.edition_or_reissue_cluster_count,
            "compilation_or_multi_release_appearance_count": self.compilation_or_multi_release_appearance_count,
            "ambiguous_identity_group_count": self.ambiguous_identity_group_count,
            "duplicate_external_records_explained": self.duplicate_external_records_explained,
            "duplicate_external_records_unresolved": self.duplicate_external_records_unresolved,
            "output_files": self.output_files,
        }


def analyze_release_identity(
    source_name: str,
    out_dir: str | Path = "reports",
    data_dir: str | Path | None = None,
    limit: int | None = None,
) -> ReleaseIdentityAnalysisResult:
    """Generate release-aware identity reports for one local external dataset."""

    source_name = validate_source_name(source_name)
    out_dir = Path(out_dir)
    input_csv = source_external_tracks_csv(source_name, data_dir)
    records = _read_external_records(input_csv, limit=limit)
    groups = _classify_identity_groups(_group_records(records))

    report_dir = out_dir / REPORT_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    output_files = {
        "identity_groups": str(report_dir / IDENTITY_GROUPS_FILENAME),
        "release_appearances": str(report_dir / RELEASE_APPEARANCES_FILENAME),
        "possible_true_duplicates": str(report_dir / POSSIBLE_TRUE_DUPLICATES_FILENAME),
        "legitimate_release_appearances": str(report_dir / LEGITIMATE_RELEASE_APPEARANCES_FILENAME),
        "ambiguous_identity_groups": str(report_dir / AMBIGUOUS_IDENTITY_GROUPS_FILENAME),
    }

    _write_csv(
        report_dir / IDENTITY_GROUPS_FILENAME,
        IDENTITY_GROUP_FIELDS,
        (group.to_identity_row() for group in groups),
    )
    _write_csv(
        report_dir / RELEASE_APPEARANCES_FILENAME,
        RELEASE_APPEARANCE_FIELDS,
        (
            record.appearance_row(group.identity_key)
            for group in groups
            for record in group.records
        ),
    )
    _write_csv(
        report_dir / POSSIBLE_TRUE_DUPLICATES_FILENAME,
        POSSIBLE_TRUE_DUPLICATE_FIELDS,
        (
            group.to_possible_duplicate_row()
            for group in groups
            if group.classification == "possible_true_duplicate"
        ),
    )
    _write_csv(
        report_dir / LEGITIMATE_RELEASE_APPEARANCES_FILENAME,
        LEGITIMATE_RELEASE_APPEARANCE_FIELDS,
        (
            group.to_legitimate_release_row()
            for group in groups
            if group.classification
            in {
                "legitimate_release_appearance",
                "edition_or_reissue_cluster",
                "compilation_or_multi_release_appearance",
            }
        ),
    )
    _write_csv(
        report_dir / AMBIGUOUS_IDENTITY_GROUPS_FILENAME,
        AMBIGUOUS_IDENTITY_GROUP_FIELDS,
        (
            group.to_ambiguous_row()
            for group in groups
            if group.classification == "ambiguous_identity_cluster"
        ),
    )

    classification_counts = Counter(group.classification for group in groups)
    result = ReleaseIdentityAnalysisResult(
        source_name=source_name,
        total_records=len(records),
        total_identity_groups=len(groups),
        single_record_identity_count=classification_counts["single_record_identity"],
        legitimate_release_appearance_count=classification_counts["legitimate_release_appearance"],
        possible_true_duplicate_count=classification_counts["possible_true_duplicate"],
        edition_or_reissue_cluster_count=classification_counts["edition_or_reissue_cluster"],
        compilation_or_multi_release_appearance_count=classification_counts["compilation_or_multi_release_appearance"],
        ambiguous_identity_group_count=classification_counts["ambiguous_identity_cluster"],
        duplicate_external_records_explained=sum(
            len(group.records)
            for group in groups
            if len(group.records) > 1 and group.classification != "ambiguous_identity_cluster"
        ),
        duplicate_external_records_unresolved=sum(
            len(group.records)
            for group in groups
            if group.classification == "ambiguous_identity_cluster"
        ),
        report_path=str(report_dir),
        output_files=output_files,
    )
    (report_dir / SUMMARY_FILENAME).write_text(
        json.dumps(result.to_summary(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _group_records(
    records: list[ReleaseIdentityRecord],
) -> list[tuple[str, list[ReleaseIdentityRecord]]]:
    weak_by_artist_title: dict[str, list[ReleaseIdentityRecord]] = defaultdict(list)
    grouped: dict[str, list[ReleaseIdentityRecord]] = defaultdict(list)

    for record in records:
        if record.recording_gid:
            grouped[f"recording_gid:{record.recording_gid}"].append(record)
        elif record.recording_id:
            grouped[f"recording_id:{record.recording_id}"].append(record)
        else:
            weak_by_artist_title[_artist_title_key(record)].append(record)

    for artist_title_key, weak_records in weak_by_artist_title.items():
        durations = _distinct(record.duration_seconds for record in weak_records)
        if len(weak_records) > 1 and len(durations) > 1:
            grouped[f"artist_title:{artist_title_key}"].extend(weak_records)
            continue
        for record in weak_records:
            if record.duration_seconds:
                key = f"artist_title_duration:{artist_title_key}:{record.duration_seconds}"
            else:
                key = f"artist_title:{artist_title_key}"
            grouped[key].append(record)

    return sorted(
        grouped.items(),
        key=lambda item: (_sort_group_records(item[1]), item[0]),
    )


def _classify_identity_groups(
    grouped_records: list[tuple[str, list[ReleaseIdentityRecord]]],
) -> list[ReleaseIdentityGroup]:
    groups = [
        _classify_group(identity_key, tuple(sorted(records, key=_record_sort_key)))
        for identity_key, records in grouped_records
    ]
    return sorted(
        groups,
        key=lambda group: (
            CLASSIFICATIONS.index(group.classification),
            group.records[0].artist.casefold(),
            group.records[0].title.casefold(),
            group.identity_key,
        ),
    )


def _classify_group(
    identity_key: str,
    records: tuple[ReleaseIdentityRecord, ...],
) -> ReleaseIdentityGroup:
    if len(records) == 1:
        return ReleaseIdentityGroup(
            identity_key=identity_key,
            records=records,
            classification="single_record_identity",
            confidence_tier="high" if _has_recording_identity(records) else "medium",
            rationale="Only one external metadata row belongs to this identity.",
        )

    repeated_source_ids = _repeated_values(record.source_record_id for record in records)
    identical_rows = _identical_identity_rows(records)
    release_keys = _release_keys(records)
    albums = _distinct(record.album for record in records)
    durations = _distinct(record.duration_seconds for record in records)
    has_recording_identity = _has_recording_identity(records)
    has_different_release_evidence = len(release_keys) > 1 or len(albums) > 1

    if not has_recording_identity and len(durations) > 1:
        return ReleaseIdentityGroup(
            identity_key=identity_key,
            records=records,
            classification="ambiguous_identity_cluster",
            confidence_tier="low",
            rationale="Weak artist/title identity has conflicting durations and no MusicBrainz recording identity.",
            ambiguity_reason="conflicting_duration_without_recording_identity",
        )
    if (repeated_source_ids or identical_rows) and not has_different_release_evidence:
        return ReleaseIdentityGroup(
            identity_key=identity_key,
            records=records,
            classification="possible_true_duplicate",
            confidence_tier="high",
            rationale="Rows repeat the same source record or exact identity tuple without different release evidence.",
            duplicate_reason="repeated_source_record_id" if repeated_source_ids else "identical_artist_album_title_track_duration",
        )
    if has_recording_identity and has_different_release_evidence and _has_compilation_album(albums):
        return ReleaseIdentityGroup(
            identity_key=identity_key,
            records=records,
            classification="compilation_or_multi_release_appearance",
            confidence_tier="high",
            rationale="Same recording appears across compilation, collection, soundtrack, or many-release album evidence.",
        )
    if has_recording_identity and has_different_release_evidence and _has_edition_album(albums):
        return ReleaseIdentityGroup(
            identity_key=identity_key,
            records=records,
            classification="edition_or_reissue_cluster",
            confidence_tier="high",
            rationale="Same recording appears across edition, remaster, deluxe, or reissue album evidence.",
        )
    if has_recording_identity and has_different_release_evidence:
        return ReleaseIdentityGroup(
            identity_key=identity_key,
            records=records,
            classification="legitimate_release_appearance",
            confidence_tier="high",
            rationale="Same MusicBrainz recording appears across different releases or album names.",
        )
    if not has_recording_identity and has_different_release_evidence:
        return ReleaseIdentityGroup(
            identity_key=identity_key,
            records=records,
            classification="ambiguous_identity_cluster",
            confidence_tier="medium",
            rationale="Artist/title identity appears across release evidence without a MusicBrainz recording identity.",
            ambiguity_reason="weak_identity_across_multiple_releases",
        )
    return ReleaseIdentityGroup(
        identity_key=identity_key,
        records=records,
        classification="possible_true_duplicate",
        confidence_tier="medium",
        rationale="Multiple rows share the same identity with no clear different release evidence.",
        duplicate_reason="same_identity_without_release_evidence",
    )


def _read_external_records(
    input_csv: Path,
    limit: int | None,
) -> list[ReleaseIdentityRecord]:
    if not input_csv.exists():
        return []
    records: list[ReleaseIdentityRecord] = []
    with input_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            records.append(ReleaseIdentityRecord.from_row(row))
            if limit is not None and len(records) >= limit:
                break
    return records


def _parse_payload(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(_clean_string(value) or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _artist_title_key(record: ReleaseIdentityRecord) -> str:
    return "\x1f".join([_identity_key(record.artist), _identity_key(record.title)])


def _identity_key(value: str) -> str:
    without_punctuation = PUNCTUATION_RE.sub(" ", value)
    return " ".join(without_punctuation.casefold().split())


def _release_keys(records: Iterable[ReleaseIdentityRecord]) -> list[str]:
    keys = []
    for record in records:
        if record.release_gid:
            keys.append(f"release_gid:{record.release_gid}")
        elif record.release_id:
            keys.append(f"release_id:{record.release_id}")
    return _distinct(keys)


def _distinct(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value}, key=lambda value: value.casefold())


def _representative_value(values: Iterable[str]) -> str:
    distinct = _distinct(values)
    return distinct[0] if len(distinct) == 1 else ""


def _repeated_values(values: Iterable[str]) -> bool:
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            return True
        seen.add(value)
    return False


def _identical_identity_rows(records: tuple[ReleaseIdentityRecord, ...]) -> bool:
    identities = [
        (
            _identity_key(record.artist),
            _identity_key(record.album),
            _identity_key(record.title),
            record.track_number,
            record.duration_seconds,
        )
        for record in records
    ]
    return len(identities) != len(set(identities))


def _has_recording_identity(records: Iterable[ReleaseIdentityRecord]) -> bool:
    return any(record.recording_gid or record.recording_id for record in records)


def _has_edition_album(albums: list[str]) -> bool:
    return any(EDITION_RE.search(album) for album in albums)


def _has_compilation_album(albums: list[str]) -> bool:
    return len(albums) >= 3 or any(COMPILATION_RE.search(album) for album in albums)


def _sort_group_records(records: list[ReleaseIdentityRecord]) -> tuple[str, str, str]:
    first = sorted(records, key=_record_sort_key)[0]
    return (first.artist.casefold(), first.title.casefold(), first.album.casefold())


def _record_sort_key(record: ReleaseIdentityRecord) -> tuple[str, str, str, str]:
    return (
        record.artist.casefold(),
        record.title.casefold(),
        record.album.casefold(),
        record.source_record_id,
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: Iterable[dict[str, Any]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
