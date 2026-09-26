"""Source validation for multimodal interpretations of conference PDF regions.

A provider may classify a region and propose labels, values, and a trend, but
nothing it reports is trusted on its own. Every value must be found in an
independent source channel:

* ``pdf_text``: region words, page text, deterministic numeric candidates;
* ``ocr``: local OCR of the same region crop, at or above the confidence
  threshold (OCR below the threshold is reported but supports nothing).

Label-value pairs must be confirmed by x/y alignment of PDF words or of OCR
tokens; a trend is supported only when it matches the trend of supported,
aligned values. If OCR pairs a label with a different value than the
provider, the region fails closed. Model output never reaches ``verified``,
and OCR support caps it at ``partially_verified`` as well.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.mops_conference_pdf_semantics import RegionContext, Word, infer_trend_from_pairs

_NUMERIC_TYPES = {"chart", "table"}
_NUMBER_TOKEN_RE = re.compile(r"[-+(]?\d[\d,]*(?:\.\d+)?%?\)?")


def normalize_numeric(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    text = re.sub(r"[\s,]", "", text)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return text.lstrip("+")


def normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip().casefold()


def _numbers_in(text: str) -> set[str]:
    return {normalize_numeric(item) for item in _NUMBER_TOKEN_RE.findall(text or "")} - {""}


def _pdf_numbers(source: RegionContext, numeric_candidates: list[str]) -> set[str]:
    tokens = {normalize_numeric(word.text.strip(",;:")) for word in source.words}
    tokens |= {normalize_numeric(item) for item in numeric_candidates}
    tokens |= _numbers_in(source.page_text)
    return {token for token in tokens if token}


class _OcrIndex:
    """Accepted and low-confidence OCR evidence of one region."""

    def __init__(self, tokens: list[Any]) -> None:
        self.accepted_numbers: dict[str, float] = {}
        self.low_numbers: dict[str, float] = {}
        accepted_text, self.words = [], []
        self.word_confidence: dict[int, float] = {}
        for token in tokens:
            target = self.accepted_numbers if token.accepted else self.low_numbers
            for number in _numbers_in(token.normalized_text):
                target[number] = max(target.get(number, 0.0), token.confidence)
            if token.accepted:
                accepted_text.append(token.normalized_text)
                for word in token.words():
                    self.words.append(word)
                    self.word_confidence[id(word)] = token.confidence
        self.haystack = normalize_label(" | ".join(accepted_text))


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


def _label_words(words: list[Word], label: str) -> list[Word]:
    """Positions of a label; multi-word labels match consecutive tokens."""
    parts = normalize_label(label).split(" ")
    if len(parts) == 1:
        return _find_words(words, label, numeric=False)
    out = []
    normalized = [normalize_label(word.text.strip(",;:")) for word in words]
    for start in range(len(words) - len(parts) + 1):
        if normalized[start:start + len(parts)] == parts:
            span = words[start:start + len(parts)]
            out.append(Word(label, (min(w.bbox[0] for w in span), min(w.bbox[1] for w in span),
                                    max(w.bbox[2] for w in span), max(w.bbox[3] for w in span))))
    return out


def _aligned(label_word: Word, value_word: Word) -> bool:
    same_column = abs(label_word.cx - value_word.cx) <= max((label_word.bbox[2] - label_word.bbox[0]), 18.0)
    same_row = (
        abs(label_word.cy - value_word.cy) <= max((label_word.bbox[3] - label_word.bbox[1]) / 2, 4.0)
        and value_word.bbox[0] >= label_word.bbox[0]
    )
    return same_column or same_row


def _pair_aligned(words: list[Word], label: str, value_text: str) -> bool:
    """Label and value share a column (x) or a row (y, value to the right)."""
    label_words = _label_words(words, label)
    value_words = _find_words(words, value_text, numeric=True)
    return any(_aligned(lw, vw) for lw in label_words for vw in value_words)


def _nearest_ocr_values(ocr: _OcrIndex, label: str) -> set[str]:
    """Accepted OCR numbers positioned as this label's value (nearest aligned number)."""
    found: set[str] = set()
    for label_word in _label_words(ocr.words, label):
        candidates = [
            word for word in ocr.words
            if word is not label_word and _numbers_in(word.text) and _aligned(label_word, word)
            and normalize_numeric(word.text) == next(iter(_numbers_in(word.text)))
        ]
        if candidates:
            nearest = min(candidates, key=lambda w: abs(w.cx - label_word.cx) + abs(w.cy - label_word.cy))
            found.add(normalize_numeric(nearest.text))
    return found


