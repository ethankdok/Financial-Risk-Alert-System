"""Gated multimodal interpretation of conference PDF regions.

Only regions the deterministic parser marked ``gemini_eligible`` are sent, as
a cropped PNG plus the PDF-native text and candidates already extracted. The
existing server-side ``GeminiFinancialAnalyst`` provides key handling, model
fallback, and timeouts. Responses are schema-validated, then checked against
the PDF sources by ``conference_pdf_evidence_validator``. Provider problems
never raise: the record keeps its deterministic evidence and records the
failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.conference_pdf_evidence_validator import validate_region_interpretation
from app.services.mops_conference_pdf_semantics import RegionContext, load_pymupdf

REGION_TYPES = ("chart", "table", "image", "diagram", "decorative", "unknown")
TRENDS = ("increasing", "decreasing", "stable", "mixed", "unknown")
PROMPT_VERSION = "conference-pdf-region-v1"
_DEFAULT_MAX_CALLS = 60
_CONCURRENCY = 4
_CROP_PADDING = 8.0
_CROP_DPI = 150

_NULLABLE_STRING = {"type": ["string", "null"]}
REGION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "region_type": {"type": "string", "enum": list(REGION_TYPES)},
        "chart_type": _NULLABLE_STRING,
        "title": _NULLABLE_STRING,
        "labels": {"type": "array", "items": {"type": "string"}},
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": _NULLABLE_STRING,
                    "value_text": {"type": "string"},
                    "series": _NULLABLE_STRING,
                },
                "required": ["label", "value_text", "series"],
                "additionalProperties": False,
            },
        },
        "unit": _NULLABLE_STRING,
        "series": {"type": "array", "items": {"type": "string"}},
        "trend": {"type": "string", "enum": list(TRENDS)},
        "is_forecast": {"type": ["boolean", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "requires_review": {"type": "boolean"},
    },
    "required": [
        "region_type", "chart_type", "title", "labels", "values", "unit",
        "series", "trend", "is_forecast", "confidence", "requires_review",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You classify one cropped region of an official company investor-conference slide. "
    "You receive the cropped image and PDF-native text already extracted near the region. "
    "Report only what is visible in the image or present in the supplied text. "
    "Copy every number exactly as printed (keep %, commas, decimals, signs); never compute, "
    "round, estimate, or read values off an axis scale. If a bar or point has no printed value, omit it. "
    "Pair a label with a value only when the image shows they belong together. "
    "Use trend 'unknown' unless the printed values make the direction clear. "
    "Mark periods with E/F suffixes or words like guidance/outlook/forecast as is_forecast. "
    "Logos, icons, photos without data, and backgrounds are 'decorative' or 'image'. "
    "When unsure, use region_type 'unknown' and requires_review true. Do not give investment advice."
)


class RegionValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None
    value_text: str = Field(min_length=1, max_length=64)
    series: str | None


class RegionInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_type: Literal["chart", "table", "image", "diagram", "decorative", "unknown"]
    chart_type: str | None
    title: str | None
    labels: list[str] = Field(max_length=60)
    values: list[RegionValue] = Field(max_length=120)
    unit: str | None
    series: list[str] = Field(max_length=20)
    trend: Literal["increasing", "decreasing", "stable", "mixed", "unknown"]
    is_forecast: bool | None
    confidence: float = Field(ge=0, le=1)
    requires_review: bool


def _request_text(record: dict[str, Any], source: RegionContext) -> str:
    return json.dumps({
        "task": "Interpret this slide region. Return JSON matching the schema.",
        "page_title": source.page_title,
        "caption": source.caption,
        "region_text": source.region_text[:2000],
        "deterministic_evidence": {
            "candidate_type": record.get("evidence_type"),
            "numeric_candidates": record.get("numeric_candidates") or [],
            "period_candidates": record.get("period_candidates") or [],
            "unit_candidates": record.get("unit_candidates") or [],
            "labels": record.get("labels") or [],
            "columns": record.get("columns") or [],
        },
    }, ensure_ascii=False)


def crop_png(page: Any, bbox: tuple[float, float, float, float]) -> bytes:
    fitz = load_pymupdf()
    rect = fitz.Rect(
        max(page.rect.x0, bbox[0] - _CROP_PADDING), max(page.rect.y0, bbox[1] - _CROP_PADDING),
        min(page.rect.x1, bbox[2] + _CROP_PADDING), min(page.rect.y1, bbox[3] + _CROP_PADDING),
    )
    return page.get_pixmap(clip=rect, dpi=_CROP_DPI).tobytes("png")


class GeminiRegionInterpreter:
    """Region interpreter backed by the project's existing Gemini provider."""

    provider_label = "gemini"

    def __init__(self, provider: Any | None = None, *, max_calls: int | None = None) -> None:
        if provider is None:
            from app.services.gemini_financial_analyst import GeminiFinancialAnalyst

            provider = GeminiFinancialAnalyst()
        self.provider = provider
        if max_calls is None:
            max_calls = int(os.getenv("CONFERENCE_PDF_MULTIMODAL_MAX_CALLS", "") or _DEFAULT_MAX_CALLS)
        self.max_calls = max(0, int(max_calls))
        self.calls = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    # One long-lived loop keeps the provider's async client on a single loop and
    # works whether or not the caller already runs an event loop.
    def _run(self, coroutine: Any) -> Any:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
                self._thread.start()
        timeout = float(getattr(self.provider, "timeout_seconds", 45.0)) * 2 * max(1, _CONCURRENCY) + 30
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout=timeout)

    def close(self) -> None:
        """Release the provider's async client and the background loop."""
        with self._lock:
            loop, thread = self._loop, getattr(self, "_thread", None)
            self._loop = None
        if loop is None:
            return
        aclose = getattr(getattr(self.provider, "_client", None), "aclose", None)
        try:
            if callable(aclose):
                asyncio.run_coroutine_threadsafe(aclose(), loop).result(timeout=10)
            asyncio.run_coroutine_threadsafe(loop.shutdown_default_executor(), loop).result(timeout=10)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=10)
        if not loop.is_running():
            loop.close()
        if hasattr(self.provider, "_client") and callable(aclose):
            self.provider._client = None

    def interpret_page(self, page: Any, items: list[tuple[dict[str, Any], RegionContext]]) -> None:
        if not bool(getattr(self.provider, "configured", False)):
            for record, _ in items:
                _mark(record, "unavailable", error={"error_type": "NotConfigured"})
            return
        scheduled = []
        for record, source in items:
            if self.calls >= self.max_calls:
                _mark(record, "skipped", error={"error_type": "CallBudgetExhausted"})
                continue
            self.calls += 1
            try:
                image = crop_png(page, source.bbox)
            except Exception as exc:  # rendering failure: keep deterministic evidence
                _mark(record, "failed", error={"error_type": type(exc).__name__})
                continue
            scheduled.append((record, source, image))
        if not scheduled:
            return
        try:
            outcomes = self._run(self._interpret_all(scheduled))
        except Exception as exc:
            outcomes = [exc] * len(scheduled)
        for (record, source, _), outcome in zip(scheduled, outcomes):
            if isinstance(outcome, BaseException):
                _mark(record, "failed", error=self._safe_error(outcome))
                continue
            payload, model = outcome
            try:
                interpretation = RegionInterpretation(**payload).model_dump()
            except (ValidationError, TypeError) as exc:
                _mark(record, "failed", error={"error_type": "SchemaValidationError", "detail": str(exc)[:200]})
                continue
            apply_interpretation(record, source, interpretation, provider=self.provider_label, model=model)

    async def _interpret_all(self, scheduled: list[tuple[dict[str, Any], RegionContext, bytes]]) -> list[Any]:
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def one(record: dict[str, Any], source: RegionContext, image: bytes) -> Any:
            async with semaphore:
                contents = [{"role": "user", "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": image}},
                    {"text": _request_text(record, source)},
                ]}]
                return await self.provider.generate_structured(
                    contents, system_instruction=_SYSTEM_PROMPT, schema=REGION_SCHEMA, max_output_tokens=2500,
                )

        return await asyncio.gather(*(one(*item) for item in scheduled), return_exceptions=True)

    def _safe_error(self, exc: BaseException) -> dict[str, Any]:
        safe = getattr(self.provider, "_safe_trace_error", None)
        if callable(safe) and isinstance(exc, Exception):
            fields = safe(exc)
            return {
                "error_type": fields.get("error_type"),
                "error_code": fields.get("error_code"),
                "detail": fields.get("safe_error_message"),
            }
        return {"error_type": type(exc).__name__}


