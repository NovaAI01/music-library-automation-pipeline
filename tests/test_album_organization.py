import csv
import json
import os

import pytest

from app.album_organization import (
    UNKNOWN_ALBUM,
    generate_album_organization_plan,
    infer_album,
)
import app.album_organization as album_organization
from app.main import main


def test_album_inference_from_tag_is_high_confidence():
    result = infer_album(album_tag="Wisconsin Death Trip", parent_folder="Static-X")

    assert result.album == "Wisconsin Death Trip"
    assert result.confidence == "high"
    assert result.reason == "album_tag_present"
    assert result.requires_review is False


def test_album_inference_uses_immediate_album_folder_not_uploader_path():
    result = infer_album(
        parent_folder="Uploader Channel/Artist Name - Album Name [Full Album]",
        artist="Artist Name",
        title="Track Name",
    )

    assert result.album == "Album Name"
    assert result.confidence == "medium"
    assert result.reason == "album_like_parent_folder"
    assert "Uploader Channel" not in result.album


@pytest.mark.parametrize(
    "parent_folder",
    [
        "Some Channel/Artist Name – Album Name (Full Album Stream)",
        "Some Channel/Artist Name — Album Name [FULL ALBUM STREAM]",
        "Some Channel/Artist Name | Album Name [Full album]",
        "Some Channel/Artist Name ｜ Album Name FULL ALBUM",
    ],
)
def test_album_inference_strips_artist_prefix_and_full_album_decorations(
    parent_folder,
):
    result = infer_album(
        parent_folder=parent_folder,
        artist="Artist Name",
        title="Track Name",
    )

    assert result.album == "Album Name"


def test_album_inference_without_artist_uses_album_folder_only():
    result = infer_album(
        parent_folder="Uploader/Album Name",
        artist=None,
        title="Track Name",
    )

    assert result.album == "Album Name"


def test_album_inference_preserves_clean_album_folder_under_resolved_artist():
    result = infer_album(
        parent_folder="Uploader Channel/Album Name Deluxe",
        artist="Artist Name",
        title="Track Name",
    )

    assert result.album == "Album Name Deluxe"


def test_album_inference_fallback_requires_review():
    result = infer_album(album_tag="", parent_folder="Static-X", artist="Static-X")

    assert result.album == UNKNOWN_ALBUM
    assert result.confidence == "low"
    assert result.requires_review is True


def test_album_organization_plan_writes_csv_and_json(tmp_path, monkeypatch):
    library_root = tmp_path / "library"
    tagged = (
        library_root
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It.flac"
    )
    fallback = (
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "Nirvana - Breed.flac"
    )
    _write_file(tagged, b"not a real flac")
    _write_file(fallback, b"not a real flac")
    monkeypatch.setattr(
        album_organization,
        "_read_flac_tags",
        lambda path: {
            "album": "Wisconsin Death Trip",
            "artist": "Static-X",
            "title": "Push It",
        }
        if path == tagged
        else {},
    )

    result = generate_album_organization_plan(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    report_dir = tmp_path / "reports" / "album_organization_plan"
    summary = json.loads(
        (report_dir / "album_organization_summary.json").read_text(encoding="utf-8")
    )
    rows = _read_csv(report_dir / "album_organization_plan.csv")

    assert result.total_files == 2
    assert summary["total_files"] == 2
    assert summary["high_confidence"] == 1
    assert summary["low_confidence"] == 1
    assert rows[0]["current_path"] == str(tagged)
    assert rows[0]["proposed_path"].endswith(
        "Alternative Metal/Static-X/Wisconsin Death Trip/Static-X - Push It.flac"
    )
    assert rows[0]["confidence"] == "high"
    assert rows[1]["album"] == UNKNOWN_ALBUM
    assert rows[1]["requires_review"] == "True"


def test_album_organization_plan_does_not_mutate_audio_files(tmp_path):
    library_root = tmp_path / "library"
    track = library_root / "Alternative Metal" / "Nu Metal" / "Static-X" / "Push It.flac"
    _write_file(track, b"not a real flac")
    before = (track.read_bytes(), os.stat(track).st_mtime_ns)

    generate_album_organization_plan(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )

    after = (track.read_bytes(), os.stat(track).st_mtime_ns)
    assert after == before


def test_album_organization_cli_writes_reports(tmp_path, capsys):
    library_root = tmp_path / "library"
    _write_file(
        library_root / "Alternative Metal" / "Nu Metal" / "Static-X" / "Push It.flac",
        b"not a real flac",
    )

    exit_code = main(
        [
            "plan-album-organization",
            "--library-root",
            str(library_root),
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "total_files=1" in output
    assert "low_confidence=1" in output
    assert (
        tmp_path
        / "reports"
        / "album_organization_plan"
        / "album_organization_plan.csv"
    ).exists()


def _write_file(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))
