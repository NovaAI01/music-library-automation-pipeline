import csv
import json

from app.artist_credit_parser import (
    ArtistCreditInputRecord,
    analyze_artist_credits,
    parse_artist_credit,
)
from app.external_metadata import EXTERNAL_TRACK_FIELDS
from app.main import main


def test_solo_artist_parsing():
    parsed = parse_artist_credit(_record("1", "Slowdive"))

    assert parsed.credit_pattern == "solo_artist"
    assert parsed.primary_artist == "Slowdive"
    assert parsed.featured_artists == ()
    assert parsed.confidence_tier == "high"


def test_feat_ft_featuring_parsing():
    cases = [
        ("Alpha feat. Beta", "feat_artist"),
        ("Alpha ft Beta", "ft_artist"),
        ("Alpha featuring Beta", "featuring_artist"),
    ]

    for raw_artist, pattern in cases:
        parsed = parse_artist_credit(_record("1", raw_artist))
        assert parsed.credit_pattern == pattern
        assert parsed.primary_artist == "Alpha"
        assert parsed.featured_artists == ("Beta",)
        assert parsed.confidence_tier == "high"


def test_with_parsing():
    parsed = parse_artist_credit(_record("1", "Alpha with Beta"))

    assert parsed.credit_pattern == "with_artist"
    assert parsed.primary_artist == "Alpha"
    assert parsed.collaborating_artists == ("Beta",)
    assert parsed.confidence_tier == "medium"


def test_ampersand_collaboration():
    parsed = parse_artist_credit(_record("1", "Alpha & Beta"))

    assert parsed.credit_pattern == "ampersand_collaboration"
    assert parsed.primary_artist == "Alpha"
    assert parsed.collaborating_artists == ("Beta",)


def test_comma_collaboration():
    parsed = parse_artist_credit(_record("1", "Alpha, Beta"))

    assert parsed.credit_pattern == "comma_collaboration"
    assert parsed.primary_artist == "Alpha"
    assert parsed.collaborating_artists == ("Beta",)


def test_multi_artist_credit():
    parsed = parse_artist_credit(_record("1", "Alpha, Beta, Gamma"))

    assert parsed.credit_pattern == "multi_artist_credit"
    assert parsed.primary_artist == "Alpha"
    assert parsed.collaborating_artists == ("Beta", "Gamma")


def test_x_collaboration():
    parsed = parse_artist_credit(_record("1", "Alpha x Beta"))

    assert parsed.credit_pattern == "x_collaboration"
    assert parsed.primary_artist == "Alpha"
    assert parsed.collaborating_artists == ("Beta",)


def test_vs_collaboration():
    parsed = parse_artist_credit(_record("1", "Alpha vs Beta"))

    assert parsed.credit_pattern == "versus_artist"
    assert parsed.primary_artist == "Alpha"
    assert parsed.collaborating_artists == ("Beta",)


def test_ambiguous_string_preserved():
    parsed = parse_artist_credit(_record("1", "Earth, Wind & Fire"))

    assert parsed.credit_pattern == "unknown_or_ambiguous"
    assert parsed.primary_artist == ""
    assert parsed.confidence_tier == "low"
    assert "ambiguous_credit" in parsed.parser_flags


def test_source_artifact_rejected_low_confidence():
    parsed = parse_artist_credit(_record("1", "Uploader Channel"))

    assert parsed.credit_pattern == "unknown_or_ambiguous"
    assert parsed.primary_artist == ""
    assert parsed.confidence_tier == "low"
    assert "source_artifact" in parsed.parser_flags


def test_unresolved_output_generation(tmp_path):
    _write_external_tracks(
        tmp_path,
        [
            {"source_record_id": "1", "artist": "Alpha feat. Beta", "title": "Song"},
            {"source_record_id": "2", "artist": "Uploader Channel", "title": "Song"},
        ],
    )

    analyze_artist_credits("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    unresolved = _read_csv(
        tmp_path / "reports" / "artist_credit_analysis" / "unresolved_artist_credits.csv"
    )
    assert len(unresolved) == 1
    assert unresolved[0]["source_record_id"] == "2"


def test_summary_generation(tmp_path):
    _write_external_tracks(
        tmp_path,
        [
            {"source_record_id": "1", "artist": "Alpha feat. Beta", "title": "Song"},
            {"source_record_id": "2", "artist": "Alpha & Gamma", "title": "Song"},
            {"source_record_id": "3", "artist": "Solo", "title": "Song"},
            {"source_record_id": "4", "artist": "YouTube Topic", "title": "Song"},
        ],
    )

    result = analyze_artist_credits(
        "local_fixture",
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
    )

    summary = json.loads(
        (tmp_path / "reports" / "artist_credit_analysis" / "artist_credit_summary.json")
        .read_text(encoding="utf-8")
    )
    assert result.total_records == 4
    assert summary["featured_artist_count"] == 1
    assert summary["collaboration_count"] == 1
    assert summary["solo_artist_count"] == 1
    assert summary["unresolved_count"] == 1
    assert summary["high_confidence_count"] == 2
    assert summary["medium_confidence_count"] == 1
    assert summary["low_confidence_count"] == 1


def test_no_mutation_of_input_file(tmp_path):
    input_path = _write_external_tracks(
        tmp_path,
        [{"source_record_id": "1", "artist": "Alpha feat. Beta", "title": "Song"}],
    )
    before = input_path.read_bytes()

    analyze_artist_credits("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    assert input_path.read_bytes() == before


def test_deterministic_output_order(tmp_path):
    _write_external_tracks(
        tmp_path,
        [
            {"source_record_id": "2", "artist": "Beta feat. Gamma", "title": "Second"},
            {"source_record_id": "1", "artist": "Alpha & Delta", "title": "First"},
        ],
    )

    analyze_artist_credits("local_fixture", out_dir=tmp_path / "reports", data_dir=tmp_path / "data")

    parsed = _read_csv(
        tmp_path / "reports" / "artist_credit_analysis" / "parsed_artist_credits.csv"
    )
    assert [row["source_record_id"] for row in parsed] == ["2", "1"]


def test_cli_analyze_artist_credits(tmp_path, monkeypatch, capsys):
    _write_external_tracks(
        tmp_path,
        [{"source_record_id": "1", "artist": "Portishead", "title": "Glory Box"}],
    )
    monkeypatch.delenv("MUSIC_INTELLIGENCE_DATA_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "analyze-artist-credits",
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
    assert (
        tmp_path
        / "reports"
        / "artist_credit_analysis"
        / "top_collaborators.csv"
    ).exists()


def _record(source_record_id, artist):
    return ArtistCreditInputRecord(
        source_name="local_fixture",
        source_record_id=source_record_id,
        artist=artist,
        album="Album",
        title="Title",
    )


def _write_external_tracks(tmp_path, rows):
    path = tmp_path / "data" / "external_metadata" / "local_fixture"
    path.mkdir(parents=True, exist_ok=True)
    csv_path = path / "external_tracks.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXTERNAL_TRACK_FIELDS)
        writer.writeheader()
        for row in rows:
            complete = {field: "" for field in EXTERNAL_TRACK_FIELDS}
            complete.update(
                {
                    "source_name": "local_fixture",
                    "raw_payload_json": "{}",
                    "ingested_at": "2026-05-15T00:00:00+00:00",
                }
            )
            complete.update(row)
            writer.writerow(complete)
    return csv_path


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
