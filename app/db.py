"""SQLite storage for the observation ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("music_library.sqlite3")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    total_files_seen INTEGER NOT NULL DEFAULT 0,
    audio_files_seen INTEGER NOT NULL DEFAULT 0,
    files_failed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS observed_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    parent_folder TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (scan_run_id) REFERENCES scan_runs(id)
);

CREATE TABLE IF NOT EXISTS audio_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_file_id INTEGER NOT NULL,
    duration_seconds REAL,
    sample_rate INTEGER,
    channels INTEGER,
    bitrate INTEGER,
    codec TEXT,
    container TEXT,
    probe_status TEXT NOT NULL,
    probe_error TEXT,
    FOREIGN KEY (observed_file_id) REFERENCES observed_files(id)
);

CREATE TABLE IF NOT EXISTS tag_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_file_id INTEGER NOT NULL,
    title TEXT,
    artist TEXT,
    album TEXT,
    album_artist TEXT,
    genre TEXT,
    date TEXT,
    track_number TEXT,
    disc_number TEXT,
    composer TEXT,
    comment TEXT,
    tag_status TEXT NOT NULL,
    FOREIGN KEY (observed_file_id) REFERENCES observed_files(id)
);

CREATE TABLE IF NOT EXISTS filename_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_file_id INTEGER NOT NULL,
    cleaned_filename TEXT NOT NULL,
    possible_artist TEXT,
    possible_title TEXT,
    possible_mix TEXT,
    possible_track_number TEXT,
    filename_pattern TEXT NOT NULL,
    parser_confidence REAL NOT NULL,
    FOREIGN KEY (observed_file_id) REFERENCES observed_files(id)
);

CREATE TABLE IF NOT EXISTS track_identity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_file_id INTEGER NOT NULL,
    probable_artist TEXT,
    probable_title TEXT,
    probable_album TEXT,
    probable_year TEXT,
    probable_mix TEXT,
    identity_confidence REAL NOT NULL,
    identity_status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (observed_file_id) REFERENCES observed_files(id)
);

CREATE TABLE IF NOT EXISTS classification_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_file_id INTEGER NOT NULL,
    primary_genre TEXT,
    subgenre TEXT,
    energy_level TEXT,
    vocal_style TEXT,
    mood_json TEXT NOT NULL,
    classification_confidence REAL NOT NULL,
    classification_status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (observed_file_id) REFERENCES observed_files(id)
);

CREATE TABLE IF NOT EXISTS purchase_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    request_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_request_id INTEGER NOT NULL,
    provider_name TEXT NOT NULL,
    provider_url TEXT NOT NULL,
    purchase_type TEXT NOT NULL,
    price REAL,
    currency TEXT,
    format_notes TEXT,
    usage_scope TEXT,
    option_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (purchase_request_id) REFERENCES purchase_requests(id)
);

CREATE TABLE IF NOT EXISTS purchase_proofs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_option_id INTEGER NOT NULL,
    proof_path TEXT NOT NULL,
    proof_type TEXT NOT NULL,
    proof_status TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (purchase_option_id) REFERENCES purchase_options(id)
);

CREATE TABLE IF NOT EXISTS intake_unlocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_request_id INTEGER NOT NULL,
    proof_id INTEGER NOT NULL,
    unlock_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (purchase_request_id),
    FOREIGN KEY (purchase_request_id) REFERENCES purchase_requests(id),
    FOREIGN KEY (proof_id) REFERENCES purchase_proofs(id)
);

CREATE TABLE IF NOT EXISTS intake_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_request_id INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    intake_root TEXT NOT NULL,
    batch_status TEXT NOT NULL,
    total_files_seen INTEGER NOT NULL,
    audio_files_copied INTEGER NOT NULL,
    skipped_files INTEGER NOT NULL,
    duplicate_files INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (purchase_request_id) REFERENCES purchase_requests(id)
);

CREATE TABLE IF NOT EXISTS intake_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_batch_id INTEGER NOT NULL,
    original_path TEXT NOT NULL,
    intake_path TEXT,
    sha256 TEXT,
    extension TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    file_status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (intake_batch_id) REFERENCES intake_batches(id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_batch_id INTEGER NOT NULL,
    scan_run_id INTEGER,
    pipeline_status TEXT NOT NULL,
    scan_status TEXT,
    identity_status TEXT,
    classification_status TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with row access and foreign keys enabled."""

    connection = sqlite3.connect(Path(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Create the observation ledger schema when it does not already exist."""

    with connect(db_path) as connection:
        connection.executescript(SCHEMA)


def get_scan_summary(
    scan_run_id: int, db_path: str | Path = DEFAULT_DB_PATH
) -> sqlite3.Row | None:
    """Return aggregate counts for one scan run."""

    with connect(db_path) as connection:
        return connection.execute(
            """
            SELECT
                scan_runs.id,
                scan_runs.source_path,
                scan_runs.started_at,
                scan_runs.completed_at,
                scan_runs.status,
                scan_runs.total_files_seen,
                scan_runs.audio_files_seen,
                scan_runs.files_failed,
                COUNT(observed_files.id) AS observed_files,
                COUNT(audio_observations.id) AS audio_observations,
                COUNT(tag_observations.id) AS tag_observations,
                COUNT(filename_observations.id) AS filename_observations
            FROM scan_runs
            LEFT JOIN observed_files
                ON observed_files.scan_run_id = scan_runs.id
            LEFT JOIN audio_observations
                ON audio_observations.observed_file_id = observed_files.id
            LEFT JOIN tag_observations
                ON tag_observations.observed_file_id = observed_files.id
            LEFT JOIN filename_observations
                ON filename_observations.observed_file_id = observed_files.id
            WHERE scan_runs.id = ?
            GROUP BY scan_runs.id
            """,
            (scan_run_id,),
        ).fetchone()
