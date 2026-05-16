import csv
import json

from app.external_metadata import EXTERNAL_TRACK_FIELDS
from app.main import main
from app.release_identity_analysis import (
    IDENTITY_GROUP_FIELDS,
    RELEASE_APPEARANCE_FIELDS,
    analyze_release_identity,
)


def test_same_recording_across_albums_is_legitimate_release_appearance(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            _track("1", "Low", "Things We Lost in the Fire", "Sunflower", recording_gid="rec-1", release_gid="rel-1"),
            _track("2", "Low", "A Lifetime of Temporary Relief", "Sunflower", recording_gid="rec-1", release_gid="rel-2"),
        ],
    )

    result = analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    rows = _read_csv(tmp_path / "reports" / "release_identity_analysis" / "identity_groups.csv")
    assert result.legitimate_release_appearance_count == 1
    assert rows[0]["classification"] == "legitimate_release_appearance"
    assert rows[0]["distinct_album_count"] == "2"
    assert rows[0]["distinct_release_count"] == "2"


def test_repeated_source_record_is_possible_true_duplicate(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            _track("dup", "Ride", "Nowhere", "Vapour Trail", recording_gid="rec-1", release_gid="rel-1"),
            _track("dup", "Ride", "Nowhere", "Vapour Trail", recording_gid="rec-1", release_gid="rel-1"),
        ],
    )

    analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    duplicates = _read_csv(
        tmp_path / "reports" / "release_identity_analysis" / "possible_true_duplicates.csv"
    )
    assert duplicates[0]["duplicate_reason"] == "repeated_source_record_id"
    assert duplicates[0]["representative_artist"] == "Ride"
    assert json.loads(duplicates[0]["source_record_ids_json"]) == ["dup"]


def test_edition_or_reissue_album_names_are_clustered(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            _track("1", "Slowdive", "Souvlaki", "Alison", recording_gid="rec-1", release_gid="rel-1"),
            _track("2", "Slowdive", "Souvlaki Deluxe Edition", "Alison", recording_gid="rec-1", release_gid="rel-2"),
        ],
    )

    analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    rows = _read_csv(tmp_path / "reports" / "release_identity_analysis" / "identity_groups.csv")
    assert rows[0]["classification"] == "edition_or_reissue_cluster"
    legitimate = _read_csv(
        tmp_path / "reports" / "release_identity_analysis" / "legitimate_release_appearances.csv"
    )
    assert legitimate[0]["release_count"] == "2"


def test_compilation_or_best_of_appearance_is_clustered(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            _track("1", "Sparks", "Sparks", "Wonder Girl", recording_gid="rec-1", release_gid="rel-1"),
            _track("2", "Sparks", "Past Tense: The Best of Sparks", "Wonder Girl", recording_gid="rec-1", release_gid="rel-2"),
        ],
    )

    analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    rows = _read_csv(tmp_path / "reports" / "release_identity_analysis" / "identity_groups.csv")
    assert rows[0]["classification"] == "compilation_or_multi_release_appearance"


def test_conflicting_duration_without_recording_identity_is_ambiguous(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            _track("1", "Portishead", "Dummy", "Roads", duration_seconds="300"),
            _track("2", "Portishead", "Dummy", "Roads", duration_seconds="305"),
        ],
    )

    analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    ambiguous = _read_csv(
        tmp_path / "reports" / "release_identity_analysis" / "ambiguous_identity_groups.csv"
    )
    assert ambiguous[0]["ambiguity_reason"] == "conflicting_duration_without_recording_identity"
    conflicting = json.loads(ambiguous[0]["conflicting_values_json"])
    assert conflicting["duration_seconds"] == ["300", "305"]


