"""Coverage matrix for multi-company official conference documents (metadata only).

Combines the discovery report with JSD-adapter records from the configured
archive repository. The output contains no document text, so it can be
committed; the full-text corpus export goes to a gitignored directory.

Run from fintrust_backend:
  python -m scripts.build_conference_coverage --discovery <discovery.json> \\
      --archive-root data/official-ir-pdfs-live-test --tickers 2330,2454 \\
      --output-json <coverage.json> --output-md <coverage.md> \\
      [--corpus-dir data/jsd-corpus] [--gcs-report <ticker>=<migration.json> ...]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.services.conference_jsd_corpus_adapter import build_records, comparable_pairs, export_corpus
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository


def company_row(ticker: str, discovery: dict | None, records: list, gcs: dict | None) -> dict:
    pairs = comparable_pairs(records)
    ready = [item for item in records if item.jsd_ready]
    quarantined = [item for item in records if item.provenance.get("quarantined")]
    not_ready = [item for item in records if not item.jsd_ready and not item.provenance.get("quarantined")]
    return {
        "ticker": ticker,
        "company": (records[0].record["company"] if records else (discovery or {}).get("company")),
        "industry": (records[0].record["industry"] if records else (discovery or {}).get("industry")),
        "official_source": "MOPS t100sb02_1 法人說明會簡報 (mopsov.twse.com.tw)",
        "source_pages": sorted({item.record["source_page"] for item in records if item.record["source_page"]}),
        "discovered_documents": (discovery or {}).get("discovered_documents", 0),
        "discovered_listing_periods": (discovery or {}).get("listing_claimed_periods", []),
        "processed_documents": len(records),
        "verified_periods": sorted({item.record["period"] for item in ready}),
        "document_types": dict(Counter(item.record["document_type"] for item in records)),
        "languages": dict(Counter(item.record["language"] for item in records)),
        "jsd_ready_records": len(ready),
        "adjacent_comparable_pairs": len(pairs),
        "transcript_calibration_compatible_pairs": sum(1 for pair in pairs if pair["transcript_calibration_compatible"]),
        "pairs": [{key: pair[key] for key in ("document_type", "language", "period_1", "period_2")} for pair in pairs],
        "quarantined_documents": [{"filename": item.provenance["filename"],
                                   "reasons": item.provenance.get("quarantine_reasons")} for item in quarantined],
        "not_ready_documents": [{"filename": item.provenance["filename"], "issues": item.readiness_issues,
                                 "period_detected_in_document": item.provenance.get("period_detected_in_document"),
                                 "document_type": item.record["document_type"]} for item in not_ready],
        "text_length_range": ([min(item.record["text_length"] for item in ready),
                               max(item.record["text_length"] for item in ready)] if ready else None),
        "discovery_anomalies": (discovery or {}).get("anomalies", []),
        "gcs": gcs,
    }


def to_markdown(rows: list[dict]) -> str:
    lines = [
        "# Official conference-PDF coverage (multi-company)",
        "",
        "Metadata only: no document text. Source: MOPS t100sb02_1 official listing and downloads.",
        "`jsd_ready` = satisfies the JSD input contract; it is not a calibration-suitability claim.",
        "",
        "| Ticker | Company | Industry | Discovered | Processed | Verified periods | Types | Languages | JSD-ready | Adjacent pairs | Transcript-cal pairs | Quarantined | Not ready | GCS objects |",
        "|---|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        gcs = row.get("gcs") or {}
        lines.append(
            f"| {row['ticker']} | {row['company']} | {row['industry']} | {row['discovered_documents']} | "
            f"{row['processed_documents']} | {', '.join(row['verified_periods']) or '—'} | "
            f"{', '.join(f'{k}×{v}' for k, v in row['document_types'].items()) or '—'} | "
            f"{', '.join(f'{k}×{v}' for k, v in row['languages'].items()) or '—'} | {row['jsd_ready_records']} | "
            f"{row['adjacent_comparable_pairs']} | {row['transcript_calibration_compatible_pairs']} | "
            f"{len(row['quarantined_documents'])} | {len(row['not_ready_documents'])} | "
            f"{gcs.get('objects', '—')} |")
    lines += ["", "## Documents that are not JSD-ready or are quarantined", ""]
    for row in rows:
        for item in row["quarantined_documents"]:
            lines.append(f"- {row['ticker']} `{item['filename']}` quarantined: {', '.join(item['reasons'] or [])}")
        for item in row["not_ready_documents"]:
            lines.append(f"- {row['ticker']} `{item['filename']}` ({item['document_type']}): {', '.join(item['issues'])}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--tickers", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--gcs-report", action="append", default=[], help="<ticker>=<migration report json>")
    args = parser.parse_args()
    discovery = {item["ticker"]: item for item in json.loads(args.discovery.read_text(encoding="utf-8"))["companies"]}
    gcs_reports: dict[str, dict] = {}
    for value in args.gcs_report:
        ticker, path = value.split("=", 1)
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        gcs_reports.setdefault(ticker, {"objects": 0, "bytes": 0, "uploaded": 0, "skipped_same_sha256": 0,
                                        "conflicts": 0, "verified": 0})
        entry = gcs_reports[ticker]
        entry["objects"] += report.get("planned", 0)
        entry["bytes"] += report.get("planned_bytes", 0)
        entry["uploaded"] += report.get("uploaded", 0)
        entry["skipped_same_sha256"] += report.get("skipped_same_sha256", 0)
        entry["conflicts"] += len(report.get("conflicts", []))
        entry["verified"] += (report.get("verification") or {}).get("verified", 0)
    repository = FileConferencePdfArchiveRepository(args.archive_root)
    rows, all_records = [], []
    for ticker in [item.strip() for item in args.tickers.split(",") if item.strip()]:
        records = build_records(repository, ticker)
        all_records.extend(records)
        rows.append(company_row(ticker, discovery.get(ticker), records, gcs_reports.get(ticker)))
    payload = {"generated_by": "scripts/build_conference_coverage.py", "companies": rows}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(to_markdown(rows), encoding="utf-8")
    if args.corpus_dir:
        print(json.dumps(export_corpus(all_records, args.corpus_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
