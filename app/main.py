"""Command line interface for the music-library normalization system."""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import FastAPI

from app import db
from app.classifier import classify_scan_run
from app.duplicate_quarantine import quarantine_duplicates
from app.duplicate_report import generate_duplicate_report
from app.duplicate_review import generate_duplicate_review_plan
from app.identity_engine import identify_scan_run
from app.intake import run_intake
from app.library_qa import generate_library_qa_report
from app.manual_review_ui import router as manual_review_ui_router
from app.metadata_audit import generate_metadata_audit_report
from app.metadata_plan import generate_metadata_plan
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
from app.quarantine_restore import restore_quarantine
from app.report_ui import router as report_ui_router
from app.review_report import generate_review_report
from app.scanner import scan


app = FastAPI(title="Music Library Reports")
app.include_router(report_ui_router)
app.include_router(manual_review_ui_router)


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

    duplicate_review_parser = subparsers.add_parser(
        "duplicate-review",
        help="Create read-only keep/remove recommendations for duplicates.",
    )
    duplicate_review_parser.add_argument(
        "--duplicate-report-id", required=True, type=int
    )
    duplicate_review_parser.add_argument("--out", default="reports")

    quarantine_parser = subparsers.add_parser(
        "quarantine-duplicates",
        help="Move duplicate remove candidates into a quarantine folder.",
    )
    quarantine_parser.add_argument("--review-plan-id", required=True, type=int)
    quarantine_parser.add_argument("--quarantine-root", required=True)
    quarantine_parser.add_argument("--dry-run", action="store_true")

    restore_quarantine_parser = subparsers.add_parser(
        "restore-quarantine",
        help="Restore files from a duplicate quarantine run.",
    )
    restore_quarantine_parser.add_argument(
        "--quarantine-run-id", required=True, type=int
    )
    restore_quarantine_parser.add_argument("--dry-run", action="store_true")

    library_qa_parser = subparsers.add_parser(
        "library-qa",
        help="Export read-only QA reports for an organised library.",
    )
    library_qa_parser.add_argument("--library-root", required=True)
    library_qa_parser.add_argument("--quarantine-root", required=True)
    library_qa_parser.add_argument("--out", default="reports")

    metadata_audit_parser = subparsers.add_parser(
        "metadata-audit",
        help="Export read-only FLAC metadata audit reports.",
    )
    metadata_audit_parser.add_argument("--library-root", required=True)
    metadata_audit_parser.add_argument("--out", required=True)

    metadata_plan_parser = subparsers.add_parser(
        "metadata-plan",
        help="Create a read-only FLAC metadata tag correction plan.",
    )
    metadata_plan_parser.add_argument("--library-root", required=True)
    metadata_plan_parser.add_argument("--out", required=True)

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

    if args.command == "duplicate-review":
        result = generate_duplicate_review_plan(
            duplicate_report_id=args.duplicate_report_id,
            out_dir=args.out,
            db_path=db_path,
        )
        print(f"plan_path={result.plan_path}")
        print(f"total_groups={result.total_groups}")
        print(f"files_reviewed={result.total_files_reviewed}")
        print(f"keeper_count={result.keeper_count}")
        print(f"remove_candidate_count={result.remove_candidate_count}")
        return 0

    if args.command == "quarantine-duplicates":
        result = quarantine_duplicates(
            review_plan_id=args.review_plan_id,
            quarantine_root=args.quarantine_root,
            dry_run=args.dry_run,
            db_path=db_path,
        )
        print(f"quarantine_run_id={result.quarantine_run_id}")
        print(f"total_remove_candidates={result.total_remove_candidates}")
        print(f"moved={result.moved_count}")
        print(f"skipped={result.skipped_count}")
        print(f"failed={result.failed_count}")
        print(f"dry_run={str(result.dry_run).lower()}")
        return 0

    if args.command == "restore-quarantine":
        result = restore_quarantine(
            quarantine_run_id=args.quarantine_run_id,
            dry_run=args.dry_run,
            db_path=db_path,
        )
        print(f"restore_run_id={result.restore_run_id}")
        print(f"total_restore_candidates={result.total_restore_candidates}")
        print(f"restored={result.restored_count}")
        print(f"skipped={result.skipped_count}")
        print(f"failed={result.failed_count}")
        print(f"dry_run={str(result.dry_run).lower()}")
        return 0

    if args.command == "library-qa":
        result = generate_library_qa_report(
            library_root=args.library_root,
            quarantine_root=args.quarantine_root,
            out_dir=args.out,
            db_path=db_path,
        )
        print(f"report_path={result.report_path}")
        print(f"total_library_files={result.total_library_files}")
        print(f"total_quarantine_files={result.total_quarantine_files}")
        print(f"genre_count={result.genre_count}")
        print(f"subgenre_count={result.subgenre_count}")
        print(f"artist_count={result.artist_count}")
        print(f"active_duplicate_group_count={result.active_duplicate_group_count}")
        print(
            "historical_duplicate_group_count="
            f"{result.historical_duplicate_group_count}"
        )
        print(
            "quarantined_duplicate_file_count="
            f"{result.quarantined_duplicate_file_count}"
        )
        print(f"missing_file_count={result.missing_file_count}")
        print(f"unresolved_missing_file_count={result.unresolved_missing_file_count}")
        return 0

    if args.command == "metadata-audit":
        result = generate_metadata_audit_report(
            library_root=args.library_root,
            out_dir=args.out,
        )
        print(f"report_path={result.report_path}")
        print(f"total_flac_files={result.total_flac_files}")
        print(f"readable_flac_files={result.readable_flac_files}")
        print(f"unreadable_flac_files={result.unreadable_flac_files}")
        print(f"missing_tag_count={result.missing_tag_count}")
        print(f"malformed_tag_count={result.malformed_tag_count}")
        print(
            "inconsistent_artist_group_count="
            f"{result.inconsistent_artist_group_count}"
        )
        print(
            "inconsistent_title_group_count="
            f"{result.inconsistent_title_group_count}"
        )
        return 0

    if args.command == "metadata-plan":
        result = generate_metadata_plan(
            library_root=args.library_root,
            out_dir=args.out,
        )
        print(f"report_path={result.report_path}")
        print(f"total_flac_files={result.total_flac_files}")
        print(f"readable_flac_files={result.readable_flac_files}")
        print(f"unreadable_flac_files={result.unreadable_flac_files}")
        print(f"proposed_update_count={result.proposed_update_count}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
