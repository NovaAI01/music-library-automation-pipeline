import csv
import json
from pathlib import Path

from app import db
from app.canonical_confidence import (
    confidence_tier,
    generate_canonical_confidence_report,
    normalize_confidence,
    score_canonical_entity,
    score_weighted_evidence,
)
from app.canonical_entity_classifier import CandidateContext, classify_candidate
from app.canonical_entity_graph import build_canonical_graph
from app.main import main


def test_strong_positive_evidence_overrides_weak_artifact_evidence():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="records",
        entity_value="Records",
        evidence_count=5,
        average_reliability=0.78,
        folder_agreement=True,
        role_agreement=True,
        artifact_flags=["source_artifact_pattern"],
    )

    assert scored.raw_positive_score > scored.raw_negative_score
    assert scored.confidence_tier in {"medium", "high"}


def test_dominant_artifact_evidence_blocks_entity():
    scored = score_canonical_entity(
        entity_type="artist",
        entity_key="warnerrecordsvault",
        entity_value="Warner Records Vault",
        evidence_count=1,
        artifact_flags=["source_artifact_pattern", "uploader_signature"],
        title_like_artist=True,
    )

    assert scored.raw_negative_score > scored.raw_positive_score
    assert scored.confidence_tier == "blocked"


def test_repeated_canonical_evidence_boosts_confidence():
    sparse = score_canonical_entity(entity_type="track", entity_key="dig", entity_value="Dig", evidence_count=1)
    repeated = score_canonical_entity(entity_type="track", entity_key="dig", entity_value="Dig", evidence_count=4, role_agreement=True)

    assert repeated.normalized_confidence > sparse.normalized_confidence
    assert repeated.raw_positive_score > sparse.raw_positive_score


def test_temporal_reinforcement_increases_confidence():
    short_lived = score_canonical_entity(
        entity_type="album",
        entity_key="ld50",
        entity_value="L.D. 50",
        evidence_count=2,
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-01-02T00:00:00+00:00",
    )
    stable = score_canonical_entity(
        entity_type="album",
        entity_key="ld50",
        entity_value="L.D. 50",
        evidence_count=2,
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-03-01T00:00:00+00:00",
    )

    assert stable.normalized_confidence > short_lived.normalized_confidence
    assert "stable_temporal_presence" in stable.positive_evidence_json


def test_isolated_occurrence_lowers_confidence():
    isolated = score_canonical_entity(entity_type="artist", entity_key="x", entity_value="X", evidence_count=1)
    repeated = score_canonical_entity(entity_type="artist", entity_key="x", entity_value="X", evidence_count=3)

    assert "isolated_occurrence" in isolated.negative_evidence_json
    assert isolated.normalized_confidence < repeated.normalized_confidence


def test_confidence_normalization_stability_and_tier_boundaries():
    assert 0.0 <= normalize_confidence(-100) <= 1.0
    assert 0.0 <= normalize_confidence(100) <= 1.0
    assert confidence_tier(0.80) == "high"
    assert confidence_tier(0.60) == "medium"
    assert confidence_tier(0.40) == "low"
    assert confidence_tier(0.30, raw_positive_score=0.1, raw_negative_score=0.6) == "blocked"


def test_weighted_breakdown_is_explainable_json():
    scored = score_weighted_evidence(
        entity_type="artist",
        entity_key="flyleaf",
        entity_value="Flyleaf",
        positive=["repeated_artist_metadata", "folder_agreement"],
        negative=["isolated_occurrence"],
    )
    breakdown = json.loads(scored.weighted_score_breakdown_json)

    assert breakdown["positive_total"] > 0
    assert breakdown["negative_total"] > 0
    assert breakdown["formula"] == "normalized(raw_positive_score - raw_negative_score)"


def test_graph_scoring_integration_uses_weighted_confidence(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    _insert_observation(db_path, "Flyleaf", "I'm So Sick", "Flyleaf", "Flyleaf - I'm So Sick.flac")
    _insert_observation(db_path, "Flyleaf", "Fully Alive", "Flyleaf", "Flyleaf - Fully Alive.flac")

    graph = build_canonical_graph(db_path=db_path, reports_dir=tmp_path / "reports")

    assert graph.artists[0].confidence_score >= 0.74
    assert graph.artists[0].confidence_tier == "high"


def test_classifier_integration_preserves_strong_canonical_evidence():
    result = classify_candidate(
        CandidateContext(
            candidate_value="Records",
            field_name="artist",
            folder_artist="/music/Records",
            value_artist_count=5,
            role_evidence_count=5,
            role_status="canonical",
            active_roles=["artist", "source_artifact"],
            role_flags=["multi_role_entity"],
        )
    )

    assert result.proposed_entity_type == "canonical_artist"
    assert "weak_artifact_signal_overridden" in result.flags


def test_confidence_report_generation_and_cli(tmp_path, capsys):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(db_path, "Audioslave", "Cochise", "Audioslave", "Audioslave - Cochise.flac")
    _insert_observation(db_path, "Audioslave", "Show Me How To Live", "Audioslave", "Audioslave - Show Me How To Live.flac")
    _insert_observation(db_path, "Warner Records Vault", "Push It", "Wisconsin Death Trip", "Static-X - Push It.flac")

    result = generate_canonical_confidence_report(out_dir=reports, db_path=db_path)
    report_dir = reports / "canonical_confidence"
    summary = json.loads((report_dir / "confidence_summary.json").read_text(encoding="utf-8"))
    rows = _read_csv(report_dir / "scored_entities.csv")

    assert result.total_scored_entities >= 4
    assert summary["average_confidence"] > 0
    assert rows[0]["positive_evidence_json"]
    assert (report_dir / "confidence_breakdowns.json").exists()

    exit_code = main(["--db", str(db_path), "canonical-confidence", "--out", str(reports)])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "total_scored_entities=" in output


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
