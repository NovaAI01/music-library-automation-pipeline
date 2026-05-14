import csv
import json
from pathlib import Path

from app import db
from app.canonical_confidence import score_canonical_entity
from app.canonical_entity_graph import build_canonical_graph
from app.main import main
from app.promotion_lifecycle import (
    evaluate_lifecycle,
    generate_promotion_lifecycle_report,
    lifecycle_summary,
)


def test_candidate_to_probationary():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="flyleaf",
        entity_value="Flyleaf",
        evidence_count=2,
        folder_agreement=True,
        role_agreement=True,
    )

    lifecycle = evaluate_lifecycle(scored, evidence_count=2, first_seen="2026-01-01T00:00:00+00:00", last_seen="2026-01-01T00:00:00+00:00")

    assert lifecycle.lifecycle_state == "probationary"
    assert lifecycle.transition_source == "new_observation"


def test_probationary_to_canonical():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="flyleaf",
        entity_value="Flyleaf",
        evidence_count=5,
        folder_agreement=True,
        role_agreement=True,
        graph_reinforcement=True,
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-03-01T00:00:00+00:00",
    )

    lifecycle = evaluate_lifecycle(
        scored,
        previous_state="probationary",
        evidence_count=5,
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-03-01T00:00:00+00:00",
        graph_relationships=2,
    )

    assert lifecycle.lifecycle_state == "canonical"
    assert lifecycle.transition_source == "probationary_to_canonical"


def test_canonical_to_deprecated():
    scored = score_canonical_entity(
        entity_type="album",
        entity_key="bad",
        entity_value="Bad",
        evidence_count=1,
        artifact_flags=["source_artifact_pattern", "uploader_signature"],
    )

    lifecycle = evaluate_lifecycle(scored, previous_state="canonical", evidence_count=1)

    assert lifecycle.lifecycle_state == "deprecated"
    assert lifecycle.transition_source == "canonical_deprecated"


def test_conflicted_state_detection():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="aliceinchains",
        entity_value="Alice in Chains",
        evidence_count=4,
        folder_agreement=True,
        role_agreement=True,
        artifact_flags=["conflicting_role_pattern", "source_artifact_pattern"],
    )

    lifecycle = evaluate_lifecycle(scored, evidence_count=4, conflict_count=2, role_conflict=True)

    assert lifecycle.lifecycle_state == "conflicted"
    assert "strong positive and negative" in lifecycle.lifecycle_reason


def test_blocked_state_persistence():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="warnerrecordsvault",
        entity_value="Warner Records Vault",
        evidence_count=1,
        artifact_flags=["source_artifact_pattern", "uploader_signature"],
        title_like_artist=True,
    )

    lifecycle = evaluate_lifecycle(scored, previous_state="blocked", evidence_count=1)

    assert lifecycle.lifecycle_state == "blocked"
    assert lifecycle.transition_source == "state_retained"


def test_temporal_reinforcement_promotion():
    scored = score_canonical_entity(
        entity_type="album",
        entity_key="ld50",
        entity_value="L.D. 50",
        evidence_count=2,
        role_agreement=True,
    )

    lifecycle = evaluate_lifecycle(
        scored,
        evidence_count=2,
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-04-01T00:00:00+00:00",
        graph_relationships=1,
    )

    assert lifecycle.lifecycle_state in {"canonical", "probationary"}
    assert "temporal_days" in lifecycle.temporal_snapshot


def test_weak_evidence_decay_remains_candidate():
    scored = score_canonical_entity(entity_type="track", entity_key="x", entity_value="X", evidence_count=1)

    lifecycle = evaluate_lifecycle(scored, previous_state="candidate", evidence_count=1)

    assert lifecycle.lifecycle_state == "candidate"


def test_graph_integration_uses_lifecycle_states(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    _insert_observation(db_path, "Flyleaf", "I'm So Sick", "Flyleaf", "Flyleaf - I'm So Sick.flac")
    _insert_observation(db_path, "Flyleaf", "Fully Alive", "Flyleaf", "Flyleaf - Fully Alive.flac")

    graph = build_canonical_graph(db_path=db_path, reports_dir=tmp_path / "reports")

    assert graph.artists[0].status in {"probationary", "canonical"}
    assert graph.summary["canonical_artist_count"] == 1


def test_report_generation_and_cli(tmp_path, capsys):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Audioslave", "Cochise", "Audioslave", "Audioslave - Cochise.flac")
    _insert_observation(db_path, "Audioslave", "Show Me How To Live", "Audioslave", "Audioslave - Show Me How To Live.flac")

    result = generate_promotion_lifecycle_report(out_dir=reports, db_path=db_path)
    report_dir = reports / "promotion_lifecycle"
    summary = json.loads((report_dir / "lifecycle_summary.json").read_text(encoding="utf-8"))
    rows = _read_csv(report_dir / "lifecycle_entities.csv")

    assert result.probationary_count + result.canonical_count + result.candidate_count >= 1
    assert summary["promoted_this_run"] == 0
    assert rows[0]["confidence_snapshot"]
    assert (report_dir / "canonical_entities.csv").exists()
    assert (report_dir / "deprecated_entities.csv").exists()

    exit_code = main(["--db", str(db_path), "promotion-lifecycle", "--out", str(reports)])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "candidate_count=" in output


def test_transition_explainability():
    scored = score_canonical_entity(entity_type="track", entity_key="dig", entity_value="Dig", evidence_count=3, role_agreement=True)

    lifecycle = evaluate_lifecycle(scored, evidence_count=3, graph_relationships=1)

    assert lifecycle.lifecycle_reason
    assert json.loads(lifecycle.confidence_snapshot)["normalized_confidence"] == scored.normalized_confidence
    assert "graph_reinforced" in json.loads(lifecycle.graph_snapshot)


def test_lifecycle_summary_counts_promotions_and_demotions():
    canonical = evaluate_lifecycle(
        score_canonical_entity(entity_type="artist", entity_key="a", entity_value="A", evidence_count=5, folder_agreement=True, role_agreement=True, graph_reinforcement=True),
        previous_state="probationary",
        evidence_count=5,
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-03-01T00:00:00+00:00",
        graph_relationships=1,
    )
    deprecated = evaluate_lifecycle(
        score_canonical_entity(entity_type="artist", entity_key="b", entity_value="B", evidence_count=1, artifact_flags=["source_artifact_pattern", "uploader_signature"]),
        previous_state="canonical",
        evidence_count=1,
    )

    summary = lifecycle_summary([canonical, deprecated], {("artist", "a"): "probationary", ("artist", "b"): "canonical"})

    assert summary["promoted_this_run"] == 1
    assert summary["demoted_this_run"] == 1


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
            VALUES (?, ?, ?, ?, ?, '.flac', 10, ?, '2026-01-01T00:00:00+00:00')
            """,
            (scan_run_id, str(path), path.name, f"/music/{artist}", path.name, f"sha-{path.name}"),
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
