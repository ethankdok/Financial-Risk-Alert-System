"""Phase 5 retrospective descriptive experiment gate.

A descriptive, holdout-only fixed-threshold confusion matrix. It never
estimates fraud probabilities or claims predictive skill; real-world labels
must come from independently documented future outcomes, not score values.
No file/database/network operations.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence
import re

VERSION = "fintrust_pit_holdout_evaluation_v1"
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
TICKER = re.compile(r"^[0-9]{4,6}$")


def _timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None and dt.utcoffset() is not None else None


def _score(raw: Any) -> Decimal | None:
    if isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value.is_finite() else None


def evaluate_holdout(
    observations: Sequence[dict[str, Any]],
    *,
    threshold: str,
    threshold_id: str,
    horizon_days: int = 365,
    training_tickers: Sequence[str] = (),
    experiment_id: str = "",
) -> dict[str, Any]:
    """Evaluate only a predefined threshold, explicit PIT and held-out labels.

    Every observation must contain:
    ticker, cutoff_at, score, score_source_sha256, data_available_at,
    label_kind ('documented_event' or 'verified_no_event'),
    label_source_sha256, and either event_at or followup_through.
    """
    limit = _score(threshold)
    if limit is None or not threshold_id.strip() or not experiment_id.strip():
        raise ValueError("finite threshold and pre-registered IDs required")
    if isinstance(horizon_days, bool) or not 1 <= horizon_days <= 3650:
        raise ValueError("invalid follow-up horizon")
    training = set(training_tickers)
    if any(not TICKER.fullmatch(t) for t in training):
        raise ValueError("invalid training company ticker")
    seen: set[tuple[str, str]] = set()
    accepted: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []

    for i, row in enumerate(observations):
        ticker = str(row.get("ticker") or "")
        reason: str | None = None
        cutoff = _timestamp(row.get("cutoff_at"))
        published = _timestamp(row.get("data_available_at"))
        val = _score(row.get("score"))
        label = row.get("label_kind")
        data_hash = str(row.get("score_source_sha256") or "")
        label_hash = str(row.get("label_source_sha256") or "")
        if not TICKER.fullmatch(ticker):
            reason = "invalid_ticker"
        elif ticker in training:
            reason = "company_leakage_from_training"
        elif cutoff is None or published is None:
            reason = "unknown_cutoff_or_publication_instant"
        elif published >= cutoff:
            reason = "score_uses_information_unavailable_at_cutoff"
        elif val is None:
            reason = "invalid_or_missing_score"
        elif not SHA256.fullmatch(data_hash) or not SHA256.fullmatch(label_hash):
            reason = "unverifiable_score_or_outcome_provenance"
        elif label not in ("documented_event", "verified_no_event"):
            reason = "unknown_or_unverified_outcome"
        elif row.get("sample_role") != "holdout":
            reason = "not_predeclared_holdout"
        if reason is None:
            assert cutoff is not None
            unique = (ticker, cutoff.isoformat())
            if unique in seen:
                reason = "duplicate_company_cutoff"
        if reason is None:
            horizon_end = cutoff + timedelta(days=horizon_days)
            if label == "documented_event":
                event_at = _timestamp(row.get("event_at"))
                if event_at is None or not cutoff < event_at <= horizon_end:
                    reason = "event_not_verified_in_future_horizon"
            elif label == "verified_no_event":
                followup = _timestamp(row.get("followup_through"))
                if followup is None or followup < horizon_end:
                    reason = "negative_control_followup_incomplete"
                elif row.get("event_at") is not None:
                    reason = "negative_control_has_event"
        if reason:
            exclusions.append({"observation_index": i, "ticker": ticker, "reason": reason})
        else:
            seen.add((ticker, cutoff.isoformat()))
            accepted.append({
                "ticker": ticker,
                "cutoff_at": cutoff.isoformat(),
                "score": str(val),
                "score_source_sha256": data_hash.lower(),
                "label_source_sha256": label_hash.lower(),
                "event": label == "documented_event",
                "flagged": val >= limit,
            })
    positives = sum(x["event"] for x in accepted)
    negatives = len(accepted) - positives
    tp = sum(x["flagged"] and x["event"] for x in accepted)
    fp = sum(x["flagged"] and not x["event"] for x in accepted)
    fn = sum(not x["flagged"] and x["event"] for x in accepted)
    tn = sum(not x["flagged"] and not x["event"] for x in accepted)

    def ratio(num: int, den: int) -> str | None:
        return str(Decimal(num) / Decimal(den)) if den else None

    complete = len(exclusions) == 0 and positives > 0 and negatives > 0 and len(accepted) >= 2
    return {
        "method_version": VERSION,
        "experiment_id": experiment_id,
        "threshold": str(limit), "threshold_id": threshold_id,
        "horizon_days": horizon_days,
        "sample_size_submitted": len(observations),
        "sample_size_admitted": len(accepted),
        "positive_outcomes": positives, "negative_controls": negatives,
        "exclusions": exclusions, "accepted_observations": accepted,
        "status": "descriptive_cohort_computable_not_preregistered" if complete
                  else "insufficient_observed_holdout_evidence",
        "preregistration_status": "unverified_identifier_only",
        "threshold_pre_registered": False,
        "outcome_source_authenticity_independently_verified": False,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn} if complete else None,
        "descriptive_metrics": ({
            "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn),
            "specificity": ratio(tn, tn + fp),
            "false_positive_rate": ratio(fp, fp + tn),
        } if complete else None),
        "probability_calibrated": False,
        "fraud_prediction_validated": False,
        "causal_inference_supported": False,
        "limitations": [
            "Labels require independently documented outcomes and complete control follow-up.",
            "Only information demonstrably available before each cutoff is admissible.",
            "Threshold ID is an asserted label, not independently verified preregistration.",
            "Independent timestamped preregistration and verified outcome documents are still required for predictive validation.",
            "Disjoint training company IDs are required; excluding a company after looking at outcomes is not acceptable.",
            "Metrics are descriptive for this holdout sample; no statistical confidence or Taiwan calibration is inferred.",
            "Unknown or missing outcomes are exclusions, never silently negative controls.",
        ],
    }
