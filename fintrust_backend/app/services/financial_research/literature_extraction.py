"""Line-level extraction of literature-model inputs from the preserved official raw archive (read-only).

Sources are the archived artifacts already referenced by ``financial_filing_versions`` (approved baseline); nothing is
downloaded. Each artifact's SHA-256 is re-verified before parsing and the bytes are never modified.

- **TIFRS XBRL** (FY2013+; ``mops_xbrl_instance`` / ``mops_inline_xbrl``): every non-dimensional, TWD-denominated fact
  of the primary-statement taxonomies (balance sheet, comprehensive income, cash flows) whose context is a full fiscal
  year or a fiscal-year-end / IFRS-transition instant of the filing year or the comparative year. Values are exact
  Decimals as tagged (TWD).
- **TW-GAAP consolidated annual-report PDF text** (FY2011-2012 ``official_pdf``): only the catalogued account-code
  lines of the consolidated balance sheet and income statement and the catalogued labels of the cash-flow statement,
  current and comparative columns, with the printed line kept verbatim. Statements are located by title; the unit
  (新台幣仟元/千元), the printed ROC year and the consolidated title are verified, and arithmetic identities are
  checked (total assets = total liabilities and equity; net sales - operating costs = gross profit). PDFs whose
  statement pages carry no text layer are recorded as ``statement_pages_not_machine_readable`` (no OCR is attempted).

No observation is admitted to STRICT_AS_OF: the verified strict source contract admits only observation-level
timestamps of the canonical facts, so ``pit_admitted`` is always false here (artifact timing is kept for review).
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.case_knowledge import accounting_regime
from app.services.historical_audit.normalization import _is_statement_namespace
from app.services.historical_audit.xbrl_document import parse_xbrl_document

EXTRACTOR_VERSION = "literature_line_extractor_v1"
PIT_BASIS = ("not_admitted: the current STRICT_AS_OF contract admits only observation-level verified timestamps of "
             "canonical facts; literature line observations carry artifact-level timing only")

# TW-GAAP catalogue: account codes (balance sheet / income statement) and cash-flow labels.
TWGAAP_BALANCE_CODES = ("1100", "1120", "1140", "1150", "1160", "1178", "1180", "11XX", "120X", "1200", "1310", "1320",
                        "1330", "1350", "1360", "1421", "1430", "1440", "1450", "1460", "1480", "15XX", "1XXX", "2100",
                        "2110", "2160", "2270", "21XX", "2410", "2420", "2430", "24XX", "2XXX", "3110", "3120", "3XXX")
TWGAAP_INCOME_CODES = ("4100", "5000", "5910", "6100", "6200", "6300", "6000", "7900", "9600")
DEDUCTION_CODES = {"5000", "6100", "6200", "6300", "6000"}  # printed in parentheses as deductions
TWGAAP_CASHFLOW_LABELS = ("各項折舊(含出租資產及閒置資產)", "各項折舊(含出租資產)", "各項折舊", "折舊費用", "各項攤提",
                          "攤銷費用", "長期借款增加", "舉借長期借款", "發行應付公司債", "發行公司債",
                          "應付公司債(減少)增加", "應付公司債增加", "現金增資", "員工認股權執行",
                          "營業活動之淨現金流入(出)", "營業活動之淨現金流入", "營業活動之淨現金流出")
_CJK_DIGITS = {"〇": 0, "○": 0, "０": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
               "八": 8, "九": 9}
_NUMBER_TOKEN = re.compile(r"\(?\$?\d[\d,]*(?:\.\d+)?\)?|(?<!\S)-(?!\S)")
_CODE_TOKEN = re.compile(r"(?<![\w.,/(])(\dXXX|\d{2}XX|\d{3}X|\d{4}|15XY|15X9|361X)(?=\s)")
_HAS_CJK = re.compile(r"[　-鿿＀-￯]")


class ExtractionError(RuntimeError):
    pass


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def observation_id(*parts: Any) -> str:
    return "lobs1_" + hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:32]


def _base(filing: dict[str, Any], framework: str) -> dict[str, Any]:
    return {"ticker": filing["ticker"], "filing_version_id": filing["filing_version_id"],
            "filing_version_type": filing["filing_version_type"], "filing_fiscal_year": filing["fiscal_year"],
            "source_kind": filing["source_kind"], "accounting_framework": framework,
            "statement_scope": filing["statement_scope"], "raw_sha256": filing["content_hash"],
            "source_url": filing.get("source_url"), "extractor_version": EXTRACTOR_VERSION,
            "artifact_available_at": filing.get("available_at"),
            "artifact_availability_status": filing.get("availability_status"),
            "pit_admitted": False, "pit_basis": PIT_BASIS}


# --------------------------------------------------------------------------------------------- XBRL
def extract_xbrl(content: bytes, filing: dict[str, Any]) -> list[dict[str, Any]]:
    year = int(filing["fiscal_year"])
    document = parse_xbrl_document(content)
    if document.entity_identifiers and document.entity_identifiers != {filing["ticker"]}:
        raise ExtractionError("entity_identifier_mismatch")
    scope = document.statement_scope()[0]
    if scope != filing["statement_scope"]:
        raise ExtractionError(f"statement_scope_mismatch:{scope}")
    instants = {date(year, 12, 31), date(year - 1, 12, 31), date(year - 1, 1, 1)}
    durations = {(date(y, 1, 1), date(y, 12, 31)) for y in (year, year - 1)}
    base = _base(filing, "TIFRS")
    method = "inline_xbrl" if document.document_format != "xbrl_instance" else "xbrl_instance"
    rows: dict[str, dict[str, Any]] = {}
    for fact in document.numeric_facts:
        if fact.is_nil or fact.value is None or not _is_statement_namespace(fact.namespace):
            continue
        context = document.contexts.get(fact.context_ref)
        if context is None or context.dimensional:
            continue
        if document.units.get(fact.unit_ref or "", "").lower() != "iso4217:twd":
            continue
        if context.instant is not None and context.instant in instants:
            period = {"period_type": "instant", "period_start": None, "period_end": context.instant.isoformat()}
        elif context.instant is None and (context.start, context.end) in durations:
            period = {"period_type": "duration", "period_start": context.start.isoformat(),
                      "period_end": context.end.isoformat()}
        else:
            continue
        value = dm.text(fact.value)
        oid = observation_id(EXTRACTOR_VERSION, filing["filing_version_id"], filing["content_hash"], fact.concept,
                             period["period_type"], period["period_start"], period["period_end"], value)
        rows[oid] = {**base, **period, "observation_id": oid, "statement": _statement(fact.namespace),
                     "line_key": fact.local_name, "source_concept": fact.concept, "value": value,
                     "published_value": fact.value_text, "published_unit": "TWD",
                     "locator": f"context={fact.context_ref};decimals={fact.decimals}", "extraction_method": method,
                     "checks": {}}
    return sorted(rows.values(), key=lambda r: r["observation_id"])


def _statement(namespace: str) -> str:
    lowered = namespace.lower()
    if "scf" in lowered or "/cf" in lowered:
        return "cash_flow_statement"
    return "primary_statement"


# --------------------------------------------------------------------------------------------- TW-GAAP PDF
def roc_year(text: str) -> int | None:
    match = re.search(r"民國([〇○０零一二三四五六七八九]{2,3})年", re.sub(r"\s+", "", text))
    if not match:
        return None
    value = 0
    for char in match.group(1):
        value = value * 10 + _CJK_DIGITS[char]
    return value


def _amount(token: str) -> Decimal | None:
    if token == "-":
        return Decimal(0)
    cleaned = token.replace("$", "")
    return dm.parse_decimal(cleaned)


def _row_tokens(segment: str) -> list[str]:
    kept = " ".join(part for part in segment.split() if not _HAS_CJK.search(part) or re.match(r"^[\d,().$-]+$", part))
    return _NUMBER_TOKEN.findall(kept)


def parse_code_rows(text: str, codes: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Two-column statement rows ``CODE label [notes] amount pct amount pct`` for the catalogued codes (pure)."""
    found: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        matches = list(_CODE_TOKEN.finditer(line))
        for index, match in enumerate(matches):
            code = match.group(1)
            if code not in codes or code in found:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            segment = line[match.end():end]
            label = re.sub(r"\s+", "", re.split(r"[\d$(]", segment, maxsplit=1)[0])
            tokens = _row_tokens(segment)
            if len(tokens) < 4 or "." in tokens[0] or "." in tokens[2] or not ("." in tokens[1] or tokens[1] == "-"):
                continue
            found[code] = {"label": label, "current": tokens[0], "comparative": tokens[2], "line": line.strip()}
    return found


