from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.analysis_repository import build_analysis_repository
from app.services.official_evidence_service import OfficialEvidenceService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = BACKEND_ROOT / "data" / "demo-output" / "official-evidence-summary.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build official evidence aggregate metadata for demos.")
    parser.add_argument("--ticker", default="2330")
    parser.add_argument("--material-event-year", type=int, default=2024)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    repository = build_analysis_repository()
    evidence = OfficialEvidenceService(repository=repository).build(
        args.ticker,
        material_event_year=args.material_event_year,
    )
    payload = evidence.model_dump(mode="json")
    payload["repository_backend"] = getattr(repository, "backend_name", "unknown")
    payload["financial_snapshot_present"] = payload.get("financial_snapshot") is not None
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["output_file"] = str(output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