def _mark(record: dict[str, Any], status: str, *, error: dict[str, Any] | None = None) -> None:
    record["semantic_provider"] = "gemini"
    record["semantic_provider_status"] = status
    if error:
        record["semantic_provider_error"] = error
    # Deterministic evidence stays as-is; an unavailable provider never upgrades anything.
    if record.get("verification_status") == "verified":
        return
    if status != "completed" and record.get("evidence_type") in {"unknown", "chart", "image"}:
        record["verification_status"] = "needs_review"


def apply_interpretation(
    record: dict[str, Any],
    source: RegionContext,
    interpretation: dict[str, Any],
    *,
    provider: str,
    model: str | None,
) -> None:
    status, report = validate_region_interpretation(interpretation, source, record)
    record["provider_interpretation"] = interpretation
    record["validation"] = report
    record["semantic_provider"] = provider
    record["semantic_model"] = model
    record["semantic_prompt_version"] = PROMPT_VERSION
    record["semantic_provider_status"] = "completed"
    record["extraction_method"] = f"{record.get('extraction_method')}+gemini_multimodal"

    deterministic_type = record.get("evidence_type")
    region_type = interpretation["region_type"]
    if deterministic_type in {"unknown", "image"} and region_type != "unknown":
        record["evidence_type"] = region_type
    record["chart_type"] = interpretation.get("chart_type") or record.get("chart_type")
    if interpretation.get("series"):
        record["series"] = interpretation["series"]
    if interpretation.get("unit") and report.get("unit_supported"):
        record["unit"] = interpretation["unit"]
    if interpretation.get("is_forecast") is not None:
        record["is_forecast"] = interpretation["is_forecast"]
    if interpretation.get("title") and report.get("title_supported"):
        record["title"] = interpretation["title"]

    if record.get("mapping_status") != "aligned" and interpretation["values"]:
        record["values"] = [
            {**{key: value for key, value in item.items() if value is not None},
             "source": provider,
             "value_supported": check["value_supported"],
             "mapping_supported": check["mapping_supported"]}
            for item, check in zip(interpretation["values"], report["values"])
        ]
        record["mapping_status"] = "source_aligned" if report["mapping_established"] else "provider_only"
        if interpretation["labels"]:
            record["labels"] = interpretation["labels"]
    if not record.get("trend") and interpretation["trend"] != "unknown":
        record["trend"] = interpretation["trend"]
        record["trend_source"] = provider
    record["trend_supported"] = report["trend_supported"]

    if record.get("verification_status") != "verified":
        record["verification_status"] = status
    record["confidence"] = round(
        min(float(interpretation["confidence"]), 0.85) * (1.0 if status == "partially_verified" else 0.6), 3,
    )


