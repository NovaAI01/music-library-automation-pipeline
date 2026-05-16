"""Configurable runtime data paths for large external metadata artifacts."""

from __future__ import annotations

import os
import re
from pathlib import Path


DATA_ROOT_ENV_VAR = "MUSIC_INTELLIGENCE_DATA_ROOT"
DEFAULT_DATA_ROOT = Path("data")

_SOURCE_SAFE_RE = re.compile(r"[^a-z0-9_-]+")


def get_data_root(data_root: str | Path | None = None) -> Path:
    """Return the configured data root, creating it when needed."""

    root_value = data_root
    if root_value is None:
        root_value = os.environ.get(DATA_ROOT_ENV_VAR) or DEFAULT_DATA_ROOT
    root = Path(root_value).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def external_metadata_root(data_root: str | Path | None = None) -> Path:
    return _mkdir(get_data_root(data_root) / "external_metadata")


def reports_root(data_root: str | Path | None = None) -> Path:
    return _mkdir(get_data_root(data_root) / "reports")


def cache_root(data_root: str | Path | None = None) -> Path:
    return _mkdir(get_data_root(data_root) / "cache")


def raw_dumps_root(data_root: str | Path | None = None) -> Path:
    return _mkdir(get_data_root(data_root) / "raw_dumps")


def source_metadata_dir(source_name: str, data_root: str | Path | None = None) -> Path:
    safe_source_name = sanitize_source_name(source_name)
    return _mkdir(external_metadata_root(data_root) / safe_source_name)


def source_external_tracks_csv(
    source_name: str,
    data_root: str | Path | None = None,
) -> Path:
    return source_metadata_dir(source_name, data_root) / "external_tracks.csv"


def source_external_tracks_jsonl(
    source_name: str,
    data_root: str | Path | None = None,
) -> Path:
    return source_metadata_dir(source_name, data_root) / "external_tracks.jsonl"


def sanitize_source_name(source_name: str) -> str:
    raw = str(source_name).strip()
    if not raw:
        raise ValueError("source name cannot be empty")
    if "/" in raw or "\\" in raw:
        raise ValueError("source name cannot contain path separators")
    if raw in {".", ".."}:
        raise ValueError("source name cannot be a relative path segment")

    sanitized = _SOURCE_SAFE_RE.sub("_", raw.casefold()).strip("_")
    if not sanitized or sanitized in {".", ".."}:
        raise ValueError("source name must contain at least one safe character")
    return sanitized


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
