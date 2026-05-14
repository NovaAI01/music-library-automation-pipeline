import csv
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.canonical_confidence import score_canonical_entity
from app.canonical_entity_graph import generate_canonical_graph
from app.conflict_governance import (
    evaluate_conflict,
    generate_conflict_governance_report,
)
from app.main import app, main


def test_alias_collision_conflict():
    conflict = evaluate_conflict(
        conflict_type="alias_collision",
        source_entity="Static X",
        target_entity="STATIC X",
        entity_role="artist",
        confidence_snapshot={"normalized_confidence": 0.61, "raw_positive_score": 0.44, "raw_negative_score": 0.34},
        positive_evidence_json=_evidence_json("repeated_artist_metadata", "metadata", 0.35),
        negative_evidence_json=_evidence_json("conflicting_graph_relationship", "reliability", 0.34),
        lifecycle_state="probationary",
    )

    assert conflict.conflict_type == "alias_collision"
    assert conflict.conflict_status in {"blocked_merge", "needs_review"}
    assert "confidence" in conflict.contradiction_reason or "review" in conflict.recommended_action


def test_role_collision_conflict_blocks_merge():
    conflict = evaluate_conflict(
        conflict_type="role_collision",
        source_entity="Push It",
        target_entity="Static-X",
        entity_role="ambiguous",
        confidence_snapshot={"normalized_confidence": 0.58, "raw_positive_score": 0.7, "raw_negative_score": 0.42},
        negative_evidence_json=_evidence_json("conflicting_role_pattern", "role_conflict", 0.32),
        lifecycle_state="probationary",
    )

    assert conflict.conflict_status == "blocked_merge"
    assert "roles conflict" in conflict.contradiction_reason


def test_collaboration_ambiguity_conflict_blocks_merge():
    conflict = evaluate_conflict(
        conflict_type="ambiguous_collaboration",
        source_entity="Alice & Chains",
        target_entity="Alice in Chains",
        entity_role="artist",
        confidence_snapshot={"normalized_confidence": 0.62, "raw_positive_score": 0.7, "raw_negative_score": 0.2},
        lifecycle_state="probationary",
    )

    assert conflict.conflict_status == "blocked_merge"
    assert "collaboration string" in conflict.contradiction_reason


def test_artifact_merge_veto():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="warner records vault",
        entity_value="Warner Records Vault",
        evidence_count=2,
        artifact_flags=["source_artifact_pattern", "uploader_signature"],
    )

    conflict = evaluate_conflict(
        conflict_type="artifact_collision",
        source_entity="Warner Records Vault",
        target_entity="Warner Records",
        entity_role="artist",
        confidence_snapshot=json.loads(scored.weighted_score_breakdown_json) | {
            "normalized_confidence": scored.normalized_confidence,
            "raw_positive_score": scored.raw_positive_score,
            "raw_negative_score": scored.raw_negative_score,
        },
        positive_evidence_json=scored.positive_evidence_json,
        negative_evidence_json=scored.negative_evidence_json,
        lifecycle_state="candidate",
    )

    assert conflict.conflict_status == "blocked_merge"
    assert "artifact evidence" in conflict.contradiction_reason


def test_lifecycle_blocked_merge_veto():
    conflict = evaluate_conflict(
        conflict_type="duplicate_identity_conflict",
        source_entity="A",
        target_entity="B",
        entity_role="artist",
        confidence_snapshot={"normalized_confidence": 0.7, "raw_positive_score": 0.8, "raw_negative_score": 0.2},
        lifecycle_state="blocked",
    )

    assert conflict.conflict_status == "blocked_merge"
    assert "lifecycle state is blocked" in conflict.contradiction_reason


