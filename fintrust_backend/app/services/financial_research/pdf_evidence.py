"""Statement-page evidence from an archived, SHA-256-verified official financial-report PDF (v2).

Locates the consolidated balance sheet page by its title and extracts the TIFRS account-code totals
(1XXX 資產總計, 2XXX 負債總計, 3XXX 權益總計, 31XX 本公司業主權益總計). The mapping is by official account
code, not by fuzzy label matching. Extraction is local (pypdf); no OCR, no LLM, no network.

Every result is a typed evidence record, never ``None``:

- ``status=extracted`` carries the exact filing-version identity, the re-verified content SHA-256, the page, and
  explicit checks for the statement unit (``單位：新台幣千元``), the fiscal year printed on the page (ROC year) and the
  consolidated scope (page title). Numerical equality may be claimed only when all three checks are ``verified``.
- ``status=unavailable`` states why (no consolidated PDF, ambiguous versions, unreadable archive, page not found, no
  PDF library). The PDF is selected by exact filing-version identity compatible with the compared XBRL version; it
  is never chosen by sort order.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any

from app.services.financial_research import decimal_math as dm

EXTRACTOR_VERSION = "pdf_balance_sheet_totals_v2"
ACCOUNT_CODES = {"1XXX": "total_assets", "2XXX": "total_liabilities", "3XXX": "equity",
                 "31XX": "equity_attributable_to_owners_of_parent"}
_TITLE = "合併資產負債表"
_LINE = re.compile(r"^\s*(?P<code>1XXX|2XXX|3XXX|31XX)\s+(?P<label>\S+)\s+\$?\s*(?P<amount>\(?[\d,]+\)?)")
_UNITS = ("單位：新台幣千元", "單位:新台幣千元")
_ROC_DATE = re.compile(r"民國(\d{2,3})年(?:及(\d{2,3})年)?(?:12月31日)")


class PdfEvidenceUnavailable(RuntimeError):
    pass


def _extractor() -> tuple[Any, str]:
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise PdfEvidenceUnavailable("pdf_library_unavailable") from exc
    return pypdf, f"pypdf {pypdf.__version__}"


def parse_balance_sheet_page(text: str) -> dict[str, Any] | None:
    """Totals and identity signals of one page if it is the consolidated balance sheet; ``None`` otherwise (pure)."""
    compact = re.sub(r"\s+", "", text)
    if _TITLE not in compact or "1XXX" not in text:
        return None
    totals: dict[str, Any] = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match and ACCOUNT_CODES[match["code"]] not in totals:
            totals[ACCOUNT_CODES[match["code"]]] = {
                "account_code": match["code"], "label": match["label"],
                "value_thousand_twd": dm.text(dm.parse_decimal(match["amount"])), "line": line.strip()}
    printed = re.search(r"-\s*(\d+)\s*-", text)
    date = _ROC_DATE.search(compact)
    return {"printed_page_label": printed.group(1) if printed else None,
            "unit": "TWD_thousand" if any(unit in compact for unit in _UNITS) else "unverified",
            "statement_title": _TITLE, "statement_scope": "consolidated",
            "reporting_roc_year": int(date.group(1)) if date else None,
            "comparative_roc_year": int(date.group(2)) if date and date.group(2) else None,
            "totals": totals}


def balance_sheet_totals(content: bytes) -> dict[str, Any]:
    pypdf, extractor = _extractor()
    reader = pypdf.PdfReader(io.BytesIO(content))
    for number, page in enumerate(reader.pages, start=1):
        parsed = parse_balance_sheet_page(page.extract_text() or "")
        if parsed is not None:
            return {"extractor_version": EXTRACTOR_VERSION, "extractor": extractor, "pdf_page_index": number, **parsed}
    raise PdfEvidenceUnavailable("balance_sheet_page_not_found")


def identity_checks(evidence: dict[str, Any], fiscal_year: int) -> dict[str, str]:
    """Unit, fiscal-year and scope checks; each is ``verified`` or a reason (pure)."""
    return {
        "unit": "verified" if evidence.get("unit") == "TWD_thousand" else "unit_unverified",
        "fiscal_year": ("verified" if evidence.get("reporting_roc_year") == fiscal_year - 1911
                        else "fiscal_year_not_found_on_page" if evidence.get("reporting_roc_year") is None
                        else "fiscal_year_mismatch"),
        "statement_scope": "verified" if evidence.get("statement_scope") == "consolidated" else "scope_unverified",
    }


def unavailable(fiscal_year: int, reason: str, **extra: Any) -> dict[str, Any]:
    return {"fiscal_year": fiscal_year, "status": "unavailable", "reason": reason,
            "extractor_version": EXTRACTOR_VERSION, **extra}


class ArchivePdfEvidenceProvider:
    """Reads the consolidated annual-report PDF of a fiscal year from the immutable raw archive (hash-verified)."""

    def __init__(self, repository: Any, archive: Any) -> None:
        self.repository, self.archive = repository, archive
        self._cache: dict[tuple[str, int, str | None], dict[str, Any]] = {}

    def statement_evidence(self, ticker: str, fiscal_year: int, *, xbrl_version_type: str | None) -> dict[str, Any]:
        key = (ticker, fiscal_year, xbrl_version_type)
        if key not in self._cache:
            self._cache[key] = self._evidence(ticker, fiscal_year, xbrl_version_type)
        return self._cache[key]

    def _evidence(self, ticker: str, fiscal_year: int, xbrl_version_type: str | None) -> dict[str, Any]:
        candidates = [v for v in self.repository.list_filing_versions(ticker, fiscal_year, fiscal_year)
                      if v["source_kind"] == "official_pdf" and v["statement_scope"] == "consolidated"
                      and v["fiscal_year"] == fiscal_year and v["period"] == f"{fiscal_year}FY"]
        if not candidates:
            return unavailable(fiscal_year, "no_consolidated_annual_pdf_version")
        compatible = [v for v in candidates if v["filing_version_type"] == xbrl_version_type]
        if len(compatible) != 1:
            return unavailable(fiscal_year, "no_pdf_version_matching_xbrl_version_type" if not compatible
                               else "ambiguous_pdf_versions",
                               candidate_versions=sorted(v["filing_version_id"] for v in candidates),
                               xbrl_version_type=xbrl_version_type)
        version = compatible[0]
        try:
            content = self.archive.read(version["raw_storage_path"])  # re-verifies the content-addressed SHA-256
        except (RuntimeError, OSError, ValueError):
            return unavailable(fiscal_year, "archive_unreadable_or_hash_mismatch", filing_version_id=version["filing_version_id"])
        if hashlib.sha256(content).hexdigest() != version["content_hash"]:
            return unavailable(fiscal_year, "content_sha256_mismatch", filing_version_id=version["filing_version_id"])
        try:
            totals = balance_sheet_totals(content)
        except PdfEvidenceUnavailable as exc:
            return unavailable(fiscal_year, str(exc), filing_version_id=version["filing_version_id"])
        evidence = {"fiscal_year": fiscal_year, "status": "extracted", **totals,
                    "filing_version_id": version["filing_version_id"], "filing_version_type": version["filing_version_type"],
                    "selection_basis": "only consolidated annual PDF version with the same filing_version_type as the XBRL",
                    "pdf_sha256": version["content_hash"], "content_sha256_verified": True,
                    "source_url": version["source_url"], "artifact_available_at": version["available_at"],
                    "artifact_availability_status": version["availability_status"]}
        evidence["checks"] = identity_checks(evidence, fiscal_year)
        return evidence
