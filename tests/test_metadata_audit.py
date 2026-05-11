import csv
import json
import os

from app import metadata_audit
from app.main import main
from app.metadata_audit import (
    INCONSISTENT_HEADERS,
    MALFORMED_TAG_HEADERS,
    MISSING_TAG_HEADERS,
    generate_metadata_audit_report,
)


def test_writes_metadata_audit_summary(tmp_path, monkeypatch):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)

    result = generate_metadata_audit_report(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    summary = json.loads(
        (tmp_path / "reports" / "metadata_audit" / "metadata_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.total_flac_files == 5
    assert result.readable_flac_files == 4
    assert result.unreadable_flac_files == 1
    assert summary["total_flac_files"] == 5
    assert summary["missing_tag_count"] == 2
    assert summary["inconsistent_artist_group_count"] == 1
    assert summary["inconsistent_title_group_count"] == 2
    assert "created_at" not in summary


def test_writes_expected_csv_files_and_headers(tmp_path, monkeypatch):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)

    generate_metadata_audit_report(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    report_dir = tmp_path / "reports" / "metadata_audit"

    assert _csv_headers(report_dir / "inconsistent_artists.csv") == list(
        INCONSISTENT_HEADERS
    )
    assert _csv_headers(report_dir / "inconsistent_titles.csv") == list(
        INCONSISTENT_HEADERS
    )
    assert _csv_headers(report_dir / "missing_tags.csv") == list(MISSING_TAG_HEADERS)
    assert _csv_headers(report_dir / "malformed_tags.csv") == list(
        MALFORMED_TAG_HEADERS
    )


def test_detects_missing_tags(tmp_path, monkeypatch):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)

    generate_metadata_audit_report(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    rows = _read_csv(tmp_path / "reports" / "metadata_audit" / "missing_tags.csv")

    assert rows == [
        {"path": "Deftones/02.flac", "field": "date"},
        {"path": "Deftones/02.flac", "field": "genre"},
    ]


def test_detects_malformed_tag_values(tmp_path, monkeypatch):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)

    generate_metadata_audit_report(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    rows = _read_csv(tmp_path / "reports" / "metadata_audit" / "malformed_tags.csv")
    issue_keys = {(row["path"], row["field"], row["issue_type"]) for row in rows}

    assert ("Deftones/02.flac", "album", "duplicate_whitespace") in issue_keys
    assert ("Deftones/02.flac", "artist", "trailing_space") in issue_keys
    assert ("Deftones/02.flac", "title", "probable_junk_suffix") in issue_keys
    assert ("Deftones/02.flac", "tracknumber", "malformed_tracknumber") in issue_keys
    assert ("Static-X/01.flac", "artist", "separator_symbol") in issue_keys
    assert ("Static-X/bad.flac", "_file", "unreadable_flac") in issue_keys


def test_detects_inconsistent_artist_and_title_groups(tmp_path, monkeypatch):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)

    generate_metadata_audit_report(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    artist_rows = _read_csv(
        tmp_path / "reports" / "metadata_audit" / "inconsistent_artists.csv"
    )
    title_rows = _read_csv(
        tmp_path / "reports" / "metadata_audit" / "inconsistent_titles.csv"
    )

    assert artist_rows == [
        {
            "normalized_value": "staticx",
            "variants": "Static -X | static -x",
            "file_count": "2",
            "paths": "Static-X/01.flac | Static-X/02.flac",
            "issue_types": (
                "inconsistent_capitalization | "
                "mixed_casing_within_artist_group | separator_inconsistency"
            ),
        }
    ]
    title_issue_types = {
        row["normalized_value"]: row["issue_types"] for row in title_rows
    }
    assert title_issue_types["change"] == "inconsistent_capitalization"
    assert title_issue_types["pushit"] == "separator_inconsistency"


def test_output_is_deterministic(tmp_path, monkeypatch):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)
    out_dir = tmp_path / "reports"

    generate_metadata_audit_report(library_root=library_root, out_dir=out_dir)
    first = _report_bytes(out_dir / "metadata_audit")
    generate_metadata_audit_report(library_root=library_root, out_dir=out_dir)
    second = _report_bytes(out_dir / "metadata_audit")

    assert second == first


def test_does_not_mutate_flac_files(tmp_path, monkeypatch):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)
    tracked_files = sorted(path for path in library_root.rglob("*") if path.is_file())
    before = {
        path: (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in tracked_files
    }

    generate_metadata_audit_report(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )

    after = {
        path: (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in tracked_files
    }
    assert after == before


def test_cli_works(tmp_path, monkeypatch, capsys):
    library_root = _make_metadata_fixture(tmp_path, monkeypatch)
    out_dir = tmp_path / "reports"

    exit_code = main(
        [
            "metadata-audit",
            "--library-root",
            str(library_root),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={out_dir / 'metadata_audit'}" in output
    assert "total_flac_files=5" in output
    assert "unreadable_flac_files=1" in output
    assert (out_dir / "metadata_audit" / "metadata_summary.json").exists()


def test_missing_library_root_writes_empty_reports(tmp_path):
    result = generate_metadata_audit_report(
        library_root=tmp_path / "missing",
        out_dir=tmp_path / "reports",
    )

    assert result.total_flac_files == 0
    assert _read_csv(tmp_path / "reports" / "metadata_audit" / "missing_tags.csv") == []


def _make_metadata_fixture(tmp_path, monkeypatch):
    library_root = tmp_path / "Organised_Library"
    tags_by_path = {
        "Static-X/01.flac": {
            "artist": ["Static -X"],
            "albumartist": ["Static -X"],
            "album": ["Wisconsin Death Trip"],
            "title": ["Push It"],
            "genre": ["Industrial Metal"],
            "date": ["1999"],
            "tracknumber": ["1/12"],
        },
        "Static-X/02.flac": {
            "artist": ["static -x"],
            "albumartist": ["Static -X"],
            "album": ["Wisconsin Death Trip"],
            "title": ["Push_It"],
            "genre": ["Industrial Metal"],
            "date": ["1999"],
            "tracknumber": ["02"],
        },
        "Deftones/01.flac": {
            "artist": ["Deftones"],
            "album_artist": ["Deftones"],
            "album": ["White Pony"],
            "title": ["Change"],
            "genre": ["Alternative Metal"],
            "date": ["2000"],
            "tracknumber": ["11"],
        },
        "Deftones/02.flac": {
            "artist": ["Deftones "],
            "album_artist": ["Deftones"],
            "album": ["White  Pony"],
            "title": ["change [Official Video]"],
            "tracknumber": ["A1"],
        },
    }
    for relative_path in [
        *tags_by_path,
        "Static-X/bad.flac",
        "ignored.mp3",
    ]:
        _write_file(library_root / relative_path, relative_path.encode("utf-8"))

    class FakeFLAC:
        def __init__(self, path):
            relative_path = path.relative_to(library_root).as_posix()
            if relative_path == "Static-X/bad.flac":
                raise ValueError("not a valid FLAC")
            self.tags = tags_by_path[relative_path]

        def get(self, key):
            return self.tags.get(key)

    monkeypatch.setattr(metadata_audit, "FLAC", FakeFLAC)
    return library_root


def _write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _csv_headers(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return next(csv.reader(file_handle))


def _report_bytes(report_dir):
    return {
        path.name: path.read_bytes()
        for path in sorted(report_dir.iterdir())
        if path.is_file()
    }
