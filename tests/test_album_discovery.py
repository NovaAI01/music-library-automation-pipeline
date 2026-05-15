import csv
import json

import pytest

from app.album_discovery import (
    SUGGESTION_HEADERS,
    generate_album_discovery,
)
from app.main import build_parser, main


def test_unknown_album_detection_and_local_suggestion(tmp_path):
    library_root = _make_library(tmp_path)

    result = generate_album_discovery(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    suggestions = _read_suggestions(tmp_path)

    assert result.total_tracks_checked == 3
    assert result.unknown_album_tracks == 2
    assert result.total_suggestions == 1
    assert suggestions[0] == {
        "file_path": "Metal/Static-X/Unknown Album/Wisconsin Death Trip - 01 - Push It.mp3",
        "artist": "Static-X",
        "title": "Push It",
        "current_album": "Unknown Album",
        "suggested_album": "Wisconsin Death Trip",
        "release_year": "",
        "confidence": "low",
        "confidence_reason": "Local filename evidence contains an album-like token; no external metadata was used.",
        "source": "local_filename",
        "source_url": "",
        "requires_human_review": True,
    }


def test_writes_csv_json_and_summary(tmp_path):
    library_root = _make_library(tmp_path)

    generate_album_discovery(library_root=library_root, out_dir=tmp_path / "reports")
    report_dir = tmp_path / "reports" / "album_discovery"

    assert (report_dir / "album_discovery_summary.json").exists()
    assert (report_dir / "album_discovery_suggestions.json").exists()
    assert _csv_headers(report_dir / "album_discovery_suggestions.csv") == list(
        SUGGESTION_HEADERS
    )
    csv_rows = _read_csv(report_dir / "album_discovery_suggestions.csv")
    assert csv_rows[0]["requires_human_review"] == "true"
    summary = json.loads(
        (report_dir / "album_discovery_summary.json").read_text(encoding="utf-8")
    )
    assert summary["low_confidence_count"] == 1
    assert summary["network_lookup_used"] is False


def test_network_lookup_flag_is_unavailable_in_v1(tmp_path):
    library_root = _make_library(tmp_path)
    former_network_flag = "--use" + "-network"

    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "discover-albums",
                "--library-root",
                str(library_root),
                former_network_flag,
            ]
        )


def test_command_registration(tmp_path, capsys):
    library_root = _make_library(tmp_path)

    exit_code = main(
        [
            "discover-albums",
            "--library-root",
            str(library_root),
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={tmp_path / 'reports' / 'album_discovery'}" in output
    assert "network_lookup_used=false" in output
    command_names = build_parser()._subparsers._group_actions[0].choices
    assert "discover-albums" in command_names


def _make_library(tmp_path):
    library_root = tmp_path / "library"
    _touch(
        library_root
        / "Metal"
        / "Static-X"
        / "Unknown Album"
        / "Wisconsin Death Trip - 01 - Push It.mp3"
    )
    _touch(library_root / "Metal" / "Deftones" / "Unknown Album" / "Deftones - Change.mp3")
    _touch(library_root / "Metal" / "Chevelle" / "Wonder What's Next" / "Chevelle - Send.mp3")
    return library_root


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _read_suggestions(tmp_path):
    return json.loads(
        (
            tmp_path
            / "reports"
            / "album_discovery"
            / "album_discovery_suggestions.json"
        ).read_text(encoding="utf-8")
    )["suggestions"]


def _csv_headers(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return next(csv.reader(file_handle))


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))