def test_summary_metrics_and_output_csv_structure(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            _track("single", "Can", "Future Days", "Moonshake", recording_gid="rec-single", release_gid="rel-single"),
            _track("legit-1", "Low", "Album A", "Song", recording_gid="rec-legit", release_gid="rel-a"),
            _track("legit-2", "Low", "Album B", "Song", recording_gid="rec-legit", release_gid="rel-b"),
            _track("dup", "Ride", "Nowhere", "Vapour Trail", recording_gid="rec-dup", release_gid="rel-dup"),
            _track("dup", "Ride", "Nowhere", "Vapour Trail", recording_gid="rec-dup", release_gid="rel-dup"),
            _track("amb-1", "Tool", "Album", "Track", duration_seconds="100"),
            _track("amb-2", "Tool", "Album", "Track", duration_seconds="110"),
        ],
    )

    result = analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    report_dir = tmp_path / "reports" / "release_identity_analysis"
    summary = json.loads((report_dir / "release_identity_summary.json").read_text(encoding="utf-8"))
    assert result.total_records == 7
    assert summary["source_name"] == "local_fixture"
    assert summary["total_records"] == 7
    assert summary["single_record_identity_count"] == 1
    assert summary["legitimate_release_appearance_count"] == 1
    assert summary["possible_true_duplicate_count"] == 1
    assert summary["ambiguous_identity_group_count"] == 1
    assert summary["duplicate_external_records_explained"] == 4
    assert summary["duplicate_external_records_unresolved"] == 2
    assert set(summary["output_files"]) == {
        "identity_groups",
        "release_appearances",
        "possible_true_duplicates",
        "legitimate_release_appearances",
        "ambiguous_identity_groups",
    }
    assert _read_csv_headers(report_dir / "identity_groups.csv") == list(IDENTITY_GROUP_FIELDS)
    assert _read_csv_headers(report_dir / "release_appearances.csv") == list(RELEASE_APPEARANCE_FIELDS)


def test_deterministic_ordering(tmp_path):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [
            _track("z1", "Zed", "Album Z", "Song Z", recording_gid="rec-z", release_gid="rel-z"),
            _track("a1", "Alpha", "Album A", "Song A", recording_gid="rec-a", release_gid="rel-a"),
            _track("a2", "Alpha", "Album B", "Song A", recording_gid="rec-a", release_gid="rel-b"),
        ],
    )

    analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    rows = _read_csv(tmp_path / "reports" / "release_identity_analysis" / "identity_groups.csv")
    assert [row["classification"] for row in rows] == [
        "single_record_identity",
        "legitimate_release_appearance",
    ]
    assert [row["artist"] for row in rows] == ["Zed", "Alpha"]


def test_no_mutation_of_input_file(tmp_path):
    source_path = _write_external_tracks(
        tmp_path,
        "local_fixture",
        [_track("1", "Massive Attack", "Mezzanine", "Angel", recording_gid="rec-1", release_gid="rel-1")],
    )
    before = source_path.read_bytes()

    analyze_release_identity("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    assert source_path.read_bytes() == before


def test_cli_analyze_release_identity(tmp_path, monkeypatch, capsys):
    _write_external_tracks(
        tmp_path,
        "local_fixture",
        [_track("1", "Can", "Future Days", "Moonshake", recording_gid="rec-1", release_gid="rel-1")],
    )
    monkeypatch.delenv("MUSIC_INTELLIGENCE_DATA_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "analyze-release-identity",
            "--source",
            "local_fixture",
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "source_name=local_fixture" in output
    assert "total_records=1" in output
    assert (tmp_path / "reports" / "release_identity_analysis" / "release_identity_summary.json").exists()


def _write_external_tracks(tmp_path, source_name, rows):
    path = tmp_path / "data" / "external_metadata" / source_name
    path.mkdir(parents=True, exist_ok=True)
    csv_path = path / "external_tracks.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXTERNAL_TRACK_FIELDS)
        writer.writeheader()
        for row in rows:
            complete = {field: "" for field in EXTERNAL_TRACK_FIELDS}
            complete.update(
                {
                    "source_name": source_name,
                    "raw_payload_json": "{}",
                    "ingested_at": "2026-05-16T00:00:00+00:00",
                }
            )
            complete.update(row)
            writer.writerow(complete)
    return csv_path


def _track(
    source_record_id,
    artist,
    album,
    title,
    *,
    track_number="1",
    release_year="1995",
    duration_seconds="200",
    source_url="https://example.test/recording",
    release_id="",
    release_gid="",
    recording_id="",
    recording_gid="",
):
    payload = {
        key: value
        for key, value in {
            "release_id": release_id,
            "release_gid": release_gid,
            "recording_id": recording_id,
            "recording_gid": recording_gid,
        }.items()
        if value
    }
    return {
        "source_record_id": source_record_id,
        "artist": artist,
        "album": album,
        "title": title,
        "track_number": track_number,
        "release_year": release_year,
        "duration_seconds": duration_seconds,
        "source_url": source_url,
        "raw_payload_json": json.dumps(payload, sort_keys=True),
    }


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_csv_headers(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))
