import csv
import json
import os

from fastapi.testclient import TestClient

import app.album_cohesion as album_cohesion
from app.album_cohesion import (
    AlbumCohesionTrack,
    generate_album_cohesion_report,
    infer_album_cohesion,
)
from app.main import app, build_parser, main


def test_repeated_album_grouping_and_sequential_confidence():
    groups, conflicts, orphans = infer_album_cohesion(
        [
            _track(
                "01.flac",
                album_tag="Wisconsin Death Trip",
                track_number=1,
                year="1999",
                album_folder="Wisconsin Death Trip",
            ),
            _track(
                "02.flac",
                title="Bled for Days",
                album_tag="Wisconsin Death Trip",
                track_number=2,
                year="1999",
                album_folder="Wisconsin Death Trip",
            ),
        ]
    )

    assert len(groups) == 1
    assert groups[0].album == "Wisconsin Death Trip"
    assert groups[0].confidence_tier == "high"
    assert groups[0].cohesion_score >= 0.75
    assert "sequential track numbering" in groups[0].rationale
    assert "repeated album folder structure" in groups[0].rationale
    assert conflicts == []
    assert orphans == []


def test_conflicting_album_detection():
    groups, conflicts, _ = infer_album_cohesion(
        [
            _track(
                "01.flac",
                album_tag="Wisconsin Death Trip",
                track_number=1,
                album_folder="Wisconsin Death Trip",
            ),
            _track(
                "02.flac",
                title="Bled for Days",
                album_tag="Machine",
                track_number=2,
                album_folder="Wisconsin Death Trip",
            ),
        ]
    )

    assert groups[0].classification == "conflict"
    assert groups[0].confidence_tier in {"medium", "low"}
    assert "conflicting album tags detected" in groups[0].rationale
    assert conflicts
    assert conflicts[0]["conflict_type"] == "conflicting_album_tags"


def test_orphan_track_detection():
    groups, _, orphans = infer_album_cohesion(
        [_track("loose.flac", album_tag="", album_folder="", track_number=None)]
    )

    assert groups == []
    assert len(orphans) == 1
    assert orphans[0].file_path == "loose.flac"


def test_single_handling_is_not_high_confidence():
    groups, _, orphans = infer_album_cohesion(
        [_track("single.flac", album_tag="Stand Alone", album_folder="", track_number=None)]
    )

    assert len(groups) == 1
    assert groups[0].classification == "single"
    assert groups[0].confidence_tier != "high"
    assert orphans == []


