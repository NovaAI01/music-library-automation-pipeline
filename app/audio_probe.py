"""Read-only audio probing helpers backed by ffprobe when available."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AudioProbeResult:
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    bitrate: int | None
    codec: str | None
    container: str | None
    probe_status: str
    probe_error: str | None
    tags: dict[str, str | None]
    tag_status: str


TAG_FIELDS = {
    "title": ("title",),
    "artist": ("artist",),
    "album": ("album",),
    "album_artist": ("album_artist", "albumartist"),
    "genre": ("genre",),
    "date": ("date", "year"),
    "track_number": ("track", "tracknumber"),
    "disc_number": ("disc", "discnumber"),
    "composer": ("composer",),
    "comment": ("comment", "description"),
}


def probe_audio(path: str | Path) -> AudioProbeResult:
    """Probe audio metadata without modifying the source file."""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        return _failed_result(f"ffprobe not found: {exc}")
    except subprocess.TimeoutExpired as exc:
        return _failed_result(f"ffprobe timed out: {exc}")
    except OSError as exc:
        return _failed_result(str(exc))

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip()
        return _failed_result(error or f"ffprobe exited {completed.returncode}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _failed_result(f"ffprobe returned invalid JSON: {exc}")

    return parse_ffprobe_payload(payload)


def parse_ffprobe_payload(payload: dict[str, Any]) -> AudioProbeResult:
    """Convert ffprobe JSON into ledger fields."""

    streams = payload.get("streams") or []
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        {},
    )
    format_data = payload.get("format") or {}
    tags = _extract_tags(format_data.get("tags") or audio_stream.get("tags") or {})

    return AudioProbeResult(
        duration_seconds=_to_float(
            audio_stream.get("duration") or format_data.get("duration")
        ),
        sample_rate=_to_int(audio_stream.get("sample_rate")),
        channels=_to_int(audio_stream.get("channels")),
        bitrate=_to_int(audio_stream.get("bit_rate") or format_data.get("bit_rate")),
        codec=audio_stream.get("codec_name"),
        container=format_data.get("format_name"),
        probe_status="ok",
        probe_error=None,
        tags=tags,
        tag_status="ok" if any(tags.values()) else "empty",
    )


def _failed_result(error: str) -> AudioProbeResult:
    return AudioProbeResult(
        duration_seconds=None,
        sample_rate=None,
        channels=None,
        bitrate=None,
        codec=None,
        container=None,
        probe_status="failed",
        probe_error=error,
        tags={field: None for field in TAG_FIELDS},
        tag_status="unavailable",
    )


def _extract_tags(raw_tags: dict[str, Any]) -> dict[str, str | None]:
    tags_by_lower_key = {str(key).lower(): value for key, value in raw_tags.items()}
    extracted: dict[str, str | None] = {}

    for field, candidates in TAG_FIELDS.items():
        value = None
        for candidate in candidates:
            raw_value = tags_by_lower_key.get(candidate)
            if raw_value not in (None, ""):
                value = str(raw_value)
                break
        extracted[field] = value

    return extracted


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
