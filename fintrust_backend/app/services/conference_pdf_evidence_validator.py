"""Source validation for multimodal interpretations of conference PDF regions.

A provider may classify a region and propose labels, values, and a trend, but
nothing it reports is trusted on its own. Every value must be found in a PDF
source channel (region words, page text, deterministic numeric candidates);
label-value pairs must be confirmed by x/y alignment of the PDF words; a trend
is supported only when it matches the trend of supported, aligned values.
Model output never reaches ``verified``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.mops_conference_pdf_semantics import RegionContext, Word, infer_trend_from_pairs

_NUMERIC_TYPES = {"chart", "table"}


def normalize_numeric(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    text = re.sub(r"[\s,]", "", text)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return text.lstrip("+")


def normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip().casefold()


def _source_numbers(source: RegionContext, numeric_candidates: list[str]) -> set[str]:
    tokens = {normalize_numeric(word.text.strip(",;:")) for word in source.words}
    tokens |= {normalize_numeric(item) for item in numeric_candidates}
    tokens |= {normalize_numeric(item) for item in re.findall(r"[-+(]?\d[\d,]*(?:\.\d+)?%?\)?", source.page_text)}
    return {token for token in tokens if token}


def _numeric_supported(value_text: str, source_numbers: set[str]) -> bool:
    return normalize_numeric(value_text) in source_numbers


def _label_supported(label: str, haystack: str) -> bool:
    needle = normalize_label(label)
    return bool(needle) and needle in haystack


def _find_words(words: list[Word], text: str, *, numeric: bool) -> list[Word]:
    target = normalize_numeric(text) if numeric else normalize_label(text)
    out = []
    for word in words:
        token = word.text.strip(",;:")
        candidate = normalize_numeric(token) if numeric else normalize_label(token)
        if candidate == target:
            out.append(word)
    return out


def _pair_aligned(words: list[Word], label: str, value_text: str) -> bool:
    """Label and value share a column (x) or a row (y, value to the right)."""
    label_words = _find_words(words, label, numeric=False)
    value_words = _find_words(words, value_text, numeric=True)
    for lw in label_words:
        for vw in value_words:
            same_column = abs(lw.cx - vw.cx) <= max((lw.bbox[2] - lw.bbox[0]), 18.0)
            same_row = abs(lw.cy - vw.cy) <= max((lw.bbox[3] - lw.bbox[1]) / 2, 4.0) and vw.bbox[0] >= lw.bbox[0]
            if same_column or same_row:
                return True
    return False


def validate_region_interpretation(
    interpretation: dict[str, Any],
    source: RegionContext,
    record: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Return (verification_status, validation_report) for a provider interpretation."""
    haystack = normalize_label(" ".join(filter(None, [source.page_text, source.region_text, source.caption])))
    source_numbers = _source_numbers(source, record.get("numeric_candidates") or [])

    values = interpretation.get("values") or []
    value_reports = []
    for item in values:
        value_text = str(item.get("value_text") or "")
        label = item.get("label")
        supported = _numeric_supported(value_text, source_numbers)
        label_ok = label is None or _label_supported(str(label), haystack)
        aligned = bool(label) and supported and _pair_aligned(source.words, str(label), value_text)
        value_reports.append({
            "label": label, "value_text": value_text,
            "value_supported": supported, "label_supported": label_ok, "mapping_supported": aligned,
        })

    labels = interpretation.get("labels") or []
    label_reports = {label: _label_supported(label, haystack) for label in labels}
    unit = interpretation.get("unit")
    unit_supported = None if not unit else _label_supported(str(unit), haystack)
    title = interpretation.get("title")
    title_supported = None if not title else _label_supported(str(title), haystack)

    all_values_supported = all(report["value_supported"] for report in value_reports)
    all_labels_supported = all(label_reports.values()) and all(r["label_supported"] for r in value_reports)
    mapping_established = bool(value_reports) and all(report["mapping_supported"] for report in value_reports)

    trend = interpretation.get("trend")
    trend_supported: bool | None = None
    if trend and trend != "unknown":
        deterministic = None
        if mapping_established and all_values_supported:
            deterministic = infer_trend_from_pairs(
                [str(r["label"]) for r in value_reports], [r["value_text"] for r in value_reports],
            )
        trend_supported = deterministic == trend

    region_type = interpretation.get("region_type")
    reasons = []
    if interpretation.get("requires_review"):
        reasons.append("provider_requested_review")
    if not all_values_supported:
        reasons.append("unsupported_numeric_value")
    if not all_labels_supported:
        reasons.append("unsupported_label")
    if unit_supported is False:
        reasons.append("unsupported_unit")
    if value_reports and not mapping_established:
        reasons.append("label_value_mapping_unconfirmed")
    if trend_supported is False:
        reasons.append("trend_not_confirmed_by_source")
    if region_type == "unknown":
        reasons.append("provider_region_unknown")
    if region_type in _NUMERIC_TYPES and not value_reports:
        reasons.append("no_values_extracted")
    deterministic_type = record.get("evidence_type")
    if deterministic_type in _NUMERIC_TYPES and region_type not in _NUMERIC_TYPES:
        reasons.append("provider_disagrees_with_deterministic_type")

    status = "needs_review" if reasons else "partially_verified"
    return status, {
        "values": value_reports,
        "labels": label_reports,
        "unit_supported": unit_supported,
        "title_supported": title_supported,
        "all_values_supported": all_values_supported,
        "all_labels_supported": all_labels_supported,
        "mapping_established": mapping_established,
        "trend_supported": trend_supported,
        "review_reasons": reasons,
    }
