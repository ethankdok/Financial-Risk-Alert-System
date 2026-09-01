from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.official_company_ir_sources import build_official_ir_fallback_metadata
from app.services.official_document_extraction import enrich_conferences_with_document_extraction
from app.services.official_event_sources import build_investor_conference_metadata

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = BACKEND_ROOT / "data" / "demo-output" / "investor-conference-summary.json"
DEFAULT_DEBUG_DIR = BACKEND_ROOT / "data" / "demo-output" / "mops-conference-debug"


def _load_debug_summary(ticker: str, debug_dir: Path) -> dict[str, Any] | None:
    path = debug_dir / f"mops-conference-{ticker}-debug.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic only
        return {"error": f"Unable to read debug summary: {exc}", "debug_summary_file": str(path)}


def _records_are_available(records: list) -> bool:
    return any(getattr(record, "status", None) == "available" for record in records)


def build_payload(
    *,
    tickers: list[str],
    fetch_live: bool,
    extract_documents: bool = False,
    debug_dir: str | Path | None = None,
) -> dict[str, Any]:
    results = []
    failures = []
    debug_path = Path(debug_dir) if debug_dir is not None else DEFAULT_DEBUG_DIR
    for ticker in tickers:
        try:
            records = build_investor_conference_metadata(
                ticker,
                fetch_live=fetch_live,
                debug_dir=debug_path if fetch_live else None,
            )
            mops_records = records
            debug_summary = _load_debug_summary(ticker, debug_path) if fetch_live else None
            official_ir_debug = None
            fallback_used = False
            fallback_source = None
            if fetch_live and not _records_are_available(records):
                fallback_records, official_ir_debug = build_official_ir_fallback_metadata(
                    ticker,
                    debug_dir=debug_path,
                )
                if _records_are_available(fallback_records):
                    records = fallback_records
                    fallback_used = True
                    fallback_source = "official_company_ir"

            document_debug = None
            document_results = []
            if extract_documents and _records_are_available(records):
                records, document_results, document_debug = enrich_conferences_with_document_extraction(
                    records,
                    debug_dir=debug_path,
                )

            results.append(
                {
                    "ticker": ticker,
                    "company_name": records[0].company_name if records else None,
                    "subindustry": records[0].subindustry if records else None,
                    "record_count": len(records),
                    "records": [record.model_dump(mode="json") for record in records],
                    "status": "available" if _records_are_available(records) else "metadata_only",
                    "document_links_found": [record.document_url for record in records if record.document_url],
                    "document_extract_statuses": [record.document_extract_status for record in records],
                    "text_preview_count": sum(1 for record in records if record.document_text_preview),
                    "claim_count": sum(len(record.disclosure_claims) for record in records),
                    "document_extraction_count": len(document_results),
                    "text_extracted_count": sum(1 for item in document_results if item.extract_status == "text_extracted"),
                    "download_failed_count": sum(1 for item in document_results if item.extract_status == "download_failed"),
                    "document_blocked_count": sum(1 for item in document_results if item.extract_status == "blocked_by_source"),
                    "mops_status": "available" if _records_are_available(mops_records) else "metadata_only",
                    "fallback_used": fallback_used,
                    "fallback_source": fallback_source,
                    "fallback_mode": (official_ir_debug or {}).get("fallback_mode") if fallback_used else None,
                    "blocked_by_source": bool((official_ir_debug or {}).get("blocked_by_source")),
                    "live_debug": debug_summary,
                    "official_ir_debug": official_ir_debug,
                    "document_debug": document_debug,
                }
            )
        except Exception as exc:  # pragma: no cover - live smoke diagnostic path
            failures.append(f"{ticker}: {exc}")
            results.append({"ticker": ticker, "status": "failed", "error": str(exc)})
    return {
        "phase": "phase4_investor_conference_content_mvp",
        "fetch_live": fetch_live,
        "extract_documents": extract_documents,
        "debug_dir": str(debug_path) if fetch_live else None,
        "teacher_alignment": [
            "年度財報之外，開始讀取法說會 metadata / HTML preview / 附件連結",
            "MOPS 法說會仍是優先來源；若 MOPS 回 shell/no-data，Phase 4 會暫用公司官方 IR 頁面作 fallback",
            "若公司官方 IR 於 Codespaces 回 403，改用 source-labelled search-index fallback，不把 blocked source 假裝成 live fetch 成功",
            "文件抽取層會嘗試下載 PDF / transcript / HTML，失敗時保留 download_failed 或 blocked_by_source debug，不阻斷整體 demo",
            "法說會只作為官方文字證據，不覆蓋 deterministic 財報規則結果",
            "Gemini 後續可針對 disclosure_claims 與財報指標做 evidence-grounded 摘要",
        ],
        "results": results,
        "failures": failures,
        "result": "PASS" if not failures else "WARN",
    }


def write_payload(payload: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 4 investor conference smoke.")
    parser.add_argument("--tickers", nargs="+", default=["2330", "2303", "2454", "3711"])
    parser.add_argument("--fetch-live", action="store_true", help="Attempt live MOPS HTML fetch and save parser debug artifacts.")
    parser.add_argument("--extract-documents", action="store_true", help="Attempt document/PDF/transcript extraction for discovered official links.")
    parser.add_argument("--debug-dir", default=str(DEFAULT_DEBUG_DIR), help="Directory for sanitized live MOPS HTML/debug artifacts.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--no-output", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_payload(
        tickers=[str(ticker) for ticker in args.tickers],
        fetch_live=args.fetch_live,
        extract_documents=args.extract_documents,
        debug_dir=args.debug_dir,
    )
    if not args.no_output:
        output_path = write_payload(payload, args.output)
        payload["output_file"] = str(output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