def validate_region_interpretation(
    interpretation: dict[str, Any],
    source: RegionContext,
    record: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Return (verification_status, validation_report) for a provider interpretation."""
    pdf_haystack = normalize_label(" ".join(filter(None, [source.page_text, source.region_text, source.caption])))
    pdf_numbers = _pdf_numbers(source, record.get("numeric_candidates") or [])
    ocr = _OcrIndex(list(source.ocr_tokens or []))

    def label_channels(label: str) -> list[str]:
        channels = []
        if _label_supported(label, pdf_haystack):
            channels.append("pdf_text")
        if _label_supported(label, ocr.haystack):
            channels.append("ocr")
        return channels

    values = interpretation.get("values") or []
    value_reports = []
    disagreements = []
    for item in values:
        value_text = str(item.get("value_text") or "")
        label = item.get("label")
        number = normalize_numeric(value_text)
        supported_by = []
        if number in pdf_numbers:
            supported_by.append("pdf_text")
        if number in ocr.accepted_numbers:
            supported_by.append("ocr")
        label_by = label_channels(str(label)) if label is not None else []
        mapping_by = []
        if label and supported_by:
            if "pdf_text" in supported_by and _pair_aligned(source.words, str(label), value_text):
                mapping_by.append("pdf_text")
            if "ocr" in supported_by and _pair_aligned(ocr.words, str(label), value_text):
                mapping_by.append("ocr")
        report = {
            "label": label,
            "value_text": value_text,
            "value_supported": bool(supported_by),
            "supported_by": supported_by,
            "label_supported": label is None or bool(label_by),
            "label_supported_by": label_by,
            "mapping_supported": bool(mapping_by),
            "mapping_supported_by": mapping_by,
        }
        if number in ocr.accepted_numbers:
            report["ocr_confidence"] = round(ocr.accepted_numbers[number], 4)
        elif number in ocr.low_numbers:
            report["ocr_low_confidence_match"] = round(ocr.low_numbers[number], 4)
        if label:
            ocr_values = _nearest_ocr_values(ocr, str(label))
            if ocr_values and number not in ocr_values:
                report["ocr_disagreement"] = sorted(ocr_values)
                disagreements.append({"label": label, "provider_value": value_text, "ocr_values": sorted(ocr_values)})
        value_reports.append(report)

    labels = interpretation.get("labels") or []
    label_reports = {label: bool(label_channels(label)) for label in labels}
    unit = interpretation.get("unit")
    unit_supported = None if not unit else bool(label_channels(str(unit)))
    title = interpretation.get("title")
    title_supported = None if not title else bool(label_channels(str(title)))

    all_values_supported = all(report["value_supported"] for report in value_reports)
    all_labels_supported = all(label_reports.values()) and all(r["label_supported"] for r in value_reports)
    mapping_established = bool(value_reports) and all(report["mapping_supported"] for report in value_reports)

    trend = interpretation.get("trend")
    trend_supported: bool | None = None
    if trend and trend != "unknown":
        deterministic = None
        if mapping_established and all_values_supported and not disagreements:
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
    if disagreements:
        reasons.append("ocr_disagrees_with_provider")
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
        "ocr_used": bool(source.ocr_tokens),
        "ocr_supported_values": sum(1 for r in value_reports if r["supported_by"] == ["ocr"]),
        "ocr_disagreements": disagreements,
        "review_reasons": reasons,
    }
