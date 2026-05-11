import csv
import json

from app import metadata_plan
from app.main import main
from app.metadata_plan import PLAN_HEADERS, generate_metadata_plan


def test_proposes_artist_from_folder(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    rows = _read_csv(tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv")

    assert _row(rows, "Rock/Alternative/CheVelle/CheVelle - Send the Pain Below.flac", "artist")[
        "proposed_value"
    ] == "Chevelle"


def test_proposes_title_from_filename(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    rows = _read_csv(tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv")

    assert _row(rows, "Metal/Nu Metal/KoRn/KoRn - Blind.flac", "title")[
        "proposed_value"
    ] == "Blind"


def test_strips_official_audio_from_title(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    rows = _read_csv(tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv")

    assert _row(
        rows,
        "Rock/Alternative/CheVelle/CheVelle - Send the Pain Below Official Audio.flac",
        "title",
    )["proposed_value"] == "Send the Pain Below"


def test_proposes_album_artist_from_artist(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    rows = _read_csv(tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv")

    assert _row(rows, "Metal/Nu Metal/KoRn/KoRn - Blind.flac", "album_artist")[
        "proposed_value"
    ] == "Korn"


def test_proposes_genre_from_genre_folder(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    rows = _read_csv(tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv")

    assert _row(rows, "Metal/Nu Metal/KoRn/KoRn - Blind.flac", "genre")[
        "proposed_value"
    ] == "Metal"


def test_does_not_propose_album(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    rows = _read_csv(tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv")

    assert "album" not in {row["field"] for row in rows}


def test_does_not_propose_tracknumber(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    rows = _read_csv(tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv")

    assert "tracknumber" not in {row["field"] for row in rows}


def test_writes_summary_json(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    result = generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    summary_path = tmp_path / "reports" / "metadata_plan" / "metadata_plan_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert result.proposed_update_count == summary["proposed_update_count"]
    assert summary["total_flac_files"] == 4
    assert summary["readable_flac_files"] == 4
    assert "created_at" not in summary


def test_writes_csv(tmp_path, monkeypatch):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)

    generate_metadata_plan(library_root=library_root, out_dir=tmp_path / "reports")
    csv_path = tmp_path / "reports" / "metadata_plan" / "tag_update_plan.csv"

    assert _csv_headers(csv_path) == list(PLAN_HEADERS)
    assert _read_csv(csv_path)


def test_cli_works(tmp_path, monkeypatch, capsys):
    library_root = _make_metadata_plan_fixture(tmp_path, monkeypatch)
    out_dir = tmp_path / "reports"

    exit_code = main(
        [
            "metadata-plan",
            "--library-root",
            str(library_root),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={out_dir / 'metadata_plan'}" in output
    assert "total_flac_files=4" in output
    assert (out_dir / "metadata_plan" / "metadata_plan_summary.json").exists()


def _make_metadata_plan_fixture(tmp_path, monkeypatch):
    library_root = tmp_path / "Organised_Library"
    tags_by_path = {
        "Rock/Alternative/CheVelle/CheVelle - Send the Pain Below.flac": {
            "artist": ["CheVelle"],
            "albumartist": ["CheVelle"],
            "album": ["Wonder What's Next"],
            "title": ["Send the Pain Below"],
            "genre": ["Alternative"],
            "tracknumber": ["06"],
        },
        "Rock/Alternative/CheVelle/CheVelle - Send the Pain Below Official Audio.flac": {
            "artist": ["CheVelle"],
            "albumartist": ["CheVelle"],
            "album": ["Wonder What's Next"],
            "title": ["Send the Pain Below Official Audio"],
            "genre": ["Alternative"],
            "tracknumber": ["06"],
        },
        "Metal/Nu Metal/KoRn/KoRn - Blind.flac": {
            "artist": ["KoRn"],
            "album_artist": ["KoRn"],
            "album": ["KoRn"],
            "title": ["Blind (Official Video)"],
            "genre": ["Nu Metal"],
            "tracknumber": ["01"],
        },
        "Rock/Rap Metal/Rage Against The Machine/Rage Against The Machine - Killing in the Name.flac": {
            "artist": ["Rage Against The Machine"],
            "album_artist": ["Rage Against The Machine"],
            "album": ["Rage Against the Machine"],
            "title": ["Killing in the Name"],
            "genre": ["Rap Metal"],
            "tracknumber": ["02"],
        },
    }
    for relative_path in tags_by_path:
        _write_file(library_root / relative_path, relative_path.encode("utf-8"))

    class FakeFLAC:
        def __init__(self, path):
            self.tags = tags_by_path[path.relative_to(library_root).as_posix()]

        def get(self, key):
            return self.tags.get(key)

    monkeypatch.setattr(metadata_plan, "FLAC", FakeFLAC)
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


def _row(rows, path, field):
    matches = [row for row in rows if row["path"] == path and row["field"] == field]
    assert len(matches) == 1
    return matches[0]
