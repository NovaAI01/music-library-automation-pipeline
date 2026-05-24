import json
import sqlite3

from app import db
from app.filename_parser import parse_filename
from app.identity_engine import (
    REQUIRED_EVIDENCE_FIELDS,
    build_identity_evidence,
    calculate_identity_confidence,
    identify_scan_run,
    resolve_identity,
)
from app.main import main


def test_complete_tag_identity():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        tag_album="White Pony",
        tag_date="2000-06-20",
        filename_artist="Deftones",
        filename_title="Change",
    )

    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Change"
    assert result.probable_album == "White Pony"
    assert result.probable_year == "2000"
    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.95
    assert result.evidence["selected_artist_source"] == "tag"
    assert result.evidence["selected_title_source"] == "tag"


def test_filename_only_identity():
    result = resolve_identity(
        filename_artist="Unknown Band",
        filename_title="Unknown Song",
    )

    assert result.probable_artist == "Unknown Band"
    assert result.probable_title == "Unknown Song"
    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.75


def test_artist_seed_normalization():
    result = resolve_identity(filename_artist="NIN", filename_title="Closer")

    assert result.probable_artist == "Nine Inch Nails"
    assert result.probable_title == "Closer"
    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.evidence["artist_seed_matched"] == "Nine Inch Nails"


def test_conflicting_artist_detection():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        filename_artist="Korn",
        filename_title="Change",
    )

    assert result.identity_status == "conflicting"
    assert result.identity_confidence == 0.40
    assert result.probable_artist == "Deftones"
    assert "tag_artist_conflicts_with_filename_artist" in result.evidence[
        "conflict_reasons"
    ]


def test_conflicting_title_detection():
    result = resolve_identity(
        tag_artist="Unknown Band",
        tag_title="Change",
        filename_artist="Unknown Band",
        filename_title="Digital Bath",
    )

    assert result.identity_status == "conflicting"
    assert result.identity_confidence == 0.40
    assert result.probable_title == "Change"
    assert "tag_title_conflicts_with_filename_title" in result.evidence[
        "conflict_reasons"
    ]


