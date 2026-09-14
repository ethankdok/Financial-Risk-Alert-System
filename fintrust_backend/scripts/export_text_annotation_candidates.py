from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.analysis_repository import build_analysis_repository
from app.services.text_intelligence import (
    FinancialTextIntelligenceService,
    documents_from_official_events,
    export_annotation_candidates_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export sentence-level annotation candidates from persisted official evidence.")
    parser.add_argument("--ticker", required=True, help="Company ticker, e.g. 2454")
    parser.add_argument("--output", required=True, help="CSV output path")
    args = parser.parse_args()

    repository = build_analysis_repository()
    documents = documents_from_official_events(
        ticker=args.ticker,
        conferences=repository.list_investor_conferences(args.ticker),
        material_events=repository.list_material_events(args.ticker),
    )
    analysis = FinancialTextIntelligenceService().analyze_documents(documents, include_irrelevant_sentences=True)
    sentences = [sentence for document in analysis.documents for sentence in document.sentences]
    Path(args.output).write_text(export_annotation_candidates_csv(sentences), encoding="utf-8")
    print(f"exported {len(sentences)} candidate sentences to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