def parse_total_rows(text: str) -> dict[str, dict[str, Any]]:
    """Balance-sheet total rows printed without an account code (e.g. ``資 產 總 計 $x pct $y pct``) (pure)."""
    found: dict[str, dict[str, Any]] = {}
    for label in ("資產總計",):
        pattern = re.compile(r"\s*".join(map(re.escape, label)) + r"(?P<rest>\s+.*)$")
        for line in text.splitlines():
            match = pattern.search(line)
            if not match or label in found:
                continue
            tokens = _row_tokens(match.group("rest"))
            if len(tokens) >= 4 and "." not in tokens[0] and "." not in tokens[2] and "." in tokens[1]:
                found[label] = {"label": label, "current": tokens[0], "comparative": tokens[2], "line": line.strip()}
    return found


def parse_label_rows(text: str, labels: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Cash-flow rows ``label amount amount`` (two fiscal-year columns) for the catalogued labels (pure)."""
    found: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        for label in sorted(labels, key=len, reverse=True):
            if label in found:
                continue
            pattern = re.compile(r"(?<![一-鿿])" + re.escape(label) + r"\s+(\(?\$?[\d,]+\)?|-)\s+(\(?\$?[\d,]+\)?|-)(?=\s|$)")
            match = pattern.search(line)
            if match:
                found[label] = {"label": label, "current": match.group(1), "comparative": match.group(2),
                                "line": line.strip()}
                line = line[:match.start()] + " " * (match.end() - match.start()) + line[match.end():]
    return found


def _locate(pages: list[str], title: str, marker: str) -> tuple[int, str] | None:
    for number, text in enumerate(pages, start=1):
        compact = re.sub(r"\s+", "", text)
        if title in compact and marker in text:
            return number, text
    return None


def extract_twgaap_pdf(content: bytes, filing: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Catalogued statement lines of a TW-GAAP consolidated annual report; returns (observations, diagnostics)."""
    import pypdf

    year = int(filing["fiscal_year"])
    reader = pypdf.PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages[:20]]
    diagnostics: dict[str, Any] = {"extractor": f"pypdf {pypdf.__version__}", "pages_scanned": len(pages)}
    located = {"balance_sheet": _locate(pages, "合併資產負債表", "11XX"),
               "income_statement": _locate(pages, "合併損益表", "4100"),
               "cash_flow_statement": _locate(pages, "合併現金流量表", "營業活動")}
    diagnostics["statement_pages"] = {name: (loc[0] if loc else None) for name, loc in located.items()}
    if not any(located.values()):
        diagnostics["status"] = "statement_pages_not_machine_readable"
        return [], diagnostics
    base = _base(filing, accounting_regime(filing["ticker"], year) or "unknown")
    rows: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    for statement, loc in located.items():
        if loc is None:
            checks[statement] = "statement_page_not_found"
            continue
        page_number, text = loc
        compact = re.sub(r"\s+", "", text)
        identity = {"unit": "verified" if ("新台幣仟元" in compact or "新台幣千元" in compact) else "unit_unverified",
                    "fiscal_year": "verified" if roc_year(text) == year - 1911 else f"roc_year_{roc_year(text)}",
                    "scope": "verified" if "合併" in compact else "scope_unverified"}
        checks[statement] = identity
        if any(state != "verified" for state in identity.values()):
            continue
        if statement == "cash_flow_statement":
            parsed = {f"label:{k}": v for k, v in parse_label_rows(text, TWGAAP_CASHFLOW_LABELS).items()}
        else:
            codes = TWGAAP_BALANCE_CODES if statement == "balance_sheet" else TWGAAP_INCOME_CODES
            parsed = {f"code:{k}": v for k, v in parse_code_rows(text, codes).items()}
            if statement == "balance_sheet":
                parsed.update({f"label:{k}": v for k, v in parse_total_rows(text).items()})
        for line_key, row in parsed.items():
            code = line_key.split(":", 1)[1]
            for column, fiscal_year in (("current", year), ("comparative", year - 1)):
                amount = _amount(row[column])
                if amount is None:
                    continue
                if code in DEDUCTION_CODES:
                    amount = -amount
                value = dm.text(dm.to_twd(amount, "TWD_thousand"))
                if statement == "balance_sheet":
                    period = {"period_type": "instant", "period_start": None, "period_end": f"{fiscal_year}-12-31"}
                else:
                    period = {"period_type": "duration", "period_start": f"{fiscal_year}-01-01",
                              "period_end": f"{fiscal_year}-12-31"}
                oid = observation_id(EXTRACTOR_VERSION, filing["filing_version_id"], filing["content_hash"], line_key,
                                     period["period_type"], period["period_start"], period["period_end"], value)
                rows.append({**base, **period, "observation_id": oid, "statement": statement, "line_key": line_key,
                             "source_concept": f"{line_key} {row['label']}".strip(), "value": value,
                             "published_value": row[column], "published_unit": "TWD_thousand",
                             "locator": f"pdf_page={page_number};column={column};line={row['line'][:160]}",
                             "extraction_method": "pdf_text_account_code" if line_key.startswith("code:")
                             else "pdf_text_label", "checks": identity})
    diagnostics["identity_checks"] = checks
    diagnostics["arithmetic_checks"] = _arithmetic_checks(rows, year)
    diagnostics["status"] = "extracted" if rows else "no_catalogued_lines_found"
    for row in rows:
        row["checks"] = {**row["checks"], "arithmetic": diagnostics["arithmetic_checks"]}
    return sorted(rows, key=lambda r: r["observation_id"]), diagnostics


