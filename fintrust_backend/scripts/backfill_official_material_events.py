from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.official_event_models import MaterialEventRecord
from app.services.analysis_repository import AnalysisRepository, build_analysis_repository
from app.services.official_event_sources import (
    build_material_event_metadata,
    build_twse_material_event_metadata,
    is_persistable_material_event,
    material_event_identity,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or execute an idempotent official material-event backfill."
    )
    parser.add_argument("--ticker", required=True, help="Registered semiconductor ticker, e.g. 2454.")
    parser.add_argument("--year", action="append", type=int, default=[], help="Calendar year to query from MOPS. Repeatable.")
    parser.add_argument("--start-date", default=None, help="Inclusive YYYY-MM-DD date filter.")
    parser.add_argument("--end-date", default=None, help="Inclusive YYYY-MM-DD date filter.")
    parser.add_argument("--max-items", type=int, default=10)
    parser.add_argument("--fetch-details", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Plan only; do not write.")
    mode.add_argument("--execute", action="store_true", help="Persist discovered real official events.")
    return parser.parse_args()


def _in_date_range(record: MaterialEventRecord, *, start_date: str | None, end_date: str | None) -> bool:
    event_date = record.event_date or ""
    if start_date and event_date < start_date:
        return False
    if end_date and event_date > end_date:
        return False
    return True


def _dedupe(records: list[MaterialEventRecord]) -> tuple[list[MaterialEventRecord], int]:
    output: list[MaterialEventRecord] = []
    seen: set[str] = set()
    duplicates = 0
    for record in records:
        identity = material_event_identity(record)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        output.append(record.model_copy(update={"event_id": identity}))
    return output, duplicates


def plan_material_event_backfill(
    *,
    ticker: str,
    years: list[int],
    start_date: str | None = None,
    end_date: str | None = None,
    max_items: int = 10,
    fetch_details: bool = False,
    repository: AnalysisRepository | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    repository = repository or build_analysis_repository()
    source_attempts: list[dict[str, Any]] = []
    discovered: list[MaterialEventRecord] = []
    diagnostics: list[MaterialEventRecord] = []

    try:
        twse_records = build_twse_material_event_metadata(ticker, max_items=max_items)
        source_attempts.append({"source": "twse_openapi", "status": "completed", "record_count": len(twse_records)})
        discovered.extend(twse_records)
    except Exception as exc:  # pragma: no cover - live network availability varies.
        source_attempts.append({"source": "twse_openapi", "status": "error", "error": str(exc)})

    for year in years:
        try:
            mops_records = build_material_event_metadata(
                ticker,
                year=year,
                fetch_live=True,
                fetch_details=fetch_details,
                max_items=max_items,
            )
            source_attempts.append({"source": "mops", "year": year, "status": "completed", "record_count": len(mops_records)})
            discovered.extend(mops_records)
        except Exception as exc:  # pragma: no cover - live network availability varies.
            source_attempts.append({"source": "mops", "year": year, "status": "error", "error": str(exc)})

    filtered = [record for record in discovered if _in_date_range(record, start_date=start_date, end_date=end_date)]
    real_records = [record for record in filtered if is_persistable_material_event(record)]
    diagnostics = [record for record in filtered if not is_persistable_material_event(record)]
    real_records, duplicate_discovered = _dedupe(real_records)

    existing = repository.list_material_events(ticker, limit=500)
    existing_ids = {material_event_identity(record) for record in existing}
    create_or_update = [record for record in real_records if material_event_identity(record) not in existing_ids]
    already_persisted = [record for record in real_records if material_event_identity(record) in existing_ids]

    persisted = {"material_events": 0, "investor_conferences": 0}
    if execute and real_records:
        persisted = repository.save_official_events(
            ticker=ticker,
            investor_conferences=[],
            material_events=real_records,
            refreshed_at=datetime.now(timezone.utc),
        )

    return {
        "ticker": ticker,
        "execute": execute,
        "dry_run": not execute,
        "period": {"years": years, "start_date": start_date, "end_date": end_date},
        "sources_attempted": source_attempts,
        "records_discovered": len(discovered),
        "available_records": len(real_records),
        "diagnostic_records_not_persistable": len(diagnostics),
        "duplicates_discovered": duplicate_discovered,
        "already_persisted": len(already_persisted),
        "would_persist": len(real_records) if not execute else 0,
        "would_create_or_update": len(create_or_update) if not execute else 0,
        "persisted": persisted,
        "records": [record.model_dump(mode="json") for record in real_records],
        "diagnostics": [record.model_dump(mode="json") for record in diagnostics],
    }


def main() -> None:
    args = parse_args()
    execute = bool(args.execute)
    report = plan_material_event_backfill(
        ticker=args.ticker,
        years=args.year,
        start_date=args.start_date,
        end_date=args.end_date,
        max_items=args.max_items,
        fetch_details=args.fetch_details,
        execute=execute,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
