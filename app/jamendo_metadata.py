"""Fetch Jamendo metadata-only records into ExternalTrackRecord input files."""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from app.data_paths import source_metadata_dir
from app.musicbrainz_converter import OUTPUT_FIELDS, REJECTED_FIELDS


SOURCE_NAME = "jamendo"
TRACKS_URL = "https://api.jamendo.com/v3.0/tracks/"
DEFAULT_PAGE_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 30.0
MISSING_CLIENT_ID_MESSAGE = (
    "JAMENDO_CLIENT_ID is required for live Jamendo metadata acquisition"
)
MEDIA_PAYLOAD_KEYS = frozenset(
    {
        "audio",
        "audiodownload",
        "audiodownload_allowed",
        "proaudio",
        "audio_download",
        "download",
        "waveform",
        "stream",
    }
)


@dataclass(frozen=True)
class JamendoAcquisitionResult:
    source_name: str
    requested_limit: int
    fetched_records: int
    accepted_records: int
    rejected_records: int
    output_csv: str
    output_jsonl: str
    duration_seconds: float
    metadata_only: bool
    audio_download_allowed: bool
    client_id_source: str
    report_path: str
    rejected_csv: str
    sample_csv: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "requested_limit": self.requested_limit,
            "fetched_records": self.fetched_records,
            "accepted_records": self.accepted_records,
            "rejected_records": self.rejected_records,
            "output_csv": self.output_csv,
            "output_jsonl": self.output_jsonl,
            "duration_seconds": self.duration_seconds,
            "metadata_only": self.metadata_only,
            "audio_download_allowed": self.audio_download_allowed,
            "client_id_source": self.client_id_source,
        }


