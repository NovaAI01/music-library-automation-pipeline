"""Read-only FLAC metadata audit reports."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from mutagen.flac import FLAC


AUDIT_FIELDS: tuple[str, ...] = (
    "artist",
    "album_artist",
    "album",
    "title",
    "genre",
    "date",
    "tracknumber",
)
FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "artist": ("artist",),
    "album_artist": ("album_artist", "albumartist", "album artist"),
    "album": ("album",),
    "title": ("title",),
    "genre": ("genre",),
    "date": ("date", "year"),
    "tracknumber": ("tracknumber", "track"),
}
INCONSISTENT_HEADERS: tuple[str, ...] = (
    "normalized_value",
    "variants",
    "file_count",
    "paths",
    "issue_types",
)
MISSING_TAG_HEADERS: tuple[str, ...] = ("path", "field")
MALFORMED_TAG_HEADERS: tuple[str, ...] = (
    "path",
    "field",
    "value",
    "issue_type",
    "detail",
)

_DUPLICATE_WHITESPACE_RE = re.compile(r"\s{2,}")
_JUNK_SUFFIX_RE = re.compile(
    r"\s*(?:"
    r"\[[A-Za-z0-9_-]{8,}\]"
    r"|\((?:official\s+(?:audio|video|visualizer)|audio|video|hd|4k|lyrics?|explicit)\)"
    r"|\[(?:official\s+(?:audio|video|visualizer)|audio|video|hd|4k|lyrics?|explicit)\]"
    r")\s*$",
    re.IGNORECASE,
)
_TRACKNUMBER_RE = re.compile(r"^(?:0*[1-9]\d?|[1-9]\d{2,})(?:/0*[1-9]\d*)?$")


@dataclass(frozen=True)
class MetadataAuditResult:
    report_path: str
    total_flac_files: int
    readable_flac_files: int
    unreadable_flac_files: int
    missing_tag_count: int
    malformed_tag_count: int
    inconsistent_artist_group_count: int
    inconsistent_title_group_count: int


@dataclass(frozen=True)
class MetadataRecord:
    path: Path
    relative_path: str
    tags: dict[str, str | None]
    read_error: str | None = None


def generate_metadata_audit_report(
    *,
    library_root: str | Path,
    out_dir: str | Path = "reports",
) -> MetadataAuditResult:
    """Export read-only metadata audit reports for all FLAC files below a root."""

    library_root_path = Path(library_root).expanduser()
    report_dir = Path(out_dir).expanduser() / "metadata_audit"
    report_dir.mkdir(parents=True, exist_ok=True)

    records = [_read_flac_tags(path, library_root_path) for path in _iter_flac_files(library_root_path)]
    missing_rows = _missing_tag_rows(records)
    malformed_rows = _malformed_tag_rows(records)
    artist_rows = _inconsistent_rows(records, field="artist")
    title_rows = _inconsistent_rows(records, field="title")
    issue_counts = Counter(row["issue_type"] for row in malformed_rows)
    if missing_rows:
        issue_counts["missing_tag"] = len(missing_rows)

    summary = {
        "library_root": str(library_root_path),
        "total_flac_files": len(records),
        "readable_flac_files": sum(1 for record in records if record.read_error is None),
        "unreadable_flac_files": sum(1 for record in records if record.read_error is not None),
        "missing_tag_count": len(missing_rows),
        "malformed_tag_count": len(malformed_rows),
        "inconsistent_artist_group_count": len(artist_rows),
        "inconsistent_title_group_count": len(title_rows),
        "counts_by_issue_type": dict(sorted(issue_counts.items())),
    }

    _write_json(report_dir / "metadata_summary.json", summary)
    _write_csv(report_dir / "inconsistent_artists.csv", INCONSISTENT_HEADERS, artist_rows)
    _write_csv(report_dir / "inconsistent_titles.csv", INCONSISTENT_HEADERS, title_rows)
    _write_csv(report_dir / "missing_tags.csv", MISSING_TAG_HEADERS, missing_rows)
    _write_csv(report_dir / "malformed_tags.csv", MALFORMED_TAG_HEADERS, malformed_rows)

    return MetadataAuditResult(
        report_path=str(report_dir),
        total_flac_files=summary["total_flac_files"],
        readable_flac_files=summary["readable_flac_files"],
        unreadable_flac_files=summary["unreadable_flac_files"],
        missing_tag_count=summary["missing_tag_count"],
        malformed_tag_count=summary["malformed_tag_count"],
        inconsistent_artist_group_count=summary["inconsistent_artist_group_count"],
        inconsistent_title_group_count=summary["inconsistent_title_group_count"],
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


def _missing_tag_rows(records: Iterable[MetadataRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if record.read_error is not None:
            continue
        for field in AUDIT_FIELDS:
            if record.tags[field] in (None, ""):
                rows.append({"path": record.relative_path, "field": field})
    return sorted(rows, key=lambda row: (row["path"], row["field"]))


def _malformed_tag_rows(records: Iterable[MetadataRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if record.read_error is not None:
            rows.append(
                {
                    "path": record.relative_path,
                    "field": "_file",
                    "value": "",
                    "issue_type": "unreadable_flac",
                    "detail": record.read_error,
                }
            )
            continue
        for field, value in record.tags.items():
            if value in (None, ""):
                continue
            rows.extend(_value_issues(record.relative_path, field, value))
    return sorted(
        rows,
        key=lambda row: (row["path"], row["field"], row["issue_type"], row["value"]),
    )


def _value_issues(path: str, field: str, value: str) -> list[dict[str, str]]:
    checks = [
        ("trailing_space", value != value.rstrip(), "tag value has trailing whitespace"),
        ("duplicate_whitespace", bool(_DUPLICATE_WHITESPACE_RE.search(value)), "tag value contains repeated whitespace"),
        ("separator_symbol", _has_separator_symbol_issue(value), "tag value contains inconsistent separator symbols"),
        ("probable_junk_suffix", bool(_JUNK_SUFFIX_RE.search(value)), "tag value ends with a probable source or video suffix"),
    ]
    if field == "tracknumber":
        checks.append(
            (
                "malformed_tracknumber",
                not bool(_TRACKNUMBER_RE.match(value.strip())),
                "tracknumber should be a positive number or number/total",
            )
        )

    return [
        {
            "path": path,
            "field": field,
            "value": value,
            "issue_type": issue_type,
            "detail": detail,
        }
        for issue_type, failed, detail in checks
        if failed
    ]


def _has_separator_symbol_issue(value: str) -> bool:
    return "_" in value or " -" in value or "- " in value


def _inconsistent_rows(records: Iterable[MetadataRecord], *, field: str) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[MetadataRecord]] = defaultdict(list)
    for record in records:
        if record.read_error is not None:
            continue
        value = record.tags.get(field)
        if not value:
            continue
        normalized = _normalize_group_value(value)
        if normalized:
            grouped[normalized].append(record)

    rows: list[dict[str, Any]] = []
    for normalized, group_records in grouped.items():
        variants = sorted({record.tags[field] or "" for record in group_records})
        issue_types = _group_issue_types(variants, field=field)
        if not issue_types:
            continue
        rows.append(
            {
                "normalized_value": normalized,
                "variants": " | ".join(variants),
                "file_count": len(group_records),
                "paths": " | ".join(sorted(record.relative_path for record in group_records)),
                "issue_types": " | ".join(issue_types),
            }
        )

    return sorted(rows, key=lambda row: row["normalized_value"])


def _group_issue_types(variants: list[str], *, field: str) -> list[str]:
    issue_types: set[str] = set()
    if len(variants) <= 1:
        return []
    if len({variant.strip() for variant in variants}) == 1:
        return []
    comparison_values = [_comparison_value(variant) for variant in variants]
    if len({value.casefold() for value in comparison_values}) == 1:
        issue_types.add("inconsistent_capitalization")
    if any(_normalize_separators(value) != value for value in comparison_values) and len(
        {_normalize_separators(value).casefold() for value in comparison_values}
    ) == 1:
        issue_types.add("separator_inconsistency")
    if field == "artist" and len({value.casefold() for value in comparison_values}) < len(variants):
        issue_types.add("mixed_casing_within_artist_group")
    if not issue_types:
        issue_types.add("variant_spelling")
    return sorted(issue_types)


def _normalize_group_value(value: str) -> str:
    normalized = _normalize_separators(_comparison_value(value))
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _comparison_value(value: str) -> str:
    return _JUNK_SUFFIX_RE.sub("", value).strip()


def _normalize_separators(value: str) -> str:
    return value.replace("_", " ").replace(" -", "-").replace("- ", "-")


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
