"""Command line interface for the music-library normalization system."""

from __future__ import annotations

import argparse
from pathlib import Path

from app import db
from app.classifier import classify_scan_run
from app.duplicate_report import generate_duplicate_report
from app.identity_engine import identify_scan_run
from app.intake import run_intake
from app.pipeline import run_intake_pipeline
from app.placement_executor import execute_placement
from app.placement_planner import plan_scan_run_placements
from app.purchase_gateway import (
    add_purchase_option,
    attach_purchase_proof,
    build_purchase_report,
    create_purchase_request,
    unlock_intake,
)
from app.review_report import generate_review_report
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

    intake_parser = subparsers.add_parser(
        "intake", help="Copy unlocked local files into the controlled intake area."
    )
    intake_parser.add_argument("--purchase-request-id", required=True, type=int)
    intake_parser.add_argument("--source", required=True)
    intake_parser.add_argument("--dest", required=True)

    pipeline_parser = subparsers.add_parser(
        "pipeline-run", help="Scan, identify, and classify an intake batch."
    )
    pipeline_parser.add_argument("--intake-batch-id", required=True, type=int)
    pipeline_parser.add_argument("--rerun", action="store_true")

    placement_parser = subparsers.add_parser(
        "plan-placement", help="Create deterministic placement plans for a scan run."
    )
    placement_parser.add_argument("--scan-run-id", required=True, type=int)

    execute_placement_parser = subparsers.add_parser(
        "execute-placement", help="Copy planned placement rows into an output root."
    )
    execute_placement_parser.add_argument("--scan-run-id", required=True, type=int)
    execute_placement_parser.add_argument("--dest", required=True)

    review_parser = subparsers.add_parser(
        "review-report", help="Export reviewable reports for placement plans."
    )
    review_parser.add_argument("--scan-run-id", required=True, type=int)
    review_parser.add_argument("--out", default="reports")

    duplicate_parser = subparsers.add_parser(
        "duplicate-report",
        help="Export read-only duplicate candidate reports for organised files.",
    )
    duplicate_parser.add_argument("--scan-run-id", required=True, type=int)
    duplicate_parser.add_argument("--library-root", required=True)
    duplicate_parser.add_argument("--out", default="reports")

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

    if args.command == "intake":
        result = run_intake(
            purchase_request_id=args.purchase_request_id,
            source_path=args.source,
            intake_root=args.dest,
            db_path=db_path,
        )
        print(f"intake_batch_id={result.intake_batch_id}")
        print(f"batch_status={result.batch_status}")
        print(f"total_files_seen={result.total_files_seen}")
        print(f"audio_files_copied={result.audio_files_copied}")
        print(f"skipped_files={result.skipped_files}")
        print(f"duplicate_files={result.duplicate_files}")
        return 0

    if args.command == "pipeline-run":
        result = run_intake_pipeline(
            args.intake_batch_id,
            rerun=args.rerun,
            db_path=db_path,
        )
        print(f"pipeline_run_id={result.pipeline_run_id}")
        print(f"intake_batch_id={result.intake_batch_id}")
        print(f"scan_run_id={result.scan_run_id}")
        print(f"scan_status={result.scan_status}")
        print(f"identity_status={result.identity_status}")
        print(f"classification_status={result.classification_status}")
        print(f"pipeline_status={result.pipeline_status}")
        return 0

    if args.command == "plan-placement":
        summary = plan_scan_run_placements(args.scan_run_id, db_path)
        print(f"total={summary.total}")
        print(f"planned={summary.planned}")
        print(f"needs_review={summary.needs_review}")
        print(f"blocked_unknown_identity={summary.blocked_unknown_identity}")
        print(
            "blocked_unknown_classification="
            f"{summary.blocked_unknown_classification}"
        )
        print(f"conflict={summary.conflict}")
        return 0

    if args.command == "execute-placement":
        result = execute_placement(
            scan_run_id=args.scan_run_id,
            output_root=args.dest,
            db_path=db_path,
        )
        print(f"execution_id={result.execution_id}")
        print(f"output_root={result.output_root}")
        print(f"total_planned={result.total_planned}")
        print(f"copied={result.copied_count}")
        print(f"skipped={result.skipped_count}")
        print(f"failed={result.failed_count}")
        return 0

    if args.command == "review-report":
        result = generate_review_report(
            scan_run_id=args.scan_run_id,
            out_dir=args.out,
            db_path=db_path,
        )
        print(f"report_path={result.report_path}")
        print(f"total_plans={result.total_plans}")
        print(f"planned={result.planned_count}")
        print(f"needs_review={result.needs_review_count}")
        print(f"blocked={result.blocked_count}")
        print(f"conflicts={result.conflict_count}")
        return 0

    if args.command == "duplicate-report":
        result = generate_duplicate_report(
            scan_run_id=args.scan_run_id,
            library_root=args.library_root,
            out_dir=args.out,
            db_path=db_path,
        )
        print(f"report_path={result.report_path}")
        print(f"total_files_checked={result.total_files_checked}")
        print(f"exact_hash_groups={result.exact_hash_groups}")
        print(f"same_artist_title_groups={result.same_artist_title_groups}")
        print(f"probable_variant_groups={result.variant_title_groups}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
