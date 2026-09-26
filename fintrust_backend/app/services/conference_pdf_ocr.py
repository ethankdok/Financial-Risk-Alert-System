"""Targeted local OCR for raster regions of conference PDFs.

OCR is a third, independent evidence channel next to the PDF text layer and
the multimodal interpretation. It runs only on regions the semantic parser
marked ``ocr_eligible`` (meaningful raster or text-less visual regions), on
the same region crop the interpreter sees. OCR text is kept as OCR text with
its own provenance; it is never presented as selectable PDF text and never
makes evidence ``verified`` on its own.

The engine is optional (``CONFERENCE_PDF_OCR_PROVIDER=rapidocr``, installed
from requirements-ocr.txt). Missing packages, model problems, timeouts, and
engine errors are recorded on the region and never stop the pipeline.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.mops_conference_pdf_semantics import BBox, RegionContext, Word, render_region_png

DEFAULT_MIN_CONFIDENCE = 0.85
DEFAULT_DPI = 200
DEFAULT_MAX_REGIONS = 100
DEFAULT_TIMEOUT_SECONDS = 60.0
_MINUS_SIGNS = dict.fromkeys(map(ord, "−‒–—―﹣－"), "-")


def normalize_ocr_text(text: str) -> str:
    """Safe normalization only: NFKC (full-width to half-width), minus signs, whitespace.
    Look-alike characters (O/0, I/1, l/1) are deliberately left alone."""
    value = unicodedata.normalize("NFKC", text or "").translate(_MINUS_SIGNS)
    return re.sub(r"\s+", " ", value).strip()


def parse_min_confidence(raw: str | float | None) -> float:
    """Threshold on a 0-1 scale; values above 1 are read as percentages."""
    if raw in (None, ""):
        return DEFAULT_MIN_CONFIDENCE
    value = float(raw)
    return value / 100.0 if value > 1 else value


@dataclass(frozen=True)
class OCRResult:
    """Engine output in crop-pixel coordinates; confidence normalized to 0-1."""

    text: str
    bbox: tuple[float, float, float, float] | None
    confidence: float


@dataclass(frozen=True)
class OcrToken:
    """One OCR line mapped back to PDF coordinates."""

    raw_text: str
    normalized_text: str
    bbox: BBox | None
    pixel_bbox: tuple[float, float, float, float] | None
    confidence: float
    accepted: bool

    def words(self) -> list[Word]:
        """Split a line into positioned tokens (widths apportioned by characters)."""
        if self.bbox is None:
            return []
        parts = self.normalized_text.split(" ")
        total = sum(len(part) for part in parts) + max(len(parts) - 1, 0)
        width = self.bbox[2] - self.bbox[0]
        out, cursor = [], 0
        for part in parts:
            x0 = self.bbox[0] + width * cursor / max(total, 1)
            x1 = self.bbox[0] + width * (cursor + len(part)) / max(total, 1)
            out.append(Word(part, (x0, self.bbox[1], x1, self.bbox[3])))
            cursor += len(part) + 1
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "bbox": None if self.bbox is None else [round(v, 2) for v in self.bbox],
            "pixel_bbox": None if self.pixel_bbox is None else [round(v, 1) for v in self.pixel_bbox],
            "confidence": round(self.confidence, 4),
            "accepted": self.accepted,
        }


class ConferencePdfOCR(Protocol):
    engine_name: str
    extraction_method: str

    def engine_version(self) -> str | None: ...

    def recognize(self, image_bytes: bytes) -> list[OCRResult]: ...


class OcrUnavailableError(RuntimeError):
    """The OCR engine or its models cannot be loaded in this environment."""


class RapidOcrEngine:
    """RapidOCR (PP-OCR models on ONNX Runtime); models ship inside the package."""

    engine_name = "rapidocr"
    extraction_method = "rapidocr_onnx"

    def __init__(self) -> None:
        self._engine: Any | None = None

    def _load(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr import RapidOCR
            except Exception as exc:  # ImportError, or a broken native dependency
                raise OcrUnavailableError(f"rapidocr is not importable: {type(exc).__name__}") from exc
            try:
                self._engine = RapidOCR()
            except Exception as exc:
                raise OcrUnavailableError(f"rapidocr models could not be loaded: {type(exc).__name__}") from exc
        return self._engine

    def engine_version(self) -> str | None:
        try:
            from importlib.metadata import version

            return f"rapidocr {version('rapidocr')}; onnxruntime {version('onnxruntime')}"
        except Exception:
            return None

    def recognize(self, image_bytes: bytes) -> list[OCRResult]:
        output = self._load()(image_bytes)
        texts = list(getattr(output, "txts", None) or [])
        scores = list(getattr(output, "scores", None) or [])
        boxes = getattr(output, "boxes", None)
        if len(scores) != len(texts):
            raise ValueError("OCR output has mismatched texts and scores")
        results = []
        for index, text in enumerate(texts):
            bbox = None
            if boxes is not None and index < len(boxes):
                points = [(float(x), float(y)) for x, y in boxes[index]]
                bbox = (min(x for x, _ in points), min(y for _, y in points),
                        max(x for x, _ in points), max(y for _, y in points))
            score = float(scores[index])
            results.append(OCRResult(str(text), bbox, score / 100.0 if score > 1 else score))
        return results


class RegionOcrRunner:
    """Runs an OCR engine on eligible region crops and records provenance."""

    def __init__(
        self,
        engine: ConferencePdfOCR,
        *,
        dpi: int | None = None,
        min_confidence: float | None = None,
        max_regions: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.engine = engine
        self.dpi = int(dpi or os.getenv("CONFERENCE_PDF_OCR_DPI", "") or DEFAULT_DPI)
        self.min_confidence = (
            min_confidence if min_confidence is not None
            else parse_min_confidence(os.getenv("CONFERENCE_PDF_OCR_MIN_CONFIDENCE"))
        )
        if max_regions is None:
            max_regions = int(os.getenv("CONFERENCE_PDF_OCR_MAX_REGIONS", "") or DEFAULT_MAX_REGIONS)
        self.max_regions = max(0, int(max_regions))
        self.timeout_seconds = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)
        self.processed = 0
        self._unavailable: str | None = None
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def _provenance(self, status: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": status,
            "engine": self.engine.engine_name,
            "engine_version": self.engine.engine_version(),
            "extraction_method": self.engine.extraction_method,
            "dpi": self.dpi,
            "min_confidence": self.min_confidence,
            **extra,
        }

    def process_page(self, page: Any, items: list[tuple[dict[str, Any], RegionContext]]) -> None:
        for record, source in items:
            if self._unavailable is not None:
                record["ocr_status"] = "unavailable"
                record["ocr"] = self._provenance("unavailable", error={"error_type": self._unavailable})
                continue
            if self.processed >= self.max_regions:
                record["ocr_status"] = "skipped"
                record["ocr"] = self._provenance("skipped", error={"error_type": "RegionBudgetExhausted"})
                continue
            self.processed += 1
            try:
                image, clip = render_region_png(page, source.bbox, dpi=self.dpi)
                if self._executor is None:
                    self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                results = self._executor.submit(self.engine.recognize, image).result(timeout=self.timeout_seconds)
                tokens = self._tokens(results, clip)
            except OcrUnavailableError as exc:
                self._unavailable = type(exc).__name__
                record["ocr_status"] = "unavailable"
                record["ocr"] = self._provenance("unavailable", error={"error_type": type(exc).__name__,
                                                                       "detail": str(exc)[:160]})
                continue
            except concurrent.futures.TimeoutError:
                self.close()  # abandon the stuck worker; a fresh one serves the next region
                record["ocr_status"] = "failed"
                record["ocr"] = self._provenance("failed", error={"error_type": "Timeout"})
                continue
            except Exception as exc:
                record["ocr_status"] = "failed"
                record["ocr"] = self._provenance("failed", error={"error_type": type(exc).__name__})
                continue
            source.ocr_tokens = tokens
            record["ocr_status"] = "completed"
            record["ocr"] = self._provenance(
                "completed",
                source_region=record.get("region"),
                crop_bbox=[round(v, 2) for v in clip],
                token_count=len(tokens),
                accepted_count=sum(1 for token in tokens if token.accepted),
                candidates=[token.as_dict() for token in tokens],
            )

    def _tokens(self, results: list[OCRResult], clip: BBox) -> list[OcrToken]:
        scale = self.dpi / 72.0
        tokens = []
        for item in results:
            if not isinstance(item.text, str) or not (0.0 <= item.confidence <= 1.0):
                raise ValueError("invalid OCR result")
            normalized = normalize_ocr_text(item.text)
            if not normalized:
                continue
            bbox = None
            if item.bbox is not None:
                bbox = (clip[0] + item.bbox[0] / scale, clip[1] + item.bbox[1] / scale,
                        clip[0] + item.bbox[2] / scale, clip[1] + item.bbox[3] / scale)
            tokens.append(OcrToken(
                raw_text=item.text, normalized_text=normalized, bbox=bbox, pixel_bbox=item.bbox,
                confidence=item.confidence, accepted=item.confidence >= self.min_confidence,
            ))
        return tokens


def build_region_ocr_from_env() -> RegionOcrRunner | None:
    """Opt-in: CONFERENCE_PDF_OCR_PROVIDER=rapidocr. Default is no OCR; an unknown
    value disables OCR rather than failing acquisition."""
    try:
        return build_region_ocr(os.getenv("CONFERENCE_PDF_OCR_PROVIDER", ""))
    except ValueError:
        return None


def build_region_ocr(provider: str | None) -> RegionOcrRunner | None:
    name = (provider or "").strip().lower()
    if name in {"", "none"}:
        return None
    if name == "rapidocr":
        return RegionOcrRunner(RapidOcrEngine())
    raise ValueError(f"Unsupported conference PDF OCR provider: {provider!r}")
