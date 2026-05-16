"""Convert extracted MusicBrainz dump tables into ExternalTrackRecord CSV input."""

from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


OUTPUT_FIELDS = (
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
)

REJECTED_FIELDS = ("source_record_id", "rejection_reason", "raw_payload_json")


@dataclass(frozen=True)
class MusicBrainzConversionResult:
    input_tracks_seen: int
    accepted_records: int
    rejected_records: int
    output_csv: str
    rejected_csv: str
    limit_applied: int | None
    duration_seconds: float
    report_path: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "input_tracks_seen": self.input_tracks_seen,
            "accepted_records": self.accepted_records,
            "rejected_records": self.rejected_records,
            "output_csv": self.output_csv,
            "rejected_csv": self.rejected_csv,
            "limit_applied": self.limit_applied,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class TrackRow:
    id: str
    gid: str
    recording_id: str
    medium_id: str
    position: str
    number: str
    name: str
    artist_credit_id: str
    length_ms: str


@dataclass(frozen=True)
class RecordingRow:
    id: str
    gid: str
    name: str
    artist_credit_id: str
    length_ms: str


@dataclass(frozen=True)
class MediumRow:
    id: str
    release_id: str


@dataclass(frozen=True)
class ReleaseRow:
    id: str
    gid: str
    name: str
    artist_credit_id: str


@dataclass(frozen=True)
class ArtistCreditNameRow:
    artist_credit_id: str
    position: int
    artist_id: str
    name: str
    join_phrase: str


