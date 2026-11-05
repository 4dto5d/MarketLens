from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from local_presence_miner import __version__
from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import list_leads
from local_presence_miner.database.schema import Lead, SearchRunLead
from local_presence_miner.domain.models import SearchCriteria
from local_presence_miner.logging_config import configure_logging
from local_presence_miner.services.comparison_service import ComparisonService
from local_presence_miner.services.export_service import ExportService
from local_presence_miner.services.google_places import estimate_places_api_calls
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.mockup_service import MockupService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.search_workflow import SearchWorkflow
from local_presence_miner.services.static_site_service import StaticSiteService
from local_presence_miner.services.v0111_backfill_service import V0111BackfillService


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args)
    if args.command == "preflight":
        return preflight_command(args)
    parser.print_help()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-presence-miner", description="MarketLens Local CLI")
    parser.add_argument("--version", action="version", version=f"MarketLens Local {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Run a lead search and optional local outputs.")
    add_common_args(run)
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--offline", "--demo", dest="offline", action="store_true", help="Use bundled demo data. This is the default.")
    mode.add_argument("--online", dest="offline", action="store_false", help="Use Google Places and live website audits.")
    run.set_defaults(offline=True)
    run.add_argument("--reports", action="store_true", help="Generate HTML reports for the collected leads.")
    run.add_argument(
        "--report-kind",
        choices=["owner_short", "owner_full", "internal"],
        default="owner_full",
        help="Report density/audience. Internal includes outreach drafts.",
    )
    run.add_argument("--mockups", "--builders", dest="mockups", action="store_true", help="Generate static website concept mockups.")
    run.add_argument("--comparisons", action="store_true", help="Generate competitor comparison HTML reports.")
    run.add_argument("--proposals", action="store_true", help="Generate owner-facing proposal HTML files.")
    run.add_argument("--site-exports", action="store_true", help="Generate static paid-style starter website folders.")
    run.add_argument("--packages", action="store_true", help="Export ZIP lead packages for the top leads.")
    run.add_argument("--top-mockups", type=int, default=3, help="Number of top leads to use for mockups/packages.")
    run.add_argument("--pagespeed", action="store_true", help="Run optional PageSpeed checks for live websites.")
    run.add_argument("--rendered-audit", action="store_true", help="Rendered fetching remains security-skipped; ordinary audit is available.")
    run.add_argument("--screenshots", action="store_true", help="Capture desktop/mobile images; requires --rendered-audit.")
    run.add_argument("--safe-live-test", action="store_true", help="Limit live retrieval to five businesses and enrich all five.")
    run.add_argument("--ai-mode", choices=["off", "prompt", "prompt-paste", "api"], default="off")
    run.add_argument("--export-csv", action="store_true", help="Export the current lead table to CSV.")
    run.add_argument("--out", type=Path, default=None, help="Output directory. Also stores the CLI SQLite DB unless --database is used.")
    run.add_argument("--database", type=Path, default=None, help="SQLite database path.")
    run.add_argument("--debug", action="store_true", help="Print tracebacks and debug log messages.")

    preflight = subparsers.add_parser("preflight", help="Check local setup and API-key state.")
    preflight.add_argument("--out", type=Path, default=None)
    preflight.add_argument("--database", type=Path, default=None)
    preflight.add_argument("--debug", action="store_true")
    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--city", default="Flint")
    parser.add_argument("--state", "--state-region", dest="state_region", default="MI")
    parser.add_argument("--niche", "--category", dest="niche", default="roofers")
    parser.add_argument("--target-zip", "--zip", dest="target_zip_code", default="48502")
    parser.add_argument("--miles", "--target-radius-miles", dest="target_radius_miles", type=int, default=10)
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--min-review-count", type=int, default=0)
    parser.add_argument("--min-rating", type=float, default=0.0)
    parser.add_argument(
        "--google-data-depth",
        choices=["economy", "balanced", "deep"],
        default="economy",
        help="Rich Place Details cap: economy 8, balanced 20, deep 40.",
    )
    parser.add_argument("--output-name", default="cli-search")


