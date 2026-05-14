import csv
import json
import os

from fastapi.testclient import TestClient

from app.album_cohesion import AlbumCohesionTrack, infer_album_cohesion
from app.evidence_reliability import (
    generate_evidence_reliability_report,
    score_evidence,
)
from app.main import app, build_parser, main


def test_uploader_detection():
    reliability = score_evidence("Static-X Topic - Push It Official Audio", field="artist")

    assert reliability.reliability_tier == "low"
    assert "uploader_or_channel_signature" in reliability.reliability_flags
    assert "official_media_suffix" in reliability.reliability_flags


def test_noisy_title_detection():
    reliability = score_evidence("Push It (Official Video) [YouTube]", field="title")

    assert reliability.reliability_tier == "low"
    assert "noisy_title_or_album" in reliability.reliability_flags
    assert "platform_branding" in reliability.reliability_flags


def test_canonical_agreement_scores_high():
    reliability = score_evidence(
        "Push It",
        field="title",
        canonical_values=["Push It"],
        repeated_count=3,
        album_cohesion_score=0.92,
        sequential_tracks=True,
        prior_approvals=2,
    )

    assert reliability.reliability_tier == "high"
    assert reliability.reliability_score > 0.9
    assert "canonical_match" in reliability.reliability_flags


def test_mixed_casing_and_remaster_pollution():
    casing = score_evidence("PUSH IT", field="title")
    remaster = score_evidence("Wisconsin Death Trip - 20th Anniversary Remastered 2020", field="album")

    assert "all_caps_anomaly" in casing.reliability_flags
    assert "remaster_noise" in remaster.reliability_flags
    assert remaster.reliability_score < 0.56


def test_cohesion_downranks_polluted_album_names():
    groups, _, _ = infer_album_cohesion(
        [
            _track("01.flac", album_tag="Official Audio - YouTube Topic", track_number=1),
            _track("02.flac", title="Bled for Days", album_tag="Official Audio - YouTube Topic", track_number=2),
        ]
    )

    assert groups[0].confidence_tier != "high"
    assert "polluted album-name evidence down-ranked" in groups[0].rationale
    assert "low-reliability uploader artifacts ignored where possible" in groups[0].rationale


def test_report_generation_and_no_mutation(tmp_path):
    reports = tmp_path / "reports"
    suggestions = reports / "metadata_suggestions"
    suggestions.mkdir(parents=True)
    source = tmp_path / "track.flac"
    source.write_bytes(b"unchanged")
    before = (source.read_bytes(), os.stat(source).st_mtime_ns)
    _write_json(
        suggestions / "metadata_suggestions.json",
        {
            "suggestions": [
                {
                    "suggestion_key": "s1",
                    "file_path": str(source),
                    "field": "title",
                    "current_value": "Push It Topic (Official Audio) [YouTube]",
                    "proposed_value": "Push It",
                    "suggestion_type": "junk_suffix_removal",
                    "confidence": "medium",
                    "rationale": "cleanup",
                    "requires_human_review": True,
                    "source_evidence": [],
                },
                {
                    "suggestion_key": "s2",
                    "file_path": str(source),
                    "field": "title",
                    "current_value": "Push It",
                    "proposed_value": "Push It",
                    "suggestion_type": "title_cleanup",
                    "confidence": "high",
                    "rationale": "canonical",
                    "requires_human_review": True,
                    "source_evidence": [],
                },
            ]
        },
    )
    album_cohesion = reports / "album_cohesion"
    album_cohesion.mkdir()
    _write_json(
        album_cohesion / "album_groups.json",
        {
            "groups": [
                {
                    "group_key": "static-x:wisconsin",
                    "album": "Wisconsin Death Trip",
                    "artist": "Static-X",
                    "cohesion_score": 0.92,
                    "rationale": ["sequential track numbering"],
                    "tracks": [
                        {
                            "file_path": str(source),
                            "artist": "Static-X",
                            "title": "Push It",
                            "album_tag": "Wisconsin Death Trip",
                            "source_folder": "Static-X/Wisconsin Death Trip",
                        }
                    ],
                }
            ]
        },
    )

    result = generate_evidence_reliability_report(out_dir=reports, db_path=tmp_path / "db.sqlite3")
    report_dir = reports / "evidence_reliability"
    summary = json.loads((report_dir / "evidence_reliability_summary.json").read_text(encoding="utf-8"))
    unreliable = _read_csv(report_dir / "unreliable_evidence.csv")
    reliable = _read_csv(report_dir / "reliable_patterns.csv")

    assert result.total_records == 9
    assert summary["uploader_artifacts_detected"] >= 1
    assert summary["noisy_titles_detected"] >= 1
    assert unreliable
    assert reliable
    assert (report_dir / "reliability_groups.json").exists()
    assert (source.read_bytes(), os.stat(source).st_mtime_ns) == before


