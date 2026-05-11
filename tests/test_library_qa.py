import csv
import json
import os

from app.library_qa import (
    ARTIST_HEADERS,
    FILE_HEALTH_HEADERS,
    GENRE_HEADERS,
    QUARANTINE_HEADERS,
    generate_library_qa_report,
)
from app.main import main


def test_counts_library_files(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    assert result.total_library_files == 4


def test_counts_quarantine_files(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    assert result.total_quarantine_files == 2


def test_counts_artists_from_folder_structure(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )
    artist_rows = _read_csv(tmp_path / "reports" / "library_qa" / "artists.csv")

    assert result.artist_count == 3
    assert {row["artist"] for row in artist_rows} == {
        "Deftones",
        "Nirvana",
        "Static-X",
    }


def test_counts_genres_and_subgenres_from_folder_structure(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    result = generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    assert result.genre_count == 2
    assert result.subgenre_count == 3


def test_writes_json_summary(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )
    summary_path = tmp_path / "reports" / "library_qa" / "library_qa_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["library_root"] == str(library_root)
    assert summary["quarantine_root"] == str(quarantine_root)
    assert summary["total_library_files"] == 4
    assert summary["total_quarantine_files"] == 2
    assert "created_at" in summary


def test_writes_csv_reports(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)

    generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )
    report_dir = tmp_path / "reports" / "library_qa"

    assert _csv_headers(report_dir / "artists.csv") == list(ARTIST_HEADERS)
    assert _csv_headers(report_dir / "genres.csv") == list(GENRE_HEADERS)
    assert _csv_headers(report_dir / "quarantine_summary.csv") == list(
        QUARANTINE_HEADERS
    )
    assert _csv_headers(report_dir / "file_health.csv") == list(FILE_HEALTH_HEADERS)
    assert len(_read_csv(report_dir / "file_health.csv")) == 6


def test_does_not_mutate_files(tmp_path):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    tracked_files = [
        path
        for root in (library_root, quarantine_root)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    before = {
        path: (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in tracked_files
    }

    generate_library_qa_report(
        library_root=library_root,
        quarantine_root=quarantine_root,
        out_dir=tmp_path / "reports",
        db_path=tmp_path / "missing.sqlite3",
    )

    after = {
        path: (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in tracked_files
    }
    assert after == before


def test_cli_works(tmp_path, capsys):
    library_root, quarantine_root = _make_library_fixture(tmp_path)
    out_dir = tmp_path / "reports"

    exit_code = main(
        [
            "--db",
            str(tmp_path / "missing.sqlite3"),
            "library-qa",
            "--library-root",
            str(library_root),
            "--quarantine-root",
            str(quarantine_root),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={out_dir / 'library_qa'}" in output
    assert "total_library_files=4" in output
    assert "total_quarantine_files=2" in output
    assert (out_dir / "library_qa" / "library_qa_summary.json").exists()


def _make_library_fixture(tmp_path):
    library_root = tmp_path / "Organised_Library"
    quarantine_root = tmp_path / "Quarantine_Duplicates"

    _write_file(
        library_root
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It.flac",
        b"static-x",
    )
    _write_file(
        library_root
        / "Alternative Metal"
        / "Shoegaze Metal"
        / "Deftones"
        / "Deftones - Change.mp3",
        b"deftones",
    )
    _write_file(
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "Nirvana - Breed.wav",
        b"nirvana",
    )
    _write_file(
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "Nirvana - Lounge Act.m4a",
        b"lounge",
    )
    _write_file(
        library_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana"
        / "cover.jpg",
        b"not audio",
    )
    _write_file(
        quarantine_root
        / "Alternative Rock"
        / "Grunge"
        / "Nirvana - Breed duplicate.wav",
        b"quarantined",
    )
    _write_file(
        quarantine_root / "Loose" / "Deftones - Change duplicate.mp3",
        b"duplicate",
    )
    return library_root, quarantine_root


def _write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _csv_headers(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return next(csv.reader(file_handle))
