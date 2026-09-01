from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.analysis_repository import build_analysis_repository
from app.services.official_event_ingestion import OfficialEventIngestionService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = BACKEND_ROOT / "data" / "demo-output" / "official-events-refresh-smoke.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live official event refresh smoke against configured official sources.")
    parser.add_argument("--ticker", default="2454")
    parser.add_argument("--material-event-year", type=int, default=None)
    parser.add_argument("--no-extract-documents", action="store_true")
    parser.add_argument("--no-material-details", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--no-output", action="store_true")
    return parser.parse_args()


def _counts_by_status(items: list[Any], status_attr: str = "status") -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(getattr(item, status_attr, "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> None:
    args = parse_args()
    repository = build_analysis_repository()
    result = OfficialEventIngestionService(repository=repository).refresh_company(
        args.ticker,
        material_event_year=args.material_event_year,
        extract_documents=not args.no_extract_documents,
        material_fetch_details=not args.no_material_details,
    )
    payload = result.model_dump(mode="json")
    payload["repository_backend"] = getattr(repository, "backend_name", "unknown")
    payload["conference_status_counts"] = _counts_by_status(result.investor_conferences)
    payload["conference_extract_status_counts"] = _counts_by_status(result.investor_conferences, "document_extract_status")
    payload["material_event_status_counts"] = _counts_by_status(result.material_events)
    payload["persisted_readback"] = {
        "investor_conferences": len(repository.list_investor_conferences(result.ticker)),
        "material_events": len(repository.list_material_events(result.ticker)),
    }
    if not args.no_output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["output_file"] = str(output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
