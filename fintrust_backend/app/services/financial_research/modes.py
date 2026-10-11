"""The three explicit analysis modes and request validation (no implicit default, no hidden fallback)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.services.historical_audit.models import TAIPEI


class AnalysisMode(str, Enum):
    RETROSPECTIVE_FORENSIC = "RETROSPECTIVE_FORENSIC"
    STRICT_AS_OF = "STRICT_AS_OF"
    CURRENT_EVIDENCE_RECONCILIATION = "CURRENT_EVIDENCE_RECONCILIATION"


MODE_DESCRIPTIONS = {
    AnalysisMode.RETROSPECTIVE_FORENSIC: (
        "Post-event reconstruction from the full archive, including the 2016-11-13 restatement notices. hindsight=true; "
        "not evidence of ex-ante predictability."),
    AnalysisMode.STRICT_AS_OF: (
        "Only observations verifiably available strictly before cutoff_at (exclusive). Missing inputs are reported as "
        "not computable; full data is never substituted."),
    AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION: (
        "Compares currently verifiable official sources for the same ticker, period, scope, unit and metric. A mismatch "
        "is unresolved evidence, not a proven restatement, misstatement or fraud."),
}


class AnalysisRequestError(ValueError):
    """Invalid research request (maps to HTTP 422)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"error_code": self.code, "message": self.message}


class ModeNotSupportedError(AnalysisRequestError):
    """The mode is valid but not meaningful for this capability (maps to HTTP 409)."""


def parse_mode(value: Any) -> AnalysisMode:
    if value is None or str(value).strip() == "":
        raise AnalysisRequestError("analysis_mode_required",
                                   "analysis_mode is required: RETROSPECTIVE_FORENSIC, STRICT_AS_OF or "
                                   "CURRENT_EVIDENCE_RECONCILIATION (there is no default).")
    try:
        return AnalysisMode(str(value).strip())
    except ValueError as exc:
        raise AnalysisRequestError("analysis_mode_invalid", f"Unknown analysis_mode {value!r}.") from exc


def parse_cutoff(value: Any) -> datetime:
    """A timezone-aware instant. Bare dates are refused: the caller must state the exact exclusive instant."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if len(text) <= 10:
            raise AnalysisRequestError("cutoff_at_not_instant",
                                       "cutoff_at must be a timezone-aware ISO-8601 instant, e.g. 2016-05-13T00:00:00+08:00.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AnalysisRequestError("cutoff_at_invalid", f"cutoff_at {text!r} is not ISO-8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AnalysisRequestError("cutoff_at_naive", "cutoff_at must carry a timezone offset.")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AnalysisContext:
    mode: AnalysisMode
    cutoff_at: datetime | None  # UTC, exclusive; set only for STRICT_AS_OF

    @property
    def hindsight(self) -> bool:
        return self.mode is AnalysisMode.RETROSPECTIVE_FORENSIC

    @property
    def reader_as_of(self) -> datetime | None:
        """The historical reader treats a datetime as inclusive (+1 µs); this yields exactly ``< cutoff_at``."""
        return None if self.cutoff_at is None else self.cutoff_at - timedelta(microseconds=1)

    def admits(self, available_at: datetime | None) -> bool:
        if self.mode is not AnalysisMode.STRICT_AS_OF:
            return True
        return available_at is not None and available_at < self.cutoff_at  # type: ignore[operator]

    def as_dict(self) -> dict[str, Any]:
        return {
            "analysis_mode": self.mode.value,
            "cutoff_at": self.cutoff_at.isoformat() if self.cutoff_at else None,
            "cutoff_at_taipei": self.cutoff_at.astimezone(TAIPEI).isoformat() if self.cutoff_at else None,
            "cutoff_semantics": "exclusive: effective_available_at < cutoff_at" if self.cutoff_at else None,
            "hindsight": self.hindsight,
            "mode_description": MODE_DESCRIPTIONS[self.mode],
        }


def build_context(mode: Any, cutoff_at: Any = None, *, allowed: tuple[AnalysisMode, ...] | None = None) -> AnalysisContext:
    parsed = parse_mode(mode)
    if allowed is not None and parsed not in allowed:
        raise ModeNotSupportedError(
            "analysis_mode_not_supported",
            f"{parsed.value} is not supported here; allowed: {', '.join(m.value for m in allowed)}.")
    if parsed is AnalysisMode.STRICT_AS_OF:
        if cutoff_at is None or str(cutoff_at).strip() == "":
            raise AnalysisRequestError("cutoff_at_required", "STRICT_AS_OF requires cutoff_at (exclusive, timezone-aware).")
        return AnalysisContext(parsed, parse_cutoff(cutoff_at))
    if cutoff_at is not None and str(cutoff_at).strip() != "":
        raise AnalysisRequestError("cutoff_at_not_allowed",
                                   f"cutoff_at applies only to STRICT_AS_OF; {parsed.value} uses no cutoff.")
    return AnalysisContext(parsed, None)