def fetch_jamendo_metadata(
    limit: int,
    out_dir: str | Path = "reports",
    page_size: int = DEFAULT_PAGE_SIZE,
    source: str = SOURCE_NAME,
    client_id: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    dry_run: bool = False,
    data_dir: str | Path | None = None,
    fetch_json: Callable[[str, float], dict[str, Any]] | None = None,
    progress_stream: TextIO | None = None,
) -> JamendoAcquisitionResult:
    """Fetch Jamendo track metadata and write normalized importer inputs."""

    started = time.monotonic()
    if source != SOURCE_NAME:
        raise ValueError("--source is fixed to jamendo")
    if limit < 1:
        raise ValueError("--limit must be a positive integer")
    if page_size < 1:
        raise ValueError("--page-size must be a positive integer")
    if timeout <= 0:
        raise ValueError("--timeout must be positive")

    resolved_client_id, client_id_source = resolve_client_id(client_id)
    if not resolved_client_id:
        raise JamendoCredentialError(MISSING_CLIENT_ID_MESSAGE)

    output_dir = source_metadata_dir(source, data_dir)
    output_csv = output_dir / "raw_jamendo.csv"
    output_jsonl = output_dir / "raw_jamendo.jsonl"
    report_dir = Path(out_dir) / "jamendo_metadata"
    rejected_csv = report_dir / "rejected_records.csv"
    sample_csv = report_dir / "sample_records.csv"

    fetched_records = 0
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []

    if not dry_run:
        progress_handle = progress_stream or sys.stderr
        print(
            f"fetching_jamendo_metadata requested_limit={limit} page_size={page_size}",
            file=progress_handle,
        )
        fetcher = fetch_json or _fetch_json
        for page in _iter_track_record_pages(
            client_id=resolved_client_id,
            limit=limit,
            page_size=page_size,
            timeout=timeout,
            fetch_json=fetcher,
        ):
            for payload in page:
                fetched_records += 1
                row, rejection_reason = map_jamendo_record(payload)
                if rejection_reason:
                    rejected.append(
                        {
                            "source_record_id": row["source_record_id"],
                            "rejection_reason": rejection_reason,
                            "raw_payload_json": row["raw_payload_json"],
                        }
                    )
                else:
                    accepted.append(row)
            print(
                "jamendo_progress "
                f"fetched={fetched_records} "
                f"accepted={len(accepted)} "
                f"rejected={len(rejected)} "
                f"requested={limit}",
                file=progress_handle,
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_csv, OUTPUT_FIELDS, accepted)
    _write_jsonl(output_jsonl, accepted)
    _write_csv(rejected_csv, REJECTED_FIELDS, rejected)
    _write_csv(sample_csv, OUTPUT_FIELDS, accepted[:20])

    result = JamendoAcquisitionResult(
        source_name=source,
        requested_limit=limit,
        fetched_records=fetched_records,
        accepted_records=len(accepted),
        rejected_records=len(rejected),
        output_csv=str(output_csv),
        output_jsonl=str(output_jsonl),
        duration_seconds=round(time.monotonic() - started, 6),
        metadata_only=True,
        audio_download_allowed=False,
        client_id_source=client_id_source,
        report_path=str(report_dir),
        rejected_csv=str(rejected_csv),
        sample_csv=str(sample_csv),
    )
    (report_dir / "acquisition_summary.json").write_text(
        json.dumps(result.to_summary(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


class JamendoCredentialError(RuntimeError):
    """Raised when live Jamendo metadata acquisition has no client id."""


def resolve_client_id(client_id: str | None) -> tuple[str, str]:
    argument_value = _clean_string(client_id)
    if argument_value:
        return argument_value, "argument"
    environment_value = _clean_string(os.environ.get("JAMENDO_CLIENT_ID"))
    if environment_value:
        return environment_value, "environment"
    return "", "missing"


def build_tracks_url(client_id: str, offset: int, limit: int) -> str:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit < 1:
        raise ValueError("limit must be positive")
    params: list[tuple[str, str | int]] = [
        ("client_id", client_id),
        ("format", "json"),
        ("limit", limit),
        ("offset", offset),
        ("order", "id_asc"),
    ]
    return f"{TRACKS_URL}?{urllib.parse.urlencode(params)}"


def map_jamendo_record(payload: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    raw_payload_json = _compact_json(_sanitize_raw_payload(payload))
    track_id = _clean_string(payload.get("id"))
    title = _first_present(payload.get("name"), payload.get("title"))
    artist = _clean_string(payload.get("artist_name"))
    album = _clean_string(payload.get("album_name"))
    row = {
        "source_record_id": track_id,
        "artist": artist,
        "album": album,
        "title": title,
        "track_number": _clean_string(payload.get("position")),
        "release_year": _release_year(payload),
        "label": "",
        "duration_seconds": _duration_seconds(payload.get("duration")),
        "genre": _genre(payload),
        "source_url": _source_url(payload, track_id),
        "raw_payload_json": raw_payload_json,
    }
    if not track_id:
        return row, "missing_track_id"
    if not any((title, artist, album)):
        return row, "missing_title_artist_album"
    return row, None


def _iter_track_records(
    client_id: str,
    limit: int,
    page_size: int,
    timeout: float,
    fetch_json: Callable[[str, float], dict[str, Any]],
):
    for page in _iter_track_record_pages(
        client_id=client_id,
        limit=limit,
        page_size=page_size,
        timeout=timeout,
        fetch_json=fetch_json,
    ):
        yield from page


def _iter_track_record_pages(
    client_id: str,
    limit: int,
    page_size: int,
    timeout: float,
    fetch_json: Callable[[str, float], dict[str, Any]],
):
    offset = 0
    remaining = limit
    while remaining > 0:
        rows = min(page_size, remaining)
        url = build_tracks_url(client_id, offset=offset, limit=rows)
        payload = fetch_json(url, timeout)
        records = _extract_results(payload)
        if not records:
            break
        page = records[:remaining]
        yield page
        remaining -= len(page)
        if remaining == 0 or len(records) < rows:
            break
        offset += rows


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "music-library-system/1.0 metadata-only"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Jamendo response must be a JSON object")
    return payload


def _extract_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Jamendo response must be a JSON object")
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("Jamendo response missing results list")
    if not all(isinstance(record, dict) for record in results):
        raise ValueError("Jamendo results must be JSON objects")
    return results


def _release_year(payload: dict[str, Any]) -> str:
    for key in ("releasedate", "release_date", "date"):
        value = _clean_string(payload.get(key))
        if len(value) >= 4 and value[:4].isdigit():
            year = int(value[:4])
            if 1000 <= year <= 2999:
                return str(year)
    return ""


def _duration_seconds(value: Any) -> str:
    text = _clean_string(value)
    if not text:
        return ""
    try:
        seconds = float(text)
    except ValueError:
        return ""
    if seconds < 0:
        return ""
    return str(int(seconds))


def _genre(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("tags"),
        _nested(payload, "musicinfo", "tags"),
        _nested(payload, "musicinfo", "tags", "genres"),
    ]
    for value in candidates:
        joined = _join_value(value)
        if joined:
            return joined
    return ""


def _source_url(payload: dict[str, Any], track_id: str) -> str:
    for key in ("shareurl", "url"):
        value = _clean_string(payload.get(key))
        if value:
            return value
    if track_id:
        return f"https://www.jamendo.com/track/{urllib.parse.quote(track_id)}"
    return ""


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_present(*values: Any) -> str:
    for value in values:
        joined = _join_value(value)
        if joined:
            return joined
    return ""


def _join_value(value: Any) -> str:
    if isinstance(value, dict):
        flattened: list[str] = []
        for key in sorted(value):
            joined = _join_value(value[key])
            if joined:
                flattened.append(joined)
        return "; ".join(flattened)
    if isinstance(value, (list, tuple)):
        return "; ".join(sorted(_clean_string(item) for item in value if _clean_string(item)))
    return _clean_string(value)


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _sanitize_raw_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_raw_payload(nested)
            for key, nested in value.items()
            if key not in MEDIA_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_raw_payload(item) for item in value]
    return value


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
