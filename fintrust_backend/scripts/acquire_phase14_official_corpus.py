#!/usr/bin/env python3
"""
Phase 14 Real Corpus Expansion — Acquisition Script

Fetches official disclosure evidence for 2330 / 2303 / 3711 using the
*existing* service architecture.  Does NOT reimplement any scraper or parser.

Hard constraints (per spec):
  • NO production Firestore writes (OfficialEventIngestionService is bypassed entirely)
  • NO Gemini / paid API calls
  • NO demo_fixture provenance mislabeling (real data stays real)
  • Existing 2454 corpus is loaded and merged, NOT rebuilt
  • Only records with truly analyzable full text enter the corpus

Provenance values used:
  "REAL_LIVE_ACQUISITION"      — fetched at run time, full text obtained
  "SEEDED_IR_INDEX_METADATA_ONLY" — from SEEDED_OFFICIAL_IR_INDEX, no full text
  "ACQUISITION_BLOCKED_PROXY"  — cloud proxy returned 403; no data obtained

Usage (from repo root):
    cd fintrust_backend
    python3 scripts/acquire_phase14_official_corpus.py [--dry-run]

Outputs (written to reports/phase14/ beside this repo):
  corpus_expansion_manifest.json   — per-ticker/source acquisition result
  official_text_corpus_expanded.jsonl — 2454 rows + new rows (if any)
  annotation_candidates_expanded.csv — diversified ~400-500 annotation sample
  dataset_manifest_expanded.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]          # fintrust_backend/
REPO_ROOT = ROOT.parent                              # Financial-Risk-Alert-System/
REPORTS_DIR = REPO_ROOT / "reports" / "phase14"
EXISTING_CORPUS = REPORTS_DIR / "official_text_corpus.jsonl"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Imports from existing service layer ──────────────────────────────────────
from app.services.company_registry import get_company
from app.services.official_event_sources import (
    build_investor_conference_metadata,
    build_material_event_metadata,
)
from app.services.official_document_extraction import enrich_conferences_with_document_extraction
from app.services.text_experiments import (
    CANONICAL_TOPICS,
    WEAK_SUPERVISION_LABEL_SOURCE,
    build_phase12_official_corpus,
    corpus_manifest,
    corpus_rows_to_train_ready,
    deduplicate_corpus_rows,
    is_likely_boilerplate,
    normalize_experiment_text,
    stable_text_hash,
    stratified_annotation_sample,
    REQUIRED_ANNOTATION_COLUMNS,
    to_annotation_package_rows,
)

# ─────────────────────────────────────────────────────────────────────────────
EXPANSION_TICKERS = ["2330", "2303", "3711"]
NOW_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
SCRIPT_VERSION = "phase14-corpus-expansion-v1.0"

# Minimum character count for full text to be considered "analyzable"
MIN_FULL_TEXT_CHARS = 200
MIN_SENTENCES_FOR_INCLUSION = 5
MIN_MATERIAL_TITLE_CHARS = 10
FREEZE_MIN_COMPANIES_WITH_TEXT = 2
FREEZE_MAX_COMPANY_CONCENTRATION = 0.80
FREEZE_MIN_TOTAL_ROWS = 50
FREEZE_MIN_CORPUS_DOCUMENTS = 2

FREEZE_GATE_THRESHOLDS = {
    "min_companies_with_substantive_text": FREEZE_MIN_COMPANIES_WITH_TEXT,
    "max_company_concentration": FREEZE_MAX_COMPANY_CONCENTRATION,
    "min_total_sentence_rows": FREEZE_MIN_TOTAL_ROWS,
    "min_usable_documents": FREEZE_MIN_CORPUS_DOCUMENTS,
    "min_sentences_for_company_inclusion": MIN_SENTENCES_FOR_INCLUSION,
}


# ─────────────────────────────────────────────────────────────────────────────
def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_to_dict(record) -> dict[str, Any]:
    """Convert a Pydantic model to a plain dict (handles nested models)."""
    return json.loads(record.model_dump_json())


def _conference_record_diagnostics(record: Any, extraction_by_url: dict[str, dict[str, Any]]) -> dict[str, Any]:
    extraction = extraction_by_url.get(record.document_url or "") if record.document_url else None
    return {
        "title": record.title,
        "source": record.source_name,
        "page_url": record.source_url,
        "document_url": record.document_url,
        "document_kind": (extraction or {}).get("document_kind") or "unknown",
        "http_status": (extraction or {}).get("http_status"),
        "extract_status": record.document_extract_status,
        "full_text_char_count": len(record.document_full_text or ""),
        "error": (extraction or {}).get("error"),
        "corpus_provenance": None,
    }


def _material_event_official_text(record: Any) -> str:
    raw_text = record.raw_text or ""
    if raw_text.strip():
        return raw_text.strip()
    title = (record.title or "").strip()
    if len(title) >= MIN_MATERIAL_TITLE_CHARS and record.status == "available":
        return f"主旨：{title}"
    return ""


def _sentence_count_for_text(text: str) -> int:
    try:
        from app.services.text_intelligence import sentence_segment

        return len(sentence_segment(text))
    except Exception:
        return len([part for part in text.replace("。", ".").split(".") if part.strip()])


def _freeze_gate_result(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ticker_counts = Counter(str(row.get("ticker") or "unknown") for row in rows)
    substantive_counts = {
        ticker: count
        for ticker, count in ticker_counts.items()
        if count >= MIN_SENTENCES_FOR_INCLUSION
    }
    total_rows = len(rows)
    max_company_concentration = max((count / total_rows for count in ticker_counts.values()), default=0.0)
    usable_documents = {
        str(row.get("document_id"))
        for row in rows
        if row.get("document_id") and ticker_counts[str(row.get("ticker") or "unknown")] >= MIN_SENTENCES_FOR_INCLUSION
    }
    checks = {
        "companies_with_substantive_text": len(substantive_counts) >= FREEZE_MIN_COMPANIES_WITH_TEXT,
        "company_concentration": max_company_concentration <= FREEZE_MAX_COMPANY_CONCENTRATION,
        "total_sentence_rows": total_rows >= FREEZE_MIN_TOTAL_ROWS,
        "usable_documents": len(usable_documents) >= FREEZE_MIN_CORPUS_DOCUMENTS,
    }
    passed = all(checks.values())
    return {
        "status": "ANNOTATION_DATASET_FROZEN" if passed else "CORPUS_EXPANSION_PARTIAL",
        "passed": passed,
        "checks": checks,
        "thresholds": FREEZE_GATE_THRESHOLDS,
        "companies_with_substantive_text": sorted(substantive_counts),
        "company_sentence_counts": dict(sorted(ticker_counts.items())),
        "max_company_concentration": round(max_company_concentration, 6),
        "usable_document_count": len(usable_documents),
        "rationale": (
            "Corpus meets project operational diversity thresholds for annotation freeze."
            if passed
            else "Corpus is not frozen because usable text remains too concentrated or insufficiently diverse."
        ),
    }


def acquire_conferences(ticker: str) -> tuple[list[dict], dict]:
    """
    Run investor-conference acquisition for *ticker*.
    Returns (record_dicts, manifest_entry).
    """
    manifest_entry: dict[str, Any] = {
        "ticker": ticker,
        "source_type": "investor_conference",
        "retrieved_at": _utcnow(),
        "retrieval_status": "UNKNOWN",
        "http_status": None,
        "documents_found": 0,
        "documents_with_full_text": 0,
        "documents_extracted": 0,
        "sentence_candidate_count": 0,
        "full_text_available": False,
        "failure_reason": None,
        "record_diagnostics": [],
    }
    records_out: list[dict] = []

    try:
        raw_records = build_investor_conference_metadata(ticker, fetch_live=True)
        manifest_entry["documents_found"] = len(raw_records)

        if not raw_records:
            manifest_entry["retrieval_status"] = "NO_RECORDS_RETURNED"
            manifest_entry["failure_reason"] = (
                "build_investor_conference_metadata returned empty list — "
                "likely all sources blocked or no recent events listed."
            )
            return records_out, manifest_entry

        # Attempt document extraction (PDF/HTML full text)
        try:
            enriched, extraction_results, _debug = enrich_conferences_with_document_extraction(raw_records)
            manifest_entry["documents_extracted"] = len(extraction_results)
            extraction_by_url = {item.document_url: _record_to_dict(item) for item in extraction_results}
        except Exception as exc:
            enriched = raw_records
            extraction_by_url = {}
            manifest_entry["failure_reason"] = f"document extraction error: {exc}"

        for rec in enriched:
            d = _record_to_dict(rec)
            diagnostic = _conference_record_diagnostics(rec, extraction_by_url)
            # Determine provenance
            source_name = rec.source_name or ""
            if "seeded" in source_name.lower() or rec.document_extract_status == "seeded_index":
                d["corpus_provenance"] = "SEEDED_IR_INDEX_METADATA_ONLY"
            elif rec.document_full_text and len(rec.document_full_text) >= MIN_FULL_TEXT_CHARS:
                d["corpus_provenance"] = "REAL_LIVE_ACQUISITION"
                manifest_entry["full_text_available"] = True
                manifest_entry["documents_with_full_text"] += 1
                manifest_entry["sentence_candidate_count"] += _sentence_count_for_text(rec.document_full_text)
            elif rec.status == "blocked_by_source":
                d["corpus_provenance"] = "ACQUISITION_BLOCKED_PROXY"
            else:
                d["corpus_provenance"] = "REAL_LIVE_ACQUISITION_METADATA_ONLY"

            diagnostic["corpus_provenance"] = d["corpus_provenance"]
            manifest_entry["record_diagnostics"].append(diagnostic)
            records_out.append(d)

        any_full_text = manifest_entry["full_text_available"]
        any_blocked = any(r.get("corpus_provenance") == "ACQUISITION_BLOCKED_PROXY" for r in records_out)
        if any_full_text:
            manifest_entry["retrieval_status"] = "PASS_FULL_TEXT"
        elif records_out:
            manifest_entry["retrieval_status"] = (
                "BLOCKED_PROXY_SEEDED_FALLBACK" if any_blocked else "METADATA_ONLY"
            )
        else:
            manifest_entry["retrieval_status"] = "NO_DATA"

    except Exception as exc:
        manifest_entry["retrieval_status"] = "ACQUISITION_ERROR"
        manifest_entry["failure_reason"] = traceback.format_exc()
        print(f"  [ERROR] conference acquisition for {ticker}: {exc}")

    return records_out, manifest_entry


def acquire_material_events(ticker: str) -> tuple[list[dict], dict]:
    """
    Run material-event acquisition for *ticker*.
    Returns (record_dicts, manifest_entry).
    """
    manifest_entry: dict[str, Any] = {
        "ticker": ticker,
        "source_type": "material_event",
        "retrieved_at": _utcnow(),
        "retrieval_status": "UNKNOWN",
        "http_status": None,
        "documents_found": 0,
        "documents_with_full_text": 0,
        "documents_extracted": 0,
        "sentence_candidate_count": 0,
        "full_text_available": False,
        "failure_reason": None,
        "record_diagnostics": [],
    }
    records_out: list[dict] = []

    try:
        raw_records = build_material_event_metadata(
            ticker, year=None, fetch_live=True, fetch_details=True
        )
        manifest_entry["documents_found"] = len(raw_records)

        for rec in raw_records:
            d = _record_to_dict(rec)
            official_text = _material_event_official_text(rec)
            if official_text and official_text != (rec.raw_text or ""):
                d["raw_text"] = official_text
                d["corpus_text_source"] = "official_material_event_title"
            raw_text = official_text
            diagnostic = {
                "title": rec.title,
                "source": rec.source_name,
                "page_url": rec.source_url,
                "document_url": rec.detail_url,
                "document_kind": "html",
                "http_status": None,
                "extract_status": "raw_text_available" if rec.raw_text else "official_title_only" if raw_text else rec.status,
                "full_text_char_count": len(raw_text),
                "error": None,
                "corpus_provenance": None,
            }
            if len(raw_text) >= MIN_FULL_TEXT_CHARS:
                d["corpus_provenance"] = "REAL_LIVE_ACQUISITION"
                manifest_entry["full_text_available"] = True
                manifest_entry["documents_with_full_text"] += 1
                manifest_entry["sentence_candidate_count"] += _sentence_count_for_text(raw_text)
            elif raw_text:
                d["corpus_provenance"] = "REAL_LIVE_ACQUISITION_METADATA_ONLY"
            elif rec.status == "blocked_by_source":
                d["corpus_provenance"] = "ACQUISITION_BLOCKED_PROXY"
            else:
                d["corpus_provenance"] = "REAL_LIVE_ACQUISITION_METADATA_ONLY"
            diagnostic["corpus_provenance"] = d["corpus_provenance"]
            manifest_entry["record_diagnostics"].append(diagnostic)
            records_out.append(d)

        any_full_text = manifest_entry["full_text_available"]
        if any_full_text:
            manifest_entry["retrieval_status"] = "PASS_FULL_TEXT"
        elif records_out:
            manifest_entry["retrieval_status"] = "METADATA_ONLY"
        else:
            manifest_entry["retrieval_status"] = "NO_RECORDS_RETURNED"
            manifest_entry["failure_reason"] = (
                "TWSE OpenAPI and MOPS both returned empty — "
                "likely blocked by cloud container proxy (403)."
            )

    except Exception as exc:
        manifest_entry["retrieval_status"] = "ACQUISITION_ERROR"
        manifest_entry["failure_reason"] = traceback.format_exc()
        print(f"  [ERROR] material event acquisition for {ticker}: {exc}")

    return records_out, manifest_entry


# ─────────────────────────────────────────────────────────────────────────────
def _build_phase12_report_for_ticker(
    ticker: str,
    conference_records: list[dict],
    material_event_records: list[dict],
) -> dict[str, Any]:
    """
    Wrap acquisition results in the Phase 12 report schema expected by
    build_phase12_official_corpus.  Only records that have analyzable text
    (full text >= MIN_FULL_TEXT_CHARS or non-empty raw_text) are included.
    """
    company = get_company(ticker)
    if company is None:
        return {}

    # Filter: only records with truly analyzable text enter the corpus
    analyzable_conferences = [
        r for r in conference_records
        if (
            r.get("corpus_provenance") == "REAL_LIVE_ACQUISITION"
            and (
                (r.get("document_full_text") or "")
                + "".join(
                    e.get("full_text", "") or ""
                    for e in (r.get("document_extractions") or [])
                )
            ).strip()
        )
    ]
    analyzable_material = [
        r for r in material_event_records
        if (
            r.get("corpus_provenance") == "REAL_LIVE_ACQUISITION"
            and len(r.get("raw_text") or "") >= MIN_FULL_TEXT_CHARS
        )
    ]

    return {
        "companies": [
            {
                "ticker": ticker,
                "company_name": company.name,
                "unified": {
                    "official_events_refresh": {
                        "investor_conferences": analyzable_conferences,
                        "material_events": analyzable_material,
                    }
                },
            }
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
def load_existing_corpus() -> list[dict]:
    if not EXISTING_CORPUS.exists():
        print(f"  [WARN] Existing corpus not found: {EXISTING_CORPUS}")
        return []
    rows = []
    with open(EXISTING_CORPUS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    print(f"  Loaded {len(rows)} rows from existing 2454 corpus.")
    return rows


def build_keyword_hit_flag(text: str) -> bool:
    """True if any Phase 14 keyword cluster matches the sentence."""
    from app.services.official_event_sources import (
        CONFERENCE_TOPIC_KEYWORDS,
        MATERIAL_EVENT_KEYWORDS,
    )
    lowered = text.lower()
    for _, kws, _ in list(CONFERENCE_TOPIC_KEYWORDS) + list(MATERIAL_EVENT_KEYWORDS):
        if any(kw.lower() in lowered for kw in kws):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
def run(dry_run: bool = False) -> None:
    print(f"\n{'='*64}")
    print(f"Phase 14 Corpus Expansion — {NOW_ISO}")
    print(f"Tickers: {EXPANSION_TICKERS}")
    print(f"Dry run: {dry_run}")
    print(f"{'='*64}\n")

    acquisition_manifest: list[dict] = []
    all_new_conference_records: dict[str, list[dict]] = {}
    all_new_material_records: dict[str, list[dict]] = {}

    # ── Step 1: Acquire for each ticker ─────────────────────────────────────
    for ticker in EXPANSION_TICKERS:
        company = get_company(ticker)
        company_name = company.name if company else ticker
        print(f"\n[{ticker}] {company_name}")

        print(f"  → Investor conferences ...")
        conf_records, conf_manifest = acquire_conferences(ticker)
        conf_manifest["company_name"] = company_name
        conf_manifest["source_url"] = f"https://mops.twse.com.tw/mops/web/t100sb07_1?co_id={ticker}"
        acquisition_manifest.append(conf_manifest)
        all_new_conference_records[ticker] = conf_records

        print(f"    status={conf_manifest['retrieval_status']} | "
              f"found={conf_manifest['documents_found']} | "
              f"full_text={conf_manifest['documents_with_full_text']}")
        if conf_manifest.get("failure_reason"):
            short = str(conf_manifest["failure_reason"])[:200]
            print(f"    reason: {short}")

        print(f"  → Material events ...")
        mat_records, mat_manifest = acquire_material_events(ticker)
        mat_manifest["company_name"] = company_name
        mat_manifest["source_url"] = f"https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
        acquisition_manifest.append(mat_manifest)
        all_new_material_records[ticker] = mat_records

        print(f"    status={mat_manifest['retrieval_status']} | "
              f"found={mat_manifest['documents_found']} | "
              f"full_text={mat_manifest['documents_with_full_text']}")

    # ── Step 2: Build Phase-12-style report and extract corpus rows ──────────
    print("\n[Corpus building]")
    new_rows: list[dict] = []
    ticker_new_row_counts: dict[str, int] = {ticker: 0 for ticker in EXPANSION_TICKERS}

    for ticker in EXPANSION_TICKERS:
        conf = all_new_conference_records.get(ticker, [])
        mats = all_new_material_records.get(ticker, [])
        report = _build_phase12_report_for_ticker(ticker, conf, mats)
        if not report:
            print(f"  {ticker}: no analyzable records → skipped")
            continue

        # Count how many analyzable docs we have
        analyzable_c = len(report["companies"][0]["unified"]["official_events_refresh"]["investor_conferences"])
        analyzable_m = len(report["companies"][0]["unified"]["official_events_refresh"]["material_events"])
        print(f"  {ticker}: {analyzable_c} analyzable conferences, {analyzable_m} analyzable material events")

        if analyzable_c == 0 and analyzable_m == 0:
            print(f"  {ticker}: no full-text documents qualify → skipped from corpus")
            continue

        try:
            build_result = build_phase12_official_corpus(report, dataset_version=SCRIPT_VERSION)
            ticker_rows = build_result.rows
            ticker_new_row_counts[ticker] = len(ticker_rows)
            print(f"  {ticker}: extracted {len(ticker_rows)} sentence rows")
            if len(ticker_rows) < MIN_SENTENCES_FOR_INCLUSION:
                print(
                    f"  {ticker}: WARNING extracted sentence count is below "
                    f"MIN_SENTENCES_FOR_INCLUSION={MIN_SENTENCES_FOR_INCLUSION}; "
                    "not counted as substantive company diversity."
                )
            new_rows.extend(ticker_rows)
        except Exception as exc:
            print(f"  {ticker}: corpus build error — {exc}")
            traceback.print_exc()

    # ── Step 3: Load existing 2454 corpus and merge ──────────────────────────
    print("\n[Merging with existing 2454 corpus]")
    existing_rows = load_existing_corpus()

    all_rows = [*existing_rows, *new_rows]
    dedup_result = deduplicate_corpus_rows(all_rows)
    merged_rows = dedup_result["rows"]
    print(f"  Total before dedup: {len(all_rows)}")
    print(f"  Duplicates removed: {dedup_result['duplicate_count']}")
    print(f"  Final merged corpus: {len(merged_rows)} rows")

    # ── Step 4: Add keyword_hit flag ─────────────────────────────────────────
    for row in merged_rows:
        text = str(row.get("cleaned_text") or row.get("original_text") or "")
        row["keyword_hit"] = build_keyword_hit_flag(text)

    # Company and source breakdown
    ticker_counts = Counter(r.get("ticker") for r in merged_rows)
    source_counts = Counter(r.get("source_type") for r in merged_rows)
    label_counts = Counter(r.get("weak_relevant_label") for r in merged_rows)
    kw_hit_count = sum(1 for r in merged_rows if r.get("keyword_hit"))
    print(f"\n  Ticker distribution: {dict(ticker_counts)}")
    print(f"  Source type: {dict(source_counts)}")
    print(f"  Weak label: {dict(label_counts)}")
    print(f"  Keyword-hit: {kw_hit_count} / {len(merged_rows)}")

    # ── Step 5: Annotation candidate sampling ───────────────────────────────
    print("\n[Annotation candidate sampling]")
    try:
        # stratified_annotation_sample stratifies on weak_relevant_label + weak_topics
        # which live in the raw merged_rows (not train_ready which renames them).
        train_ready = corpus_rows_to_train_ready(merged_rows)
        print(f"  Train-ready rows: {len(train_ready)}")

        annotation_rows = stratified_annotation_sample(
            merged_rows,          # use raw rows: keeps weak_relevant_label/weak_topics
            target_size=500,
            seed=42,
        )
        annotation_package = to_annotation_package_rows(annotation_rows)
        # Add keyword_hit to annotation rows
        text_to_kw: dict[str, bool] = {
            r.get("cleaned_text", ""): bool(r.get("keyword_hit"))
            for r in merged_rows
        }
        for row in annotation_package:
            t = str(row.get("cleaned_text") or "")
            row["keyword_hit"] = text_to_kw.get(t, False)

        print(f"  Annotation candidates: {len(annotation_package)}")
        kw_a = Counter(r.get("ticker") for r in annotation_package)
        print(f"  Annotation ticker distribution: {dict(kw_a)}")
    except Exception as exc:
        annotation_package = []
        print(f"  [WARN] annotation sampling failed: {exc}")
        traceback.print_exc()

    # ── Step 6: Build drift-pair candidates ──────────────────────────────────
    # Rows from same ticker, different periods — human label stays BLANK
    def _drift_pairs(rows: list[dict]) -> list[dict]:
        from itertools import combinations
        by_ticker: dict[str, list[dict]] = {}
        for row in rows:
            t = str(row.get("ticker") or "")
            by_ticker.setdefault(t, []).append(row)

        pairs = []
        for ticker, ticker_rows in by_ticker.items():
            # Group by period
            by_period: dict[str, list[dict]] = {}
            for r in ticker_rows:
                p = str(r.get("period") or "UNKNOWN")
                by_period.setdefault(p, []).append(r)
            periods = sorted(by_period)
            for p1, p2 in list(combinations(periods, 2))[:3]:  # cap at 3 pairs per ticker
                r1 = by_period[p1][0]
                r2 = by_period[p2][0]
                pairs.append({
                    "ticker": ticker,
                    "text_1_period": p1,
                    "text_1": r1.get("cleaned_text", ""),
                    "text_2_period": p2,
                    "text_2": r2.get("cleaned_text", ""),
                    "human_drift_label": "",   # BLANK — awaiting human annotation
                    "suggestion_note": "PRELIMINARY_WEAK_SUPERVISION — not human ground truth",
                })
        return pairs

    drift_pairs = _drift_pairs(merged_rows)
    print(f"\n  Drift pair candidates: {len(drift_pairs)}")

    # ── Step 7: Build expanded dataset manifest ───────────────────────────────
    tickers_present = sorted(set(str(r.get("ticker") or "") for r in merged_rows if r.get("ticker")))
    expanded_manifest = corpus_manifest(merged_rows, dataset_version=SCRIPT_VERSION)
    freeze_gate = _freeze_gate_result(merged_rows)
    expanded_manifest["annotation_dataset_status"] = freeze_gate["status"]
    expanded_manifest["freeze_gate_rationale"] = freeze_gate
    expanded_manifest["freeze_gate_thresholds"] = FREEZE_GATE_THRESHOLDS
    expanded_manifest["expansion_ticker_sentence_counts"] = ticker_new_row_counts
    expanded_manifest["corpus_expansion_notes"] = freeze_gate["rationale"]
    expanded_manifest["expansion_tickers_attempted"] = EXPANSION_TICKERS
    expanded_manifest["expansion_tickers_with_full_text"] = [
        t for t in EXPANSION_TICKERS
        if any(str(r.get("ticker")) == t for r in new_rows)
    ]
    expanded_manifest["keyword_hit_count"] = kw_hit_count
    expanded_manifest["keyword_free_count"] = len(merged_rows) - kw_hit_count

    # ── Step 8: Write outputs ────────────────────────────────────────────────
    if dry_run:
        print("\n[DRY RUN — no files written]")
        print(json.dumps({
            "acquisition_manifest_entries": len(acquisition_manifest),
            "merged_corpus_rows": len(merged_rows),
            "new_rows": len(new_rows),
            "expansion_ticker_sentence_counts": ticker_new_row_counts,
            "annotation_candidates": len(annotation_package),
            "drift_pairs": len(drift_pairs),
            "annotation_dataset_status": expanded_manifest["annotation_dataset_status"],
            "freeze_gate_rationale": expanded_manifest["freeze_gate_rationale"],
        }, indent=2))
        return

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Acquisition manifest
    manifest_path = REPORTS_DIR / "corpus_expansion_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "script_version": SCRIPT_VERSION,
            "run_at": NOW_ISO,
            "entries": acquisition_manifest,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  Wrote: {manifest_path}")

    # Expanded corpus JSONL
    corpus_path = REPORTS_DIR / "official_text_corpus_expanded.jsonl"
    with open(corpus_path, "w", encoding="utf-8") as f:
        for row in merged_rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(f"  Wrote: {corpus_path} ({len(merged_rows)} rows)")

    # Expanded annotation candidates CSV
    if annotation_package:
        cols = list(REQUIRED_ANNOTATION_COLUMNS) + ["keyword_hit"]
        # Add any extra columns present
        extra_cols = [
            k for k in annotation_package[0].keys()
            if k not in cols
        ]
        all_cols = cols + extra_cols

        ann_path = REPORTS_DIR / "annotation_candidates_expanded.csv"
        with open(ann_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(annotation_package)
        print(f"  Wrote: {ann_path} ({len(annotation_package)} rows)")

    # Drift pairs CSV
    if drift_pairs:
        drift_path = REPORTS_DIR / "drift_pair_candidates_expanded.csv"
        drift_cols = ["ticker", "text_1_period", "text_1", "text_2_period", "text_2",
                      "human_drift_label", "suggestion_note"]
        with open(drift_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=drift_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(drift_pairs)
        print(f"  Wrote: {drift_path} ({len(drift_pairs)} pairs)")

    # Expanded dataset manifest
    ds_path = REPORTS_DIR / "dataset_manifest_expanded.json"
    with open(ds_path, "w", encoding="utf-8") as f:
        json.dump(expanded_manifest, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Wrote: {ds_path}")

    print(f"\n{'='*64}")
    print(f"RESULT: {expanded_manifest['annotation_dataset_status']}")
    print(f"Merged corpus: {len(merged_rows)} rows | New rows added: {len(new_rows)}")
    print(f"Companies: {tickers_present}")
    print(f"Freeze gate: {freeze_gate['rationale']}")
    if not new_rows:
        print("\nNOTE: Cloud proxy blocks MOPS/TWSE — no new full-text rows obtained.")
        print("Device-side execution plan (device_bash restored):")
        print("  python3 scripts/acquire_phase14_official_corpus.py")
        print("  (Run from device where mops.twse.com.tw is reachable)")
    print(f"{'='*64}\n")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 14 corpus expansion acquisition")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run acquisition but do not write output files")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
