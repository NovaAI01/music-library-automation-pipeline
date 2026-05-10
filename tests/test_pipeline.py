import sqlite3

from app import db
from app.main import main
from app.pipeline import (
    create_pipeline_run,
    get_intake_batch,
    run_intake_pipeline,
    should_block_duplicate_pipeline,
    update_pipeline_stage_status,
)


def test_invalid_intake_batch_blocks_pipeline(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"

    result = run_intake_pipeline(999, db_path=db_path)

    assert result.pipeline_status == "blocked"
    assert result.error_message == "invalid_intake_batch"
    assert result.scan_run_id is None


def test_valid_intake_batch_creates_scan_run(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    (intake_root / "Deftones - Change.mp3").write_bytes(b"audio")
    batch_id = _insert_intake_batch(db_path, intake_root)
    monkeypatch.setattr("app.scanner.probe_audio", _failed_probe)

    result = run_intake_pipeline(batch_id, db_path=db_path)

    assert result.scan_run_id is not None
    assert result.scan_status == "completed"
    assert _count_rows(db_path, "scan_runs") == 1


def test_pipeline_calls_scan_before_identify(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)
    calls = []

    def fake_scan(source, db_path):
        calls.append("scan")
        return _Stage(scan_run_id=10, status="completed")

    def fake_identify(scan_run_id, db_path):
        calls.append("identify")

    def fake_classify(scan_run_id, db_path):
        calls.append("classify")

    monkeypatch.setattr("app.pipeline.scan", fake_scan)
    monkeypatch.setattr("app.pipeline.identify_scan_run", fake_identify)
    monkeypatch.setattr("app.pipeline.classify_scan_run", fake_classify)

    run_intake_pipeline(batch_id, db_path=db_path)

    assert calls == ["scan", "identify", "classify"]


def test_classification_does_not_run_if_identity_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)
    calls = []

    def fake_scan(source, db_path):
        calls.append("scan")
        return _Stage(scan_run_id=10, status="completed")

    def fake_identify(scan_run_id, db_path):
        calls.append("identify")
        raise RuntimeError("identity failed")

    def fake_classify(scan_run_id, db_path):
        calls.append("classify")

    monkeypatch.setattr("app.pipeline.scan", fake_scan)
    monkeypatch.setattr("app.pipeline.identify_scan_run", fake_identify)
    monkeypatch.setattr("app.pipeline.classify_scan_run", fake_classify)

    result = run_intake_pipeline(batch_id, db_path=db_path)

    assert calls == ["scan", "identify"]
    assert result.pipeline_status == "failed"
    assert result.identity_status == "failed"
    assert result.classification_status is None


def test_duplicate_pipeline_blocked_without_rerun(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)
    run_id = create_pipeline_run(batch_id, db_path=db_path)
    update_pipeline_stage_status(
        run_id,
        pipeline_status="completed",
        completed=True,
        db_path=db_path,
    )

    assert should_block_duplicate_pipeline(batch_id, db_path=db_path)
    result = run_intake_pipeline(batch_id, db_path=db_path)

    assert result.pipeline_status == "blocked"
    assert result.error_message == "duplicate_pipeline_run"


def test_rerun_allows_new_pipeline_run(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)
    run_id = create_pipeline_run(batch_id, db_path=db_path)
    update_pipeline_stage_status(
        run_id,
        pipeline_status="completed",
        completed=True,
        db_path=db_path,
    )
    monkeypatch.setattr(
        "app.pipeline.scan", lambda source, db_path: _Stage(2, "completed")
    )
    monkeypatch.setattr("app.pipeline.identify_scan_run", lambda scan_run_id, db_path: None)
    monkeypatch.setattr("app.pipeline.classify_scan_run", lambda scan_run_id, db_path: None)

    result = run_intake_pipeline(batch_id, rerun=True, db_path=db_path)

    assert result.pipeline_status == "completed"
    assert result.pipeline_run_id != run_id


def test_pipeline_status_completed_when_all_stages_succeed(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)
    monkeypatch.setattr(
        "app.pipeline.scan", lambda source, db_path: _Stage(1, "completed")
    )
    monkeypatch.setattr("app.pipeline.identify_scan_run", lambda scan_run_id, db_path: None)
    monkeypatch.setattr("app.pipeline.classify_scan_run", lambda scan_run_id, db_path: None)

    result = run_intake_pipeline(batch_id, db_path=db_path)

    assert result.pipeline_status == "completed"
    assert result.scan_status == "completed"
    assert result.identity_status == "completed"
    assert result.classification_status == "completed"


def test_pipeline_status_failed_if_scan_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)
    monkeypatch.setattr(
        "app.pipeline.scan",
        lambda source, db_path: (_ for _ in ()).throw(RuntimeError("scan failed")),
    )

    result = run_intake_pipeline(batch_id, db_path=db_path)

    assert result.pipeline_status == "failed"
    assert result.scan_status == "failed"
    assert result.identity_status is None
    assert result.classification_status is None


def test_cli_pipeline_run_prints_expected_summary(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)
    monkeypatch.setattr(
        "app.pipeline.scan", lambda source, db_path: _Stage(1, "completed")
    )
    monkeypatch.setattr("app.pipeline.identify_scan_run", lambda scan_run_id, db_path: None)
    monkeypatch.setattr("app.pipeline.classify_scan_run", lambda scan_run_id, db_path: None)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "pipeline-run",
            "--intake-batch-id",
            str(batch_id),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "pipeline_run_id=1" in output
    assert f"intake_batch_id={batch_id}" in output
    assert "scan_run_id=1" in output
    assert "scan_status=completed" in output
    assert "identity_status=completed" in output
    assert "classification_status=completed" in output
    assert "pipeline_status=completed" in output


def test_get_intake_batch_returns_batch(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    intake_root = tmp_path / "intake"
    intake_root.mkdir()
    batch_id = _insert_intake_batch(db_path, intake_root)

    batch = get_intake_batch(batch_id, db_path)

    assert batch.id == batch_id
    assert batch.intake_root == str(intake_root)


class _Stage:
    def __init__(self, scan_run_id, status):
        self.scan_run_id = scan_run_id
        self.status = status


def _failed_probe(path):
    from app.audio_probe import AudioProbeResult

    return AudioProbeResult(
        duration_seconds=None,
        sample_rate=None,
        channels=None,
        bitrate=None,
        codec=None,
        container=None,
        probe_status="failed",
        probe_error="not audio",
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


def _insert_intake_batch(db_path, intake_root):
    db.init_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        request_id = connection.execute(
            """
            INSERT INTO purchase_requests (
                artist,
                title,
                album,
                request_status,
                created_at
            )
            VALUES ('Deftones', 'Change', NULL, 'intake_unlocked',
                '2026-05-10T00:00:00+00:00')
            """
        ).lastrowid
        batch_id = connection.execute(
            """
            INSERT INTO intake_batches (
                purchase_request_id,
                source_path,
                intake_root,
                batch_status,
                total_files_seen,
                audio_files_copied,
                skipped_files,
                duplicate_files,
                created_at
            )
            VALUES (?, ?, ?, 'completed', 1, 1, 0, 0,
                '2026-05-10T00:00:00+00:00')
            """,
            (request_id, str(intake_root), str(intake_root)),
        ).lastrowid
        connection.commit()
        return batch_id
    finally:
        connection.close()


def _count_rows(db_path, table):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()