def test_report_generation_and_no_mutation(tmp_path, monkeypatch):
    library_root = tmp_path / "library"
    first = library_root / "Metal" / "Nu Metal" / "Static-X" / "Wisconsin Death Trip" / "01 Push It.flac"
    second = library_root / "Metal" / "Nu Metal" / "Static-X" / "Wisconsin Death Trip" / "02 Bled for Days.flac"
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not real flac")
    before = {path: (path.read_bytes(), os.stat(path).st_mtime_ns) for path in (first, second)}
    monkeypatch.setattr(
        album_cohesion,
        "_read_flac_tags",
        lambda path: {
            "artist": "Static-X",
            "album": "Wisconsin Death Trip",
            "title": "Push It" if path == first else "Bled for Days",
            "tracknumber": "1" if path == first else "2",
            "date": "1999",
            "year": None,
        },
    )

    result = generate_album_cohesion_report(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    report_dir = tmp_path / "reports" / "album_cohesion"
    summary = json.loads((report_dir / "album_cohesion_summary.json").read_text(encoding="utf-8"))
    rows = _read_csv(report_dir / "album_groups.csv")

    assert result.total_album_groups == 1
    assert summary["high_confidence_groups"] == 1
    assert rows[0]["confidence_tier"] == "high"
    assert (report_dir / "album_groups.json").exists()
    assert (report_dir / "album_conflicts.csv").exists()
    assert (report_dir / "orphan_tracks.csv").exists()
    assert {path: (path.read_bytes(), os.stat(path).st_mtime_ns) for path in (first, second)} == before


def test_album_cohesion_cli_writes_reports(tmp_path, monkeypatch, capsys):
    library_root = tmp_path / "library"
    track = library_root / "Metal" / "Nu Metal" / "Static-X" / "Single" / "Static-X - Single.flac"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"not real flac")
    monkeypatch.setattr(
        album_cohesion,
        "_read_flac_tags",
        lambda path: {
            "artist": "Static-X",
            "album": "Single",
            "title": "Single",
            "tracknumber": None,
            "date": None,
            "year": None,
        },
    )

    exit_code = main(
        [
            "album-cohesion",
            "--library-root",
            str(library_root),
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "total_album_groups=1" in output
    assert "probable_singles=1" in output
    assert "album-cohesion" in build_parser()._subparsers._group_actions[0].choices


def test_album_cohesion_ui_rendering(tmp_path):
    app.state.reports_dir = tmp_path / "reports"
    app.state.library_root = tmp_path / "library"
    report_dir = tmp_path / "reports" / "album_cohesion"
    report_dir.mkdir(parents=True)
    _write_json(
        report_dir / "album_cohesion_summary.json",
        {
            "total_album_groups": 1,
            "high_confidence_groups": 1,
            "medium_confidence_groups": 0,
            "low_confidence_groups": 0,
            "probable_singles": 0,
            "orphan_tracks": 1,
            "conflicting_album_groups": 1,
            "created_at": "2026-05-14T00:00:00+00:00",
        },
    )
    _write_json(
        report_dir / "album_groups.json",
        {
            "groups": [
                {
                    "group_key": "static-x:wisconsindeathtrip",
                    "album": "Wisconsin Death Trip",
                    "artist": "Static-X",
                    "track_count": 2,
                    "cohesion_score": 0.96,
                    "confidence_tier": "high",
                    "classification": "album",
                    "rationale": ["sequential track numbering"],
                    "tracks": [
                        {
                            "file_path": "01.flac",
                            "album_tag": "Wisconsin Death Trip",
                            "source_folder": "Static-X/Wisconsin Death Trip",
                            "year": "1999",
                        }
                    ],
                }
            ]
        },
    )
    _write_csv(
        report_dir / "album_conflicts.csv",
        ["group_key", "album", "artist", "conflict_type", "details", "file_paths"],
        [
            {
                "group_key": "static-x:wisconsindeathtrip",
                "album": "Wisconsin Death Trip",
                "artist": "Static-X",
                "conflict_type": "conflicting_album_tags",
                "details": "Wisconsin Death Trip | Machine",
                "file_paths": "01.flac | 02.flac",
            }
        ],
    )
    _write_csv(
        report_dir / "orphan_tracks.csv",
        ["file_path", "artist", "title", "source_folder", "reason"],
        [
            {
                "file_path": "loose.flac",
                "artist": "Static-X",
                "title": "Loose",
                "source_folder": "Static-X",
                "reason": "no repeated album evidence",
            }
        ],
    )

    response = TestClient(app).get("/review/albums")

    assert response.status_code == 200
    assert "Album Cohesion" in response.text
    assert "Wisconsin Death Trip" in response.text
    assert "confidence-high" in response.text
    assert "conflicting_album_tags" in response.text
    assert "loose.flac" in response.text
    assert "sequential track numbering" in response.text


def _track(
    path,
    *,
    artist="Static-X",
    title="Push It",
    album_tag="Wisconsin Death Trip",
    track_number=1,
    year="1999",
    source_folder="Static-X/Wisconsin Death Trip",
    album_folder="Wisconsin Death Trip",
):
    return AlbumCohesionTrack(
        file_path=path,
        artist=artist,
        title=title,
        album_tag=album_tag,
        track_number=track_number,
        year=year,
        source_folder=source_folder,
        album_folder=album_folder,
        filename_album="",
        filename_artist=artist,
        filename_title=title,
    )


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
