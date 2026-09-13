from __future__ import annotations

import re


def normalize_period(text: str) -> str | None:
    """Normalize explicit Gregorian/ROC annual or quarterly periods.

    Ambiguous expressions such as "今年" are intentionally not guessed.
    """

    roc = re.search(
        r"(?P<year>1\d{2})\s*年\s*(?:(?:第\s*)?(?P<q>[1-4])\s*季|Q(?P<q2>[1-4])|全年)?",
        text,
        re.I,
    )
    if roc:
        year = int(roc.group("year")) + 1911
        quarter = roc.group("q") or roc.group("q2")
        return f"{year}Q{quarter}" if quarter else f"{year}FY"

    gregorian = re.search(
        r"(?P<year>20\d{2})\s*(?:年|/|-)?\s*(?:(?:第\s*)?(?P<q>[1-4])\s*季|Q(?P<q2>[1-4])|全年|FY)?",
        text,
        re.I,
    )
    if gregorian:
        year = int(gregorian.group("year"))
        quarter = gregorian.group("q") or gregorian.group("q2")
        return f"{year}Q{quarter}" if quarter else f"{year}FY"
    return None


def previous_year_same_period(period: str) -> str | None:
    match = re.fullmatch(r"(?P<year>20\d{2})(?P<suffix>FY|Q[1-4])", period)
    if not match:
        return None
    return f"{int(match.group('year')) - 1}{match.group('suffix')}"


def previous_quarter(period: str) -> str | None:
    match = re.fullmatch(r"(?P<year>20\d{2})Q(?P<q>[1-4])", period)
    if not match:
        return None
    year, quarter = int(match.group("year")), int(match.group("q"))
    if quarter == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{quarter - 1}"
