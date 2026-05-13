import csv
import json
import sqlite3

from app import db
from app.main import build_parser, main
from app.review_decisions import (
    approved_album_artist_rules,
    approved_artist_casing_rules,
    approved_title_cleanup_rules,
    generate_review_decision_report,
    import_review_decisions,
    record_review_decision,
    rejected_patterns,
    review_decision_summary,
    suggestion_key_from_row,
)


def test_creates_review_decision(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    suggestion = _suggestion()
    suggestion_key = suggestion_key_from_row(suggestion)

    result = record_review_decision(
        suggestion_key=suggestion_key,
        decision="approved",
        reason="artist folder confirms casing",
        suggestion=suggestion,
        db_path=db_path,
    )
    row = _fetch_one(db_path, "SELECT * FROM review_decisions")

    assert result.decision_id == row["decision_id"]
    assert row["suggestion_key"] == suggestion_key
    assert row["decision"] == "approved"
    assert row["decision_reason"] == "artist folder confirms casing"
    assert row["file_path"] == "CheVelle/CheVelle - Send.flac"
    assert json.loads(row["source_evidence_json"]) == ["metadata_plan:artist folder"]


def test_duplicate_suggestion_decision_updates_existing_row(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    suggestion = _suggestion()
    suggestion_key = suggestion_key_from_row(suggestion)

    first = record_review_decision(
        suggestion_key=suggestion_key,
        decision="deferred",
        reason="needs another pass",
        suggestion=suggestion,
        db_path=db_path,
    )
    second = record_review_decision(
        suggestion_key=suggestion_key,
        decision="rejected",
        reason="bad evidence",
        db_path=db_path,
    )
    rows = _fetch_all(db_path, "SELECT * FROM review_decisions")

    assert second.decision_id == first.decision_id
    assert len(rows) == 1
    assert rows[0]["decision"] == "rejected"
    assert rows[0]["decision_reason"] == "bad evidence"
    assert rows[0]["file_path"] == suggestion["file_path"]


def test_import_review_decisions_enriches_from_suggestions(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    suggestion = _suggestion()
    suggestion_key = suggestion_key_from_row(suggestion)
    suggestions_path = tmp_path / "metadata_suggestions.csv"
    decisions_path = tmp_path / "decisions.csv"
    _write_csv(
        suggestions_path,
        (
            "suggestion_key",
            "file_path",
            "field",
            "current_value",
            "proposed_value",
            "suggestion_type",
            "confidence",
            "source_evidence",
        ),
        [{**suggestion, "suggestion_key": suggestion_key}],
    )
    _write_csv(
        decisions_path,
        ("suggestion_key", "decision", "reason"),
        [
            {
                "suggestion_key": suggestion_key,
                "decision": "approved",
                "reason": "confirmed",
            }
        ],
    )

    result = import_review_decisions(
        suggestions_path=suggestions_path,
        decisions_path=decisions_path,
        db_path=db_path,
    )
    row = _fetch_one(db_path, "SELECT * FROM review_decisions")

    assert result.imported_count == 1
    assert result.updated_count == 0
    assert row["proposed_value"] == "Chevelle"
    assert row["decision"] == "approved"


def test_report_generation_and_summary_counts(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    _record_fixture_decisions(db_path)

    result = generate_review_decision_report(out_dir=tmp_path / "reports", db_path=db_path)
    report_dir = tmp_path / "reports" / "review_decisions"
    summary = json.loads(
        (report_dir / "review_decision_summary.json").read_text(encoding="utf-8")
    )
    rows = _read_csv(report_dir / "review_decisions.csv")

    assert result.total_decisions == 3
    assert summary == {
        "approved_count": 2,
        "deferred_count": 0,
        "rejected_count": 1,
        "total_decisions": 3,
    }
    assert len(rows) == 3


def test_knowledge_layer_helpers_summarize_without_applying_rules(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    _record_fixture_decisions(db_path)

    assert approved_artist_casing_rules(db_path)[0]["proposed_value"] == "Chevelle"
    assert approved_title_cleanup_rules(db_path)[0]["proposed_value"] == "Change"
    assert approved_album_artist_rules(db_path) == []
    assert rejected_patterns(db_path)[0]["suggestion_type"] == "missing_album_artist"


def test_review_decision_cli_commands(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    suggestion_key = suggestion_key_from_row(_suggestion())

    exit_code = main(
        [
            "--db",
            str(db_path),
            "review-decision",
            "--suggestion-key",
            suggestion_key,
            "--decision",
            "deferred",
            "--reason",
            "waiting",
        ]
    )

    assert exit_code == 0
    assert "decision=deferred" in capsys.readouterr().out
    assert "review-decision" in build_parser()._subparsers._group_actions[0].choices
    assert "import-review-decisions" in build_parser()._subparsers._group_actions[0].choices
    assert "review-decision-report" in build_parser()._subparsers._group_actions[0].choices


def test_summary_counts():
    assert review_decision_summary(
        [
            {"decision": "approved"},
            {"decision": "approved"},
            {"decision": "rejected"},
            {"decision": "deferred"},
        ]
    ) == {
        "total_decisions": 4,
        "approved_count": 2,
        "rejected_count": 1,
        "deferred_count": 1,
    }


def test_recording_decision_does_not_mutate_audio_file(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    audio_path = tmp_path / "track.flac"
    audio_path.write_bytes(b"not a real flac but must not be touched")
    before = audio_path.read_bytes()
    suggestion = {**_suggestion(), "file_path": str(audio_path)}

    record_review_decision(
        suggestion_key=suggestion_key_from_row(suggestion),
        decision="approved",
        reason="only records decision",
        suggestion=suggestion,
        db_path=db_path,
    )

    assert audio_path.read_bytes() == before


def _record_fixture_decisions(db_path):
    record_review_decision(
        suggestion_key=suggestion_key_from_row(_suggestion()),
        decision="approved",
        reason="confirmed",
        suggestion=_suggestion(),
        db_path=db_path,
    )
    title = {
        "file_path": "Deftones/Change.flac",
        "field": "title",
        "current_value": "Change [Official Video]",
        "proposed_value": "Change",
        "suggestion_type": "junk_suffix_removal",
        "confidence": "high",
        "source_evidence": ["malformed_tags:probable_junk_suffix"],
    }
    record_review_decision(
        suggestion_key=suggestion_key_from_row(title),
        decision="approved",
        reason="junk suffix",
        suggestion=title,
        db_path=db_path,
    )
    album_artist = {
        "file_path": "Deftones/Knife Prty.flac",
        "field": "album_artist",
        "current_value": "",
        "proposed_value": "Deftones",
        "suggestion_type": "missing_album_artist",
        "confidence": "high",
        "source_evidence": ["missing_tags:missing_tag"],
    }
    record_review_decision(
        suggestion_key=suggestion_key_from_row(album_artist),
        decision="rejected",
        reason="compilation track",
        suggestion=album_artist,
        db_path=db_path,
    )


def _suggestion():
    return {
        "file_path": "CheVelle/CheVelle - Send.flac",
        "field": "artist",
        "current_value": "CheVelle",
        "proposed_value": "Chevelle",
        "suggestion_type": "artist_casing",
        "confidence": "medium",
        "source_evidence": ["metadata_plan:artist folder"],
    }


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _fetch_one(db_path, sql):
    rows = _fetch_all(db_path, sql)
    assert len(rows) == 1
    return rows[0]


def _fetch_all(db_path, sql):
    db.init_db(db_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
