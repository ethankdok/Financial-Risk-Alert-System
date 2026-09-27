"""Build a metadata-only feasibility matrix for MOPS presentation calibration.

The input is the discovery-only report from ``discover_conference_sources``.
No PDFs or extracted text are read here. Files are grouped by a per-row metadata
class, never by an asserted document type, so all periods and pairs are
*potential* calibration candidates; PDF identity, SHA duplicate
checks, ``jsd_ready`` and teammate quality filters are still unverified.

Run from fintrust_backend:
  python -m scripts.build_conference_feasibility --discovery ../docs/data/conference-pdf-discovery-2017-2025.json \
      --output-json ../docs/data/conference-pdf-feasibility-2017-2025.json \
      --output-md ../docs/data/conference-pdf-feasibility-2017-2025.md
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

TARGET_PAIR = ("2025Q2", "2025Q3")
HISTORY_BEFORE = "2025Q2"
FEASIBLE_MIN = 30
BORDERLINE_MIN = 24
TARGET_TICKERS = ("2330", "2454", "2303", "3711", "2379", "3034", "2408", "2344", "6770", "2340")
# Metadata classes. Listing metadata never decides earnings_presentation vs
# financial_results_release; that comes from PDF identity (conference_document_identity).
QUARTERLY_CANDIDATE = "quarterly_results_candidate"
INVITED_ONLY = "invited_event_only"
NEEDS_PDF_IDENTITY = "needs_pdf_identity_inspection"
STAGED_VALIDATION_CLASSES = {QUARTERLY_CANDIDATE}

PERIOD_RE = re.compile(r"^(20\d{2})Q([1-4])$")
# A company's own periodic results announcement (one listing row).
PERIODIC_ROW_RE = re.compile(
    r"財務報告|財務暨營運報告|營運報告|業績展望|營運狀況說明|營運成果|第.{1,3}季.{0,6}法人說明會|季度?法人說明會|"
    r"quarterly\s+results|earnings\s+(?:call|conference|release)",
    re.I,
)
# Conference-usage context: a row announcing attendance at someone else's event,
# or an investor day / forum. Such a row never defines what the document is.
EVENT_ROW_RE = re.compile(
    r"受邀|應邀|invited|(?:^|[。，,；;\s])(?:公告)?本公司(?:將|於|\d)[^。，,；;]{0,40}參加(?!者)|"
    r"investor\s+(?:forum|day)|座談會|巡迴說明會",
    re.I,
)


def quarter_index(period: str) -> int:
    match = PERIOD_RE.fullmatch(str(period or ""))
    if not match:
        raise ValueError(f"Invalid fiscal quarter: {period}")
    return int(match.group(1)) * 4 + int(match.group(2)) - 1


def language_scope(language: str | None) -> str:
    return {"zh": "zh-Hant", "zh-Hant": "zh-Hant", "en": "en"}.get(str(language or "").strip(), "unknown")


def classify_listing_document(document: dict[str, Any]) -> dict[str, Any]:
    """Metadata class and potential period of one listed file, judged row by row.

    MOPS lists one file on several rows when a quarterly deck is reused at later
    investor forums. Document identity comes from the company's own periodic
    row; later event rows are usage context and never reclassify the file.
    """
    from app.services.conference_document_identity import claimed_period_from_listing

    rows = [str(item or "") for item in document.get("listing_summaries") or []]
    periodic = [row for row in rows if PERIODIC_ROW_RE.search(row) and not EVENT_ROW_RE.search(row)]
    events = [row for row in rows if EVENT_ROW_RE.search(row)]
    if periodic:
        _single, claims = claimed_period_from_listing(periodic)
        if len(claims) == 1:
            return {"metadata_class": QUARTERLY_CANDIDATE, "period": claims[0],
                    "period_basis": "periodic_row", "method": "listing_row:periodic_results"}
        if len(claims) > 1:
            return {"metadata_class": NEEDS_PDF_IDENTITY, "period": None, "period_basis": "conflicting_periodic_rows",
                    "method": "listing_row:periodic_results_conflict", "period_claims": claims}
        fallback = document.get("period_claimed_by_listing")
        if fallback:
            # e.g. an annual self-settled report row whose Q4 is named only on the file's other rows.
            return {"metadata_class": QUARTERLY_CANDIDATE, "period": fallback,
                    "period_basis": "other_listing_rows", "method": "listing_row:periodic_results"}
        return {"metadata_class": NEEDS_PDF_IDENTITY, "period": None, "period_basis": "none",
                "method": "listing_row:periodic_results_without_period"}
    if rows and len(events) == len(rows):
        return {"metadata_class": INVITED_ONLY, "period": None, "period_basis": "none",
                "method": "listing_row:event_only"}
    return {"metadata_class": NEEDS_PDF_IDENTITY, "period": None, "period_basis": "none",
            "method": "listing_row:unclassified"}


def adjacent_pairs(periods: set[str], *, before: str | None = None) -> list[dict[str, str]]:
    by_index = {quarter_index(period): period for period in periods}
    before_index = quarter_index(before) if before else None
    pairs = []
    for index in sorted(by_index):
        nxt = index + 1
        if nxt not in by_index:
            continue
        if before_index is not None and nxt >= before_index:
            continue
        pairs.append({"period_1": by_index[index], "period_2": by_index[nxt]})
    return pairs


def missing_between(periods: set[str]) -> list[str]:
    if not periods:
        return []
    indices = {quarter_index(period) for period in periods}
    return [
        f"{index // 4}Q{index % 4 + 1}"
        for index in range(min(indices), max(indices) + 1)
        if index not in indices
    ]


def status_for(pair_count: int) -> str:
    if pair_count >= FEASIBLE_MIN:
        return "FEASIBLE"
    if pair_count >= BORDERLINE_MIN:
        return "BORDERLINE"
    return "INSUFFICIENT"


def staged_validation_blockers(*, classification: str, metadata_class: str, language: str,
                               target_present: bool) -> list[str]:
    """Blockers for staged PDF identity validation (never a direct full backfill)."""
    reasons = []
    if classification != "FEASIBLE":
        reasons.append("scope_not_feasible")
    if metadata_class not in STAGED_VALIDATION_CLASSES:
        reasons.append(f"metadata_class_{metadata_class}")
    if language != "en":
        reasons.append("non_english_scope_not_active_for_current_method")
    if not target_present:
        reasons.append("preferred_target_pair_not_present")
    return reasons


def build_matrix(discovery: dict[str, Any], *, target_tickers: tuple[str, ...] = TARGET_TICKERS) -> dict[str, Any]:
    companies = {item["ticker"]: item for item in discovery.get("companies", [])}
    scopes: list[dict[str, Any]] = []
    for ticker in target_tickers:
        company = companies.get(ticker, {"ticker": ticker, "documents": [], "years": {}})
        slots: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        undated: dict[tuple[str, str], list[str]] = defaultdict(list)
        methods: dict[tuple[str, str], set[str]] = defaultdict(set)
        fallback_periods: dict[tuple[str, str], int] = defaultdict(int)
        for document in company.get("documents", []):
            identity = classify_listing_document(document)
            key = (identity["metadata_class"], language_scope(document.get("language")))
            methods[key].add(identity["method"])
            period = identity["period"]
            if not period or not PERIOD_RE.fullmatch(period):
                undated[key].append(document["filename"])
                continue
            slots[key][period].append(document)
            if identity["period_basis"] == "other_listing_rows":
                fallback_periods[key] += 1
        # Official quarterly files that MOPS holds only in a non-PDF format (e.g. .pptx):
        # a source gap for this PDF-text method, never a potential period.
        non_pdf_gaps: dict[tuple[str, str], set[str]] = defaultdict(set)
        for gap in company.get("non_pdf_attachments", []):
            identity = classify_listing_document(gap)
            if identity["period"]:
                non_pdf_gaps[(identity["metadata_class"], language_scope(gap.get("language")))].add(identity["period"])
        listing_years = company.get("years") or {}
        failed_years = {year: info.get("error") for year, info in listing_years.items()
                        if info.get("status") not in {"ok", "no_listing"}}
        no_listing_years = sorted(year for year, info in listing_years.items() if info.get("status") == "no_listing")

        for key in sorted(set(slots) | set(undated) | set(non_pdf_gaps)):
            metadata_class, language = key
            by_period = slots.get(key, {})
            periods = set(by_period)
            duplicate_periods = [
                {"period": period, "filenames": sorted(doc["filename"] for doc in docs)}
                for period, docs in sorted(by_period.items())
                if len(docs) > 1
            ]
            history_pairs = adjacent_pairs(periods, before=HISTORY_BEFORE)
            all_pairs = adjacent_pairs(periods)
            target_present = all(period in periods for period in TARGET_PAIR)
            warnings = [
                "metadata_only: document_type, document period, SHA duplicates, jsd_ready and text quality are unverified",
            ]
            if duplicate_periods:
                warnings.append("duplicate_metadata_candidates_require_pdf_identity_resolution")
            if fallback_periods[key]:
                warnings.append("some_periods_taken_from_other_listing_rows_of_the_same_file")
            if failed_years:
                warnings.append("some_listing_years_failed_discovery")
            gap_periods = sorted(non_pdf_gaps.get(key, set()) - periods, key=quarter_index)
            if gap_periods:
                warnings.append("some_quarters_exist_only_as_non_pdf_official_files")
            classification = status_for(len(history_pairs))
            blockers = staged_validation_blockers(classification=classification, metadata_class=metadata_class,
                                                  language=language, target_present=target_present)
            scopes.append({
                "ticker": ticker,
                "company": company.get("company"),
                "industry": company.get("industry"),
                "metadata_class": metadata_class,
                "document_type": "pending_pdf_identity",
                "language": language,
                "classification": classification,
                "staged_identity_validation_eligible": not blockers,
                "staged_identity_validation_blockers": blockers,
                "potential_historical_adjacent_pairs_before_target": len(history_pairs),
                "potential_adjacent_pairs_all_discovered_periods": len(all_pairs),
                "target_pair": {"period_1": TARGET_PAIR[0], "period_2": TARGET_PAIR[1], "potentially_present": target_present},
                "years_represented": sorted(listing_years),
                "periods_represented": sorted(periods, key=quarter_index),
                "missing_quarters_between_first_and_last": missing_between(periods),
                "duplicate_candidate_periods": duplicate_periods,
                "period_conflicts": [
                    {"filename": doc["filename"], "periods": doc.get("period_claims_all") or []}
                    for docs in by_period.values()
                    for doc in docs
                    if len(doc.get("period_claims_all") or []) > 1
                ],
                "candidate_documents": sum(len(docs) for docs in by_period.values()),
                "documents_without_potential_period": len(undated.get(key, [])),
                "periods_from_other_listing_rows": fallback_periods[key],
                "non_pdf_source_gap_periods": gap_periods,
                "classification_methods": sorted(methods[key]),
                "failed_listing_years": failed_years,
                "no_listing_years": no_listing_years,
                "warnings": warnings,
            })
    return {
        "schema_version": "fintrust.conference_pdf_feasibility.v2",
        "source": "metadata-only MOPS t100sb02_1 discovery; no PDFs or text used",
        "discovery_source_policy": discovery.get("source_policy"),
        "target_pair": {"period_1": TARGET_PAIR[0], "period_2": TARGET_PAIR[1]},
        "history_rule": "potential adjacent pairs where period_2 < 2025Q2",
        "metadata_classes": {
            QUARTERLY_CANDIDATE: "file has a company-issued periodic results row; later event rows are usage context",
            INVITED_ONLY: "every listing row announces attendance at an event (forum, broker conference, investor day)",
            NEEDS_PDF_IDENTITY: "listing text cannot establish identity or period; PDF inspection required",
        },
        "classification_thresholds": {
            "FEASIBLE": f">={FEASIBLE_MIN} potential historical adjacent pairs",
            "BORDERLINE": f"{BORDERLINE_MIN}-{FEASIBLE_MIN - 1}",
            "INSUFFICIENT": f"<{BORDERLINE_MIN}",
        },
        "important_limitations": [
            "All pairs are potential metadata-derived pairs, not confirmed calibration pairs.",
            "Metadata never decides earnings_presentation vs financial_results_release; PDF identity does.",
            "PDF processing must still validate document_type, fiscal period, SHA duplication, jsd_ready and teammate data quality.",
            "Only FEASIBLE English quarterly_results_candidate scopes may proceed, and only to staged PDF identity validation.",
        ],
        "scopes": scopes,
    }


def to_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# MOPS Presentation Calibration Feasibility",
        "",
        "Metadata only: no PDFs, full text, SHA identity checks or teammate quality checks are used.",
        "Counts below are potential adjacent-quarter pairs before 2025Q2. Exact document types come from PDF identity.",
        "",
        "| Ticker | Company | Metadata class / language | Periods | Missing | Duplicates | Potential history pairs | Target 2025Q2→2025Q3 | Status | Staged validation |",
        "|---|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    for item in matrix["scopes"]:
        lines.append(
            f"| {item['ticker']} | {item.get('company') or ''} | "
            f"{item['metadata_class']} / {item['language']} | {len(item['periods_represented'])} | "
            f"{len(item['missing_quarters_between_first_and_last'])} | {len(item['duplicate_candidate_periods'])} | "
            f"{item['potential_historical_adjacent_pairs_before_target']} | "
            f"{'yes' if item['target_pair']['potentially_present'] else 'no'} | {item['classification']} | "
            f"{'yes' if item['staged_identity_validation_eligible'] else 'no'} |"
        )
    lines += ["", "## Listing years not usable", ""]
    seen = set()
    for item in matrix["scopes"]:
        if item["ticker"] in seen:
            continue
        seen.add(item["ticker"])
        for year, error in sorted(item["failed_listing_years"].items()):
            lines.append(f"- {item['ticker']} {year}: failed — {error}")
        for year in item["no_listing_years"]:
            lines.append(f"- {item['ticker']} {year}: no official listing")
    lines += ["", "## Notes", ""]
    for item in matrix["scopes"]:
        if item["classification"] != "INSUFFICIENT" or item["duplicate_candidate_periods"]:
            blockers = (
                f" Blockers: {', '.join(item['staged_identity_validation_blockers'])}."
                if item["staged_identity_validation_blockers"] else " Eligible for staged PDF identity validation."
            )
            lines.append(
                f"- {item['ticker']} {item['metadata_class']} / {item['language']}: "
                f"{'; '.join(item['warnings'])}.{blockers}"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    matrix = build_matrix(json.loads(args.discovery.read_text(encoding="utf-8")))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(to_markdown(matrix), encoding="utf-8")
    print(json.dumps({
        "scopes": len(matrix["scopes"]),
        "feasible": sum(1 for item in matrix["scopes"] if item["classification"] == "FEASIBLE"),
        "borderline": sum(1 for item in matrix["scopes"] if item["classification"] == "BORDERLINE"),
        "insufficient": sum(1 for item in matrix["scopes"] if item["classification"] == "INSUFFICIENT"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
