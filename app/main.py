"""Command line interface for the music-library normalization system."""

from __future__ import annotations

import argparse
from pathlib import Path

from app import db
from app.classifier import classify_scan_run
from app.identity_engine import identify_scan_run
from app.purchase_gateway import (
    add_purchase_option,
    attach_purchase_proof,
    build_purchase_report,
    create_purchase_request,
    unlock_intake,
)
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

    identify_parser = subparsers.add_parser(
        "identify", help="Resolve probable track identity for a scan run."
    )
    identify_parser.add_argument("--scan-run-id", required=True, type=int)

    classify_parser = subparsers.add_parser(
        "classify", help="Classify identified tracks for a scan run."
    )
    classify_parser.add_argument("--scan-run-id", required=True, type=int)

    purchase_request_parser = subparsers.add_parser(
        "purchase-request", help="Create a purchase request for a baseline artist."
    )
    purchase_request_parser.add_argument("--artist", required=True)
    purchase_request_parser.add_argument("--title", required=True)
    purchase_request_parser.add_argument("--album")

    option_parser = subparsers.add_parser(
        "purchase-option-add", help="Add a manual external purchase option URL."
    )
    option_parser.add_argument("--request-id", required=True, type=int)
    option_parser.add_argument("--provider", required=True)
    option_parser.add_argument("--url", required=True)
    option_parser.add_argument("--type", required=True)
    option_parser.add_argument("--price", type=float)
    option_parser.add_argument("--currency")
    option_parser.add_argument("--format-notes")
    option_parser.add_argument("--scope")

    proof_parser = subparsers.add_parser(
        "purchase-proof-add", help="Attach user-supplied purchase proof metadata."
    )
    proof_parser.add_argument("--option-id", required=True, type=int)
    proof_parser.add_argument("--proof", required=True)
    proof_parser.add_argument("--status", required=True)
    proof_parser.add_argument("--type", default="receipt")
    proof_parser.add_argument("--notes")

    unlock_parser = subparsers.add_parser(
        "purchase-unlock", help="Unlock intake after acceptable purchase proof."
    )
    unlock_parser.add_argument("--request-id", required=True, type=int)

    subparsers.add_parser(
        "purchase-report", help="Print purchase request counts grouped by status."
    )

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

    if args.command == "identify":
        summary = identify_scan_run(args.scan_run_id, db_path)
        print(f"total={summary.total}")
        print(f"identified={summary.identified}")
        print(f"partial={summary.partial}")
        print(f"conflicting={summary.conflicting}")
        print(f"unknown={summary.unknown}")
        return 0

    if args.command == "classify":
        summary = classify_scan_run(args.scan_run_id, db_path)
        print(f"total={summary.total}")
        print(f"classified={summary.classified}")
        print(f"inferred={summary.inferred}")
        print(f"uncertain={summary.uncertain}")
        print(f"unknown={summary.unknown}")
        return 0

    if args.command == "purchase-request":
        request = create_purchase_request(
            artist=args.artist,
            title=args.title,
            album=args.album,
            db_path=db_path,
        )
        print(f"request_id={request.id}")
        print(f"artist={request.artist}")
        print(f"title={request.title}")
        print(f"request_status={request.request_status}")
        return 0

    if args.command == "purchase-option-add":
        option = add_purchase_option(
            request_id=args.request_id,
            provider_name=args.provider,
            provider_url=args.url,
            purchase_type=args.type,
            price=args.price,
            currency=args.currency,
            format_notes=args.format_notes,
            usage_scope=args.scope,
            db_path=db_path,
        )
        print(f"option_id={option.id}")
        print(f"request_id={option.purchase_request_id}")
        print(f"provider_name={option.provider_name}")
        print(f"option_status={option.option_status}")
        return 0

    if args.command == "purchase-proof-add":
        proof = attach_purchase_proof(
            option_id=args.option_id,
            proof_path=args.proof,
            proof_status=args.status,
            proof_type=args.type,
            notes=args.notes,
            db_path=db_path,
        )
        print(f"proof_id={proof.id}")
        print(f"option_id={proof.purchase_option_id}")
        print(f"proof_status={proof.proof_status}")
        return 0

    if args.command == "purchase-unlock":
        unlock = unlock_intake(args.request_id, db_path)
        print(f"unlock_id={unlock.id}")
        print(f"request_id={unlock.purchase_request_id}")
        print(f"proof_id={unlock.proof_id}")
        print(f"unlock_status={unlock.unlock_status}")
        return 0

    if args.command == "purchase-report":
        report = build_purchase_report(db_path)
        print(f"total={report['total']}")
        for status, count in report["by_status"].items():
            print(f"{status}={count}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