def run_command(args: argparse.Namespace) -> int:
    config = load_cli_config(args)
    configure_logging(config)
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.offline and not config.google_maps_api_key:
        print("Online mode needs GOOGLE_MAPS_API_KEY. Re-run with --offline for the free demo path.")
        return 2
    if args.offline and (args.pagespeed or args.rendered_audit or args.screenshots):
        print("PageSpeed, rendered audits, and screenshots apply only to --online live websites.")
        return 2
    if args.offline and args.safe_live_test:
        print("--safe-live-test requires --online.")
        return 2
    if args.screenshots and not args.rendered_audit:
        print("--screenshots requires --rendered-audit.")
        return 2
    ai_mode = normalize_ai_mode(args.ai_mode)

    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        changed = V0111BackfillService().run(session, config.sender)
        if QualificationService().recalculate_missing(session):
            changed += 1
        if changed:
            session.commit()
    criteria = SearchCriteria(
        city=args.city,
        state_region=args.state_region,
        niche=args.niche,
        target_zip_code=args.target_zip_code,
        target_radius_miles=args.target_radius_miles,
        radius_meters=round(args.target_radius_miles * 1609.344),
        max_results=args.max_results,
        min_review_count=args.min_review_count,
        min_rating=args.min_rating,
        top_mockups=args.top_mockups if args.mockups else 0,
        run_pagespeed=args.pagespeed,
        run_rendered_audit=args.rendered_audit,
        generate_screenshots=args.screenshots,
        output_name=args.output_name,
        demo_mode=args.offline,
        safe_live_test=args.safe_live_test and not args.offline,
        google_data_depth={"economy": "Economy", "balanced": "Balanced", "deep": "Deep Prospecting"}[args.google_data_depth],
    )

    if not args.offline:
        discovery_calls, detail_calls, total_calls = estimate_places_api_calls(criteria)
        print(f"Estimated Google calls: up to {total_calls} ({discovery_calls} Text Search + {detail_calls} Place Details).")

    try:
        search_id = SearchWorkflow(config, factory).run(criteria)
        with factory() as session:
            leads = list(
                session.execute(
                    select(Lead)
                    .join(SearchRunLead, SearchRunLead.lead_id == Lead.id)
                    .where(
                        SearchRunLead.search_id == search_id,
                        SearchRunLead.processing_status == "Succeeded",
                    )
                    .order_by(Lead.sales_priority_score.desc(), Lead.lead_score.desc(), Lead.name)
                ).scalars()
            )
            paths: list[Path] = []
            if args.reports:
                report_service = ReportService(config)
                paths.extend(report_service.generate_report(session, lead, args.report_kind) for lead in leads)
            if args.mockups:
                mockup_service = MockupService(config)
                paths.extend(mockup_service.generate_mockup(lead) for lead in leads[: args.top_mockups])
            if args.comparisons:
                comparison_service = ComparisonService(config)
                paths.extend(comparison_service.generate_comparison(session, lead, ai_mode) for lead in leads)
            if args.proposals:
                proposal_service = ProposalService(config)
                paths.extend(proposal_service.generate_proposal(session, lead) for lead in leads)
            if args.site_exports:
                site_service = StaticSiteService(config)
                paths.extend(site_service.export_site(lead, session=session) for lead in leads[: args.top_mockups])
            if args.packages:
                package_service = LeadPackageService(config)
                paths.extend(package_service.export_package(session, lead, ai_mode="prompt") for lead in leads[: args.top_mockups])
            if args.export_csv:
                paths.append(ExportService().export_leads_csv(session, config.output_dir / "exports" / "leads.csv"))

        print(f"Search complete: {search_id}")
        print(f"Leads collected: {len(leads)}")
        print(f"Database: {config.database_path}")
        print(f"Output directory: {config.output_dir}")
        if paths:
            print("Generated files:")
            for path in paths:
                print(f"- {path}")
        return 0
    except Exception:
        logging.exception("CLI run failed")
        if args.debug:
            raise
        print(f"Run failed. Check log: {config.log_path}")
        return 1


def preflight_command(args: argparse.Namespace) -> int:
    config = load_cli_config(args)
    configure_logging(config)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        changed = V0111BackfillService().run(session, config.sender)
        if QualificationService().recalculate_missing(session):
            changed += 1
        if changed:
            session.commit()
        total = len(list_leads(session))
    print("MarketLens Local preflight")
    print(f"- App data: {config.app_data_dir}")
    print(f"- Database: {config.database_path}")
    print(f"- Output directory: {config.output_dir}")
    print(f"- Existing leads: {total}")
    print(f"- Google key present: {'yes' if config.google_maps_api_key else 'no'}")
    print("- Offline/demo mode: available")
    print("- Online mode: available only when GOOGLE_MAPS_API_KEY is set")
    return 0


def load_cli_config(args: argparse.Namespace) -> AppConfig:
    config = AppConfig.load()
    output_dir = args.out.expanduser() if args.out else config.output_dir
    if args.database:
        database_path = args.database.expanduser()
    elif args.out:
        database_path = output_dir / "local_presence_miner.sqlite3"
    else:
        database_path = config.database_path
    log_path = output_dir / "logs" / "cli.log" if args.out else config.log_path
    for child in ["logs", "reports", "mockups", "comparisons", "prompts", "packages", "exports", "proposals", "site_exports"]:
        (output_dir / child).mkdir(parents=True, exist_ok=True)
    return replace(config, output_dir=output_dir, database_path=database_path, log_path=log_path)


def normalize_ai_mode(value: str) -> str:
    if value == "api":
        print("AI API mode is reserved for a future build. Writing paste-ready prompts instead.")
        return "prompt"
    return value


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
