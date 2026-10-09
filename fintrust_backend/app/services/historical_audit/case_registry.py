from __future__ import annotations

import json
from pathlib import Path

from app.services.historical_audit.models import HistoricalAuditCase


CASES_DIR = Path(__file__).with_name("cases")


class UnknownHistoricalCaseError(LookupError):
    pass


def load_cases(directory: Path = CASES_DIR) -> dict[str, HistoricalAuditCase]:
    """Reviewed historical research cases, keyed by ticker.

    This registry is deliberately separate from company_registry and the
    company master: a historical case never becomes a production company.
    """
    cases: dict[str, HistoricalAuditCase] = {}
    for path in sorted(directory.glob("*.json")):
        case = HistoricalAuditCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if case.ticker in cases:
            raise ValueError(f"Duplicate historical case ticker: {case.ticker}")
        cases[case.ticker] = case
    return cases


def get_case(ticker: str, directory: Path = CASES_DIR) -> HistoricalAuditCase:
    case = load_cases(directory).get(ticker.strip())
    if case is None:
        raise UnknownHistoricalCaseError(
            f"Ticker {ticker} is not a registered historical audit case; add a reviewed case file first."
        )
    return case
