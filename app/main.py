"""Command line interface for the music-library normalization system."""

from __future__ import annotations

import argparse
from pathlib import Path

from app import db
from app.scanner import scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main",
        description="Music-library normalization observation ledger.",
    )
    parser.add_argument(
        "--db",
        default=str(db.DEFAULT_DB_PATH),
        help="SQLite database path. Defaults to music_library.sqlite3.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create the SQLite ledger schema.")

    scan_parser = subparsers.add_parser(
        "scan", help="Observe a local music folder without modifying source files."
    )
    scan_parser.add_argument("--source", required=True, help="Music folder to scan.")

    summary_parser = subparsers.add_parser(
        "summary", help="Print scan-run summary counts."
    )
    summary_parser.add_argument("--scan-run-id", required=True, type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)

    if args.command == "init-db":
        db.init_db(db_path)
        print(f"Initialized database: {db_path}")
        return 0

    if args.command == "scan":
        result = scan(args.source, db_path)
        print(f"scan_run_id={result.scan_run_id}")
        print(f"status={result.status}")
        print(f"total_files_seen={result.total_files_seen}")
        print(f"audio_files_seen={result.audio_files_seen}")
        print(f"files_failed={result.files_failed}")
        return 0

    if args.command == "summary":
        summary = db.get_scan_summary(args.scan_run_id, db_path)
        if summary is None:
            parser.error(f"scan run not found: {args.scan_run_id}")
        for key in summary.keys():
            print(f"{key}={summary[key]}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