def test_safe_merge_candidate_with_approved_alias_evidence():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="static x",
        entity_value="Static-X",
        evidence_count=3,
        approvals=1,
        folder_agreement=True,
        role_agreement=True,
    )

    conflict = evaluate_conflict(
        conflict_type="alias_collision",
        source_entity="Static X",
        target_entity="Static-X",
        entity_role="artist",
        confidence_snapshot={
            "normalized_confidence": scored.normalized_confidence,
            "raw_positive_score": scored.raw_positive_score,
            "raw_negative_score": scored.raw_negative_score,
        },
        positive_evidence_json=scored.positive_evidence_json,
        negative_evidence_json="[]",
        lifecycle_state="probationary",
        approved_alias=True,
    )

    assert conflict.conflict_status == "safe_to_merge_candidate"
    assert "no automatic merge" in conflict.recommended_action


def test_report_generation_and_cli(tmp_path, capsys):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Static X", "Push It", "", "a.flac")
    _insert_observation(db_path, "STATIC X", "Push It", "", "b.flac")

    result = generate_conflict_governance_report(out_dir=reports, db_path=db_path)
    report_dir = reports / "conflict_governance"

    assert result.total_conflicts >= 1
    assert (report_dir / "conflict_summary.json").exists()
    assert (report_dir / "blocked_merges.csv").exists()
    rows = _read_csv(report_dir / "conflicts.csv")
    assert rows[0]["conflict_status"] in {"blocked_merge", "needs_review", "deferred"}

    exit_code = main(["--db", str(db_path), "conflict-governance", "--out", str(reports)])
    assert exit_code == 0
    assert "total_conflicts=" in capsys.readouterr().out


def test_canonical_graph_summary_integration(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Static X", "Push It", "", "a.flac")
    _insert_observation(db_path, "STATIC X", "Push It", "", "b.flac")

    generate_conflict_governance_report(out_dir=reports, db_path=db_path)
    generate_canonical_graph(out_dir=reports, db_path=db_path)
    summary = json.loads((reports / "canonical_graph" / "graph_summary.json").read_text(encoding="utf-8"))

    assert summary["unresolved_conflicts"] >= 1
    assert summary["governed_conflicts"] >= 1
    assert "blocked_merges" in summary
    assert "safe_merge_candidates" in summary
    assert "needs_review_conflicts" in summary


def test_ui_route_rendering(tmp_path):
    reports = tmp_path / "reports"
    report_dir = reports / "conflict_governance"
    report_dir.mkdir(parents=True)
    _write_json(
        report_dir / "conflict_summary.json",
        {
            "total_conflicts": 1,
            "blocked_merges": 1,
            "safe_merge_candidates": 0,
            "needs_review": 0,
        },
    )
    row = {
        "conflict_id": "conflict_1",
        "conflict_type": "artifact_collision",
        "source_entity": "Warner Records Vault",
        "target_entity": "Warner Records",
        "entity_role": "artist",
        "conflict_status": "blocked_merge",
        "severity": "high",
        "confidence_snapshot": "{}",
        "positive_evidence_json": "[]",
        "negative_evidence_json": "[]",
        "contradiction_reason": "dominant artifact evidence blocks merge",
        "recommended_action": "do not merge",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    for name in ("conflicts.csv", "blocked_merges.csv"):
        _write_csv(report_dir / name, row.keys(), [row])
    for name in ("safe_merge_candidates.csv", "needs_review.csv"):
        _write_csv(report_dir / name, row.keys(), [])
    app.state.reports_dir = reports

    response = TestClient(app).get("/review/conflicts")

    assert response.status_code == 200
    assert "Conflict Governance" in response.text
    assert "Blocked Merges" in response.text
    assert "dominant artifact evidence" in response.text


def test_no_mutation_behavior(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    media_file = tmp_path / "Static-X - Push It.flac"
    media_file.write_bytes(b"source bytes")
    before = media_file.read_bytes()
    _insert_observation(db_path, "Static X", "Push It", "", str(media_file))
    _insert_observation(db_path, "STATIC X", "Push It", "", "other.flac")

    generate_conflict_governance_report(out_dir=tmp_path / "reports", db_path=db_path)

    assert media_file.read_bytes() == before


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
            VALUES (?, ?, ?, '/music/Static-X', ?, '.flac', 10, ?, '2026-01-01T00:00:00+00:00')
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


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, headers, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=list(headers))
        writer.writeheader()
        writer.writerows(rows)