def test_uploader_tag_artist_with_filename_seed_artist_resolves_identified():
    result = resolve_identity(
        tag_artist="David Rolfe's Rock & Metal Channel.",
        tag_title="I'm So Sick",
        filename_artist="Flyleaf",
        filename_title="I'm So Sick",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Flyleaf"
    assert result.probable_title == "I'm So Sick"
    assert result.evidence["selected_artist_source"] == "filename"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["deprioritized_reason"] == "uploader_or_label_metadata"


def test_uploader_metadata_deprioritized_sets_identified_status():
    result = resolve_identity(
        tag_artist="Warner Records",
        tag_title="Warner Records",
        filename_artist="Deftones",
        filename_title="Be Quiet And Drive",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Be Quiet And Drive"
    assert result.evidence["conflict_reasons"] == []
    assert result.evidence["tag_artist_deprioritized"] is True


def test_conflict_reasons_do_not_force_conflict_for_deprioritized_tag_artist():
    result = resolve_identity(
        tag_artist="Better Noise Music",
        tag_title="Better Noise Music",
        filename_artist="Nothing More",
        filename_title="Jenny",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.evidence["conflict_reasons"] == []
    assert result.evidence["tag_artist_deprioritized"] is True


def test_label_tag_artist_with_filename_seed_artist_resolves_identified():
    result = resolve_identity(
        tag_artist="Roadrunner Records",
        tag_title="Digital Bath",
        filename_artist="Deftones",
        filename_title="Digital Bath",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Digital Bath"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["deprioritized_reason"] == "uploader_or_label_metadata"


def test_tag_artist_seed_match_remains_preferred():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        filename_artist="Deftones",
        filename_title="Change",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.95
    assert result.probable_artist == "Deftones"
    assert result.evidence["selected_artist_source"] == "tag"
    assert "tag_artist_deprioritized" not in result.evidence


def test_different_valid_seed_artists_still_conflict():
    result = resolve_identity(
        tag_artist="Deftones",
        tag_title="Change",
        filename_artist="Nothing More",
        filename_title="Change",
    )

    assert result.identity_status == "conflicting"
    assert result.identity_confidence == 0.40
    assert result.probable_artist == "Deftones"
    assert "tag_artist_conflicts_with_filename_artist" in result.evidence[
        "conflict_reasons"
    ]


def test_valid_seed_artist_vs_different_valid_seed_artist_remains_conflicting():
    result = resolve_identity(
        tag_artist="Flyleaf",
        tag_title="Fully Alive",
        filename_artist="Deftones",
        filename_title="Fully Alive",
    )

    assert result.identity_status == "conflicting"
    assert result.identity_confidence == 0.40
    assert result.evidence["conflict_reasons"] == [
        "tag_artist_conflicts_with_filename_artist"
    ]
    assert "tag_artist_deprioritized" not in result.evidence


def test_youtube_title_suffixes_are_removed():
    result = resolve_identity(
        filename_artist="Deftones",
        filename_title="Be Quiet and Drive (Official Music Video) [HD Remaster]",
    )

    assert result.probable_title == "Be Quiet and Drive"
    assert result.identity_status == "identified"


def test_title_removes_video_id_bracket():
    result = resolve_identity(
        filename_artist="Deftones",
        filename_title="Be Quiet And Drive [KvknOXGPzCQ]",
    )

    assert result.probable_title == "Be Quiet And Drive"
    assert result.identity_status == "identified"


def test_title_removes_duplicate_artist_prefix():
    result = resolve_identity(
        filename_artist="Deftones",
        filename_title="Deftones - Be Quiet And Drive",
    )

    assert result.probable_title == "Be Quiet And Drive"
    assert result.identity_status == "identified"


def test_deftones_en_dash_title_removes_artist_prefix():
    result = resolve_identity(
        filename_artist="Deftones",
        filename_title="Deftones – Risk",
    )

    assert result.probable_title == "Risk"
    assert result.identity_status == "identified"


def test_title_removes_bare_official_music_video_suffix():
    result = resolve_identity(
        filename_artist="Deftones",
        filename_title="Be Quiet And Drive Official Music Video",
    )

    assert result.probable_title == "Be Quiet And Drive"
    assert result.identity_status == "identified"


def test_better_noise_music_nothing_more_resolves_nothing_more():
    result = resolve_identity(
        tag_artist="Better Noise Music",
        tag_title="Jenny",
        filename_artist="NOTHING MORE",
        filename_title="Jenny (Official Video)",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Nothing More"
    assert result.probable_title == "Jenny"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["deprioritized_reason"] == "uploader_or_label_metadata"


def test_real_better_noise_music_example_plans_clean_identity():
    result = resolve_identity(
        tag_artist="Better Noise Music",
        tag_title="Official Music Video",
        filename_artist="NOTHING MORE",
        filename_title="NOTHING MORE - Jenny [Official Video] [KvknOXGPzCQ]",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Nothing More"
    assert result.probable_title == "Jenny"
    assert result.evidence["conflict_reasons"] == []
    assert result.evidence["tag_artist_deprioritized"] is True


def test_deftones_filename_remains_deftones_and_title_cleans():
    result = resolve_identity(
        tag_artist="Warner Records",
        tag_title="My Own Summer",
        filename_artist="Deftones",
        filename_title="My Own Summer [Official Music Video] [4K]",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "My Own Summer"
    assert result.evidence["selected_artist_source"] == "filename"
    assert result.evidence["selected_title_source"] == "filename"


def test_real_deftones_example_plans_clean_identity():
    result = resolve_identity(
        tag_artist="Warner Records",
        tag_title="Official Music Video",
        filename_artist="Deftones",
        filename_title="Deftones - Be Quiet And Drive (Official Music Video) [KvknOXGPzCQ]",
    )

    assert result.identity_status == "identified"
    assert result.identity_confidence == 0.85
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Be Quiet And Drive"
    assert result.evidence["conflict_reasons"] == []
    assert result.evidence["tag_artist_deprioritized"] is True


def test_deftones_official_video_title_becomes_identified():
    result = resolve_identity(
        tag_artist="Warner Records",
        tag_title="Official Music Video",
        filename_artist="Deftones",
        filename_title=(
            "Deftones - Change (In The House Of Flies) "
            "[Official Music Video] [ar_ytmdYy2s]"
        ),
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Change (In The House Of Flies)"
    assert result.evidence["conflict_reasons"] == []


def test_flyleaf_all_around_me_filename_seed_becomes_identified():
    result = resolve_identity(
        tag_artist="FlyleafVEVO",
        tag_title="Official Video",
        filename_artist="Flyleaf",
        filename_title="Flyleaf - All Around Me (Official Music Video)",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Flyleaf"
    assert result.probable_title == "All Around Me"
    assert result.evidence["conflict_reasons"] == []


def test_nothing_more_freefall_removes_video_id_and_official_suffix():
    result = resolve_identity(
        tag_artist="Better Noise Music",
        tag_title="Official Music Video",
        filename_artist="Nothing More",
        filename_title="Nothing More - FREEFALL (Official Audio) [_xmdbuPfN3U]",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Nothing More"
    assert result.probable_title == "FREEFALL"
    assert result.evidence["conflict_reasons"] == []


def test_title_artist_prefix_hyphen_resolves_seed_artist_and_title():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Static-X - Push It",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Static-X"
    assert result.probable_title == "Push It"


def test_parsed_static_x_filename_resolves_seed_artist_and_title():
    observation = parse_filename("Static-X - Push It [ubimQkYukxc].flac")

    result = resolve_identity(
        filename_artist=observation.possible_artist,
        filename_title=observation.possible_title,
    )

    assert result.probable_artist == "Static-X"
    assert result.probable_title == "Push It"


def test_title_artist_prefix_colon_resolves_seed_artist_and_title():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Static-X: Push It",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Static-X"
    assert result.probable_title == "Push It"


def test_title_artist_prefix_full_width_colon_resolves_seed_artist_and_title():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Static-X： Sweat of the Bud",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Static-X"
    assert result.probable_title == "Sweat of the Bud"


def test_static_x_title_removes_warner_vault_suffix():
    result = resolve_identity(
        tag_artist="Warner Records Vault",
        filename_title="Static-X - I'm With Stupid | Warner Vault",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Static-X"
    assert result.probable_title == "I'm With Stupid"


def test_title_artist_suffix_hyphen_resolves_seed_artist_and_title():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="3 Libras - A Perfect Circle",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "A Perfect Circle"
    assert result.probable_title == "3 Libras"


def test_title_artist_suffix_removes_explicit_marker():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Last Resort (explicit) - Papa Roach",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Papa Roach"
    assert result.probable_title == "Last Resort"


def test_collaboration_prefix_uses_first_seed_artist_as_primary():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Loathe & Teenage Wrist - Is It Really You",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Loathe"
    assert result.probable_title == "Is It Really You"


def test_x_collaboration_prefix_uses_first_seed_artist_as_primary():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="BAD OMENS x ERRA - ANYTHING ＞ HUMAN",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Bad Omens"
    assert result.probable_title == "ANYTHING > HUMAN"


def test_feature_prefix_uses_main_seed_artist_as_primary():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title=(
            "From Ashes To New ft. Chrissy from Against The Current "
            "- Barely Breathing"
        ),
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "From Ashes to New"
    assert result.probable_title == "Barely Breathing"


def test_nothing_more_feature_prefix_uses_main_seed_artist_as_primary():
    result = resolve_identity(
        tag_artist="Better Noise Music",
        filename_title="NOTHING MORE ft Chris Daughtry - FREEFALL",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Nothing More"
    assert result.probable_title == "FREEFALL"


def test_label_source_prefix_with_seed_title_resolves_artist_and_title():
    result = resolve_identity(
        tag_artist="Warner Records Vault",
        filename_title="Warner Records Vault / Static-X - Push It",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Static-X"
    assert result.probable_title == "Push It"


def test_label_source_prefix_with_collaboration_uses_first_seed_artist():
    result = resolve_identity(
        tag_artist="SharpTone Records",
        filename_title="SharpTone Records / Loathe & Teenage Wrist - Is It Really You",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Loathe"
    assert result.probable_title == "Is It Really You"


def test_better_noise_title_feature_prefix_resolves_seed_artist():
    result = resolve_identity(
        tag_artist="Better Noise Music",
        filename_title=(
            "Better Noise Music / From Ashes To New ft. Chrissy from Against "
            "The Current - Barely Breathing"
        ),
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "From Ashes to New"
    assert result.probable_title == "Barely Breathing"


def test_seed_artist_prefix_en_dash_resolves_canonical_artist_case():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Fit For A King – Slave To Nothing",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Fit for a King"
    assert result.probable_title == "Slave To Nothing"


def test_whitespace_only_seed_artist_prefix_resolves_title():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Spiritbox   Holy Roller",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Spiritbox"
    assert result.probable_title == "Holy Roller"


def test_seed_artist_prefix_en_dash_beartooth_resolves_title():
    result = resolve_identity(
        tag_artist="Uploader Channel",
        filename_title="Beartooth – The Lines",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Beartooth"
    assert result.probable_title == "The Lines"


def test_non_seed_phrase_does_not_resolve_red_seed_artist():
    result = resolve_identity(filename_title="girl in red")

    assert result.probable_artist is None
    assert result.probable_title == "girl in red"
    assert result.identity_status == "partial"


def test_different_seed_tag_artist_and_title_primary_still_conflicts():
    result = resolve_identity(
        tag_artist="Deftones",
        filename_title="Korn - Freak on a Leash",
    )

    assert result.identity_status == "conflicting"
    assert result.probable_artist == "Deftones"
    assert "tag_artist_conflicts_with_title_artist" in result.evidence[
        "conflict_reasons"
    ]


def test_parent_folder_seed_artist_supports_identification():
    result = resolve_identity(
        tag_artist="Some Upload Channel",
        tag_title="Official Video",
        filename_title="All Around Me",
        parent_folder="Incoming/Flyleaf",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Flyleaf"
    assert result.probable_title == "All Around Me"
    assert result.evidence["selected_artist_source"] == "parent_folder"
    assert result.evidence["conflict_reasons"] == []


def test_fit_for_a_king_parent_folder_supports_title_only_filename():
    result = resolve_identity(
        filename_title="Slave to Nothing",
        parent_folder="Incoming/Fit For a King",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Fit for a King"
    assert result.probable_title == "Slave to Nothing"
    assert result.evidence["selected_artist_source"] == "parent_folder"


def test_crossfade_music_tv_parent_folder_alias_supports_title_only_filename():
    result = resolve_identity(
        filename_title="Already Gone",
        parent_folder="Incoming/CrossfadeMusicTV",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Crossfade"
    assert result.probable_title == "Already Gone"
    assert result.evidence["selected_artist_source"] == "parent_folder"


def test_non_seed_uploader_tag_cannot_create_conflict_with_filename_seed_artist():
    result = resolve_identity(
        tag_artist="Roadrunner Records",
        tag_title="Official Audio",
        filename_artist="Deftones",
        filename_title="Deftones — Tempest [-1mH96_bVM0]",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Deftones"
    assert result.probable_title == "Tempest"
    assert result.evidence["conflict_reasons"] == []


def test_numbered_chapter_filename_title_beats_youtube_tag_title_noise():
    observation = parse_filename("01 - Papercut.mp3")

    result = resolve_identity(
        tag_artist="Warner Records Vault",
        tag_title="Linkin Park - Papercut [Official Music Video]",
        filename_artist=observation.possible_artist,
        filename_title=observation.possible_title,
        filename_track_number=observation.possible_track_number,
        parent_folder="Hybrid Theory",
    )

    assert result.identity_status == "identified"
    assert result.probable_artist == "Linkin Park"
    assert result.probable_title == "Papercut"
    assert result.probable_album == "Hybrid Theory"
    assert result.evidence["selected_title_source"] == "filename"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["conflict_reasons"] == []


def test_numbered_chapter_uploader_artist_does_not_override_filename_title():
    observation = parse_filename("02 - Forgotten.mp3")

    result = resolve_identity(
        tag_artist="Better Noise Music",
        tag_title="Official Music Video",
        filename_artist=observation.possible_artist,
        filename_title=observation.possible_title,
        filename_track_number=observation.possible_track_number,
        parent_folder="Hybrid Theory",
    )

    assert result.identity_status == "partial"
    assert result.probable_artist is None
    assert result.probable_title == "Forgotten"
    assert result.probable_album == "Hybrid Theory"
    assert result.evidence["selected_artist_source"] is None
    assert result.evidence["selected_title_source"] == "filename"
    assert result.evidence["tag_artist_deprioritized"] is True
    assert result.evidence["conflict_reasons"] == []


def test_numbered_chapter_album_folder_is_not_invented_as_artist():
    observation = parse_filename("03 Track Name.flac")

    result = resolve_identity(
        tag_artist="Better Noise Music",
        tag_title="Official Audio",
        filename_artist=observation.possible_artist,
        filename_title=observation.possible_title,
        filename_track_number=observation.possible_track_number,
        parent_folder="Hybrid Theory",
    )

    assert result.probable_artist is None
    assert result.probable_title == "Track Name"
    assert result.probable_album == "Hybrid Theory"
    assert result.identity_status == "partial"


def test_numbered_chapter_album_folder_strips_uploader_and_artist_prefix():
    observation = parse_filename("01 Track Name.flac")

    result = resolve_identity(
        tag_artist="Artist Name",
        tag_title="Track Name",
        filename_artist=observation.possible_artist,
        filename_title=observation.possible_title,
        filename_track_number=observation.possible_track_number,
        parent_folder="Uploader Channel/Artist Name - Album Name [Full Album]",
    )

    assert result.probable_artist == "Artist Name"
    assert result.probable_title == "Track Name"
    assert result.probable_album == "Album Name"
    assert "Uploader Channel" not in result.probable_album


def test_numbered_chapter_album_folder_does_not_invent_artist():
    observation = parse_filename("01 Track Name.flac")

    result = resolve_identity(
        filename_artist=observation.possible_artist,
        filename_title=observation.possible_title,
        filename_track_number=observation.possible_track_number,
        parent_folder="Uploader/Album Name",
    )

    assert result.probable_artist is None
    assert result.probable_title == "Track Name"
    assert result.probable_album == "Album Name"
    assert result.identity_status == "partial"


def test_parent_folder_treated_as_weak_evidence():
    result = resolve_identity(parent_folder="Deftones")

    assert result.probable_artist == "Deftones"
    assert result.probable_title is None
    assert result.identity_status == "partial"
    assert result.identity_confidence == 0.60
    assert result.evidence["selected_artist_source"] == "parent_folder"


def test_partial_artist_only():
    result = resolve_identity(tag_artist="Deftones")

    assert result.probable_artist == "Deftones"
    assert result.probable_title is None
    assert result.identity_status == "partial"
    assert result.identity_confidence == 0.60


def test_partial_title_only():
    result = resolve_identity(filename_title="Change")

    assert result.probable_artist is None
    assert result.probable_title == "Change"
    assert result.identity_status == "partial"
    assert result.identity_confidence == 0.60


def test_unknown_identity():
    result = resolve_identity()

    assert result.probable_artist is None
    assert result.probable_title is None
    assert result.identity_status == "unknown"
    assert result.identity_confidence == 0.10


def test_deterministic_confidence_scoring():
    assert (
        calculate_identity_confidence(
            identity_status="identified",
            selected_artist_source="tag",
            selected_title_source="tag",
            tag_artist="Deftones",
            tag_title="Change",
        )
        == 0.95
    )
    assert (
        calculate_identity_confidence(
            identity_status="identified",
            selected_artist_source="filename",
            selected_title_source="filename",
            filename_artist="Deftones",
            filename_title="Change",
            artist_seed_matched="Deftones",
        )
        == 0.85
    )
    assert calculate_identity_confidence(identity_status="partial") == 0.60
    assert calculate_identity_confidence(identity_status="conflicting") == 0.40
    assert calculate_identity_confidence(identity_status="unknown") == 0.10


def test_evidence_json_contains_required_fields():
    evidence = build_identity_evidence(
        selected_artist_source="filename",
        selected_title_source="filename",
        tag_artist=None,
        tag_title=None,
        filename_artist="Deftones",
        filename_title="Change",
        parent_folder="Deftones",
        artist_seed_matched="Deftones",
        conflict_reasons=[],
    )

    assert set(REQUIRED_EVIDENCE_FIELDS).issubset(evidence)
    assert json.loads(json.dumps(evidence)) == evidence


def test_cli_writes_identity_rows(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    db.init_db(db_path)

    scan_run_id = _insert_observed_track(
        db_path,
        tag_artist=None,
        tag_title=None,
        filename_artist="Deftones",
        filename_title="Change",
        parent_folder="Albums/Deftones",
    )

    exit_code = main(
        [
            "--db",
            str(db_path),
            "identify",
            "--scan-run-id",
            str(scan_run_id),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "total=1" in output
    assert "identified=1" in output

    rows = _fetch_all(db_path, "SELECT * FROM track_identity")
    assert len(rows) == 1
    assert rows[0]["probable_artist"] == "Deftones"
    assert rows[0]["probable_title"] == "Change"
    assert rows[0]["identity_status"] == "identified"
    assert rows[0]["identity_confidence"] == 0.85
    evidence = json.loads(rows[0]["evidence_json"])
    assert set(REQUIRED_EVIDENCE_FIELDS).issubset(evidence)


def _insert_observed_track(
    db_path,
    *,
    tag_artist,
    tag_title,
    filename_artist,
    filename_title,
    parent_folder,
):
    connection = sqlite3.connect(db_path)
    try:
        scan_run_id = connection.execute(
            """
            INSERT INTO scan_runs (
                source_path,
                started_at,
                status,
                total_files_seen,
                audio_files_seen,
                files_failed
            )
            VALUES ('/music', '2026-05-10T00:00:00+00:00', 'completed', 1, 1, 0)
            """
        ).lastrowid
        observed_file_id = connection.execute(
            """
            INSERT INTO observed_files (
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
            VALUES (?, '/music', 'Albums/Deftones/Change.mp3', ?, 'Change.mp3',
                '.mp3', 10, 'abc', '2026-05-10T00:00:00+00:00')
            """,
            (scan_run_id, parent_folder),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO tag_observations (
                observed_file_id,
                title,
                artist,
                album,
                album_artist,
                genre,
                date,
                track_number,
                disc_number,
                composer,
                comment,
                tag_status
            )
            VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'ok')
            """,
            (observed_file_id, tag_title, tag_artist),
        )
        connection.execute(
            """
            INSERT INTO filename_observations (
                observed_file_id,
                cleaned_filename,
                possible_artist,
                possible_title,
                possible_mix,
                possible_track_number,
                filename_pattern,
                parser_confidence
            )
            VALUES (?, 'Deftones - Change', ?, ?, NULL, NULL, 'artist_title', 0.8)
            """,
            (observed_file_id, filename_artist, filename_title),
        )
        connection.commit()
        return scan_run_id
    finally:
        connection.close()


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