def _arithmetic_checks(rows: list[dict[str, Any]], year: int) -> dict[str, str]:
    def value(key: str, fiscal_year: int) -> Decimal | None:
        for row in rows:
            if row["line_key"] == key and row["period_end"] == f"{fiscal_year}-12-31":
                return dm.parse_decimal(row["value"])
        return None

    result = {}
    for fiscal_year in (year, year - 1):
        assets = value("code:1XXX", fiscal_year) or value("label:資產總計", fiscal_year)
        liabilities, equity = value("code:2XXX", fiscal_year), value("code:3XXX", fiscal_year)
        result[f"balance_{fiscal_year}"] = ("verified" if None not in (assets, liabilities, equity)
                                            and assets == dm.add(liabilities, equity) else "failed_or_incomplete")
        sales, cogs, gross = value("code:4100", fiscal_year), value("code:5000", fiscal_year), value("code:5910", fiscal_year)
        result[f"gross_profit_{fiscal_year}"] = ("verified" if None not in (sales, cogs, gross)
                                                 and dm.sub(sales, cogs) == gross else "failed_or_incomplete")
    return result


def _tifrs_pdf_status(content: bytes) -> dict[str, Any]:
    """TIFRS PDFs are not parsed (the XBRL of a version is its structured source); record whether the statement pages
    are machine-readable so a missing original-version input has a precise reason."""
    import pypdf

    pages = [page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(content)).pages[:20]]
    readable = _locate(pages, "合併資產負債表", "1XXX") is not None
    return {"status": "tifrs_pdf_text_not_parsed_xbrl_is_structured_source" if readable
            else "statement_pages_not_machine_readable",
            "pages_without_text_in_first_20": sum(1 for text in pages if len(text.strip()) < 20)}