def test_evidence_reliability_cli(tmp_path, capsys):
    reports = tmp_path / "reports"
    suggestions = reports / "metadata_suggestions"
    suggestions.mkdir(parents=True)
    _write_json(
        suggestions / "metadata_suggestions.json",
        {"suggestions": [{"file_path": "a.flac", "field": "artist", "current_value": "Static-X Topic", "proposed_value": "Static-X"}]},
    )

    exit_code = main(["--db", str(tmp_path / "db.sqlite3"), "evidence-reliability", "--out", str(reports)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "total_records=2" in output
    assert "evidence-reliability" in build_parser()._subparsers._group_actions[0].choices


def test_reliability_ui_rendering(tmp_path):
    app.state.reports_dir = tmp_path / "reports"
    app.state.db_path = tmp_path / "db.sqlite3"
    report_dir = tmp_path / "reports" / "evidence_reliability"
    report_dir.mkdir(parents=True)
    _write_json(
        report_dir / "evidence_reliability_summary.json",
        {
            "total_records": 2,
            "high_reliability": 1,
            "medium_reliability": 0,
            "low_reliability": 1,
            "uploader_artifacts_detected": 1,
            "noisy_titles_detected": 1,
            "conflicting_artist_patterns": 0,
            "canonical_matches": 1,
            "created_at": "2026-05-14T00:00:00+00:00",
        },
    )
    _write_json(
        report_dir / "reliability_groups.json",
        {
            "records": [
                {
                    "record_key": "r1",
                    "file_path": "01.flac",
                    "field": "title",
                    "value": "Push It Official Audio",
                    "source": "metadata_suggestion_current",
                    "reliability_score": 0.24,
                    "reliability_tier": "low",
                    "reliability_flags": ["uploader_or_channel_signature", "noisy_title_or_album"],
                    "rationale": ["uploader or channel wording detected"],
                },
                {
                    "record_key": "r2",
                    "file_path": "02.flac",
                    "field": "title",
                    "value": "Push It",
                    "source": "metadata_suggestion_proposed",
                    "reliability_score": 0.84,
                    "reliability_tier": "high",
                    "reliability_flags": ["canonical_match"],
                    "rationale": ["normalization knowledge supports value"],
                },
            ],
            "groups": [],
        },
    )
    _write_csv(report_dir / "unreliable_evidence.csv", ["record_key"], [{"record_key": "r1"}])
    _write_csv(report_dir / "reliable_patterns.csv", ["pattern_key"], [{"pattern_key": "title:pushit"}])

    response = TestClient(app).get("/review/reliability")

    assert response.status_code == 200
    assert "Evidence Reliability" in response.text
    assert "Uploader Artifacts" in response.text
    assert "Canonical Matches" in response.text
    assert "confidence-low" in response.text
    assert "Push It Official Audio" in response.text


def _track(path, *, artist="Static-X", title="Push It", album_tag="Wisconsin Death Trip", track_number=1):
    return AlbumCohesionTrack(
        file_path=path,
        artist=artist,
        title=title,
        album_tag=album_tag,
        track_number=track_number,
        year="1999",
        source_folder="Static-X/Wisconsin Death Trip",
        album_folder="Wisconsin Death Trip",
        filename_album="",
        filename_artist=artist,
        filename_title=title,
    )


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
