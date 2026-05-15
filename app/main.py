"""Command line interface for the music-library normalization system."""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import FastAPI

from app.album_cohesion import generate_album_cohesion_report
from app.album_discovery import generate_album_discovery
from app.album_organization import generate_album_organization_plan
from app import db
from app.alias_equivalence_audit import generate_alias_equivalence_audit_report
from app.classifier import classify_scan_run
from app.canonical_entity_graph import generate_canonical_graph
from app.canonical_entity_classifier import generate_canonical_entity_classification_report
from app.canonical_confidence import generate_canonical_confidence_report
from app.conflict_governance import generate_conflict_governance_report
from app.duplicate_quarantine import quarantine_duplicates
from app.duplicate_report import generate_duplicate_report
from app.duplicate_review import generate_duplicate_review_plan
from app.entity_boundary import generate_entity_boundary_report
from app.entity_roles import generate_entity_role_report
from app.evidence_reliability import generate_evidence_reliability_report
from app.external_metadata import import_external_metadata
from app.identity_engine import identify_scan_run
from app.large_scale_validation import validate_external_metadata
from app.intake import run_intake
from app.library_qa import generate_library_qa_report
from app.library_app_ui import router as library_app_ui_router
from app.manual_review_ui import router as manual_review_ui_router
from app.metadata_audit import generate_metadata_audit_report
from app.metadata_plan import generate_metadata_plan
from app.metadata_suggestion_ui import router as metadata_suggestion_ui_router
from app.metadata_suggestions import generate_metadata_suggestions
from app.normalization_knowledge import (
    build_normalization_knowledge,
    router as normalization_knowledge_router,
)
from app.pipeline import run_intake_pipeline
from app.placement_executor import execute_placement
from app.placement_planner import plan_scan_run_placements
from app.promotion_lifecycle import generate_promotion_lifecycle_report
from app.purchase_gateway import (
    add_purchase_option,
    attach_purchase_proof,
    build_purchase_report,
    create_purchase_request,
    unlock_intake,
)
from app.quarantine_restore import restore_quarantine
from app.report_ui import router as report_ui_router
from app.review_decisions import (
    generate_review_decision_report,
    import_review_decisions,
    record_review_decision,
)
from app.review_report import generate_review_report
from app.scanner import scan
from app.validation_benchmark import benchmark_validation
from tools.portfolio_demo.demo_generator import generate_demo
from tools.portfolio_demo.ui_screenshot_capture import capture_ui_screenshots


