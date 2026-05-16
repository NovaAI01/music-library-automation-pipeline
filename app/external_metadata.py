"""External metadata ingestion contract and local file importer."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.data_paths import source_external_tracks_csv, source_external_tracks_jsonl


SUPPORTED_SOURCE_NAMES = (
    "musicbrainz",
    "discogs",
    "jamendo",
    "internet_archive",
    "youtube_metadata",
    "local_fixture",
)

EXTERNAL_TRACK_FIELDS = (
    "source_name",
    "source_record_id",
    "artist",
    "album",
    "title",
    "track_number",
    "release_year",
    "label",
    "duration_seconds",
    "genre",
    "source_url",
    "raw_payload_json",
    "ingested_at",
)

INPUT_FIELDS = (
    "artist",
    "album",
    "title",
    "track_number",
    "release_year",
    "label",
    "duration_seconds",
    "genre",
    "source_url",
    "raw_payload_json",
    "source_record_id",
)


@dataclass(frozen=True)
class ExternalTrackRecord:
    source_name: str
    source_record_id: str
    artist: str = ""
    album: str = ""
    title: str = ""
    track_number: str = ""
    release_year: int | None = None
    label: str = ""
    duration_seconds: int | None = None
    genre: str = ""
    source_url: str = ""
    raw_payload_json: str = "{}"
    ingested_at: str = ""

    def to_csv_row(self) -> dict[str, str]:
        row = self.to_json_dict()
        return {
            key: "" if row[key] is None else str(row[key])
            for key in EXTERNAL_TRACK_FIELDS
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_record_id": self.source_record_id,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "track_number": self.track_number,
            "release_year": self.release_year,
            "label": self.label,
            "duration_seconds": self.duration_seconds,
            "genre": self.genre,
            "source_url": self.source_url,
            "raw_payload_json": self.raw_payload_json,
            "ingested_at": self.ingested_at,
        }


@dataclass(frozen=True)
class RejectedExternalRecord:
    row_number: int
    error: str
    raw_record_json: str


@dataclass(frozen=True)
class ExternalMetadataIngestionResult:
    source_name: str
    input_records: int
    accepted_records: int
    rejected_records: int
    missing_artist_count: int
    missing_album_count: int
    missing_title_count: int
    generated_id_count: int
    output_csv: str
    output_jsonl: str
    report_path: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "input_records": self.input_records,
            "accepted_records": self.accepted_records,
            "rejected_records": self.rejected_records,
            "missing_artist_count": self.missing_artist_count,
            "missing_album_count": self.missing_album_count,
            "missing_title_count": self.missing_title_count,
            "generated_id_count": self.generated_id_count,
            "output_csv": self.output_csv,
            "output_jsonl": self.output_jsonl,
        }


def validate_source_name(source_name: str) -> str:
    normalized = _clean_string(source_name)
    if normalized not in SUPPORTED_SOURCE_NAMES:
        supported = ", ".join(SUPPORTED_SOURCE_NAMES)
        raise ValueError(f"unsupported external metadata source: {normalized}. Supported: {supported}")
    return normalized


def import_external_metadata(
    source_name: str,
    input_path: str | Path,
    out_dir: str | Path = "reports",
    data_dir: str | Path | None = None,
) -> ExternalMetadataIngestionResult:
    source_name = validate_source_name(source_name)
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    ingested_at = _utc_timestamp()

    accepted: list[ExternalTrackRecord] = []
    rejected: list[RejectedExternalRecord] = []
    generated_id_count = 0

    for row_number, row in _iter_input_records(input_path):
        try:
            record, generated_id = normalize_external_record(
                row,
                source_name=source_name,
                ingested_at=ingested_at,
            )
            accepted.append(record)
            if generated_id:
                generated_id_count += 1
        except ValueError as exc:
            rejected.append(
                RejectedExternalRecord(
                    row_number=row_number,
                    error=str(exc),
                    raw_record_json=_json_dumps(row),
                )
            )

    output_csv = source_external_tracks_csv(source_name, data_dir)
    output_jsonl = source_external_tracks_jsonl(source_name, data_dir)
    _write_external_tracks_csv(output_csv, accepted)
    _write_external_tracks_jsonl(output_jsonl, accepted)

    report_dir = out_dir / "external_metadata_ingestion"
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_external_tracks_csv(report_dir / "external_tracks_sample.csv", accepted[:20])
    _write_rejected_records(report_dir / "rejected_records.csv", rejected)

    result = ExternalMetadataIngestionResult(
        source_name=source_name,
        input_records=len(accepted) + len(rejected),
        accepted_records=len(accepted),
        rejected_records=len(rejected),
        missing_artist_count=sum(1 for record in accepted if not record.artist),
        missing_album_count=sum(1 for record in accepted if not record.album),
        missing_title_count=sum(1 for record in accepted if not record.title),
        generated_id_count=generated_id_count,
        output_csv=str(output_csv),
        output_jsonl=str(output_jsonl),
        report_path=str(report_dir),
    )
    (report_dir / "ingestion_summary.json").write_text(
        json.dumps(result.to_summary(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def normalize_external_record(
    row: dict[str, Any],
    source_name: str,
    ingested_at: str | None = None,
) -> tuple[ExternalTrackRecord, bool]:
    source_name = validate_source_name(source_name)
    artist = _clean_string(row.get("artist"))
    album = _clean_string(row.get("album"))
    title = _clean_string(row.get("title"))
    if not any((artist, album, title)):
        raise ValueError("at least one of artist, title, or album is required")

    source_record_id = _clean_string(row.get("source_record_id"))
    generated_id = False
    if not source_record_id:
        source_record_id = generate_deterministic_source_record_id(
            source_name=source_name,
            artist=artist,
            album=album,
            title=title,
            track_number=_clean_string(row.get("track_number")),
        )
        generated_id = True

    raw_payload_json = _normalize_raw_payload(row)
    record = ExternalTrackRecord(
        source_name=source_name,
        source_record_id=source_record_id,
        artist=artist,
        album=album,
        title=title,
        track_number=_clean_string(row.get("track_number")),
        release_year=_clean_int(row.get("release_year"), "release_year"),
        label=_clean_string(row.get("label")),
        duration_seconds=_clean_int(row.get("duration_seconds"), "duration_seconds"),
        genre=_clean_string(row.get("genre")),
        source_url=_clean_string(row.get("source_url")),
        raw_payload_json=raw_payload_json,
        ingested_at=ingested_at or _utc_timestamp(),
    )
    return record, generated_id


def generate_deterministic_source_record_id(
    source_name: str,
    artist: str = "",
    album: str = "",
    title: str = "",
    track_number: str = "",
) -> str:
    parts = [source_name, artist, album, title, track_number]
    identity = "\x1f".join(_clean_string(part).casefold() for part in parts)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"generated:{digest}"


class ExternalMetadataAdapter:
    source_name: str

    def fetch(self, *args: Any, **kwargs: Any) -> list[ExternalTrackRecord]:
        raise NotImplementedError(
            f"live fetching is not implemented for {self.source_name}; "
            "v1 supports local CSV and JSONL ingestion only"
        )

    def map_record(self, payload: dict[str, Any]) -> ExternalTrackRecord:
        record, _generated = normalize_external_record(
            payload,
            source_name=self.source_name,
        )
        return record


def get_source_adapter(source_name: str) -> ExternalMetadataAdapter:
    source_name = validate_source_name(source_name)
    adapter_cls = _ADAPTERS[source_name]
    return adapter_cls()


class MusicBrainzMetadataAdapter(ExternalMetadataAdapter):
    source_name = "musicbrainz"


class DiscogsMetadataAdapter(ExternalMetadataAdapter):
    source_name = "discogs"


class JamendoMetadataAdapter(ExternalMetadataAdapter):
    source_name = "jamendo"


class InternetArchiveMetadataAdapter(ExternalMetadataAdapter):
    source_name = "internet_archive"


class YouTubeMetadataAdapter(ExternalMetadataAdapter):
    source_name = "youtube_metadata"


class LocalFixtureMetadataAdapter(ExternalMetadataAdapter):
    source_name = "local_fixture"


_ADAPTERS: dict[str, type[ExternalMetadataAdapter]] = {
    "musicbrainz": MusicBrainzMetadataAdapter,
    "discogs": DiscogsMetadataAdapter,
    "jamendo": JamendoMetadataAdapter,
    "internet_archive": InternetArchiveMetadataAdapter,
    "youtube_metadata": YouTubeMetadataAdapter,
    "local_fixture": LocalFixtureMetadataAdapter,
}


def _iter_input_records(input_path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    if input_path.suffix.lower() == ".jsonl":
        yield from _iter_jsonl_records(input_path)
        return
    yield from _iter_csv_records(input_path)


def _iter_csv_records(input_path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            yield row_number, {key: row.get(key, "") for key in INPUT_FIELDS}


def _iter_jsonl_records(input_path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with input_path.open(encoding="utf-8") as handle:
        for row_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                yield row_number, {"raw_payload_json": stripped, "_json_error": str(exc)}
                continue
            if not isinstance(payload, dict):
                yield row_number, {"raw_payload_json": stripped, "_json_error": "line is not a JSON object"}
                continue
            yield row_number, payload


def _normalize_raw_payload(row: dict[str, Any]) -> str:
    raw_payload = row.get("raw_payload_json")
    if raw_payload is None or _clean_string(raw_payload) == "":
        return _json_dumps(row)
    if isinstance(raw_payload, (dict, list)):
        return _json_dumps(raw_payload)
    raw_payload_json = _clean_string(raw_payload)
    try:
        json.loads(raw_payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"raw_payload_json must be valid JSON: {exc.msg}") from exc
    return raw_payload_json


def _write_external_tracks_csv(path: Path, records: Iterable[ExternalTrackRecord]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXTERNAL_TRACK_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def _write_external_tracks_jsonl(path: Path, records: Iterable[ExternalTrackRecord]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_json_dict(), sort_keys=True) + "\n")


def _write_rejected_records(path: Path, records: Iterable[RejectedExternalRecord]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("row_number", "error", "raw_record_json"))
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "row_number": record.row_number,
                    "error": record.error,
                    "raw_record_json": record.raw_record_json,
                }
            )


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_int(value: Any, field_name: str) -> int | None:
    cleaned = _clean_string(value)
    if cleaned == "":
        return None
    try:
        return int(cleaned)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer or empty") from exc


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
