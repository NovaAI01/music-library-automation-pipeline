import sqlite3

from app import db
from app.intake import (
    build_intake_destination,
    calculate_sha256,
    intake_requires_unlock,
    is_supported_audio_file,
    run_intake,
    unique_destination_path,
)
from app.main import main
from app.purchase_gateway import (
    add_purchase_option,
    attach_purchase_proof,
    create_purchase_request,
    unlock_intake,
)


def test_intake_blocked_without_unlock(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    (source / "song.mp3").write_bytes(b"audio")
    request = create_purchase_request(
        artist="Deftones",
        title="Change",
        db_path=db_path,
    )

    result = run_intake(
        purchase_request_id=request.id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert intake_requires_unlock(request.id, db_path)
    assert result.batch_status == "blocked"
    assert result.total_files_seen == 0
    assert not dest.exists()
    assert _fetch_all(db_path, "SELECT batch_status FROM intake_batches")[0][
        "batch_status"
    ] == "blocked"


def test_intake_allowed_with_unlock(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    (source / "song.mp3").write_bytes(b"audio")
    request_id = _unlocked_request(db_path)

    result = run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert not intake_requires_unlock(request_id, db_path)
    assert result.batch_status == "completed"
    assert result.audio_files_copied == 1


def test_supported_audio_file_copied(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    original = source / "song.FLAC"
    original.write_bytes(b"audio")
    request_id = _unlocked_request(db_path)

    result = run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert is_supported_audio_file(original)
    assert result.audio_files_copied == 1
    copied = dest / "song.FLAC"
    assert copied.read_bytes() == b"audio"
    rows = _fetch_all(db_path, "SELECT file_status, intake_path FROM intake_files")
    assert rows[0]["file_status"] == "copied"
    assert rows[0]["intake_path"] == str(copied)


def test_unsupported_file_skipped(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    (source / "cover.jpg").write_bytes(b"image")
    request_id = _unlocked_request(db_path)

    result = run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert result.total_files_seen == 1
    assert result.skipped_files == 1
    assert not (dest / "cover.jpg").exists()
    row = _fetch_all(db_path, "SELECT file_status, reason FROM intake_files")[0]
    assert row["file_status"] == "skipped_unsupported"
    assert row["reason"] == "unsupported_extension"


def test_source_file_never_modified(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    original = source / "song.mp3"
    original.write_bytes(b"audio")
    before_hash = calculate_sha256(original)
    before_mtime = original.stat().st_mtime_ns
    request_id = _unlocked_request(db_path)

    run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert original.exists()
    assert calculate_sha256(original) == before_hash
    assert original.stat().st_mtime_ns == before_mtime


def test_relative_folder_structure_preserved(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    nested = source / "Album" / "Disc 1"
    nested.mkdir(parents=True)
    original = nested / "song.mp3"
    original.write_bytes(b"audio")
    request_id = _unlocked_request(db_path)

    assert build_intake_destination(original, source, dest) == (
        dest / "Album" / "Disc 1" / "song.mp3"
    )

    run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert (dest / "Album" / "Disc 1" / "song.mp3").exists()


def test_duplicate_sha256_detected(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    (source / "one.mp3").write_bytes(b"same")
    (source / "two.mp3").write_bytes(b"same")
    request_id = _unlocked_request(db_path)

    result = run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert result.audio_files_copied == 1
    assert result.duplicate_files == 1
    statuses = [row["file_status"] for row in _fetch_all(db_path, "SELECT file_status FROM intake_files ORDER BY id")]
    assert statuses == ["copied", "duplicate"]


def test_destination_overwrite_prevented(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    dest.mkdir()
    (source / "song.mp3").write_bytes(b"new audio")
    existing = dest / "song.mp3"
    existing.write_bytes(b"existing")
    request_id = _unlocked_request(db_path)

    assert unique_destination_path(existing) == dest / "song (1).mp3"

    run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert existing.read_bytes() == b"existing"
    assert (dest / "song (1).mp3").read_bytes() == b"new audio"


def test_intake_batch_counts_are_correct(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    (source / "one.mp3").write_bytes(b"one")
    (source / "two.wav").write_bytes(b"one")
    (source / "notes.txt").write_bytes(b"text")
    request_id = _unlocked_request(db_path)

    result = run_intake(
        purchase_request_id=request_id,
        source_path=source,
        intake_root=dest,
        db_path=db_path,
    )

    assert result.batch_status == "completed"
    assert result.total_files_seen == 3
    assert result.audio_files_copied == 1
    assert result.skipped_files == 1
    assert result.duplicate_files == 1


def test_cli_intake_creates_rows(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source"
    dest = tmp_path / "intake"
    source.mkdir()
    (source / "song.mp3").write_bytes(b"audio")
    request_id = _unlocked_request(db_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "intake",
            "--purchase-request-id",
            str(request_id),
            "--source",
            str(source),
            "--dest",
            str(dest),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "intake_batch_id=1" in output
    assert "batch_status=completed" in output
    assert "audio_files_copied=1" in output
    assert len(_fetch_all(db_path, "SELECT * FROM intake_batches")) == 1
    assert len(_fetch_all(db_path, "SELECT * FROM intake_files")) == 1


def _unlocked_request(db_path):
    request = create_purchase_request(
        artist="Deftones",
        title="Change",
        db_path=db_path,
    )
    option = add_purchase_option(
        request_id=request.id,
        provider_name="Bandcamp",
        provider_url="https://example.com/deftones-change",
        purchase_type="digital_download",
        db_path=db_path,
    )
    attach_purchase_proof(
        option_id=option.id,
        proof_path="/tmp/receipt.pdf",
        proof_status="verified",
        db_path=db_path,
    )
    unlock_intake(request.id, db_path)
    return request.id


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
