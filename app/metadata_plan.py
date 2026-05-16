"""Read-only metadata normalization plans from organised library paths."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from mutagen.flac import FLAC

from app.metadata_audit import AUDIT_FIELDS, FIELD_CANDIDATES, MetadataRecord


PLAN_HEADERS: tuple[str, ...] = (
    "path",
    "field",
    "current_value",
    "proposed_value",
    "reason",
)
PLANNED_FIELDS: tuple[str, ...] = ("artist", "title", "genre", "album_artist")
KNOWN_ARTIST_CASING: dict[str, str] = {
    "chevelle": "Chevelle",
    "korn": "Korn",
    "rage against the machine": "Rage Against the Machine",
}

_SOURCE_SUFFIXES = (
    "Official HD Video",
    "Official Visualizer",
    "Official Audio",
    "Official Video",
    "Visualizer",
    "Audio",
    "HD",
    "4K",
)
_SOURCE_SUFFIX_RE = re.compile(
    r"\s*(?:[\[(]\s*)?(?:"
    + "|".join(re.escape(suffix) for suffix in _SOURCE_SUFFIXES)
    + r")(?:\s*[\])])?\s*$",
    re.IGNORECASE,
)
_DUPLICATE_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class MetadataPlanResult:
    report_path: str
    total_flac_files: int
    readable_flac_files: int
    unreadable_flac_files: int
    proposed_update_count: int


def generate_metadata_plan(
    *,
    library_root: str | Path,
    out_dir: str | Path = "reports",
) -> MetadataPlanResult:
    """Export a read-only tag correction plan from an organised library tree."""

    library_root_path = Path(library_root).expanduser()
    report_dir = Path(out_dir).expanduser() / "metadata_plan"
    report_dir.mkdir(parents=True, exist_ok=True)

    records = [_read_flac_tags(path, library_root_path) for path in _iter_flac_files(library_root_path)]
    rows = _plan_rows(records)
    counts_by_field = Counter(row["field"] for row in rows)
    summary = {
        "library_root": str(library_root_path),
        "total_flac_files": len(records),
        "readable_flac_files": sum(1 for record in records if record.read_error is None),
        "unreadable_flac_files": sum(1 for record in records if record.read_error is not None),
        "proposed_update_count": len(rows),
        "counts_by_field": dict(sorted(counts_by_field.items())),
    }

    _write_json(report_dir / "metadata_plan_summary.json", summary)
    _write_csv(report_dir / "tag_update_plan.csv", PLAN_HEADERS, rows)

    return MetadataPlanResult(
        report_path=str(report_dir),
        total_flac_files=summary["total_flac_files"],
        readable_flac_files=summary["readable_flac_files"],
        unreadable_flac_files=summary["unreadable_flac_files"],
        proposed_update_count=summary["proposed_update_count"],
    )


def _iter_flac_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".flac")


def _read_flac_tags(path: Path, library_root: Path) -> MetadataRecord:
    relative_path = path.relative_to(library_root).as_posix()
    try:
        audio = FLAC(path)
    except Exception as exc:  # mutagen raises several parse-specific exceptions.
        return MetadataRecord(
            path=path,
            relative_path=relative_path,
            tags={field: None for field in AUDIT_FIELDS},
            read_error=str(exc),
        )

    return MetadataRecord(
        path=path,
        relative_path=relative_path,
        tags={field: _tag_value(audio, FIELD_CANDIDATES[field]) for field in AUDIT_FIELDS},
    )


def _tag_value(audio: Any, candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        values = audio.get(candidate)
        if values:
            cleaned_values = [str(value) for value in values if str(value) != ""]
            if cleaned_values:
                return "; ".join(cleaned_values)
    return None


def _plan_rows(records: Iterable[MetadataRecord]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        if record.read_error is not None:
            continue
        proposed = _proposed_values(record.relative_path)
        for field in PLANNED_FIELDS:
            proposed_value = proposed.get(field)
            if proposed_value is None:
                continue
            current_value = record.tags.get(field) or ""
            if current_value == proposed_value:
                continue
            rows.append(
                {
                    "path": record.relative_path,
                    "field": field,
                    "current_value": current_value,
                    "proposed_value": proposed_value,
                    "reason": _reason_for_field(field),
                }
            )
    return sorted(rows, key=lambda row: (row["path"], row["field"]))


def _proposed_values(relative_path: str) -> dict[str, str]:
    path = Path(relative_path)
    parts = path.parts
    if len(parts) < 4:
        return {}

    raw_artist = parts[-2]
    artist = _normalize_artist_casing(raw_artist)
    return {
        "artist": artist,
        "title": _title_from_filename(path.stem, raw_artist),
        "genre": parts[0],
        "album_artist": artist,
    }


def _title_from_filename(stem: str, raw_artist: str) -> str:
    prefix = f"{raw_artist} - "
    title = stem[len(prefix) :] if stem.startswith(prefix) else stem
    title = _strip_source_suffixes(title)
    return _DUPLICATE_WHITESPACE_RE.sub(" ", title).strip()


def _strip_source_suffixes(title: str) -> str:
    previous = None
    stripped = title.strip()
    while previous != stripped:
        previous = stripped
        stripped = _SOURCE_SUFFIX_RE.sub("", stripped).strip()
    return stripped


def _normalize_artist_casing(artist: str) -> str:
    return KNOWN_ARTIST_CASING.get(artist.casefold(), artist)


def _reason_for_field(field: str) -> str:
    reasons = {
        "artist": "artist folder",
        "title": "filename",
        "genre": "top-level genre folder",
        "album_artist": "album_artist should equal artist",
    }
    return reasons[field]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, headers: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
