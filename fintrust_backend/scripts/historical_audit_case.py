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
from app.services.historical_audit.export import export_historical_facts
from app.services.historical_audit.quality import quality_report
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
