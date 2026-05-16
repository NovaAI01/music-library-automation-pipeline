"""Fetch Internet Archive metadata-only records into ExternalTrackRecord input files."""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.data_paths import source_metadata_dir
from app.musicbrainz_converter import OUTPUT_FIELDS, REJECTED_FIELDS


SOURCE_NAME = "internet_archive"
ADVANCED_SEARCH_URL = "https://archive.org/advancedsearch.php"
DEFAULT_PAGE_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 30.0
SEARCH_FIELDS = (
    "identifier",
    "title",
    "creator",
    "collection",
    "date",
    "year",
    "subject",
    "genre",
    "album",
    "label",
    "duration",
)


@dataclass(frozen=True)
class InternetArchiveAcquisitionResult:
    source_name: str
    query: str
    requested_limit: int
    fetched_records: int
    accepted_records: int
    rejected_records: int
    output_csv: str
    output_jsonl: str
    duration_seconds: float
    metadata_only: bool
    audio_download_allowed: bool
    report_path: str
    rejected_csv: str
    sample_csv: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "query": self.query,
            "requested_limit": self.requested_limit,
            "fetched_records": self.fetched_records,
            "accepted_records": self.accepted_records,
            "rejected_records": self.rejected_records,
            "output_csv": self.output_csv,
            "output_jsonl": self.output_jsonl,
            "duration_seconds": self.duration_seconds,
            "metadata_only": self.metadata_only,
            "audio_download_allowed": self.audio_download_allowed,
        }


def fetch_internet_archive_metadata(
    query: str,
    limit: int,
    out_dir: str | Path = "reports",
    page_size: int = DEFAULT_PAGE_SIZE,
    source: str = SOURCE_NAME,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    dry_run: bool = False,
    data_dir: str | Path | None = None,
    fetch_json: Callable[[str, float], dict[str, Any]] | None = None,
) -> InternetArchiveAcquisitionResult:
    """Fetch metadata-only search records and write normalized importer inputs."""

    started = time.monotonic()
    query = str(query).strip()
    if not query:
        raise ValueError("--query cannot be empty")
    if source != SOURCE_NAME:
        raise ValueError("--source is fixed to internet_archive")
    if limit < 1:
        raise ValueError("--limit must be a positive integer")
    if page_size < 1:
        raise ValueError("--page-size must be a positive integer")
    if timeout <= 0:
        raise ValueError("--timeout must be positive")

    output_dir = source_metadata_dir(source, data_dir)
    output_csv = output_dir / "raw_internet_archive.csv"
    output_jsonl = output_dir / "raw_internet_archive.jsonl"
    report_dir = Path(out_dir) / "internet_archive_metadata"
    rejected_csv = report_dir / "rejected_records.csv"
    sample_csv = report_dir / "sample_records.csv"

    fetched_records = 0
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []

    if not dry_run:
        fetcher = fetch_json or _fetch_json
        for payload in _iter_search_docs(
            query=query,
            limit=limit,
            page_size=page_size,
            timeout=timeout,
            fetch_json=fetcher,
        ):
            fetched_records += 1
            row, rejection_reason = map_internet_archive_record(payload)
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

    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_csv, OUTPUT_FIELDS, accepted)
    _write_jsonl(output_jsonl, accepted)
    _write_csv(rejected_csv, REJECTED_FIELDS, rejected)
    _write_csv(sample_csv, OUTPUT_FIELDS, accepted[:20])

    result = InternetArchiveAcquisitionResult(
        source_name=source,
        query=query,
        requested_limit=limit,
        fetched_records=fetched_records,
        accepted_records=len(accepted),
        rejected_records=len(rejected),
        output_csv=str(output_csv),
        output_jsonl=str(output_jsonl),
        duration_seconds=round(time.monotonic() - started, 6),
        metadata_only=True,
        audio_download_allowed=False,
        report_path=str(report_dir),
        rejected_csv=str(rejected_csv),
        sample_csv=str(sample_csv),
    )
    (report_dir / "acquisition_summary.json").write_text(
        json.dumps(result.to_summary(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def build_search_url(query: str, page: int, rows: int) -> str:
    if page < 1:
        raise ValueError("page must be positive")
    if rows < 1:
        raise ValueError("rows must be positive")
    params: list[tuple[str, str | int]] = [
        ("q", query),
        ("output", "json"),
        ("page", page),
        ("rows", rows),
    ]
    params.extend(("fl[]", field) for field in SEARCH_FIELDS)
    return f"{ADVANCED_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def map_internet_archive_record(payload: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    raw_payload_json = _compact_json(payload)
    identifier = _clean_string(payload.get("identifier"))
    evidence_values = (
        payload.get("title"),
        payload.get("creator"),
        payload.get("collection"),
        payload.get("subject"),
        payload.get("genre"),
    )
    row = {
        "source_record_id": identifier,
        "artist": _join_value(payload.get("creator")),
        "album": _first_present(payload.get("album"), payload.get("collection")),
        "title": _clean_string(payload.get("title")) or identifier,
        "track_number": "",
        "release_year": _release_year(payload),
        "label": _join_value(payload.get("label")),
        "duration_seconds": _duration_seconds(payload.get("duration")),
        "genre": _first_present(payload.get("subject"), payload.get("genre")),
        "source_url": (
            f"https://archive.org/details/{urllib.parse.quote(identifier)}"
            if identifier
            else ""
        ),
        "raw_payload_json": raw_payload_json,
    }
    if not identifier:
        return row, "missing_identifier"
    if not any(_has_value(value) for value in evidence_values):
        return row, "missing_title_creator_collection_subject_evidence"
    return row, None


def _iter_search_docs(
    query: str,
    limit: int,
    page_size: int,
    timeout: float,
    fetch_json: Callable[[str, float], dict[str, Any]],
):
    page = 1
    remaining = limit
    while remaining > 0:
        rows = min(page_size, remaining)
        url = build_search_url(query, page, rows)
        payload = fetch_json(url, timeout)
        docs = _extract_docs(payload)
        if not docs:
            break
        for doc in docs[:remaining]:
            yield doc
            remaining -= 1
            if remaining == 0:
                break
        if len(docs) < rows:
            break
        page += 1


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "music-library-system/1.0 metadata-only"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Internet Archive response must be a JSON object")
    return payload


def _extract_docs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Internet Archive response must be a JSON object")
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ValueError("Internet Archive response missing response object")
    docs = response.get("docs")
    if not isinstance(docs, list):
        raise ValueError("Internet Archive response missing docs list")
    if not all(isinstance(doc, dict) for doc in docs):
        raise ValueError("Internet Archive docs must be JSON objects")
    return docs


def _release_year(payload: dict[str, Any]) -> str:
    for key in ("year", "date"):
        value = _join_value(payload.get(key))
        if len(value) >= 4 and value[:4].isdigit():
            year = int(value[:4])
            if 1000 <= year <= 2999:
                return str(year)
        if len(value) == 4 and value.isdigit():
            return value
    return ""


def _duration_seconds(value: Any) -> str:
    text = _join_value(value)
    if not text:
        return ""
    try:
        seconds = float(text)
    except ValueError:
        return ""
    if seconds < 0:
        return ""
    return str(int(seconds))


def _first_present(*values: Any) -> str:
    for value in values:
        joined = _join_value(value)
        if joined:
            return joined
    return ""


def _join_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "; ".join(sorted(_clean_string(item) for item in value if _clean_string(item)))
    return _clean_string(value)


def _has_value(value: Any) -> bool:
    return bool(_join_value(value))


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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
