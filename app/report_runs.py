"""Deterministic report run paths and manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.data_paths import get_data_root, sanitize_source_name


COMMAND_REPORT_DIRS = {
    "convert-musicbrainz-dump": "musicbrainz_conversion",
    "import-external-metadata": "external_metadata_ingestion",
    "analyze-artist-credits": "artist_credit_analysis",
    "analyze-release-identity": "release_identity_analysis",
    "benchmark-validation": "validation_benchmark",
}


@dataclass(frozen=True)
class ReportRun:
    source_name: str
    run_label: str
    run_root: Path

    def command_dir(self, command_name: str) -> Path:
        return self.run_root / COMMAND_REPORT_DIRS[command_name]

    @property
    def manifest_path(self) -> Path:
        return self.run_root / "run_manifest.json"


def resolve_report_out_dir(
    out_dir: str | Path,
    *,
    source_name: str,
    run_label: str | None = None,
) -> Path:
    """Return the report root for a command, preserving legacy paths by default."""

    out_path = Path(out_dir).expanduser()
    if not run_label:
        out_path.mkdir(parents=True, exist_ok=True)
        return out_path
    return create_report_run(out_path, source_name=source_name, run_label=run_label).run_root


def create_report_run(
    out_dir: str | Path,
    *,
    source_name: str,
    run_label: str,
) -> ReportRun:
    source_name = sanitize_source_name(source_name)
    run_label = sanitize_run_label(run_label)
    run_root = Path(out_dir).expanduser() / "runs" / source_name / run_label
    run_root.mkdir(parents=True, exist_ok=True)
    return ReportRun(source_name=source_name, run_label=run_label, run_root=run_root)


def write_run_manifest(
    *,
    out_dir: str | Path,
    source_name: str,
    run_label: str | None,
    command_name: str,
    report_path: str | Path,
    data_root: str | Path | None = None,
) -> Path | None:
    """Create or update a run manifest for labeled report runs."""

    if not run_label:
        return None
    run = create_report_run(out_dir, source_name=source_name, run_label=run_label)
    manifest = _read_manifest(run.manifest_path)
    if not manifest:
        manifest = {
            "source_name": run.source_name,
            "run_label": run.run_label,
            "created_at": _utc_timestamp(),
            "commands_run": [],
            "report_paths": {},
            "data_root": str(get_data_root(data_root)),
            "metadata_only": True,
            "audio_downloaded": False,
            "local_library_mutated": False,
            "canonical_graph_mutated": False,
        }

    commands_run = list(manifest.get("commands_run", []))
    commands_run.append(command_name)
    manifest["commands_run"] = commands_run
    report_paths = dict(manifest.get("report_paths", {}))
    report_paths[command_name] = str(report_path)
    manifest["report_paths"] = report_paths
    manifest["data_root"] = str(get_data_root(data_root))

    run.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run.manifest_path


def sanitize_run_label(run_label: str) -> str:
    return sanitize_source_name(run_label)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
