import csv
import json

from app.main import build_parser, main
from app.metadata_suggestions import (
    SUGGESTION_HEADERS,
    generate_metadata_suggestions,
)


def test_generates_deterministic_suggestions_without_api_key(tmp_path, monkeypatch):
    plan_path, audit_dir = _make_suggestion_fixture(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = generate_metadata_suggestions(
        metadata_plan_path=plan_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "reports",
    )
    suggestions = _read_suggestions_json(tmp_path)

    assert result.ai_enrichment_used is False
    assert result.total_suggestions == 5
    assert {row["suggestion_type"] for row in suggestions} == {
        "artist_casing",
        "duplicate_whitespace_cleanup",
        "junk_suffix_removal",
        "missing_album_artist",
        "separator_cleanup",
    }
    assert all(row["requires_human_review"] is True for row in suggestions)


def test_confidence_classification(tmp_path, monkeypatch):
    plan_path, audit_dir = _make_suggestion_fixture(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    generate_metadata_suggestions(
        metadata_plan_path=plan_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "reports",
    )
    suggestions = _read_suggestions_json(tmp_path)

    assert _suggestion(suggestions, "CheVelle/CheVelle - Send.flac", "artist")[
        "confidence"
    ] == "medium"
    assert _suggestion(suggestions, "Static-X/Static-X - Push_It.flac", "title")[
        "confidence"
    ] == "low"
    assert _suggestion(suggestions, "Deftones/Deftones - Change.flac", "title")[
        "confidence"
    ] == "high"


def test_summary_counts(tmp_path, monkeypatch):
    plan_path, audit_dir = _make_suggestion_fixture(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = generate_metadata_suggestions(
        metadata_plan_path=plan_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "reports",
    )
    summary = json.loads(
        (
            tmp_path
            / "reports"
            / "metadata_suggestions"
            / "metadata_suggestion_summary.json"
        ).read_text(encoding="utf-8")
    )

    assert summary == {
        "total_suggestions": 5,
        "high_confidence_count": 3,
        "medium_confidence_count": 1,
        "low_confidence_count": 1,
        "requires_human_review_count": 5,
        "ai_enrichment_used": False,
    }
    assert result.high_confidence_count == 3


def test_writes_csv_and_json_outputs(tmp_path, monkeypatch):
    plan_path, audit_dir = _make_suggestion_fixture(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    generate_metadata_suggestions(
        metadata_plan_path=plan_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "reports",
    )
    report_dir = tmp_path / "reports" / "metadata_suggestions"

    assert (report_dir / "metadata_suggestions.json").exists()
    assert (report_dir / "metadata_suggestion_summary.json").exists()
    assert _csv_headers(report_dir / "metadata_suggestions.csv") == list(
        SUGGESTION_HEADERS
    )
    csv_rows = _read_csv(report_dir / "metadata_suggestions.csv")
    assert csv_rows
    assert csv_rows[0]["requires_human_review"] == "true"


def test_command_registration(tmp_path, monkeypatch, capsys):
    plan_path, audit_dir = _make_suggestion_fixture(tmp_path)
    out_dir = tmp_path / "reports"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = main(
        [
            "metadata-suggestions",
            "--metadata-plan",
            str(plan_path),
            "--metadata-audit",
            str(audit_dir),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={out_dir / 'metadata_suggestions'}" in output
    assert "total_suggestions=5" in output
    assert "ai_enrichment_used=false" in output
    command_names = build_parser()._subparsers._group_actions[0].choices
    assert "metadata-suggestions" in command_names


def test_metadata_plan_alias_resolves_existing_tag_update_plan(tmp_path, monkeypatch):
    plan_path, audit_dir = _make_suggestion_fixture(tmp_path)
    alias_path = plan_path.with_name("metadata_plan.csv")
    legacy_path = plan_path.with_name("tag_update_plan.csv")
    plan_path.rename(legacy_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = generate_metadata_suggestions(
        metadata_plan_path=alias_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "reports",
    )

    assert result.total_suggestions == 5


def test_enrichment_cannot_change_proposed_values(tmp_path, monkeypatch):
    plan_path, audit_dir = _make_suggestion_fixture(tmp_path)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    generate_metadata_suggestions(
        metadata_plan_path=plan_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "without_key",
    )
    deterministic_values = {
        (row["file_path"], row["field"]): row["proposed_value"]
        for row in _read_suggestions_json(tmp_path, root="without_key")
    }

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    generate_metadata_suggestions(
        metadata_plan_path=plan_path,
        metadata_audit_dir=audit_dir,
        out_dir=tmp_path / "with_key",
    )
    enriched = _read_suggestions_json(tmp_path, root="with_key")

    assert {
        (row["file_path"], row["field"]): row["proposed_value"] for row in enriched
    } == deterministic_values
    assert any("AI-assisted rationale enrichment" in row["rationale"] for row in enriched)


def _make_suggestion_fixture(tmp_path):
    plan_path = tmp_path / "reports" / "metadata_plan" / "metadata_plan.csv"
    audit_dir = tmp_path / "reports" / "metadata_audit"
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
            },
            {
                "path": "Static-X/Static-X - Push_It.flac",
                "field": "title",
                "current_value": "Push_It",
                "proposed_value": "Push It",
                "reason": "filename",
            },
            {
                "path": "Deftones/Deftones - Change.flac",
                "field": "title",
                "current_value": "Change [Official Video]",
                "proposed_value": "Change",
                "reason": "filename",
            },
            {
                "path": "Deftones/Deftones - Knife Prty.flac",
                "field": "album_artist",
                "current_value": "",
                "proposed_value": "Deftones",
                "reason": "album_artist should equal artist",
            },
            {
                "path": "Deftones/Deftones - Digital Bath.flac",
                "field": "title",
                "current_value": "Digital  Bath",
                "proposed_value": "Digital Bath",
                "reason": "filename",
            },
            {
                "path": "Metal/Nu Metal/KoRn/KoRn - Blind.flac",
                "field": "genre",
                "current_value": "Nu Metal",
                "proposed_value": "Metal",
                "reason": "top-level genre folder",
            },
        ],
    )
    _write_csv(
        audit_dir / "malformed_tags.csv",
        ("path", "field", "value", "issue_type", "detail"),
        [
            {
                "path": "Deftones/Deftones - Change.flac",
                "field": "title",
                "value": "Change [Official Video]",
                "issue_type": "probable_junk_suffix",
                "detail": "tag value ends with a probable source or video suffix",
            },
            {
                "path": "Deftones/Deftones - Digital Bath.flac",
                "field": "title",
                "value": "Digital  Bath",
                "issue_type": "duplicate_whitespace",
                "detail": "tag value contains repeated whitespace",
            },
        ],
    )
    _write_csv(
        audit_dir / "missing_tags.csv",
        ("path", "field"),
        [
            {
                "path": "Deftones/Deftones - Knife Prty.flac",
                "field": "album_artist",
            }
        ],
    )
    _write_csv(
        audit_dir / "inconsistent_artists.csv",
        ("normalized_value", "variants", "file_count", "paths", "issue_types"),
        [],
    )
    _write_csv(
        audit_dir / "inconsistent_titles.csv",
        ("normalized_value", "variants", "file_count", "paths", "issue_types"),
        [
            {
                "normalized_value": "pushit",
                "variants": "Push It | Push_It",
                "file_count": "2",
                "paths": "Static-X/Static-X - Push_It.flac | Static-X/Static-X - Push It.flac",
                "issue_types": "separator_inconsistency",
            }
        ],
    )
    return plan_path, audit_dir


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))


def _csv_headers(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return next(csv.reader(file_handle))


def _read_suggestions_json(tmp_path, root="reports"):
    return json.loads(
        (
            tmp_path
            / root
            / "metadata_suggestions"
            / "metadata_suggestions.json"
        ).read_text(encoding="utf-8")
    )["suggestions"]


def _suggestion(suggestions, path, field):
    matches = [
        row for row in suggestions if row["file_path"] == path and row["field"] == field
    ]
    assert len(matches) == 1
    return matches[0]