def build_region_interpreter_from_env() -> GeminiRegionInterpreter | None:
    """Multimodal interpretation is opt-in: CONFERENCE_PDF_MULTIMODAL_PROVIDER=gemini."""
    if os.getenv("CONFERENCE_PDF_MULTIMODAL_PROVIDER", "").strip().lower() != "gemini":
        return None
    return GeminiRegionInterpreter()


def semantic_gating_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    regions = [item for item in records if item.get("evidence_type") != "text"]
    statuses = [item.get("semantic_provider_status", "not_requested") for item in regions]
    eligible = sum(1 for item in regions if item.get("gemini_eligible"))
    calls = sum(1 for status in statuses if status in {"completed", "failed"})
    return {
        "total_semantic_regions": len(regions),
        "gemini_eligible": eligible,
        "gemini_calls": calls,
        "gemini_skipped": len(regions) - calls,
        "gemini_skipped_not_eligible": len(regions) - eligible,
        "gemini_unavailable": statuses.count("unavailable"),
        "gemini_budget_skipped": sum(
            1 for item in regions
            if (item.get("semantic_provider_error") or {}).get("error_type") == "CallBudgetExhausted"
        ),
        "gemini_successes": statuses.count("completed"),
        "gemini_failures": statuses.count("failed"),
    }


def merge_gating_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        for key, value in item.items():
            merged[key] = merged.get(key, 0) + int(value or 0)
    return merged
