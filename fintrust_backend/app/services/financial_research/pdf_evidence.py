"""Statement-page evidence from an archived, SHA-256-verified official financial-report PDF.

Locates the consolidated balance sheet page by its title and extracts the TIFRS account-code totals
(1XXX 資產總計, 2XXX 負債總計, 3XXX 權益總計, 31XX 本公司業主權益總計). The mapping is by official account
code, not by fuzzy label matching. Amounts are thousand TWD as printed on the statement. Extraction is local
(pypdf); no OCR, no LLM, no network.
"""

from __future__ import annotations

import io
import re
from typing import Any

from app.services.financial_research import decimal_math as dm

EXTRACTOR_VERSION = "pdf_balance_sheet_totals_v1"
ACCOUNT_CODES = {"1XXX": "total_assets", "2XXX": "total_liabilities", "3XXX": "equity",
                 "31XX": "equity_attributable_to_owners_of_parent"}
_TITLE = "合併資產負債表"
_LINE = re.compile(r"^\s*(?P<code>1XXX|2XXX|3XXX|31XX)\s+(?P<label>\S+)\s+\$?\s*(?P<amount>\(?[\d,]+\)?)")
_UNITS = ("單位：新台幣千元", "單位:新台幣千元")


class PdfEvidenceUnavailable(RuntimeError):
    pass


def _extractor() -> tuple[Any, str]:
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise PdfEvidenceUnavailable("pypdf is not installed in this deployment") from exc
    return pypdf, f"pypdf {pypdf.__version__}"


def balance_sheet_totals(content: bytes) -> dict[str, Any]:
    pypdf, extractor = _extractor()
    reader = pypdf.PdfReader(io.BytesIO(content))
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        compact = re.sub(r"\s+", "", text)
        if _TITLE not in compact or "1XXX" not in text:
            continue
        unit_ok = any(unit in compact for unit in _UNITS)
        totals: dict[str, Any] = {}
        for line in text.splitlines():
            match = _LINE.match(line)
            if match and ACCOUNT_CODES[match["code"]] not in totals:
                totals[ACCOUNT_CODES[match["code"]]] = {
                    "account_code": match["code"], "label": match["label"],
                    "value_thousand_twd": dm.text(dm.parse_decimal(match["amount"])), "line": line.strip()}
        printed = re.search(r"-\s*(\d+)\s*-", text)
        return {"extractor_version": EXTRACTOR_VERSION, "extractor": extractor, "pdf_page_index": number,
                "printed_page_label": printed.group(1) if printed else None,
                "unit": "TWD_thousand" if unit_ok else "unverified", "totals": totals}
    raise PdfEvidenceUnavailable("consolidated balance sheet page not found")


class ArchivePdfEvidenceProvider:
    """Reads the consolidated annual-report PDF of a fiscal year from the immutable raw archive (hash-verified)."""

    def __init__(self, repository: Any, archive: Any) -> None:
        self.repository, self.archive = repository, archive
        self._cache: dict[tuple[str, int], dict[str, Any] | None] = {}

    def statement_totals(self, ticker: str, fiscal_year: int) -> dict[str, Any] | None:
        key = (ticker, fiscal_year)
        if key in self._cache:
            return self._cache[key]
        result = None
        versions = [v for v in self.repository.list_filing_versions(ticker, fiscal_year, fiscal_year)
                    if v["source_kind"] == "official_pdf" and v["statement_scope"] == "consolidated"]
        for version in sorted(versions, key=lambda v: v["filing_version_id"]):
            try:
                content = self.archive.read(version["raw_storage_path"])  # re-verifies SHA-256
                totals = balance_sheet_totals(content)
            except (PdfEvidenceUnavailable, RuntimeError, OSError, ValueError):
                continue
            result = {**totals, "filing_version_id": version["filing_version_id"], "pdf_sha256": version["content_hash"],
                      "source_url": version["source_url"], "artifact_available_at": version["available_at"],
                      "artifact_availability_status": version["availability_status"],
                      "filing_version_type": version["filing_version_type"]}
            break
        self._cache[key] = result
        return result
