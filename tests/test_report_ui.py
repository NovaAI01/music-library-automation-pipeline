import csv
import json
import re

from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_dashboard_route_returns_200(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports")

    assert response.status_code == 200
    assert "Total library files" in response.text
    assert "4" in response.text


def test_artists_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/artists")

    assert response.status_code == 200
    assert "Static-X" in response.text


def test_genres_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/genres")

    assert response.status_code == 200
    assert "Alternative Metal" in response.text


def test_quarantine_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/quarantine")

    assert response.status_code == 200
    assert "duplicate.flac" in response.text


def test_duplicate_page_renders(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/duplicates")

    assert response.status_code == 200
    assert "Historical Duplicate Groups" in response.text
    assert "same_artist_title:static-x:push it" in response.text


def test_missing_report_files_are_handled_gracefully(tmp_path):
    client = _client(tmp_path)

    response = client.get("/reports")

    assert response.status_code == 200
    assert "Missing report data" in response.text
    assert "Total library files" in response.text


def test_file_health_search_filters_rows(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/reports/file-health?q=quarantine")

    assert response.status_code == 200
    assert "duplicate.flac" in response.text
    assert "Push It.flac" not in response.text


def test_app_dashboard_route_renders_unified_navigation(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)
    _write_metadata_fixture(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "Music Library Intelligence Platform" in response.text
    assert "Total tracks" in response.text
    assert "Albums" in response.text
    assert "Unknown albums" in response.text
    assert "Album plan rows" in response.text
    assert "/import" in response.text
    assert "/library/albums" in response.text
    assert "/library/tracks" in response.text
    assert "/player" in response.text
    assert 'class="active">Dashboard' in response.text
    assert "dark" in response.text
    assert "Your home base for importing" in response.text


def test_import_page_renders_workflow(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/import")

    assert response.status_code == 200
    assert "Library intake path" in response.text
    assert "python -m app.main scan" in response.text
    assert "Operational Workflow" in response.text


def test_library_listing_routes_render(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    library = client.get("/library")
    artists = client.get("/library/artists?q=Static")
    genres = client.get("/library/genres?q=Alternative")
    tracks = client.get("/library/tracks?q=Push")
    albums = client.get("/library/albums?q=Wisconsin")

    assert library.status_code == 200
    assert "Organized Browser" in library.text
    assert "Albums" in library.text
    assert artists.status_code == 200
    assert "Static-X" in artists.text
    assert "Wisconsin Death Trip" in artists.text
    assert genres.status_code == 200
    assert "Alternative Metal" in genres.text
    assert tracks.status_code == 200
    assert "Static-X - Push It.flac" in tracks.text
    assert "Album" in tracks.text
    assert "/media/audio?path=Alternative%20Metal/Nu%20Metal/Static-X/Static-X%20-%20Push%20It.flac" in tracks.text
    assert albums.status_code == 200
    assert "Wisconsin Death Trip" in albums.text
    assert "Play album" in albums.text
    assert "Back to Library" in tracks.text
    assert "Dashboard</a>" in tracks.text


def test_organization_preview_routes_render_scan_judgment_and_tree(tmp_path):
    client = _client(tmp_path)
    _write_organization_preview_fixture(tmp_path)

    response = client.get(
        "/library/organization-preview",
        params={
            "scan_run_id": "15",
            "placement_status": "needs_review",
            "q": "Disguise",
        },
    )
    tree = client.get("/library/organization-preview/tree", params={"scan_run_id": "15"})

    assert response.status_code == 200
    assert "Messy Source -&gt; System Judgment -&gt; Organized Destination" in response.text
    assert "Latest Scan Run Summary" in response.text
    assert "Motionless In White - Disguise (Full Album)" in response.text
    assert "OrganizedLibrary/_Review/placement" in response.text
    assert "unsplit_full_album" in response.text
    assert "Deftones - Around The Fur" not in response.text
    assert tree.status_code == 200
    assert "OrganizedLibrary/Music" in tree.text
    assert "OrganizedLibrary/_Review" in tree.text
    assert "OrganizedLibrary/_Unresolved" in tree.text


def test_album_browser_not_empty_when_tracks_exist_without_album_folder(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get("/library/albums?q=Unknown")

    assert response.status_code == 200
    assert "Unknown Album" in response.text
    assert "Static-X" in response.text


def test_dashboard_uses_album_plan_metrics_when_available(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)
    plan_dir = tmp_path / "reports" / "album_organization_plan"
    plan_dir.mkdir(parents=True)
    _write_json(
        plan_dir / "album_organization_summary.json",
        {
            "total_files": 4,
            "unknown_album_count": 2,
        },
    )
    _write_csv(
        plan_dir / "album_organization_plan.csv",
        [
            "current_path",
            "proposed_path",
            "artist",
            "album",
            "title",
            "confidence",
            "reason",
            "requires_review",
        ],
        [],
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "Album plan rows" in response.text
    assert "4" in response.text


def test_album_detail_route_lists_tracks_and_play_links(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    albums = client.get("/library/albums?q=Wisconsin")
    album_key = re.search(r"/library/albums/([^\"?]+)", albums.text).group(1)
    detail = client.get(f"/library/albums/{album_key}")

    assert detail.status_code == 200
    assert "Wisconsin Death Trip" in detail.text
    assert "Static-X - Bled for Days.flac" in detail.text
    assert "/media/audio?path=Alternative%20Metal/Nu%20Metal/Static-X/Wisconsin%20Death%20Trip/Static-X%20-%20Bled%20for%20Days.flac" in detail.text
    assert "Back to Albums" in detail.text


def test_unified_review_and_metadata_routes_render(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)
    _write_metadata_fixture(tmp_path)

    review = client.get("/review")
    duplicates = client.get("/review/duplicates")
    metadata = client.get("/review/metadata")

    assert review.status_code == 200
    assert "Unified Review Hub" in review.text
    assert "Duplicate Review" in review.text
    assert "Metadata Review" in review.text
    assert duplicates.status_code == 200
    assert "Active Duplicate Groups" in duplicates.text
    assert metadata.status_code == 200
    assert "Metadata suggestions are review-only" in metadata.text
    assert "missing_album_artist" in metadata.text
    assert "Back to Review" in metadata.text
    assert "confidence-high" in metadata.text


def test_player_and_settings_routes_render(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    player = client.get("/player")
    settings = client.get("/settings")

    assert player.status_code == 200
    assert "<audio" in player.text
    assert "Play file" in player.text
    assert "Playable Albums" in player.text
    assert "Alternative Metal/Nu Metal/Static-X/Static-X - Push It.flac" in player.text
    assert settings.status_code == 200
    assert "Library root" in settings.text
    assert "Reports directory" in settings.text
    assert str(tmp_path / "library") in settings.text


def test_audio_route_serves_file_under_library_root(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)

    response = client.get(
        "/media/audio",
        params={"path": "Alternative Metal/Nu Metal/Static-X/Static-X - Push It.flac"},
    )

    assert response.status_code == 200
    assert response.content == b"audio"
    assert response.headers["content-type"].startswith("audio/flac")


def test_audio_route_blocks_path_traversal(tmp_path):
    client = _client(tmp_path)
    _write_report_fixture(tmp_path)
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"outside")

    response = client.get("/media/audio", params={"path": "../outside.flac"})

    assert response.status_code == 404


def _client(tmp_path):
    app.state.reports_dir = tmp_path / "reports"
    app.state.library_root = tmp_path / "library"
    app.state.quarantine_root = tmp_path / "quarantine"
    app.state.db_path = tmp_path / "music_library.sqlite3"
    return TestClient(app)


def _write_report_fixture(tmp_path):
    reports_dir = tmp_path / "reports"
    qa_dir = reports_dir / "library_qa"
    duplicate_dir = reports_dir / "duplicates_scan_1"
    qa_dir.mkdir(parents=True)
    duplicate_dir.mkdir(parents=True)

    _write_json(
        qa_dir / "library_qa_summary.json",
        {
            "total_library_files": 4,
            "total_quarantine_files": 1,
            "artist_count": 2,
            "album_count": 1,
            "genre_count": 2,
            "active_duplicate_group_count": 1,
            "unresolved_missing_file_count": 0,
            "created_at": "2026-05-10T00:00:00+00:00",
        },
    )
    _write_csv(
        qa_dir / "artists.csv",
        ["artist", "genre", "subgenre", "file_count"],
        [
            {
                "artist": "Static-X",
                "genre": "Alternative Metal",
                "subgenre": "Nu Metal",
                "file_count": "2",
            },
            {
                "artist": "Nirvana",
                "genre": "Alternative Rock",
                "subgenre": "Grunge",
                "file_count": "2",
            },
        ],
    )
    _write_csv(
        qa_dir / "genres.csv",
        ["genre", "subgenre", "artist_count", "file_count"],
        [
            {
                "genre": "Alternative Metal",
                "subgenre": "Nu Metal",
                "artist_count": "1",
                "file_count": "2",
            },
            {
                "genre": "Alternative Rock",
                "subgenre": "Grunge",
                "artist_count": "1",
                "file_count": "2",
            },
        ],
    )
    _write_csv(
        qa_dir / "quarantine_summary.csv",
        ["extension", "file_count", "size_bytes"],
        [{"extension": ".flac", "file_count": "1", "size_bytes": "100"}],
    )
    library_file = (
        tmp_path
        / "library"
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It.flac"
    )
    duplicate_file = (
        tmp_path
        / "library"
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Static-X - Push It duplicate.flac"
    )
    album_file = (
        tmp_path
        / "library"
        / "Alternative Metal"
        / "Nu Metal"
        / "Static-X"
        / "Wisconsin Death Trip"
        / "Static-X - Bled for Days.flac"
    )
    quarantine_file = tmp_path / "quarantine" / "duplicate.flac"
    for path in (library_file, duplicate_file, album_file, quarantine_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
    _write_csv(
        qa_dir / "file_health.csv",
        ["path", "size_bytes", "extension", "status"],
        [
            {
                "path": str(library_file),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "library_present",
            },
            {
                "path": str(duplicate_file),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "library_present",
            },
            {
                "path": str(album_file),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "library_present",
            },
            {
                "path": str(quarantine_file),
                "size_bytes": "100",
                "extension": ".flac",
                "status": "quarantine_present",
            },
        ],
    )
    _write_json(
        duplicate_dir / "duplicate_summary.json",
        {
            "scan_run_id": 1,
            "total_files_checked": 2,
            "same_artist_title_groups": 1,
        },
    )
    _write_csv(
        duplicate_dir / "exact_hash_duplicates.csv",
        [
            "duplicate_group_key",
            "duplicate_type",
            "artist",
            "normalized_title",
            "file_path",
            "file_size_bytes",
            "sha256",
            "reason",
        ],
        [],
    )
    _write_csv(
        duplicate_dir / "same_artist_title_duplicates.csv",
        [
            "duplicate_group_key",
            "duplicate_type",
            "artist",
            "normalized_title",
            "file_path",
            "file_size_bytes",
            "sha256",
            "reason",
        ],
        [
            {
                "duplicate_group_key": "same_artist_title:static-x:push it",
                "duplicate_type": "same_artist_title",
                "artist": "Static-X",
                "normalized_title": "push it",
                "file_path": str(library_file),
                "file_size_bytes": "100",
                "sha256": "hash-1",
                "reason": "same_planned_artist_and_normalized_title",
            },
            {
                "duplicate_group_key": "same_artist_title:static-x:push it",
                "duplicate_type": "same_artist_title",
                "artist": "Static-X",
                "normalized_title": "push it",
                "file_path": str(duplicate_file),
                "file_size_bytes": "100",
                "sha256": "hash-2",
                "reason": "same_planned_artist_and_normalized_title",
            },
        ],
    )
    _write_csv(
        duplicate_dir / "probable_variants.csv",
        [
            "duplicate_group_key",
            "duplicate_type",
            "artist",
            "normalized_title",
            "file_path",
            "file_size_bytes",
            "sha256",
            "reason",
        ],
        [],
    )


def _write_metadata_fixture(tmp_path):
    reports_dir = tmp_path / "reports"
    audit_dir = reports_dir / "metadata_audit"
    plan_dir = reports_dir / "metadata_plan"
    suggestions_dir = reports_dir / "metadata_suggestions"
    audit_dir.mkdir(parents=True, exist_ok=True)
    plan_dir.mkdir(parents=True, exist_ok=True)
    suggestions_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        audit_dir / "metadata_summary.json",
        {
            "missing_tag_count": 2,
            "malformed_tag_count": 1,
            "unreadable_flac_files": 0,
            "created_at": "2026-05-10T00:00:00+00:00",
        },
    )
    _write_json(
        plan_dir / "metadata_plan_summary.json",
        {"proposed_update_count": 3},
    )
    _write_json(
        suggestions_dir / "metadata_suggestions.json",
        {
            "suggestions": [
                {
                    "file_path": "Alternative Metal/Static-X/Push It.flac",
                    "field": "album_artist",
                    "current_value": "",
                    "proposed_value": "Static-X",
                    "confidence": "high",
                    "suggestion_type": "missing_album_artist",
                    "rationale": "album_artist should equal artist",
                    "source_evidence": ["metadata_plan"],
                    "requires_human_review": True,
                }
            ]
        },
    )


def _write_organization_preview_fixture(tmp_path):
    db_path = tmp_path / "music_library.sqlite3"
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO scan_runs (
                id,
                source_path,
                started_at,
                completed_at,
                status,
                total_files_seen,
                audio_files_seen,
                files_failed
            )
            VALUES (
                15,
                '/home/jack/Music/ScarletteTrackLibrary',
                '2026-05-31T10:00:00+00:00',
                '2026-05-31T10:01:00+00:00',
                'completed',
                3,
                3,
                0
            )
            """
        )
        rows = [
            {
                "id": 1,
                "relative_path": "Warner Records Vault/Deftones - Around The Fur (Full Album)/01 My Own Summer (Shove It).flac",
                "parent_folder": "Warner Records Vault/Deftones - Around The Fur (Full Album)",
                "filename": "01 My Own Summer (Shove It).flac",
                "artist": "Deftones",
                "album": "Around The Fur",
                "title": "My Own Summer (Shove It)",
                "identity_status": "identified",
                "classification_status": "classified",
                "primary_genre": "Alternative Metal",
                "subgenre": "Nu Metal",
                "placement_status": "planned",
                "planned_path": "OrganizedLibrary/Music/Artists/Deftones/Albums/Around The Fur/01 - My Own Summer (Shove It).flac",
                "reason": {"reasons": []},
            },
            {
                "id": 2,
                "relative_path": "Motionless In White - Disguise (Full Album)/ Motionless In White - Disguise (Full Album).flac",
                "parent_folder": "Motionless In White - Disguise (Full Album)",
                "filename": " Motionless In White - Disguise (Full Album).flac",
                "artist": "Motionless in White",
                "album": "Disguise",
                "title": "Disguise (Full Album)",
                "identity_status": "identified",
                "classification_status": "classified",
                "primary_genre": "Metalcore",
                "subgenre": "",
                "placement_status": "needs_review",
                "planned_path": "OrganizedLibrary/_Review/placement/Motionless In White - Disguise (Full Album)/Motionless In White - Disguise (Full Album).flac",
                "reason": {"reasons": ["unsplit_full_album"]},
            },
            {
                "id": 3,
                "relative_path": "Unknown/Unknown Track.flac",
                "parent_folder": "Unknown",
                "filename": "Unknown Track.flac",
                "artist": None,
                "album": None,
                "title": None,
                "identity_status": "unknown",
                "classification_status": "unknown",
                "primary_genre": None,
                "subgenre": None,
                "placement_status": "blocked_unknown_identity",
                "planned_path": "OrganizedLibrary/_Unresolved/unknown/Unknown/Unknown Track.flac",
                "reason": {"reasons": ["identity_unknown"]},
            },
        ]
        for row in rows:
            connection.execute(
                """
                INSERT INTO observed_files (
                    id,
                    scan_run_id,
                    source_path,
                    relative_path,
                    parent_folder,
                    filename,
                    extension,
                    file_size_bytes,
                    sha256,
                    created_at
                )
                VALUES (?, 15, '/home/jack/Music/ScarletteTrackLibrary', ?, ?, ?, '.flac', 10, ?, '2026-05-31T10:00:00+00:00')
                """,
                (row["id"], row["relative_path"], row["parent_folder"], row["filename"], f"hash-{row['id']}"),
            )
            connection.execute(
                """
                INSERT INTO track_identity (
                    observed_file_id,
                    probable_artist,
                    probable_title,
                    probable_album,
                    probable_year,
                    probable_mix,
                    identity_confidence,
                    identity_status,
                    evidence_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, NULL, NULL, 0.9, ?, '{}', '2026-05-31T10:00:00+00:00')
                """,
                (
                    row["id"],
                    row["artist"],
                    row["title"],
                    row["album"],
                    row["identity_status"],
                ),
            )
            connection.execute(
                """
                INSERT INTO classification_results (
                    observed_file_id,
                    primary_genre,
                    subgenre,
                    energy_level,
                    vocal_style,
                    mood_json,
                    classification_confidence,
                    classification_status,
                    evidence_json,
                    created_at
                )
                VALUES (?, ?, ?, NULL, NULL, '[]', 0.9, ?, '{}', '2026-05-31T10:00:00+00:00')
                """,
                (
                    row["id"],
                    row["primary_genre"],
                    row["subgenre"],
                    row["classification_status"],
                ),
            )
            connection.execute(
                """
                INSERT INTO placement_plans (
                    observed_file_id,
                    scan_run_id,
                    source_path,
                    planned_relative_path,
                    planned_artist,
                    planned_album,
                    planned_title,
                    planned_primary_genre,
                    planned_subgenre,
                    placement_confidence,
                    placement_status,
                    reason_json,
                    created_at
                )
                VALUES (?, 15, '/home/jack/Music/ScarletteTrackLibrary', ?, ?, ?, ?, ?, ?, 0.9, ?, ?, '2026-05-31T10:00:00+00:00')
                """,
                (
                    row["id"],
                    row["planned_path"],
                    row["artist"],
                    row["album"],
                    row["title"],
                    row["primary_genre"],
                    row["subgenre"],
                    row["placement_status"],
                    json.dumps(row["reason"]),
                ),
            )


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