# --------------------------------------------------------------------------------------------- archive driver
def extract_filing(raw_root: str | Path, filing: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read one archived artifact (SHA-256 re-verified) and extract its line observations."""
    path = Path(raw_root) / filing["raw_storage_path"]
    diagnostics: dict[str, Any] = {"filing_version_id": filing["filing_version_id"], "fiscal_year": filing["fiscal_year"],
                                   "filing_version_type": filing["filing_version_type"],
                                   "source_kind": filing["source_kind"], "statement_scope": filing["statement_scope"],
                                   "raw_sha256": filing["content_hash"], "source_url": filing.get("source_url")}
    if not path.is_file():
        return [], {**diagnostics, "status": "raw_artifact_missing"}
    content = path.read_bytes()
    if sha256(content) != filing["content_hash"]:
        return [], {**diagnostics, "status": "raw_sha256_mismatch"}
    framework = accounting_regime(filing["ticker"], int(filing["fiscal_year"]))
    if filing["source_kind"] in ("mops_xbrl_instance", "mops_inline_xbrl"):
        rows = extract_xbrl(content, filing)
        return rows, {**diagnostics, "status": "extracted" if rows else "no_statement_facts", "observations": len(rows)}
    if filing["source_kind"] == "official_pdf" and framework == "TW_GAAP":
        rows, extra = extract_twgaap_pdf(content, filing)
        return rows, {**diagnostics, **extra, "observations": len(rows)}
    if filing["source_kind"] == "official_pdf":
        return [], {**diagnostics, **_tifrs_pdf_status(content)}
    return [], {**diagnostics, "status": f"unsupported_source_kind:{filing['source_kind']}"}