app = FastAPI(title="Music Library Intelligence Platform")
app.include_router(library_app_ui_router)
app.include_router(report_ui_router)
app.include_router(manual_review_ui_router)
app.include_router(metadata_suggestion_ui_router)
app.include_router(normalization_knowledge_router)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main",
        description="Music Library Intelligence Platform observation ledger.",
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

    metadata_suggestions_parser = subparsers.add_parser(
        "metadata-suggestions",
        help="Create review-only metadata cleanup suggestions from plan and audit reports.",
    )
    metadata_suggestions_parser.add_argument("--metadata-plan", required=True)
    metadata_suggestions_parser.add_argument("--metadata-audit", required=True)
    metadata_suggestions_parser.add_argument("--out", default="reports")

    review_decision_parser = subparsers.add_parser(
        "review-decision",
        help="Record a human decision for one metadata suggestion.",
    )
    review_decision_parser.add_argument("--suggestion-key", required=True)
    review_decision_parser.add_argument(
        "--decision", required=True, choices=("approved", "rejected", "deferred")
    )
    review_decision_parser.add_argument("--reason", required=True)

    import_review_decisions_parser = subparsers.add_parser(
        "import-review-decisions",
        help="Import human review decisions from CSV into the audit ledger.",
    )
    import_review_decisions_parser.add_argument("--suggestions", required=True)
    import_review_decisions_parser.add_argument("--decisions", required=True)

    review_decision_report_parser = subparsers.add_parser(
        "review-decision-report",
        help="Export persisted review decision summary reports.",
    )
    review_decision_report_parser.add_argument("--out", default="reports")

    build_normalization_knowledge_parser = subparsers.add_parser(
        "build-normalization-knowledge",
        help="Derive reusable normalization rules from human review decisions.",
    )
    build_normalization_knowledge_parser.add_argument("--out", default="reports")

    album_organization_parser = subparsers.add_parser(
        "plan-album-organization",
        help="Create a read-only album-folder organization plan for a library.",
    )
    album_organization_parser.add_argument("--library-root", required=True)
    album_organization_parser.add_argument("--out", default="reports")

    album_cohesion_parser = subparsers.add_parser(
        "album-cohesion",
        help="Create read-only repeated-evidence album cohesion reports.",
    )
    album_cohesion_parser.add_argument("--out", default="reports")
    album_cohesion_parser.add_argument(
        "--library-root",
        help="Optional library root to scan directly instead of reports/library_qa/file_health.csv.",
    )

    evidence_reliability_parser = subparsers.add_parser(
        "evidence-reliability",
        help="Score metadata evidence reliability from existing reports and review knowledge.",
    )
    evidence_reliability_parser.add_argument("--out", default="reports")

    canonical_graph_parser = subparsers.add_parser(
        "canonical-graph",
        help="Build persistent canonical entities and evidence-governed relationships.",
    )
    canonical_graph_parser.add_argument("--out", default="reports")

    conflict_governance_parser = subparsers.add_parser(
        "conflict-governance",
        help="Classify unresolved canonical conflicts into review-only governance buckets.",
    )
    conflict_governance_parser.add_argument("--out", default="reports")

    alias_equivalence_audit_parser = subparsers.add_parser(
        "alias-equivalence-audit",
        help="Audit deterministic alias equivalence decisions against governance outcomes.",
    )
    alias_equivalence_audit_parser.add_argument("--out", default="reports")

    entity_boundaries_parser = subparsers.add_parser(
        "entity-boundaries",
        help="Classify raw metadata candidate boundaries before canonical graph insertion.",
    )
    entity_boundaries_parser.add_argument("--out", default="reports")

    entity_classification_parser = subparsers.add_parser(
        "classify-canonical-entities",
        help="Classify canonical entity candidates before graph promotion.",
    )
    entity_classification_parser.add_argument("--out", default="reports")

    entity_roles_parser = subparsers.add_parser(
        "entity-roles",
        help="Aggregate role-aware canonical entity evidence without mutating media.",
    )
    entity_roles_parser.add_argument("--out", default="reports")

    canonical_confidence_parser = subparsers.add_parser(
        "canonical-confidence",
        help="Score canonical entities with weighted positive and negative evidence.",
    )
    canonical_confidence_parser.add_argument("--out", default="reports")

    promotion_lifecycle_parser = subparsers.add_parser(
        "promotion-lifecycle",
        help="Evaluate deterministic canonical entity promotion lifecycle states.",
    )
    promotion_lifecycle_parser.add_argument("--out", default="reports")

    album_discovery_parser = subparsers.add_parser(
        "discover-albums",
        help="Create review-only album metadata suggestions for Unknown Album tracks.",
    )
    album_discovery_parser.add_argument("--library-root", required=True)
    album_discovery_parser.add_argument("--out", default="reports")

    external_metadata_parser = subparsers.add_parser(
        "import-external-metadata",
        help="Import external metadata from a local CSV or JSONL file.",
    )
    external_metadata_parser.add_argument("--source", required=True)
    external_metadata_parser.add_argument("--input", required=True)
    external_metadata_parser.add_argument("--out", default="reports")

    validation_parser = subparsers.add_parser(
        "validate-external-metadata",
        help="Generate read-only cohort validation reports for ingested external metadata.",
    )
    validation_parser.add_argument("--source", required=True)
    validation_parser.add_argument("--out", default="reports")

    benchmark_validation_parser = subparsers.add_parser(
        "benchmark-validation",
        help="Benchmark read-only external metadata validation distributions.",
    )
    benchmark_validation_parser.add_argument("--source", required=True)
    benchmark_validation_parser.add_argument("--out", default="reports")

    subparsers.add_parser(
        "capture-ui-screenshots",
        help="Capture deterministic screenshots from the local report UI.",
    )

    subparsers.add_parser(
        "generate-demo",
        help="Generate deterministic local demo frames and an optional MP4.",
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
        print(f"album_count={result.album_count}")
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

    if args.command == "metadata-suggestions":
        result = generate_metadata_suggestions(
            metadata_plan_path=args.metadata_plan,
            metadata_audit_dir=args.metadata_audit,
            out_dir=args.out,
            db_path=db_path,
        )
        print(f"report_path={result.report_path}")
        print(f"total_suggestions={result.total_suggestions}")
        print(f"high_confidence_count={result.high_confidence_count}")
        print(f"medium_confidence_count={result.medium_confidence_count}")
        print(f"low_confidence_count={result.low_confidence_count}")
        print(f"requires_human_review_count={result.requires_human_review_count}")
        print(f"ai_enrichment_used={str(result.ai_enrichment_used).lower()}")
        return 0

    if args.command == "review-decision":
        result = record_review_decision(
            suggestion_key=args.suggestion_key,
            decision=args.decision,
            reason=args.reason,
            db_path=db_path,
        )
        print(f"decision_id={result.decision_id}")
        print(f"suggestion_key={result.suggestion_key}")
        print(f"decision={result.decision}")
        print(f"decided_at={result.decided_at}")
        return 0

    if args.command == "import-review-decisions":
        result = import_review_decisions(
            suggestions_path=args.suggestions,
            decisions_path=args.decisions,
            db_path=db_path,
        )
        print(f"imported={result.imported_count}")
        print(f"updated={result.updated_count}")
        print(f"skipped={result.skipped_count}")
        return 0

    if args.command == "review-decision-report":
        result = generate_review_decision_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_decisions={result.total_decisions}")
        print(f"approved={result.approved_count}")
        print(f"rejected={result.rejected_count}")
        print(f"deferred={result.deferred_count}")
        return 0

    if args.command == "build-normalization-knowledge":
        result = build_normalization_knowledge(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_rules={result.total_rules}")
        print(f"high_confidence={result.high_confidence_count}")
        print(f"medium_confidence={result.medium_confidence_count}")
        print(f"low_confidence={result.low_confidence_count}")
        print(f"rejected_patterns={result.rejected_pattern_count}")
        return 0

    if args.command == "plan-album-organization":
        result = generate_album_organization_plan(
            library_root=args.library_root,
            out_dir=args.out,
        )
        print(f"report_path={result.report_path}")
        print(f"total_files={result.total_files}")
        print(f"high_confidence={result.high_confidence}")
        print(f"medium_confidence={result.medium_confidence}")
        print(f"low_confidence={result.low_confidence}")
        print(f"requires_review={result.requires_review}")
        print(f"unknown_album_count={result.unknown_album_count}")
        return 0

    if args.command == "album-cohesion":
        result = generate_album_cohesion_report(
            out_dir=args.out,
            library_root=args.library_root,
        )
        print(f"report_path={result.report_path}")
        print(f"total_album_groups={result.total_album_groups}")
        print(f"high_confidence_groups={result.high_confidence_groups}")
        print(f"medium_confidence_groups={result.medium_confidence_groups}")
        print(f"low_confidence_groups={result.low_confidence_groups}")
        print(f"probable_singles={result.probable_singles}")
        print(f"orphan_tracks={result.orphan_tracks}")
        print(f"conflicting_album_groups={result.conflicting_album_groups}")
        return 0

    if args.command == "evidence-reliability":
        result = generate_evidence_reliability_report(
            out_dir=args.out,
            db_path=db_path,
        )
        print(f"report_path={result.report_path}")
        print(f"total_records={result.total_records}")
        print(f"high_reliability={result.high_reliability}")
        print(f"medium_reliability={result.medium_reliability}")
        print(f"low_reliability={result.low_reliability}")
        print(f"uploader_artifacts_detected={result.uploader_artifacts_detected}")
        print(f"noisy_titles_detected={result.noisy_titles_detected}")
        print(f"conflicting_artist_patterns={result.conflicting_artist_patterns}")
        print(f"canonical_matches={result.canonical_matches}")
        return 0

    if args.command == "canonical-graph":
        result = generate_canonical_graph(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"canonical_artist_count={result.canonical_artist_count}")
        print(f"canonical_album_count={result.canonical_album_count}")
        print(f"canonical_track_count={result.canonical_track_count}")
        print(f"blocked_candidate_count={result.blocked_candidate_count}")
        print(f"alias_relationships={result.alias_relationships}")
        print(f"duplicate_relationships={result.duplicate_relationships}")
        print(f"unresolved_conflicts={result.unresolved_conflicts}")
        print(f"high_confidence_entities={result.high_confidence_entities}")
        print(f"medium_confidence_entities={result.medium_confidence_entities}")
        print(f"low_confidence_entities={result.low_confidence_entities}")
        return 0

    if args.command == "conflict-governance":
        result = generate_conflict_governance_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_conflicts={result.total_conflicts}")
        print(f"blocked_merges={result.blocked_merges}")
        print(f"safe_merge_candidates={result.safe_merge_candidates}")
        print(f"needs_review={result.needs_review}")
        print(f"deferred={result.deferred}")
        print(f"resolved={result.resolved}")
        print(f"high_severity={result.high_severity}")
        print(f"medium_severity={result.medium_severity}")
        print(f"low_severity={result.low_severity}")
        return 0

    if args.command == "alias-equivalence-audit":
        result = generate_alias_equivalence_audit_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_audited_conflicts={result.total_audited_conflicts}")
        print(f"equivalence_matches={result.equivalence_matches}")
        print(f"prevented_escalations={result.prevented_escalations}")
        print(f"missed_safe_aliases={result.missed_safe_aliases}")
        print(f"remaining_escalations={result.remaining_escalations}")
        print(f"casing_only_matches={result.casing_only_matches}")
        print(f"punctuation_only_matches={result.punctuation_only_matches}")
        print(f"whitespace_only_matches={result.whitespace_only_matches}")
        print(f"suffix_noise_rejections={result.suffix_noise_rejections}")
        print(f"collaboration_rejections={result.collaboration_rejections}")
        print(f"source_artifact_rejections={result.source_artifact_rejections}")
        print(f"role_collision_rejections={result.role_collision_rejections}")
        print(f"album_title_equivalence_matches={result.album_title_equivalence_matches}")
        print(f"album_title_prevented_escalations={result.album_title_prevented_escalations}")
        print(f"album_title_missed_safe_equivalents={result.album_title_missed_safe_equivalents}")
        return 0

    if args.command == "entity-boundaries":
        result = generate_entity_boundary_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_candidates={result.total_candidates}")
        print(f"allowed_candidates={result.allowed_candidates}")
        print(f"blocked_candidates={result.blocked_candidates}")
        print(f"quarantined_candidates={result.quarantined_candidates}")
        print(f"needs_review_candidates={result.needs_review_candidates}")
        print(f"source_artifacts_blocked={result.source_artifacts_blocked}")
        print(f"collaboration_strings_quarantined={result.collaboration_strings_quarantined}")
        print(f"title_pollution_blocked={result.title_pollution_blocked}")
        print(f"release_annotations_quarantined={result.release_annotations_quarantined}")
        return 0

    if args.command == "classify-canonical-entities":
        result = generate_canonical_entity_classification_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_candidates={result.total_candidates}")
        print(f"canonical_artist_candidates={result.canonical_artist_candidates}")
        print(f"canonical_album_candidates={result.canonical_album_candidates}")
        print(f"canonical_track_candidates={result.canonical_track_candidates}")
        print(f"blocked_candidates={result.blocked_candidates}")
        print(f"ambiguous_candidates={result.ambiguous_candidates}")
        print(f"source_artifacts={result.source_artifacts}")
        print(f"misclassified_track_titles={result.misclassified_track_titles}")
        return 0

    if args.command == "entity-roles":
        result = generate_entity_role_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_role_records={result.total_role_records}")
        print(f"multi_role_entities={result.multi_role_entities}")
        print(f"conflicted_roles={result.conflicted_roles}")
        print(f"canonical_role_agreements={result.canonical_role_agreements}")
        print(f"blocked_role_collisions={result.blocked_role_collisions}")
        return 0

    if args.command == "canonical-confidence":
        result = generate_canonical_confidence_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"total_scored_entities={result.total_scored_entities}")
        print(f"high_confidence_count={result.high_confidence_count}")
        print(f"medium_confidence_count={result.medium_confidence_count}")
        print(f"low_confidence_count={result.low_confidence_count}")
        print(f"blocked_confidence_count={result.blocked_confidence_count}")
        print(f"average_confidence={result.average_confidence}")
        print(f"average_positive_score={result.average_positive_score}")
        print(f"average_negative_score={result.average_negative_score}")
        return 0

    if args.command == "promotion-lifecycle":
        result = generate_promotion_lifecycle_report(out_dir=args.out, db_path=db_path)
        print(f"report_path={result.report_path}")
        print(f"candidate_count={result.candidate_count}")
        print(f"probationary_count={result.probationary_count}")
        print(f"canonical_count={result.canonical_count}")
        print(f"conflicted_count={result.conflicted_count}")
        print(f"blocked_count={result.blocked_count}")
        print(f"deprecated_count={result.deprecated_count}")
        print(f"promoted_this_run={result.promoted_this_run}")
        print(f"demoted_this_run={result.demoted_this_run}")
        return 0

    if args.command == "discover-albums":
        result = generate_album_discovery(
            library_root=args.library_root,
            out_dir=args.out,
        )
        print(f"report_path={result.report_path}")
        print(f"total_tracks_checked={result.total_tracks_checked}")
        print(f"unknown_album_tracks={result.unknown_album_tracks}")
        print(f"total_suggestions={result.total_suggestions}")
        print(f"high_confidence_count={result.high_confidence_count}")
        print(f"medium_confidence_count={result.medium_confidence_count}")
        print(f"low_confidence_count={result.low_confidence_count}")
        print(f"network_lookup_used={str(result.network_lookup_used).lower()}")
        print(f"cache_entries={result.cache_entries}")
        return 0

    if args.command == "import-external-metadata":
        result = import_external_metadata(
            source_name=args.source,
            input_path=args.input,
            out_dir=args.out,
        )
        print(f"report_path={result.report_path}")
        print(f"source_name={result.source_name}")
        print(f"input_records={result.input_records}")
        print(f"accepted_records={result.accepted_records}")
        print(f"rejected_records={result.rejected_records}")
        print(f"generated_id_count={result.generated_id_count}")
        print(f"output_csv={result.output_csv}")
        print(f"output_jsonl={result.output_jsonl}")
        return 0

    if args.command == "validate-external-metadata":
        result = validate_external_metadata(
            source_name=args.source,
            out_dir=args.out,
        )
        print(f"report_path={result.report_path}")
        print(f"source_name={result.source_name}")
        print(f"total_records={result.total_records}")
        print(f"total_cohorts={result.total_cohorts}")
        print(f"high_priority_cohorts={result.high_priority_cohorts}")
        print(f"malformed_record_count={result.malformed_record_count}")
        return 0

    if args.command == "benchmark-validation":
        result = benchmark_validation(
            source_name=args.source,
            out_dir=args.out,
        )
        print(f"report_path={result.report_path}")
        print(f"source_name={result.source_name}")
        print(f"total_records={result.total_records}")
        print(f"total_cohorts={result.total_cohorts}")
        print(f"total_conflicts={result.total_conflicts}")
        print(f"safe_merge_candidates={result.safe_merge_candidates}")
        print(f"blocked_merges={result.blocked_merges}")
        print(f"deferred_conflicts={result.deferred_conflicts}")
        print(f"benchmark_duration_seconds={result.benchmark_duration_seconds}")
        return 0

    if args.command == "capture-ui-screenshots":
        result = capture_ui_screenshots()
        failed_count = getattr(result, "failed_count", 0)
        print(f"captured={len(result)}")
        print(f"failed={failed_count}")
        for path in result:
            print(path)
        return 0 if result else 1

    if args.command == "generate-demo":
        result = generate_demo()
        print(f"regenerated_screenshot_count={result.regenerated_screenshot_count}")
        print(f"frame_count={len(result.frames)}")
        print(f"frames_dir={result.frames_dir}")
        print(f"manifest_path={result.manifest_path}")
        print(f"script_path={result.script_path}")
        if result.video_path is None:
            print("output_video_path=")
            print("ffmpeg_available=false")
        else:
            print(f"output_video_path={result.video_path}")
            print("ffmpeg_available=true")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
