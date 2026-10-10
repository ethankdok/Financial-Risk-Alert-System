"""CLI for the isolated historical audit-case archive (Phase 1).

Run from fintrust_backend/:  python -m scripts.historical_audit_case <command> ...
Every command uses an isolated SQLite file and never touches the production
pipeline database, Firestore, snapshots, scheduler or AI layer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.backfill import HistoricalBackfillService
from app.services.historical_audit.case_registry import get_case, load_cases
from app.services.historical_audit.evidence_export import DATASETS, export_evidence_dataset
from app.services.historical_audit.evidence_import import HistoricalEvidenceService, load_plan
from app.services.historical_audit.export import export_historical_facts
from app.services.historical_audit.quality import eps_unit_investigation, quality_report, unmapped_concept_report
from app.services.historical_audit.reader import VERSION_POLICIES, list_historical_facts
from app.services.historical_audit.repository import DEFAULT_DATABASE_PATH, HistoricalAuditRepository


DEFAULT_ARCHIVE_PATH = "./data/historical_audit/raw"


def _emit(payload: Any, output: Path | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))


def _repository(args: argparse.Namespace) -> HistoricalAuditRepository:
    return HistoricalAuditRepository(str(args.database))


def _years(args: argparse.Namespace) -> tuple[str, int, int]:
    case = get_case(args.ticker)
    start = args.start_year if args.start_year is not None else case.default_start_year
    end = args.end_year if args.end_year is not None else case.default_end_year
    return case.ticker, start, end


def command_cases(args: argparse.Namespace) -> None:
    _emit([case.model_dump(mode="json") for case in load_cases().values()])


def command_init_db(args: argparse.Namespace) -> None:
    repository = _repository(args)
    if args.ticker:
        repository.register_case(get_case(args.ticker))
    _emit({"database": str(args.database), "schema_version": repository.schema_version(), "tables": repository.table_counts()})


def command_backfill(args: argparse.Namespace) -> None:
    ticker, start, end = _years(args)
    # A dry run must not create or migrate the database.
    repository = HistoricalAuditRepository.for_planning(str(args.database)) if args.dry_run else _repository(args)
    service = HistoricalBackfillService(
        repository=repository,
        archive=RawEvidenceArchive(args.archive),
        concurrency=args.concurrency,
    )
    result = asyncio.run(service.run(
        ticker, start, end,
        source_strategy=args.source_strategy,
        manifest_path=args.manifest,
        dry_run=args.dry_run,
    ))
    payload = result.model_dump(mode="json")
    payload["evidence_matrix"] = [
        {
            "fiscal_year": year.fiscal_year,
            "acquisition_status": year.status,
            "source_url": year.source_url,
            "downloaded_at": year.downloaded_at,
            "content_hash": year.content_hash,
            "parser_status": year.parser_status,
            "filing_version_type": year.filing_version_type,
            "publication_verification_status": year.publication_verification_status,
            "document_dated_at": year.document_dated_at,
            "normalized_fact_count": year.normalized_fact_count,
            "facts_inserted": year.facts_inserted,
            "core_field_coverage": year.core_field_coverage,
            "persistence_status": year.persistence_status,
            "quality_status": year.validation_status,
            "quarantine_reason": year.quarantine_reason,
        }
        for year in result.years
    ]
    _emit(payload, args.report_json)


def command_quality(args: argparse.Namespace) -> None:
    ticker, start, end = _years(args)
    _emit(quality_report(_repository(args), RawEvidenceArchive(args.archive), ticker, start, end), args.output)


def command_query(args: argparse.Namespace) -> None:
    ticker, start, end = _years(args)
    rows = list_historical_facts(
        _repository(args), ticker, start, end,
        as_of=args.as_of, version_policy=args.version_policy,
        metrics=args.metric, periods=args.period,
        include_test_fixtures=args.include_test_fixtures,
    )
    _emit({"count": len(rows), "as_of": args.as_of, "version_policy": args.version_policy, "facts": rows})


def command_export(args: argparse.Namespace) -> None:
    ticker, start, end = _years(args)
    count = export_historical_facts(
        _repository(args), ticker, start, end,
        output_path=args.output, output_format=args.format,
        as_of=args.as_of, version_policy=args.version_policy,
        include_test_fixtures=args.include_test_fixtures,
    )
    _emit({"output": str(args.output), "format": args.format, "records": count})


def _evidence_service(args: argparse.Namespace) -> HistoricalEvidenceService:
    return HistoricalEvidenceService(repository=_repository(args), archive=RawEvidenceArchive(args.archive))


def command_evidence_acquire(args: argparse.Namespace) -> None:
    plan = load_plan(args.ticker, args.plan)
    if args.dry_run:
        _emit({"ticker": args.ticker, "dry_run": True, "sources": [
            {"source_key": s["source_key"], "category": s["category"], "parser": s["parser"],
             "method": s["request"]["method"], "url": s["request"]["url"]} for s in plan["sources"]
            if not args.only or s["source_key"] in args.only]})
        return
    outcomes = asyncio.run(_evidence_service(args).acquire(plan, refresh=args.refresh, only=set(args.only or []) or None))
    _emit({"ticker": args.ticker, "outcomes": [vars(outcome) for outcome in outcomes]}, args.report_json)


def command_evidence_import(args: argparse.Namespace) -> None:
    report = _evidence_service(args).import_evidence(load_plan(args.ticker, args.plan))
    _emit({"ticker": args.ticker, "counts": report.counts, "errors": report.errors, "warnings": report.warnings}, args.report_json)


def command_evidence_export(args: argparse.Namespace) -> None:
    ticker, start, end = _years(args)
    count = export_evidence_dataset(_repository(args), ticker, args.dataset, output_path=args.output,
                                    output_format=args.format, as_of=args.as_of, start_year=start, end_year=end)
    _emit({"output": str(args.output), "dataset": args.dataset, "format": args.format, "records": count})


def command_eps_investigation(args: argparse.Namespace) -> None:
    _emit(eps_unit_investigation(_repository(args), RawEvidenceArchive(args.archive), args.ticker), args.output)


def command_concept_coverage(args: argparse.Namespace) -> None:
    ticker, start, end = _years(args)
    _emit(unmapped_concept_report(_repository(args), ticker, start, end), args.output)


def command_research_package(args: argparse.Namespace) -> None:
    from app.services.historical_audit.package_verify import verify_package
    from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder

    if args.action == "verify":
        _emit(verify_package(args.path))
        return
    ticker, start, end = _years(args)
    conference_repository = None
    if args.include_conference and args.conference_root:
        from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository

        conference_repository = FileConferencePdfArchiveRepository(args.conference_root)
    builder = ResearchPackageBuilder(_repository(args), RawEvidenceArchive(args.archive),
                                     conference_repository=conference_repository, conference_root=args.conference_root)
    result = builder.build(PackageParameters(
        ticker=ticker, start_year=start, end_year=end, as_of=args.as_of, version_policy=args.version_policy,
        include_raw_evidence=not args.no_raw_evidence, include_conference=args.include_conference), args.output)
    result["verification"] = verify_package(args.output)
    _emit(result)


def command_cloud_sync(args: argparse.Namespace) -> None:
    """Disabled by default; see cloud_config.py for the fail-closed environment rules."""
    from app.services.historical_audit.cloud_config import HistoricalCloudConfig, build_clients
    from app.services.historical_audit.cloud_sync import HistoricalCloudSync
    from app.services.historical_audit.firestore_repository import FirestoreHistoricalResearchRepository
    from app.services.historical_audit.object_storage import GcsObjectStore

    config = HistoricalCloudConfig.from_env(allow_production=False)
    repository = _repository(args)
    if args.action == "status":
        sync = HistoricalCloudSync(repository=repository, archive=RawEvidenceArchive(args.archive),
                                   object_store=None, firestore=None, config=config)
        _emit(sync.status(args.ticker))
        return
    storage_client, firestore_client = build_clients(config)
    sync = HistoricalCloudSync(
        repository=repository, archive=RawEvidenceArchive(args.archive),
        object_store=GcsObjectStore(storage_client, config.bucket),
        firestore=FirestoreHistoricalResearchRepository(firestore_client, prefix=config.collection_prefix),
        config=config)
    report = sync.sync(args.ticker, execute=args.action == "run" and args.execute)
    _emit(vars(report))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Historical audit-case ingestion (isolated SQLite).")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser, *, years: bool = True) -> None:
        command.add_argument("--database", type=Path, default=Path(DEFAULT_DATABASE_PATH))
        command.add_argument("--archive", type=Path, default=Path(DEFAULT_ARCHIVE_PATH))
        if years:
            command.add_argument("--ticker", required=True)
            command.add_argument("--start-year", type=int)
            command.add_argument("--end-year", type=int)

    sub.add_parser("cases", help="List registered historical audit cases.").set_defaults(func=command_cases)

    init = sub.add_parser("init-db", help="Create or migrate the isolated database.")
    common(init, years=False)
    init.add_argument("--ticker")
    init.set_defaults(func=command_init_db)

    backfill = sub.add_parser("backfill", help="Acquire, archive, normalize and persist a fiscal-year range.")
    common(backfill)
    backfill.add_argument("--source-strategy", choices=("mops_t164sb01", "manifest", "archive"), default="mops_t164sb01")
    backfill.add_argument("--manifest", type=Path)
    backfill.add_argument("--dry-run", action="store_true", help="Plan only: no network, no database or archive writes.")
    backfill.add_argument("--concurrency", type=int, default=1, choices=(1, 2, 3))
    backfill.add_argument("--report-json", type=Path)
    backfill.set_defaults(func=command_backfill)

    quality = sub.add_parser("quality", help="Run archive-wide data-quality and integrity checks.")
    common(quality)
    quality.add_argument("--output", type=Path)
    quality.set_defaults(func=command_quality)

    for name, func in (("query", command_query), ("export", command_export)):
        command = sub.add_parser(name)
        common(command)
        command.add_argument("--as-of", help="YYYY-MM-DD (end of day, Asia/Taipei) or an ISO timestamp with timezone.")
        command.add_argument("--version-policy", choices=VERSION_POLICIES, default="all")
        command.add_argument("--include-test-fixtures", action="store_true")
        if name == "query":
            command.add_argument("--metric", action="append")
            command.add_argument("--period", action="append")
        else:
            command.add_argument("--format", choices=("csv", "json"), default="csv")
            command.add_argument("--output", type=Path, required=True)
        command.set_defaults(func=func)
    acquire = sub.add_parser("evidence-acquire", help="Bounded acquisition of the reviewed official evidence plan.")
    common(acquire, years=False)
    acquire.add_argument("--ticker", required=True)
    acquire.add_argument("--plan", type=Path)
    acquire.add_argument("--only", action="append", help="Restrict to these source_key values.")
    acquire.add_argument("--refresh", action="store_true", help="Download again even if an archived copy exists.")
    acquire.add_argument("--dry-run", action="store_true", help="List the planned requests; no network or writes.")
    acquire.add_argument("--report-json", type=Path)
    acquire.set_defaults(func=command_evidence_acquire)

    importer = sub.add_parser("evidence-import", help="Offline parse/link/corroborate of archived evidence.")
    common(importer, years=False)
    importer.add_argument("--ticker", required=True)
    importer.add_argument("--plan", type=Path)
    importer.add_argument("--report-json", type=Path)
    importer.set_defaults(func=command_evidence_import)

    evidence_export = sub.add_parser("evidence-export", help="Export one evidence dataset (CSV/JSON).")
    common(evidence_export)
    evidence_export.add_argument("--dataset", choices=(*DATASETS, "coverage_matrix"), required=True)
    evidence_export.add_argument("--format", choices=("csv", "json"), default="csv")
    evidence_export.add_argument("--as-of")
    evidence_export.add_argument("--output", type=Path, required=True)
    evidence_export.set_defaults(func=command_evidence_export)

    eps = sub.add_parser("eps-investigation", help="EPS unit evidence report.")
    common(eps, years=False)
    eps.add_argument("--ticker", required=True)
    eps.add_argument("--output", type=Path)
    eps.set_defaults(func=command_eps_investigation)

    concepts = sub.add_parser("concept-coverage", help="Prioritized unmapped-concept report.")
    common(concepts)
    concepts.add_argument("--output", type=Path)
    concepts.set_defaults(func=command_concept_coverage)

    package = sub.add_parser("research-package", help="Build or verify a portable research ZIP.")
    package_sub = package.add_subparsers(dest="action", required=True)
    build = package_sub.add_parser("build")
    common(build)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--as-of")
    build.add_argument("--version-policy", choices=VERSION_POLICIES, default="all")
    build.add_argument("--no-raw-evidence", action="store_true")
    build.add_argument("--include-conference", action="store_true")
    build.add_argument("--conference-root", type=Path)
    build.set_defaults(func=command_research_package)
    verify = package_sub.add_parser("verify")
    verify.add_argument("path", type=Path)
    verify.set_defaults(func=command_research_package)

    cloud = sub.add_parser("cloud-sync", help="Optional GCS/Firestore sync (disabled unless HISTORICAL_CLOUD_SYNC_ENABLED=true).")
    common(cloud, years=False)
    cloud.add_argument("action", choices=("plan", "run", "status"))
    cloud.add_argument("--ticker", required=True)
    cloud.add_argument("--execute", action="store_true", help="Required with 'run'; otherwise run is a dry-run plan.")
    cloud.set_defaults(func=command_cloud_sync)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
