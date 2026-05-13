import csv
import json

from fastapi.testclient import TestClient

from app.main import app, build_parser, main
from app.metadata_suggestions import generate_metadata_suggestions
from app.normalization_knowledge import (
    build_normalization_knowledge,
    derive_normalization_rules,
    normalization_knowledge_summary,
)
from app.review_decisions import record_review_decision, suggestion_key_from_row


def test_derives_rules_from_approved_decisions(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    for index in range(3):
        _record(
            db_path,
            {**_artist_suggestion(), "file_path": f"CheVelle/track-{index}.flac"},
            "approved",
            "confirmed casing",
        )

    rules = derive_normalization_rules(db_path=db_path)
    rule = _rule(rules, "artist_alias", "CheVelle", "Chevelle")

    assert rule.approved_count == 3
    assert rule.rejected_count == 0
    assert rule.evidence_count == 3
    assert rule.confidence == "high"
    assert "three approvals" in rule.confidence_reason
    assert json.loads(rule.examples_json)


def test_rejected_decisions_become_rejected_patterns(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    _record(db_path, {**_album_artist_suggestion(), "file_path": "a.flac"}, "approved", "one approval")
    _record(db_path, {**_album_artist_suggestion(), "file_path": "b.flac"}, "rejected", "compilation")
    _record(db_path, {**_album_artist_suggestion(), "file_path": "c.flac"}, "rejected", "guest artist")

    rules = derive_normalization_rules(db_path=db_path)
    rule = _rule(rules, "rejected_pattern", "", "Deftones")

    assert rule.approved_count == 1
    assert rule.rejected_count == 2
    assert rule.confidence == "rejected_pattern"
    assert rule.confidence_reason == "rejections outnumber approvals"


def test_confidence_scoring_and_summary(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    _record(db_path, _artist_suggestion("A", "B"), "approved", "one")
    for index in range(3):
        _record(
            db_path,
            {**_title_suggestion(), "file_path": f"Deftones/change-{index}.flac"},
            "approved",
            "cleanup",
        )
    _record(db_path, {**_separator_suggestion(), "file_path": "one.flac"}, "approved", "ok")
    _record(db_path, {**_separator_suggestion(), "file_path": "two.flac"}, "rejected", "not ok")

    rules = derive_normalization_rules(db_path=db_path)
    summary = normalization_knowledge_summary(rules)

    assert _rule(rules, "artist_alias", "A", "B").confidence == "medium"
    assert _rule(rules, "junk_suffix_cleanup", "Change [Official Video]", "Change").confidence == "high"
    assert _rule(rules, "separator_cleanup", "Push_It", "Push It").confidence == "low"
    assert summary["total_rules"] == 3
    assert summary["high_confidence_count"] == 1
    assert summary["medium_confidence_count"] == 1
    assert summary["low_confidence_count"] == 1


def test_csv_json_output_and_cli(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    _record(db_path, _artist_suggestion(), "approved", "confirmed")

    result = build_normalization_knowledge(out_dir=tmp_path / "reports", db_path=db_path)
    report_dir = tmp_path / "reports" / "normalization_knowledge"
    json_rules = json.loads(
        (report_dir / "normalization_knowledge_rules.json").read_text(encoding="utf-8")
    )["rules"]
    csv_rows = _read_csv(report_dir / "normalization_knowledge_rules.csv")

    assert result.report_path == str(report_dir)
    assert result.total_rules == 1
    assert json_rules[0]["rule_type"] == "artist_alias"
    assert csv_rows[0]["source_value"] == "CheVelle"

    exit_code = main(
        [
            "--db",
            str(db_path),
            "build-normalization-knowledge",
            "--out",
            str(tmp_path / "cli_reports"),
        ]
    )
    assert exit_code == 0
    assert "total_rules=1" in capsys.readouterr().out
    assert "build-normalization-knowledge" in build_parser()._subparsers._group_actions[0].choices


def test_metadata_suggestion_confidence_influence_keeps_human_review(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite3"
    _record(db_path, _artist_suggestion(), "approved", "confirmed")
    plan_path, audit_dir = _suggestion_fixture(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    generate_metadata_suggestions(
        metadata_plan_path=plan_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "reports",
        db_path=db_path,
    )
    suggestion = json.loads(
        (
            tmp_path
            / "reports"
            / "metadata_suggestions"
            / "metadata_suggestions.json"
        ).read_text(encoding="utf-8")
    )["suggestions"][0]

    assert suggestion["confidence"] == "high"
    assert suggestion["requires_human_review"] is True
    assert "Approved prior decision evidence" in suggestion["rationale"]
    assert any(
        evidence.startswith("normalization_knowledge:")
        for evidence in suggestion["source_evidence"]
    )


def test_knowledge_ui_route_renders_rules(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    _record(db_path, _artist_suggestion(), "approved", "confirmed")
    build_normalization_knowledge(out_dir=tmp_path / "reports", db_path=db_path)
    app.state.reports_dir = tmp_path / "reports"
    client = TestClient(app)

    response = client.get("/review/knowledge")

    assert response.status_code == 200
    assert "Normalization Knowledge" in response.text
    assert "Total rules" in response.text
    assert "artist_alias" in response.text
    assert "CheVelle" in response.text
    assert "Chevelle" in response.text
    assert "No metadata is modified" in response.text


def test_review_hub_links_to_knowledge(tmp_path):
    app.state.reports_dir = tmp_path / "reports"
    client = TestClient(app)

    response = client.get("/review")

    assert response.status_code == 200
    assert "/review/knowledge" in response.text
    assert "Knowledge" in response.text


def test_building_knowledge_does_not_mutate_audio_file(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    audio_path = tmp_path / "track.flac"
    audio_path.write_bytes(b"audio bytes remain unchanged")
    suggestion = {**_artist_suggestion(), "file_path": str(audio_path)}
    _record(db_path, suggestion, "approved", "confirmed")
    before = audio_path.read_bytes()

    build_normalization_knowledge(out_dir=tmp_path / "reports", db_path=db_path)

    assert audio_path.read_bytes() == before


def _record(db_path, suggestion, decision, reason):
    record_review_decision(
        suggestion_key=suggestion_key_from_row(suggestion),
        decision=decision,
        reason=reason,
        suggestion=suggestion,
        db_path=db_path,
    )


def _artist_suggestion(current="CheVelle", proposed="Chevelle"):
    return {
        "file_path": f"{current}/{current} - Send.flac",
        "field": "artist",
        "current_value": current,
        "proposed_value": proposed,
        "suggestion_type": "artist_casing",
        "confidence": "medium",
        "source_evidence": ["metadata_plan:artist folder"],
    }


def _title_suggestion():
    return {
        "file_path": "Deftones/Change.flac",
        "field": "title",
        "current_value": "Change [Official Video]",
        "proposed_value": "Change",
        "suggestion_type": "junk_suffix_removal",
        "confidence": "high",
        "source_evidence": ["malformed_tags:probable_junk_suffix"],
    }


def _separator_suggestion():
    return {
        "file_path": "Static-X/Push_It.flac",
        "field": "title",
        "current_value": "Push_It",
        "proposed_value": "Push It",
        "suggestion_type": "separator_cleanup",
        "confidence": "medium",
        "source_evidence": ["metadata_plan:filename"],
    }


def _album_artist_suggestion():
    return {
        "file_path": "Deftones/Knife Prty.flac",
        "field": "album_artist",
        "current_value": "",
        "proposed_value": "Deftones",
        "suggestion_type": "missing_album_artist",
        "confidence": "high",
        "source_evidence": ["missing_tags:missing_tag"],
    }


def _suggestion_fixture(tmp_path):
    plan_path = tmp_path / "plan" / "metadata_plan.csv"
    audit_dir = tmp_path / "audit"
    plan_path.parent.mkdir(parents=True)
    audit_dir.mkdir(parents=True)
    _write_csv(
        plan_path,
        ("path", "field", "current_value", "proposed_value", "reason"),
        [
            {
                "path": "CheVelle/CheVelle - Send.flac",
                "field": "artist",
                "current_value": "CheVelle",
                "proposed_value": "Chevelle",
                "reason": "artist folder",
            }
        ],
    )
    _write_csv(audit_dir / "malformed_tags.csv", ("path", "field", "value", "issue_type", "detail"), [])
    _write_csv(audit_dir / "missing_tags.csv", ("path", "field"), [])
    _write_csv(audit_dir / "inconsistent_artists.csv", ("normalized_value", "variants", "file_count", "paths", "issue_types"), [])
    _write_csv(audit_dir / "inconsistent_titles.csv", ("normalized_value", "variants", "file_count", "paths", "issue_types"), [])
    return plan_path, audit_dir


def _rule(rules, rule_type, source_value, target_value):
    matches = [
        rule
        for rule in rules
        if rule.rule_type == rule_type
        and rule.source_value == source_value
        and rule.target_value == target_value
    ]
    assert len(matches) == 1
    return matches[0]


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))
