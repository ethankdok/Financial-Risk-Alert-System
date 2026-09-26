"""Re-run semantic evidence extraction over already archived MOPS conference PDFs.

Never contacts MOPS. Each local PDF must still match the SHA-256 recorded in
manifest.json. Without --write the run only prints the aggregate summary.

Run from fintrust_backend:
  python -m scripts.reprocess_conference_pdf_semantics --archive data/official-ir-pdfs-live-test \
      --ticker 2330 --year 2025 [--multimodal gemini|replay --max-calls 60] [--ocr rapidocr]
      [--write] [--sanity FILE]

--multimodal replay re-validates the Gemini interpretations already stored in
the semantic.json files (for example against new OCR evidence) without calling
the provider again.

--summary-only reports on the semantic.json files already on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.services.conference_pdf_ocr import build_region_ocr
from app.services.conference_pdf_multimodal import (
    _mark,
    apply_interpretation,
    GeminiRegionInterpreter,
    merge_gating_metrics,
    semantic_gating_metrics,
)
from app.services.mops_conference_pdf_pipeline import _atomic_bytes, extract_pages
from app.services.mops_conference_pdf_semantics import load_pymupdf

class ReplayRegionInterpreter:
    """Re-applies stored provider interpretations; never calls a provider."""

    def __init__(self) -> None:
        self.stored: dict[tuple, dict] = {}

    @staticmethod
    def key(record: dict) -> tuple:
        region = record["region"]
        return (record["filename"], record["page"], *(round(region[k], 1) for k in ("x0", "y0", "x1", "y1")))

    def load(self, records: list[dict]) -> None:
        for record in records:
            if record.get("semantic_provider") == "gemini":
                self.stored[self.key(record)] = record

    def interpret_page(self, page, items) -> None:
        for record, source in items:
            previous = self.stored.get(self.key(record))
            if previous is None:
                _mark(record, "skipped", error={"error_type": "NoStoredInterpretation"})
            elif previous.get("provider_interpretation") is not None:
                apply_interpretation(record, source, previous["provider_interpretation"],
                                     provider="gemini", model=previous.get("semantic_model"))
                record["semantic_provider_replayed"] = True
            else:
                _mark(record, previous.get("semantic_provider_status") or "failed",
                      error=previous.get("semantic_provider_error"))
                record["semantic_provider_replayed"] = True

    def close(self) -> None:
        pass


EVIDENCE_TYPES = ("text", "table", "chart", "image", "diagram", "decorative", "unknown")
STATUSES = ("verified", "partially_verified", "needs_review")


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def _page_areas(pdf: Path) -> dict[int, float]:
    document = load_pymupdf().open(pdf)
    return {index + 1: float(page.rect.width * page.rect.height) for index, page in enumerate(document)}


def _has_mapping(record: dict) -> bool:
    if record["evidence_type"] == "table":
        return any(row.get("cells") for row in record.get("values", []) if isinstance(row, dict))
    return any(isinstance(v, dict) and v.get("label") and v.get("value_text") for v in record.get("values", []))


def summarize(records_by_file: dict[str, list[dict]], areas_by_file: dict[str, dict[int, float]]) -> dict:
    records = [item for items in records_by_file.values() for item in items]
    types = Counter(item["evidence_type"] for item in records)
    statuses = Counter(item["verification_status"] for item in records)
    giant = 0
    for name, items in records_by_file.items():
        for item in items:
            if item["evidence_type"] in {"text", "decorative"}:
                continue
            box = item["region"]
            area = (box["x1"] - box["x0"]) * (box["y1"] - box["y0"])
            if area / (areas_by_file[name].get(item["page"]) or 1) >= 0.5:
                giant += 1
    review_pages = {(item["filename"], item["page"]) for item in records if item["verification_status"] == "needs_review"}
    return {
        "semantic_total": len(records),
        "by_type": {key: types.get(key, 0) for key in EVIDENCE_TYPES},
        "by_status": {key: statuses.get(key, 0) for key in STATUSES},
        "regions_with_numeric_values": sum(
            1 for item in records if item["evidence_type"] != "text" and item.get("values")
        ),
        "regions_with_label_value_mapping": sum(1 for item in records if _has_mapping(item)),
        "label_value_mapping_source_confirmed": sum(
            1 for item in records
            if _has_mapping(item) and item.get("mapping_status") in {"aligned", "source_aligned"}
        ),
        "regions_with_trends": sum(1 for item in records if item.get("trend")),
        "trends_source_confirmed": sum(
            1 for item in records
            if item.get("trend") and (item.get("trend_source") == "deterministic" or item.get("trend_supported"))
        ),
        "non_decorative_regions_ge_50pct_page": giant,
        "pages_with_needs_review_evidence": len(review_pages),
        "gemini": merge_gating_metrics([semantic_gating_metrics(items) for items in records_by_file.values()]),
    }


def evaluate_sanity(path: Path, records_by_file: dict[str, list[dict]]) -> list[dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for case in spec["pages"]:
        page_records = [
            item for item in records_by_file.get(case["filename"], []) if item["page"] == case["page"]
        ]
        found_types = sorted({item["evidence_type"] for item in page_records})
        haystack = json.dumps(page_records, ensure_ascii=False)
        labels = case.get("obvious_labels", [])
        values = case.get("obvious_values", [])
        trend = case.get("obvious_trend")
        results.append({
            "id": case["id"],
            "expected_type": case["expected_major_type"],
            "type_found": any(kind in found_types for kind in case.get("acceptable_types", [case["expected_major_type"]])),
            "found_types": found_types,
            "labels_found": f"{sum(1 for label in labels if label in haystack)}/{len(labels)}",
            "values_found": f"{sum(1 for value in values if json.dumps(value)[1:-1] in haystack)}/{len(values)}",
            "trend_expected": trend,
            "trend_found": sorted({item["trend"] for item in page_records if item.get("trend")}),
            "statuses": dict(Counter(item["verification_status"] for item in page_records)),
            "ocr_statuses": dict(Counter(
                item.get("ocr_status") for item in page_records if item.get("ocr_eligible")
            )),
            "ocr_supported_values": [
                value["value_text"] for item in page_records for value in item.get("values", [])
                if isinstance(value, dict) and "ocr" in (value.get("supported_by") or [])
            ],
            "ocr_disagreements": [
                d for item in page_records for d in (item.get("validation") or {}).get("ocr_disagreements", [])
            ],
            "provider_statuses": dict(Counter(
                item.get("semantic_provider_status") for item in page_records if item.get("gemini_eligible")
            )),
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, default=Path("data/official-ir-pdfs"))
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--multimodal", choices=("none", "gemini", "replay"), default="none")
    parser.add_argument("--ocr", choices=("none", "rapidocr"), default="none",
                        help="targeted local OCR of eligible raster regions")
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--write", action="store_true", help="rewrite .pages/.analysis/.semantic JSON and manifest")
    parser.add_argument("--summary-only", action="store_true", help="summarize existing semantic.json files")
    parser.add_argument("--sanity", type=Path, default=None, help="sanity-set metadata JSON to score")
    args = parser.parse_args()

    directory = args.archive / args.ticker / str(args.year)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    interpreter = None
    if args.multimodal == "gemini" and not args.summary_only:
        interpreter = GeminiRegionInterpreter(max_calls=args.max_calls)
    elif args.multimodal == "replay" and not args.summary_only:
        interpreter = ReplayRegionInterpreter()
    region_ocr = None if args.summary_only else build_region_ocr(args.ocr)

    records_by_file: dict[str, list[dict]] = {}
    areas_by_file: dict[str, dict[int, float]] = {}
    try:
        for doc in manifest["documents"]:
            if "sha256" not in doc:
                continue
            base = directory / doc["filename"].removesuffix(".pdf")
            pdf = base.with_suffix(".pdf")
            raw = pdf.read_bytes()
            if hashlib.sha256(raw).hexdigest() != doc["sha256"]:
                print(f"SHA-256 mismatch for {pdf}; refusing to reprocess", file=sys.stderr)
                return 3
            areas_by_file[doc["filename"]] = _page_areas(pdf)
            if args.summary_only:
                records_by_file[doc["filename"]] = json.loads(base.with_suffix(".semantic.json").read_text(encoding="utf-8"))
                continue
            previous_pages = json.loads(base.with_suffix(".pages.json").read_text(encoding="utf-8"))
            page_ocr = any(page.get("text_extraction_method") == "ocr" for page in previous_pages)
            if isinstance(interpreter, ReplayRegionInterpreter):
                interpreter.load(json.loads(base.with_suffix(".semantic.json").read_text(encoding="utf-8")))
            pages, _problems = extract_pages(raw, filename=doc["filename"], ocr=page_ocr,
                                             interpreter=interpreter, region_ocr=region_ocr)
            for page, previous in zip(pages, previous_pages):
                for key in ("review_image_path", "review_image_error"):
                    if key in previous:
                        page[key] = previous[key]
            semantic = [item for page in pages for item in page.get("semantic_evidence", [])]
            records_by_file[doc["filename"]] = semantic
            if args.write:
                analysis = [
                    {key: value for key, value in item.items() if key != "text"}
                    for page in pages for item in page["analysis_results"]
                ]
                _atomic_bytes(base.with_suffix(".pages.json"), _json_bytes(pages))
                _atomic_bytes(base.with_suffix(".analysis.json"), _json_bytes(analysis))
                _atomic_bytes(base.with_suffix(".semantic.json"), _json_bytes(semantic))
                doc.update({
                    "analysis_results": len(analysis),
                    "semantic_results": len(semantic),
                    "semantic_region_types": sorted({item["evidence_type"] for item in semantic}),
                    "semantic_multimodal": semantic_gating_metrics(semantic),
                })
    finally:
        if interpreter is not None:
            interpreter.close()
        if region_ocr is not None:
            region_ocr.close()

    if args.write and not args.summary_only:
        integrity = manifest.setdefault("integrity", {})
        integrity["semantic_evidence_count"] = sum(len(items) for items in records_by_file.values())
        integrity["semantic_multimodal"] = merge_gating_metrics(
            [doc["semantic_multimodal"] for doc in manifest["documents"] if "semantic_multimodal" in doc]
        )
        manifest["semantic_reprocessed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_bytes(manifest_path, _json_bytes(manifest))

    output = {"summary": summarize(records_by_file, areas_by_file)}
    if args.sanity:
        output["sanity"] = evaluate_sanity(args.sanity, records_by_file)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
