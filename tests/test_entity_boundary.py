import csv
from pathlib import Path

from app import db
from app.canonical_entity_graph import build_canonical_graph
from app.conflict_governance import build_conflict_governance
from app.entity_boundary import BoundaryContext, classify_boundary, generate_entity_boundary_report


def test_title_pollution_blocked():
    boundary = classify_boundary(
        BoundaryContext(
            candidate_value="A Place For My Head",
            source_field="artist",
            folder_artist="Linkin Park",
            filename_title="A Place For My Head",
            metadata_tags={"title": "A Place For My Head"},
        )
    )

    assert boundary.boundary_status == "block"
    assert boundary.proposed_boundary_type == "track_title_pollution"


def test_official_audio_artist_blocked():
    boundary = classify_boundary(
        BoundaryContext(
            candidate_value="Heavy Is the Crown (Official Audio)",
            source_field="artist",
            folder_artist="Linkin Park",
        )
    )

    assert boundary.boundary_status == "block"
    assert boundary.proposed_boundary_type == "release_annotation"


def test_collaboration_string_quarantined():
    boundary = classify_boundary(
        BoundaryContext(
            candidate_value="Tom Morello, BEARTOOTHband",
            source_field="artist",
            folder_artist="Beartooth",
        )
    )

    assert boundary.boundary_status == "quarantine"
    assert boundary.proposed_boundary_type == "collaboration_string"


def test_uploader_artifact_blocked():
    boundary = classify_boundary(
        BoundaryContext(
            candidate_value="Lagu Pre Studio",
            source_field="artist",
            folder_artist="Static-X",
        )
    )

    assert boundary.boundary_status == "block"
    assert boundary.proposed_boundary_type == "source_artifact"


def test_valid_artists_allowed():
    for value in ("Tool", "TOOL", "System of a Down", "System Of A Down", "Alice in Chains", "Alice In Chains"):
        boundary = classify_boundary(
            BoundaryContext(candidate_value=value, source_field="artist", folder_artist=value, repeated_role_evidence=3)
        )

        assert boundary.boundary_status == "allow"
        assert boundary.proposed_boundary_type == "canonical_artist_candidate"


def test_valid_albums_allowed():
    for value in ("Badmotorfinger", "L.D. 50", "Dark Sun", "Dear Agony"):
        boundary = classify_boundary(
            BoundaryContext(
                candidate_value=value,
                source_field="album",
                folder_artist="Artist",
                repeated_role_evidence=3,
            )
        )

        assert boundary.boundary_status == "allow"
        assert boundary.proposed_boundary_type == "canonical_album_candidate"


def test_boundary_report_generation(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(
        db_path,
        artist="Heavy Is the Crown (Official Audio)",
        title="Heavy Is the Crown (Official Audio)",
        album="From Zero",
        filename="Heavy Is the Crown (Official Audio).flac",
        folder="/music/Linkin Park",
    )
    _insert_observation(
        db_path,
        artist="Tool",
        title="Sober",
        album="Undertow",
        filename="Tool - Sober.flac",
        folder="/music/Tool",
    )

    result = generate_entity_boundary_report(out_dir=reports, db_path=db_path)
    report_dir = reports / "entity_boundaries"

    assert result.total_candidates >= 2
    assert result.blocked_candidates >= 1
    assert (report_dir / "entity_boundary_summary.json").exists()
    assert (report_dir / "entity_boundaries.csv").exists()
    assert (report_dir / "blocked_boundaries.csv").exists()
    assert _read_csv(report_dir / "blocked_boundaries.csv")


def test_canonical_graph_boundary_blocks_polluted_artist_and_reduces_role_collision(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(
        db_path,
        artist="Heavy Is the Crown (Official Audio)",
        title="Heavy Is the Crown (Official Audio)",
        album="From Zero",
        filename="Heavy Is the Crown (Official Audio).flac",
        folder="/music/Linkin Park",
    )
    _insert_observation(
        db_path,
        artist="Linkin Park",
        title="Heavy Is the Crown",
        album="From Zero",
        filename="Linkin Park - Heavy Is the Crown.flac",
        folder="/music/Linkin Park",
    )

    graph = build_canonical_graph(db_path=db_path, reports_dir=reports)
    canonical_artists = {artist.canonical_name for artist in graph.artists}
    governance = build_conflict_governance(db_path=db_path, reports_dir=reports, graph=graph)

    assert "Heavy Is the Crown (Official Audio)" not in canonical_artists
    assert any("entity boundary block" in conflict.rationale for conflict in graph.unresolved_conflicts)
    assert all(conflict.conflict_type != "role_collision" for conflict in governance.conflicts)


def test_conflict_governance_safety_remains_for_legitimate_role_collisions(tmp_path):
    db_path = tmp_path / "music.sqlite3"
    reports = tmp_path / "reports"
    _insert_observation(
        db_path,
        artist="Heavy Is the Crown (Official Audio)",
        title="Heavy Is the Crown (Official Audio)",
        album="From Zero",
        filename="Heavy Is the Crown (Official Audio).flac",
        folder="/music/Linkin Park",
    )

    graph = build_canonical_graph(db_path=db_path, reports_dir=reports)
    governance = build_conflict_governance(db_path=db_path, reports_dir=reports, graph=graph)

    assert not any(conflict.conflict_status == "safe_to_merge_candidate" for conflict in governance.conflicts)
    assert any(
        "official media marker" in conflict.contradiction_reason or "defer" in conflict.recommended_action
        for conflict in governance.conflicts
    )


def _insert_observation(db_path: Path, *, artist: str, title: str, album: str, filename: str, folder: str) -> None:
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
            (scan_run_id, str(path), path.name, folder, path.name, f"sha-{path.name}"),
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
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))
