import csv
import json
from pathlib import Path

from app import db
from app.alias_equivalence_audit import (
    audit_governed_conflict,
    build_alias_equivalence_audit,
    classify_equivalence_category,
    generate_alias_equivalence_audit_report,
)
from app.conflict_governance import GovernedConflict, evaluate_conflict


def test_tool_to_tool_is_casing_only_match():
    conflict = _safe_alias_conflict("Tool", "TOOL")
    record = audit_governed_conflict(conflict)

    assert record.equivalence_category == "casing_only"
    assert record.equivalence_matched is True
    assert record.prevented_escalation is True


def test_system_of_a_down_is_casing_punctuation_spacing_safe_alias():
    conflict = _safe_alias_conflict("System of a Down", "System Of A Down")
    record = audit_governed_conflict(conflict)

    assert record.equivalence_category == "casing_punctuation_spacing"
    assert record.equivalence_matched is True
    assert record.prevented_escalation is True


def test_suffix_noise_rejection_category():
    assert (
        classify_equivalence_category(
            conflict_type="alias_collision",
            entity_role="artist",
            source_entity="Heavy Is the Crown",
            target_entity="Heavy Is the Crown (Official Audio)",
        )
        == "suffix_noise"
    )


def test_collaboration_or_feature_rejection_category():
    assert (
        classify_equivalence_category(
            conflict_type="alias_collision",
            entity_role="artist",
            source_entity="Tom Morello BEARTOOTHband",
            target_entity="Tom Morello, BEARTOOTHband",
        )
        == "collaboration_or_feature"
    )


def test_shallow_bay_album_punctuation_is_not_artist_alias_safe():
    assert (
        classify_equivalence_category(
            conflict_type="album_membership_conflict",
            entity_role="artist",
            source_entity="Shallow Bay The Best Of Breaking Benjamin",
            target_entity="Shallow Bay: The Best Of Breaking Benjamin",
        )
        == "not_alias_collision"
    )


def test_missed_safe_alias_detection_when_safe_alias_still_escalates():
    conflict = _governed_conflict(
        source_entity="Tool",
        target_entity="TOOL",
        conflict_status="needs_review",
        contradiction_reason="simulated old governance escalation",
    )

    report = build_alias_equivalence_audit(governed_conflicts=[conflict])

    assert report.summary["missed_safe_aliases"] == 1
    assert report.summary["remaining_escalations"] == 1
    assert report.audit_records[0].equivalence_matched is True


def test_alias_equivalence_audit_report_generation(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Tool", "Sober", "", "a.flac")
    _insert_observation(db_path, "TOOL", "Sober", "", "b.flac")

    result = generate_alias_equivalence_audit_report(out_dir=reports, db_path=db_path)
    report_dir = reports / "alias_equivalence_audit"

    assert result.total_audited_conflicts >= 1
    assert (report_dir / "alias_equivalence_summary.json").exists()
    assert (report_dir / "alias_equivalence_audit.csv").exists()
    assert (report_dir / "prevented_escalations.csv").exists()
    assert (report_dir / "missed_safe_aliases.csv").exists()
    assert (report_dir / "remaining_escalations.csv").exists()
    rows = _read_csv(report_dir / "alias_equivalence_audit.csv")
    assert rows


def _safe_alias_conflict(source: str, target: str) -> GovernedConflict:
    return evaluate_conflict(
        conflict_type="alias_collision",
        source_entity=source,
        target_entity=target,
        entity_role="artist",
        evidence_count=3,
        confidence_snapshot={
            "confidence_tier": "medium",
            "normalized_confidence": 0.61,
            "raw_positive_score": 0.7,
            "raw_negative_score": 0.1,
        },
        positive_evidence_json=_evidence_json("repeated_artist_metadata", "metadata", 0.7),
        negative_evidence_json="[]",
        lifecycle_state="probationary",
    )


def _governed_conflict(
    *,
    source_entity: str,
    target_entity: str,
    conflict_status: str,
    contradiction_reason: str,
) -> GovernedConflict:
    return GovernedConflict(
        conflict_id="conflict_test",
        conflict_type="alias_collision",
        source_entity=source_entity,
        target_entity=target_entity,
        entity_role="artist",
        conflict_status=conflict_status,
        severity="medium",
        confidence_snapshot=json.dumps(
            {
                "confidence_tier": "medium",
                "normalized_confidence": 0.61,
                "raw_positive_score": 0.7,
                "raw_negative_score": 0.1,
            },
            sort_keys=True,
        ),
        positive_evidence_json=_evidence_json("repeated_artist_metadata", "metadata", 0.7),
        negative_evidence_json="[]",
        contradiction_reason=contradiction_reason,
        recommended_action="queue for human review",
        created_at="2026-01-01T00:00:00+00:00",
    )


def _insert_observation(db_path: Path, artist: str, title: str, album: str, filename: str) -> None:
    db.init_db(db_path)
    path = Path(filename)
    with db.connect(db_path) as connection:
        scan_run_id = connection.execute(
            """
            INSERT INTO scan_runs (
                source_path, started_at, completed_at, status,
                total_files_seen, audio_files_seen, files_failed
            )
            VALUES ('/music', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00',
                    'completed', 1, 1, 0)
            """
        ).lastrowid
        observed_file_id = connection.execute(
            """
            INSERT INTO observed_files (
                scan_run_id, source_path, relative_path, parent_folder, filename,
                extension, file_size_bytes, sha256, created_at
            )
            VALUES (?, ?, ?, '/music/Tool', ?, '.flac', 10, ?, '2026-01-01T00:00:00+00:00')
            """,
            (scan_run_id, str(path), path.name, path.name, f"sha-{path.name}"),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO tag_observations (
                observed_file_id, title, artist, album, album_artist, tag_status
            )
            VALUES (?, ?, ?, ?, ?, 'read')
            """,
            (observed_file_id, title, artist, album, artist),
        )
        connection.execute(
            """
            INSERT INTO filename_observations (
                observed_file_id, cleaned_filename, possible_artist, possible_title,
                filename_pattern, parser_confidence
            )
            VALUES (?, ?, ?, ?, 'artist_title', 0.8)
            """,
            (observed_file_id, path.stem, artist, title),
        )


def _evidence_json(evidence_type: str, family: str, score: float) -> str:
    return json.dumps(
        [
            {
                "evidence_type": evidence_type,
                "evidence_family": family,
                "weighted_score": score,
                "calibrated_score": score,
                "rationale": "test evidence",
            }
        ],
        sort_keys=True,
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))
