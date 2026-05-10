import sqlite3

from app.audio_probe import AudioProbeResult
from app.scanner import is_supported_audio_file, scan, sha256_file


def test_scanner_ignores_hidden_files_and_folders(tmp_path, monkeypatch):
    visible = tmp_path / "visible.mp3"
    hidden_file = tmp_path / ".hidden.mp3"
    hidden_folder = tmp_path / ".secret"
    hidden_folder.mkdir()
    hidden_nested = hidden_folder / "nested.mp3"

    visible.write_bytes(b"visible")
    hidden_file.write_bytes(b"hidden")
    hidden_nested.write_bytes(b"nested")
    db_path = tmp_path / "ledger.sqlite3"

    monkeypatch.setattr("app.scanner.probe_audio", _ok_probe)

    result = scan(tmp_path, db_path)

    assert result.total_files_seen == 1
    assert result.audio_files_seen == 1

    rows = _fetch_all(db_path, "SELECT filename FROM observed_files")
    assert [row["filename"] for row in rows] == ["visible.mp3"]


def test_scanner_detects_supported_audio_extensions():
    assert is_supported_audio_file("song.mp3")
    assert is_supported_audio_file("song.WAV")
    assert is_supported_audio_file("song.flac")
    assert is_supported_audio_file("song.m4a")
    assert is_supported_audio_file("song.aac")
    assert is_supported_audio_file("song.ogg")
    assert is_supported_audio_file("song.aiff")
    assert is_supported_audio_file("song.webm")
    assert not is_supported_audio_file("cover.jpg")


def test_sha256_is_stable(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"same bytes")

    assert sha256_file(path) == sha256_file(path)
    assert sha256_file(path) == (
        "58100dc8fc06562ce3e578231dc948e083520ee49c4b4ee5"
        "a5a28bb4b4003feb"
    )


def test_broken_ffprobe_result_does_not_crash_scan(tmp_path, monkeypatch):
    path = tmp_path / "Deftones - Change.mp3"
    path.write_bytes(b"not audio")
    db_path = tmp_path / "ledger.sqlite3"

    monkeypatch.setattr("app.scanner.probe_audio", _failed_probe)

    result = scan(tmp_path, db_path)

    assert result.status == "completed"
    assert result.audio_files_seen == 1
    assert result.files_failed == 1

    audio_rows = _fetch_all(
        db_path,
        "SELECT probe_status, probe_error FROM audio_observations",
    )
    assert audio_rows[0]["probe_status"] == "failed"
    assert audio_rows[0]["probe_error"] == "bad probe"

    filename_rows = _fetch_all(
        db_path,
        """
        SELECT possible_artist, possible_title, filename_pattern
        FROM filename_observations
        """,
    )
    assert filename_rows[0]["possible_artist"] == "Deftones"
    assert filename_rows[0]["possible_title"] == "Change"
    assert filename_rows[0]["filename_pattern"] == "artist_title"


def _ok_probe(path):
    return AudioProbeResult(
        duration_seconds=123.4,
        sample_rate=44100,
        channels=2,
        bitrate=320000,
        codec="mp3",
        container="mp3",
        probe_status="ok",
        probe_error=None,
        tags={
            "title": "Visible",
            "artist": "Deftones",
            "album": None,
            "album_artist": None,
            "genre": None,
            "date": None,
            "track_number": None,
            "disc_number": None,
            "composer": None,
            "comment": None,
        },
        tag_status="ok",
    )


def _failed_probe(path):
    return AudioProbeResult(
        duration_seconds=None,
        sample_rate=None,
        channels=None,
        bitrate=None,
        codec=None,
        container=None,
        probe_status="failed",
        probe_error="bad probe",
        tags={
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "genre": None,
            "date": None,
            "track_number": None,
            "disc_number": None,
            "composer": None,
            "comment": None,
        },
        tag_status="unavailable",
    )


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
