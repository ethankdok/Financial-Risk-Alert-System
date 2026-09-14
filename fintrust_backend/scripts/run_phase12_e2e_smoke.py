from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.analysis_repository import build_analysis_repository
from app.services.official_document_extraction import enrich_conferences_with_document_extraction
from app.services.official_event_sources import build_investor_conference_metadata, build_material_event_metadata
from app.services.text_intelligence import FinancialTextIntelligenceService, documents_from_official_events
from app.services.unified_analysis_orchestrator import UnifiedAnalysisOrchestrator


def _source_classification(record: Any) -> str:
    status = getattr(record, "status", "")
    source_name = str(getattr(record, "source_name", ""))
    document_url = getattr(record, "document_url", None) or getattr(record, "detail_url", None)
    extract_status = getattr(record, "document_extract_status", "")
    if status == "blocked_by_source" or extract_status == "blocked_by_source":
        return "BLOCKED_BY_SOURCE"
    if status == "error":
        return "NETWORK_ERROR"
    if source_name == "company_official_ir" and status == "available":
        return "OFFICIAL_COMPANY_IR"
    if document_url and status == "available":
        return "OFFICIAL_DOCUMENT_LINK"
    if status == "available":
        return "LIVE_OFFICIAL_DATA"
    if "seeded" in extract_status or any("search-index fallback" in item for item in getattr(record, "limitations", [])):
        return "SEEDED_INDEX_FALLBACK"
    if status in {"metadata_only", "needs_manual_review"}:
        return "METADATA_ONLY"
    return "NO_DATA"


def _event_report(record: Any, text_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ticker": getattr(record, "ticker", None),
        "source_type": "investor_conference" if hasattr(record, "conference_date") else "material_event",
        "source_name": getattr(record, "source_name", None),
        "source_url": getattr(record, "source_url", None),
        "document_url": getattr(record, "document_url", None) or getattr(record, "detail_url", None),
        "source_status": getattr(record, "status", None),
        "source_classification": _source_classification(record),
        "document_kind": getattr(record, "document_title", None) or getattr(record, "category", None),
        "extraction_status": getattr(record, "document_extract_status", None) or getattr(record, "status", None),
        "text_length": getattr(record, "document_full_text_length", None)
        or getattr(record, "document_text_length", None)
        or len(getattr(record, "raw_text", "") or ""),
        "sentence_count": (text_analysis or {}).get("candidate_sentence_count", 0),
        "relevant_sentence_count": (text_analysis or {}).get("relevant_sentence_count", 0),
        "topics": getattr(record, "extracted_topics", None) or [getattr(record, "category", None)],
        "evidence_ids": [sentence["evidence_id"] for sentence in (text_analysis or {}).get("sentences", []) if sentence.get("relevant")],
        "period": getattr(record, "conference_date", None) or getattr(record, "event_date", None),
        "limitations": getattr(record, "limitations", []),
    }


async def run_smoke(tickers: list[str], *, output: Path, include_gemini: bool) -> dict[str, Any]:
    os.environ.setdefault("DATASTORE_BACKEND", "sqlite")
    os.environ.setdefault("FINANCIAL_DATABASE_PATH", str(ROOT / "data" / "phase12-smoke.sqlite3"))
    repository = build_analysis_repository()
    text_service = FinancialTextIntelligenceService()
    report: dict[str, Any] = {
        "schema_version": "phase12-source-provenance-v1.0",
        "datastore_backend": repository.backend_name,
        "include_gemini": include_gemini,
        "companies": [],
    }
    for ticker in tickers:
        company_report: dict[str, Any] = {"ticker": ticker, "stages": [], "sources": []}
        try:
            conferences = build_investor_conference_metadata(ticker, fetch_live=True)
            conferences, extraction_results, extraction_debug = enrich_conferences_with_document_extraction(conferences)
            materials = build_material_event_metadata(ticker, fetch_live=True, fetch_details=True)
            documents = documents_from_official_events(ticker=ticker, conferences=conferences, material_events=materials)
            text_analysis = text_service.analyze_documents(documents)
            by_document = {document.document_id: document.model_dump(mode="json") for document in text_analysis.documents}
            company_report["stages"].extend(
                [
                    {"name": "official_acquisition", "status": "PASS" if conferences or materials else "NO_DATA"},
                    {"name": "document_extraction", "status": "PASS" if any(item.extract_status == "text_extracted" for item in extraction_results) else "PARTIAL", "debug": extraction_debug},
                    {"name": "text_intelligence", "status": "PASS" if text_analysis.documents else "NO_DATA", "semantic": text_analysis.semantic_analysis},
                ]
            )
            for record in [*conferences, *materials]:
                doc_id = getattr(record, "event_id", None)
                company_report["sources"].append(_event_report(record, by_document.get(doc_id)))
            if ticker == "2454":
                unified = await UnifiedAnalysisOrchestrator(repository=repository, text_service=text_service).refresh_company(
                    ticker,
                    include_gemini=include_gemini,
                )
                company_report["unified"] = unified.model_dump(mode="json")
        except Exception as exc:
            company_report["stages"].append({"name": "phase12_smoke", "status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)})
        report["companies"].append(company_report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded Phase 12 local E2E smoke and source provenance report.")
    parser.add_argument("--tickers", default="2454", help="Comma-separated tickers. 2454 is the primary reference.")
    parser.add_argument("--output", default="reports/phase12-2454-smoke-report.json")
    parser.add_argument("--include-gemini", action="store_true", help="Attempt one configured Gemini/LLM path through existing service.")
    args = parser.parse_args()
    tickers = [item.strip() for item in args.tickers.split(",") if item.strip()]
    report = asyncio.run(run_smoke(tickers, output=Path(args.output), include_gemini=args.include_gemini))
    print(json.dumps({"output": args.output, "companies": len(report["companies"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