def convert_musicbrainz_dump(
    dump_dir: str | Path,
    output_csv: str | Path,
    limit: int | None = None,
    reports_dir: str | Path = "reports",
) -> MusicBrainzConversionResult:
    """Convert a bounded pass over MusicBrainz dump rows into ingestion CSVs."""

    started = time.monotonic()
    dump_dir = Path(dump_dir)
    output_csv = Path(output_csv)
    reports_dir = Path(reports_dir)
    if limit is not None and limit < 1:
        raise ValueError("--limit must be a positive integer when provided")

    tracks = _read_limited_tracks(dump_dir / "track", limit)
    recording_ids = {track.recording_id for track in tracks if track.recording_id}
    medium_ids = {track.medium_id for track in tracks if track.medium_id}
    artist_credit_ids = {
        track.artist_credit_id for track in tracks if track.artist_credit_id
    }

    media = _read_media(dump_dir / "medium", medium_ids)
    release_ids = {medium.release_id for medium in media.values() if medium.release_id}
    releases = _read_releases(dump_dir / "release", release_ids)
    artist_credit_ids.update(
        release.artist_credit_id
        for release in releases.values()
        if release.artist_credit_id
    )

    recordings = _read_recordings(dump_dir / "recording", recording_ids)
    artist_credit_ids.update(
        recording.artist_credit_id
        for recording in recordings.values()
        if recording.artist_credit_id
    )

    artist_credit_names = _read_artist_credit_names(
        dump_dir / "artist_credit_name", artist_credit_ids
    )
    artist_ids = {
        part.artist_id
        for parts in artist_credit_names.values()
        for part in parts
        if part.artist_id
    }
    artists = _read_artists(dump_dir / "artist", artist_ids)

    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for track in tracks:
        row, rejection = _convert_track(
            track=track,
            recordings=recordings,
            media=media,
            releases=releases,
            artist_credit_names=artist_credit_names,
            artists=artists,
        )
        if rejection:
            rejected.append(
                {
                    "source_record_id": row["source_record_id"],
                    "rejection_reason": rejection,
                    "raw_payload_json": row["raw_payload_json"],
                }
            )
        else:
            accepted.append(row)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rejected_csv = output_csv.with_name(f"{output_csv.stem}_rejected.csv")
    _write_csv(output_csv, OUTPUT_FIELDS, accepted)
    _write_csv(rejected_csv, REJECTED_FIELDS, rejected)

    report_dir = reports_dir / "musicbrainz_conversion"
    report_dir.mkdir(parents=True, exist_ok=True)
    result = MusicBrainzConversionResult(
        input_tracks_seen=len(tracks),
        accepted_records=len(accepted),
        rejected_records=len(rejected),
        output_csv=str(output_csv),
        rejected_csv=str(rejected_csv),
        limit_applied=limit,
        duration_seconds=round(time.monotonic() - started, 6),
        report_path=str(report_dir),
    )
    (report_dir / "conversion_summary.json").write_text(
        json.dumps(result.to_summary(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _convert_track(
    track: TrackRow,
    recordings: dict[str, RecordingRow],
    media: dict[str, MediumRow],
    releases: dict[str, ReleaseRow],
    artist_credit_names: dict[str, list[ArtistCreditNameRow]],
    artists: dict[str, str],
) -> tuple[dict[str, str], str | None]:
    recording = recordings.get(track.recording_id)
    medium = media.get(track.medium_id)
    release = releases.get(medium.release_id) if medium else None

    source_record_id = (
        f"musicbrainz:{track.gid}"
        if track.gid
        else f"musicbrainz:{track.id}:{track.recording_id}:{track.medium_id}"
    )
    artist = _resolve_artist_credit(
        track.artist_credit_id, artist_credit_names, artists
    )
    if not artist and release:
        artist = _resolve_artist_credit(
            release.artist_credit_id, artist_credit_names, artists
        )
    album = release.name if release else ""
    title = recording.name if recording and recording.name else track.name
    duration_seconds = _duration_seconds(
        recording.length_ms if recording and recording.length_ms else track.length_ms
    )
    recording_gid = recording.gid if recording else ""
    release_gid = release.gid if release else ""
    raw_payload = _compact_json(
        {
            "track_id": track.id,
            "track_gid": track.gid,
            "recording_id": track.recording_id,
            "recording_gid": recording_gid,
            "medium_id": track.medium_id,
            "release_id": medium.release_id if medium else "",
            "release_gid": release_gid,
            "artist_credit_id": track.artist_credit_id,
        }
    )
    row = {
        "source_record_id": source_record_id,
        "artist": artist,
        "album": album,
        "title": title,
        "track_number": track.number or track.position,
        "release_year": "",
        "label": "",
        "duration_seconds": "" if duration_seconds is None else str(duration_seconds),
        "genre": "",
        "source_url": (
            f"https://musicbrainz.org/recording/{recording_gid}"
            if recording_gid
            else ""
        ),
        "raw_payload_json": raw_payload,
    }
    missing = [
        field for field in ("artist", "album", "title") if not row[field].strip()
    ]
    if missing:
        return row, "missing_" + "_".join(missing)
    return row, None


def _read_limited_tracks(path: Path, limit: int | None) -> list[TrackRow]:
    tracks: list[TrackRow] = []
    for row in _iter_tsv_rows(path):
        if limit is not None and len(tracks) >= limit:
            break
        tracks.append(
            TrackRow(
                id=_cell(row, 0),
                gid=_cell(row, 1),
                recording_id=_cell(row, 2),
                medium_id=_cell(row, 3),
                position=_cell(row, 4),
                number=_cell(row, 5),
                name=_cell(row, 6),
                artist_credit_id=_cell(row, 7),
                length_ms=_cell(row, 8),
            )
        )
    return tracks


def _read_recordings(path: Path, needed_ids: set[str]) -> dict[str, RecordingRow]:
    recordings: dict[str, RecordingRow] = {}
    for row in _iter_tsv_rows(path):
        row_id = _cell(row, 0)
        if row_id in needed_ids:
            recordings[row_id] = RecordingRow(
                id=row_id,
                gid=_cell(row, 1),
                name=_cell(row, 2),
                artist_credit_id=_cell(row, 3),
                length_ms=_cell(row, 4),
            )
            if len(recordings) == len(needed_ids):
                break
    return recordings


def _read_media(path: Path, needed_ids: set[str]) -> dict[str, MediumRow]:
    media: dict[str, MediumRow] = {}
    for row in _iter_tsv_rows(path):
        row_id = _cell(row, 0)
        if row_id in needed_ids:
            media[row_id] = MediumRow(id=row_id, release_id=_cell(row, 1))
            if len(media) == len(needed_ids):
                break
    return media


def _read_releases(path: Path, needed_ids: set[str]) -> dict[str, ReleaseRow]:
    releases: dict[str, ReleaseRow] = {}
    for row in _iter_tsv_rows(path):
        row_id = _cell(row, 0)
        if row_id in needed_ids:
            releases[row_id] = ReleaseRow(
                id=row_id,
                gid=_cell(row, 1),
                name=_cell(row, 2),
                artist_credit_id=_cell(row, 3),
            )
            if len(releases) == len(needed_ids):
                break
    return releases


def _read_artist_credit_names(
    path: Path, needed_ids: set[str]
) -> dict[str, list[ArtistCreditNameRow]]:
    names: dict[str, list[ArtistCreditNameRow]] = {}
    found_ids: set[str] = set()
    for row in _iter_tsv_rows(path):
        artist_credit_id = _cell(row, 0)
        if artist_credit_id in needed_ids:
            names.setdefault(artist_credit_id, []).append(
                ArtistCreditNameRow(
                    artist_credit_id=artist_credit_id,
                    position=_int_or_zero(_cell(row, 1)),
                    artist_id=_cell(row, 2),
                    name=_cell(row, 3),
                    join_phrase=_raw_cell(row, 4),
                )
            )
            found_ids.add(artist_credit_id)
            if found_ids == needed_ids:
                # Artist credit rows are clustered by credit id in practice, but keep
                # scanning until the next non-matching row to avoid truncating parts.
                continue
        elif found_ids == needed_ids:
            break
    return names


def _read_artists(path: Path, needed_ids: set[str]) -> dict[str, str]:
    artists: dict[str, str] = {}
    for row in _iter_tsv_rows(path):
        row_id = _cell(row, 0)
        if row_id in needed_ids:
            artists[row_id] = _cell(row, 2)
            if len(artists) == len(needed_ids):
                break
    return artists


def _resolve_artist_credit(
    artist_credit_id: str,
    artist_credit_names: dict[str, list[ArtistCreditNameRow]],
    artists: dict[str, str],
) -> str:
    parts = sorted(
        artist_credit_names.get(artist_credit_id, ()), key=lambda part: part.position
    )
    if not parts:
        return ""
    chunks: list[str] = []
    for part in parts:
        name = part.name or artists.get(part.artist_id, "")
        if name:
            chunks.append(name)
        if part.join_phrase:
            chunks.append(part.join_phrase)
    return "".join(chunks).strip()


def _iter_tsv_rows(path: Path) -> Iterable[list[str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        yield from reader


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value == r"\N" else value.strip()


def _raw_cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value == r"\N" else value


def _duration_seconds(length_ms: str) -> int | None:
    if not length_ms:
        return None
    try:
        milliseconds = int(length_ms)
    except ValueError:
        return None
    if milliseconds < 0:
        return None
    return milliseconds // 1000


def _int_or_zero(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _compact_json(payload: dict[str, str]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
