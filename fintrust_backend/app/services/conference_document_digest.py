"""Evidence-first document digest for one archived MOPS conference PDF.

The digest answers "what does this single official document disclose", built
only from the durable archive artifacts (pages.json, semantic.json and, for old
archives without semantic evidence, analysis.json). It is deliberately separate
from the JSD / Cosine cross-period comparison.

Guarantees:
* Every bullet carries evidence_refs back to filename / page / region / status.
* Numbers are copied verbatim from the archived evidence; nothing is recomputed.
* Records that belong to another filename are rejected (no cross-document mix).
* Safe-harbor and other legal text becomes a document notice, never a risk.
* Sections keep every bullet that passes quality and dedup checks; coverage
  metrics state how much of the document the digest actually covers.
* An optional LLM may only rephrase the deterministic overview and is rejected
  wholesale if it introduces any number, period, entity, direction or
  interpretation that the cited bullets do not contain.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from datetime import date
from typing import Any

from app.services.claim_evidence_adapter import _roc_date
from app.services.jsd_bridge_service import TYPE_PREFERENCE

DIGEST_VERSION = "conference-document-digest-v1"
KEY_DISCLOSURE_LIMIT = 30
LANGUAGE_PREFERENCE = ["zh-Hant", "bilingual", "en_may_include_translation", "en"]
STATUS_RANK = {"verified": 3, "partially_verified": 2, "needs_review": 1}

SECTION_TITLES = {
    "financial_performance": ("財務表現", "Financial Performance"),
    "product_and_business_mix": ("產品與業務組合", "Product & Business Mix"),
    "operations": ("營運狀況", "Operations"),
    "outlook_and_guidance": ("未來展望", "Outlook & Guidance"),
    "strategy_and_technology": ("策略與技術進展", "Strategy & Technology"),
    "risks_and_uncertainties": ("風險與不確定性", "Risks & Uncertainties"),
    "other_disclosures": ("其他揭露", "Other Disclosures"),
}
SECTION_ORDER = list(SECTION_TITLES)
DOCUMENT_TYPE_ZH = {
    "earnings_presentation": "法說會簡報",
    "full_earnings_transcript": "法說會逐字稿",
    "financial_results_release": "財務結果新聞稿",
    "investor_presentation": "投資人簡報",
    "analyst_conference_presentation": "分析師會議簡報",
    "other_official_conference_document": "其他官方法說會文件",
}

# --- lexicons -------------------------------------------------------------------

NOTICE_HEADING_RE = re.compile(r"投資安全聲明|安全港|safe\s*harbor|forward[-\s]?looking|預測性陳述|免責|disclaimer", re.I)
# Legal language that is a notice wherever it appears, never a disclosed business risk.
NOTICE_STATEMENT_RE = re.compile(r"forward[-\s]?looking\s+statements?|safe\s*harbor|預測性陳述|安全港|投資安全聲明", re.I)
FOOTNOTE_RE = re.compile(r"^\s*(註\s*\d*\s*[:：]|note\s*\d*\s*:)", re.I)
OUTLOOK_RE = re.compile(r"展望|guidance|outlook|預期|預估|we\s+(currently\s+)?expect|forecast|下一?季|明年|next\s+quarter", re.I)
RISK_RE = re.compile(r"風險|不確定|uncertain|\brisks?\b|波動|volatil|headwind|逆風|關稅|tariff|地緣|geopolit|需求疲弱|供應短缺|shortage", re.I)
PRODUCT_RE = re.compile(r"產品類別|產品組合|產品別|應用別|地區別|營收佔比|營收比重|product\s*group|product\s*mix|segment|revenue\s*breakdown|platform", re.I)
STRATEGY_RE = re.compile(r"\bAI\b|人工智慧|先進製程|\d+\s?(nm|奈米)|製程|技術|新產品|合作|夥伴|資本支出|capex|策略|布局|佈局|roadmap|生成式|旗艦|ASIC|資料中心|data\s*center|車用|automotive|6G|Wi-?Fi\s*\d", re.I)
OPERATIONS_RE = re.compile(r"出貨|庫存|存貨|產能|稼動|供應鏈|良率|shipment|inventor|capacity|utili[sz]ation|supply\s*chain|yield", re.I)
FINANCIAL_RE = re.compile(r"營收|營業收入|毛利|營業利益|淨利|每股盈餘|EPS|revenue|margin|income|費用|現金|cash\s*flow|資產|負債|權益|expense", re.I)
NON_CONTENT_LINE_RE = re.compile(r"^\(?\s*單位\s*[:：]|^www\.|^https?://|copyright|©|all\s+rights\s+reserved", re.I)
UNIT_RE = re.compile(r"單位\s*[:：]\s*([^)）]+?)\s*[)）]")
BASIS_MARKER_RE = re.compile(r"^(Non-TIFRS|TIFRS|Non-GAAP|GAAP|Non-IFRS|IFRS)\b", re.I)
BULLET_RE = re.compile(r"^\s*([•●‧・▪■◆\-–]|\*\s|\(\d+\)|\d+[.、)]\s)")
NUMBER_TOKEN_RE = re.compile(r"\(?[-+]?\d[\d,]*(?:\.\d+)?(?:%|pts)?\)?")
LABEL_UNIT_RE = re.compile(r"[(（]\s*(元|NT\$|%|美金/新台幣|新台幣元|新台幣佰萬元|佰萬元|百萬元|千元|USD)\s*[)）]\s*$")

METRIC_LEXICON: list[tuple[str, re.Pattern[str]]] = [
    ("net_income_parent", re.compile(r"母公司業主|attributable\s+to\s+(owners|shareholders)", re.I)),
    ("eps", re.compile(r"每股盈餘|\bEPS\b|earnings\s+per\s+share", re.I)),
    ("gross_margin", re.compile(r"毛利率|gross\s+margin", re.I)),
    ("operating_margin", re.compile(r"營業利益率|operating\s+margin", re.I)),
    ("net_margin", re.compile(r"淨利率|net\s+(profit\s+)?margin", re.I)),
    ("opex_ratio", re.compile(r"營業費用率|operating\s+expense\s+ratio", re.I)),
    ("gross_profit", re.compile(r"營業毛利|gross\s+profit", re.I)),
    ("operating_income", re.compile(r"營業利益|operating\s+income", re.I)),
    ("pretax_income", re.compile(r"稅前淨利|income\s+before\s+tax", re.I)),
    ("net_income", re.compile(r"本期淨利|net\s+income", re.I)),
    ("operating_expense", re.compile(r"營業費用|operating\s+expenses?", re.I)),
    ("revenue", re.compile(r"營業收入|營收(?!佔比|比重)|net\s+revenue|^revenue", re.I)),
    ("operating_cash_flow", re.compile(r"營業活動之淨現金|operating\s+activities", re.I)),
]
CORE_METRICS = ["revenue", "gross_margin", "operating_income", "operating_margin", "net_income", "eps"]

UNIT_CURRENCIES = [
    (re.compile(r"美金\s*/\s*新台幣|USD\s*/\s*TWD", re.I), "USD/TWD"),
    (re.compile(r"美元|美金|US\$|USD", re.I), "USD"),
    (re.compile(r"人民幣|RMB|CNY", re.I), "CNY"),
    (re.compile(r"新台幣|NT\$|TWD|元", re.I), "TWD"),
]
UNIT_SCALES = [
    (re.compile(r"佰萬|百萬|million|mn", re.I), "mn"),
    (re.compile(r"億|billion|bn", re.I), "bn"),
    (re.compile(r"仟|千|thousand", re.I), "k"),
]


# --- small helpers -----------------------------------------------------------------

def _nfkc(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _squash(text: Any) -> str:
    return re.sub(r"\s+", "", _nfkc(text))


def _clean_line(text: Any) -> str:
    return re.sub(r"\s+", " ", _nfkc(text)).strip()


def _norm_value(value: str) -> str:
    raw = _squash(value).replace(",", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1].lstrip("-")
    return raw.lstrip("+")


def _num_key(value: str) -> str:
    """Numeric identity for corroboration only (never for display): -7% == (7.0%)."""
    raw = _norm_value(value)
    match = re.fullmatch(r"(-?)(\d+(?:\.\d+)?)(%|pts)?", raw)
    if not match:
        return raw
    return f"{match.group(1)}{float(match.group(2)):g}{match.group(3) or ''}"


def _norm_label(label: str) -> str:
    text = _squash(label).lower()
    text = LABEL_UNIT_RE.sub("", text)
    text = re.sub(r"[(（]%[)）]$", "", text)
    return re.sub(r"^合併", "", text)


def _cjk_count(text: str) -> int:
    return sum(1 for char in text if "一" <= char <= "鿿")


def _latin_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z\-]{1,}", text)


def _numeric_tokens(text: str) -> list[str]:
    return [token for token in NUMBER_TOKEN_RE.findall(text or "") if re.search(r"\d", token)]


def _numeric_share(text: str) -> float:
    tokens = text.split()
    if not tokens:
        return 0.0
    return sum(1 for token in tokens if re.fullmatch(r"[-+(]?[\d,.]+%?\)?(pts)?", token)) / len(tokens)


def _metric_id(label: str) -> str | None:
    for metric, pattern in METRIC_LEXICON:
        if pattern.search(label):
            return metric
    return None


def _unit_key(unit_text: str | None) -> str | None:
    """Currency + scale identity; different currencies or scales never merge."""
    if not unit_text:
        return None
    currency = next((key for pattern, key in UNIT_CURRENCIES if pattern.search(unit_text)), None)
    if currency is None:
        return _squash(unit_text).lower()
    if currency == "USD/TWD":
        return currency
    scale = next((key for pattern, key in UNIT_SCALES if pattern.search(unit_text)), "1")
    return f"{currency}_{scale}"


def _period_key(text: str) -> str | None:
    value = _squash(text)
    quarters = {"一": 1, "二": 2, "三": 3, "四": 4}
    match = re.search(r"(20\d{2})年?第([一二三四1-4])季", value)
    if match:
        quarter = match.group(2)
        return f"{match.group(1)}Q{quarters.get(quarter, quarter)}"
    match = re.search(r"(?<!\d)([1-4])Q(\d{2})(?!\d)", value, re.I)
    if match:
        return f"20{match.group(2)}Q{match.group(1)}"
    match = re.search(r"(20\d{2})-?Q([1-4])", value, re.I)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    match = re.fullmatch(r"(20\d{2})年?", value)
    if match:
        return f"{match.group(1)}FY"
    return None


def _cell_kind(column: str) -> str:
    value = _squash(column).lower()
    qualifier = re.sub(r"qoq%?|yoy%?|q-q|y-y|20\d{2}年?|第[一二三四]季|[1-4]q\d{2}|\(註\d*\)|note\d*", "", value)
    if re.search(r"qoq|q-q", value):
        return f"qoq:{qualifier}" if qualifier else "qoq"
    if re.search(r"yoy|y-y", value):
        return f"yoy:{qualifier}" if qualifier else "yoy"
    if re.search(r"佔比|比重|breakdown|share", value):
        return "share"
    return "level"


def _conference_dates(document: dict[str, Any]) -> list[tuple[str, str]]:
    """ROC conference date strings -> (start_iso, end_iso) ranges."""
    ranges = []
    for raw in document.get("conference_dates") or []:
        parts = [part for part in re.split(r"至|~|-", str(raw)) if part.strip()]
        start = _roc_date(parts[0]) if parts else None
        end = _roc_date(parts[-1]) if len(parts) > 1 else start
        if start:
            ranges.append((start, end or start))
    return ranges


def _best_status(statuses: list[str]) -> str:
    return max(statuses or ["needs_review"], key=lambda status: STATUS_RANK.get(status, 0))


def _confidence(status: str) -> str:
    return {"verified": "high", "partially_verified": "medium"}.get(status, "low")


def _ref(filename: str, page: int, *, evidence_type: str, verification_status: str, excerpt: str,
         region_id: str | None = None, extraction_method: str | None = None,
         provider: str | None = None, role: str = "primary") -> dict[str, Any]:
    return {
        "filename": filename,
        "page": page,
        "region_id": region_id,
        "evidence_type": evidence_type,
        "verification_status": verification_status,
        "extraction_method": extraction_method,
        "provider": provider,
        "excerpt": excerpt[:400],
        "role": role,
    }


# --- document selection ----------------------------------------------------------------

def _eligible(document: dict[str, Any]) -> bool:
    return bool(document.get("sha256")) and not document.get("quarantined") and not document.get("duplicate_of")


def _document_matches(document: dict[str, Any], period: str | None, conference_date: str | None) -> bool:
    if period:
        return document.get("period") == period
    if conference_date:
        return any(start <= conference_date <= end for start, end in _conference_dates(document))
    return True


def _rank(document: dict[str, Any], year: int, exact: bool) -> tuple:
    doc_type = document.get("document_type")
    language = document.get("document_language") or document.get("language")
    dates = _conference_dates(document)
    recency = (document.get("period") or "", dates[0][0] if dates else "", year)
    return (
        1 if exact else 0,
        1 if document.get("period_validation_status") == "verified" else 0,
        -(TYPE_PREFERENCE.index(doc_type) if doc_type in TYPE_PREFERENCE else len(TYPE_PREFERENCE)),
        recency,
        -(LANGUAGE_PREFERENCE.index(language) if language in LANGUAGE_PREFERENCE else len(LANGUAGE_PREFERENCE)),
    )


def select_archive_document(archive_repo: Any, ticker: str, *, period: str | None = None,
                            conference_date: str | None = None, max_years: int = 2
                            ) -> tuple[int, dict[str, Any], dict[str, Any]] | None:
    """Pick one archived document by scanning manifests only (no page hydration).

    An explicit period / conference_date searches exactly the announcement years
    that can hold it, however old. Only the untargeted "latest" fallback is
    limited to the most recent ``max_years`` years.
    """
    available = list(archive_repo.available_years(ticker) or [])
    if period and re.fullmatch(r"20\d{2}Q[1-4]", period):
        target_year = int(period[:4])
        years = [year for year in available if year in (target_year, target_year + 1)]
    elif conference_date:
        years = [year for year in available if year == int(conference_date[:4])]
    else:
        period = conference_date = None
        years = sorted(available, reverse=True)[:max_years]
    targeted = bool(period or conference_date)
    best: tuple[tuple, int, dict[str, Any], dict[str, Any]] | None = None
    for year in years:
        manifest = archive_repo.latest_manifest(ticker, year) or {}
        for document in manifest.get("documents", []) or []:
            if not _eligible(document):
                continue
            if targeted and not _document_matches(document, period, conference_date):
                continue
            key = _rank(document, year, targeted)
            if best is None or key > best[0]:
                best = (key, year, manifest, document)
    return None if best is None else (best[1], best[2], best[3])


# --- page structure ------------------------------------------------------------------------

def _boilerplate_lines(pages: list[dict[str, Any]]) -> set[str]:
    counts: dict[str, int] = {}
    for page in pages:
        for line in {_squash(line) for line in str(page.get("text") or "").splitlines() if line.strip()}:
            counts[line] = counts.get(line, 0) + 1
    threshold = max(2, (len(pages) + 1) // 2)
    return {line for line, count in counts.items() if count >= threshold}


def _is_statement_line(line: str) -> bool:
    if BULLET_RE.match(line):
        return _cjk_count(line) >= 2 or len(_latin_words(line)) >= 2
    if _numeric_share(line) >= 0.6:
        return False
    cjk, words = _cjk_count(line), len(_latin_words(line))
    punctuated = bool(re.search(r"[：:，,。；;、]", line))
    if cjk >= 6 and (punctuated or len(line) >= 40):
        return True
    return words >= 4 and (punctuated or len(line) >= 30)


def _is_table_row_line(line: str) -> bool:
    if BULLET_RE.match(line):
        return False
    tokens = _numeric_tokens(line)
    label = NUMBER_TOKEN_RE.split(line, maxsplit=1)[0]
    values = line[len(label):]
    # A table row is a short label followed by (mostly) numbers; prose that merely
    # mentions two numbers ("a forecast exchange rate of 30.6 ... to 1 US dollar") is not.
    return (len(tokens) >= 2 and not re.search(r"[，。；;]", label) and len(label.strip()) <= 30
            and _numeric_share(values) >= 0.6)


def _is_heading_line(line: str, company_name: str) -> bool:
    squashed = _squash(line)
    if not squashed or len(squashed) > 30 or NON_CONTENT_LINE_RE.search(line) or FOOTNOTE_RE.match(line):
        return False
    if company_name and company_name in squashed:
        return False
    if _numeric_share(line) >= 0.5 or BULLET_RE.match(line):
        return False
    if re.search(r"[，。；;]", line):
        return False
    return _cjk_count(line) >= 3 or len(_latin_words(line)) >= 2


class _Page:
    def __init__(self, raw: dict[str, Any], boilerplate: set[str], company_name: str) -> None:
        self.number = int(raw.get("page") or 0)
        self.company_name = company_name
        self.method = raw.get("text_extraction_method") or "selectable_text"
        self.lines = [
            _clean_line(line) for line in str(raw.get("text") or "").splitlines()
            if line.strip() and _squash(line) not in boilerplate
        ]
        self.headings = [line for line in self.lines if _is_heading_line(line, company_name)]
        match = UNIT_RE.search(" ".join(self.lines))
        self.unit_text = match.group(1).strip() if match else None
        # Long legal titles ("NOTE CONCERNING FORWARD-LOOKING STATEMENTS") exceed the
        # heading length limit, so the first lines are checked directly as well.
        self.is_notice_page = (any(NOTICE_HEADING_RE.search(line) for line in [*self.headings[:3], *self.lines[:3]])
                               or bool(NOTICE_HEADING_RE.search(" ".join(self.lines[:4]))))
        self.heading_text = " ".join(self.headings)
        self.title = self._title_block(company_name)
        # Basis markers (TIFRS / Non-TIFRS) scope the rows that follow them.
        self.basis_by_line: list[str | None] = []
        basis = None
        for line in self.lines:
            marker = BASIS_MARKER_RE.match(line)
            if marker:
                basis = marker.group(1)
            self.basis_by_line.append(basis)

    def _title_block(self, company_name: str) -> str | None:
        """The first run of consecutive heading lines, joined verbatim (max 4 lines)."""
        for index, line in enumerate(self.lines):
            if line in self.headings and not NOTICE_HEADING_RE.search(line):
                block = [line]
                for following in self.lines[index + 1:index + 4]:
                    if following not in self.headings or len(" ".join(block + [following])) > 40:
                        break
                    block.append(following)
                return " ".join(block)
        return None

    @property
    def text_status(self) -> str:
        return "verified" if self.method == "selectable_text" else "needs_review"

    def statements(self) -> list[str]:
        """Merge wrapped lines, then keep bullet / sentence statements verbatim."""
        merged: list[str] = []
        for line in self.lines:
            previous = merged[-1] if merged else None
            starts_item = bool(BULLET_RE.match(line) or FOOTNOTE_RE.match(line) or re.match(r"^[^(（：:，,、。]{1,20}[：:]", line))
            blocked = (starts_item or NON_CONTENT_LINE_RE.search(line) or _is_table_row_line(line)
                       or _is_heading_line(line, self.company_name) or previous is None
                       or re.search(r"[。.!?；;]$", previous))
            parenthetical = (previous is not None and line[:1] in "(（" and not NON_CONTENT_LINE_RE.search(line)
                             and not re.search(r"[。.!?；;]$", previous))
            # A footnote keeps absorbing wrapped lines until it ends its sentence.
            open_footnote = (previous is not None and bool(FOOTNOTE_RE.match(previous))
                             and not re.search(r"[。.]$", previous)
                             and not (BULLET_RE.match(line) or FOOTNOTE_RE.match(line) or NON_CONTENT_LINE_RE.search(line)
                                      or _is_table_row_line(line) or BASIS_MARKER_RE.match(line)))
            continuation = parenthetical or open_footnote or not blocked and (
                line[:1] in "(（" or line[:1].islower()
                or len(previous) >= 40
                or bool(FOOTNOTE_RE.match(previous))
            )
            if continuation and (_is_statement_line(previous) or FOOTNOTE_RE.match(previous)):
                joiner = " " if re.search(r"[A-Za-z0-9,]$", previous) or re.match(r"[A-Za-z(]", line) else ""
                merged[-1] = previous + joiner + line
            else:
                merged.append(line)
        results = []
        for line in merged:
            if NON_CONTENT_LINE_RE.search(line) or _is_table_row_line(line):
                continue
            if _is_statement_line(line) or FOOTNOTE_RE.match(line):
                results.append(line)
        return results

    def find_row_line(self, values: list[str], start: int = 0) -> int | None:
        target = "".join(_squash(value) for value in values)
        if not target:
            return None
        order = list(range(start, len(self.lines))) + list(range(0, start))
        for index in order:
            if target in _squash(self.lines[index]):
                return index
        return None

    def tick_values(self) -> set[str]:
        """Axis tick labels: runs of >=3 pure-number lines with a constant step."""
        ticks: set[str] = set()
        run: list[tuple[str, float]] = []

        def flush() -> None:
            # Data labels often sit in the same run as the axis; keep only the
            # maximal sub-runs that climb by a constant positive step.
            start = 0
            while start < len(run) - 2:
                step = run[start + 1][1] - run[start][1]
                end = start + 1
                while end + 1 < len(run) and abs((run[end + 1][1] - run[end][1]) - step) < 1e-9:
                    end += 1
                if step > 0 and end - start >= 2:
                    ticks.update(_norm_value(token) for token, _ in run[start:end + 1])
                    start = end
                else:
                    start += 1
            run.clear()

        for line in self.lines:
            match = re.fullmatch(r"([\d,]+(?:\.\d+)?)(%?)", line.replace(" ", ""))
            if match:
                run.append((line.replace(" ", ""), float(match.group(1).replace(",", ""))))
            else:
                flush()
        flush()
        return ticks


# --- facts ------------------------------------------------------------------------------------

class _Fact:
    def __init__(self, *, label: str, source_label: str, page: int, unit_text: str | None,
                 basis: str | None, section_hint: str, ref: dict[str, Any]) -> None:
        self.label = label
        self.source_label = source_label
        self.metric_id = _metric_id(label)
        self.basis = basis
        self.unit_text = unit_text
        self.section_hint = section_hint
        self.pages = [page]
        self.refs = [ref]
        self.cells: list[dict[str, Any]] = []

    def add_cell(self, column: str, value_text: str, ref_index: int) -> None:
        self.cells.append({
            "column": column,
            "value_text": value_text,
            "period": _period_key(column),
            "kind": _cell_kind(column),
            "unit_key": "%" if value_text.strip().rstrip(")").endswith("%") else (
                "pts" if value_text.strip().endswith("pts") else _unit_key(self.unit_text)),
            "ref_index": ref_index,
        })

    @property
    def unit_key(self) -> str | None:
        level = [cell["unit_key"] for cell in self.cells if cell["kind"] in ("level", "share")]
        return level[0] if level else _unit_key(self.unit_text)

    def identity(self) -> tuple:
        return (self.metric_id or _norm_label(self.label), self.unit_key)

    def cell_map(self) -> dict[tuple, str]:
        return {(cell["period"], cell["kind"]): _norm_value(cell["value_text"]) for cell in self.cells if cell["period"] or cell["kind"] != "level"}

    def mergeable(self, other: "_Fact") -> bool:
        if self.identity() != other.identity():
            return False
        if self.basis and other.basis and self.basis.lower() != other.basis.lower():
            return False
        mine, theirs = self.cell_map(), other.cell_map()
        overlap = set(mine) & set(theirs)
        # Same metric + unit + period + value across every shared cell; a single
        # shared cell is not enough to prove two rows are the same disclosure.
        return len(overlap) >= min(2, len(mine), len(theirs)) and len(overlap) > 0 and all(mine[key] == theirs[key] for key in overlap)

    def merge(self, other: "_Fact") -> None:
        offset = len(self.refs)
        self.refs.extend(other.refs)
        self.pages = sorted(set(self.pages) | set(other.pages))
        self.basis = self.basis or other.basis
        existing = {(cell["period"], cell["kind"]) for cell in self.cells}
        for cell in other.cells:
            key = (cell["period"], cell["kind"])
            if key in existing:
                continue
            self.cells.append({**cell, "ref_index": cell["ref_index"] + offset})

    @property
    def display_label(self) -> str:
        return f"{self.label}（{self.basis}）" if self.basis else self.label

    @property
    def status(self) -> str:
        return _best_status([ref["verification_status"] for ref in self.refs if ref["role"] == "primary"])

    def text(self) -> str:
        parts = "；".join(f"{cell['column']} {cell['value_text']}" for cell in self.cells)
        unit = f"（單位：{self.unit_text}）" if self.unit_text and self.unit_key not in ("%", "pts") else ""
        return f"{self.display_label}：{parts}{unit}"


def _row_label(line: str) -> str:
    label = NUMBER_TOKEN_RE.split(line, maxsplit=1)[0]
    label = BASIS_MARKER_RE.sub("", label.strip()).strip()
    return label


def _table_facts(record: dict[str, Any], page: _Page, filename: str) -> list[_Fact]:
    facts: list[_Fact] = []
    columns = record.get("columns") or []
    header = " | ".join(columns)
    source_lines = [line for line in str(record.get("source_text") or "").splitlines() if line.strip()]
    cursor = 0
    for row in record.get("values") or []:
        cells = row.get("cells") or []
        values = [cell.get("value_text", "") for cell in cells] or list(row.get("values") or [])
        if not cells or not values:
            continue
        index = page.find_row_line(values, cursor)
        label, basis = None, None
        if index is not None:
            cursor = index + 1
            label = _row_label(page.lines[index])
            basis = page.basis_by_line[index]
        if not label:
            label = str(row.get("row_label") or "").split()[-1] if row.get("row_label") else ""
        if not label:
            continue
        target = "".join(_squash(value) for value in values)
        row_line = next((line for line in source_lines if target in _squash(line)), page.lines[index] if index is not None else " ".join(values))
        unit_match = LABEL_UNIT_RE.search(label)
        unit_text = unit_match.group(1) if unit_match else page.unit_text
        ref = _ref(filename, page.number, evidence_type="table", region_id=record.get("region_id"),
                   verification_status=record.get("verification_status") or "needs_review",
                   extraction_method=record.get("extraction_method"),
                   provider=record.get("semantic_provider") or "deterministic",
                   excerpt=f"{header}\n{row_line}" if header else row_line)
        fact = _Fact(label=label, source_label=str(row.get("row_label") or ""), page=page.number,
                     unit_text=unit_text, basis=basis, section_hint=page.heading_text, ref=ref)
        for cell in cells:
            fact.add_cell(str(cell.get("column") or ""), str(cell.get("value_text") or ""), 0)
        facts.append(fact)
    return facts


def _chart_fact(record: dict[str, Any], page: _Page, filename: str) -> _Fact | None:
    values = [value for value in record.get("values") or [] if value.get("label") and value.get("value_text")]
    heading = next((line for line in page.headings if not NOTICE_HEADING_RE.search(line)), None)
    if not values or not heading:
        return None
    ref = _ref(filename, page.number, evidence_type="chart", region_id=record.get("region_id"),
               verification_status=record.get("verification_status") or "needs_review",
               extraction_method=record.get("extraction_method"),
               provider=record.get("semantic_provider") or "deterministic",
               excerpt=f"{heading}: {record.get('source_text') or ''}")
    unit = page.unit_text or record.get("unit")
    fact = _Fact(label=re.sub(r"^合併", "", heading) if _metric_id(heading) else heading, source_label=heading,
                 page=page.number, unit_text=unit if unit != "%" else None, basis=None,
                 section_hint=page.heading_text + (" forecast" if record.get("is_forecast") else ""), ref=ref)
    for value in values:
        fact.add_cell(str(value["label"]), str(value["value_text"]), 0)
    return fact


def _classify_fact(fact: _Fact) -> str:
    context = f"{fact.section_hint} {fact.label}"
    if OUTLOOK_RE.search(fact.section_hint) or "forecast" in fact.section_hint:
        return "outlook_and_guidance"
    if PRODUCT_RE.search(context):
        return "product_and_business_mix"
    if OPERATIONS_RE.search(fact.label):
        return "operations"
    return "financial_performance"


def _classify_statement(text: str, page: _Page) -> str:
    if OUTLOOK_RE.search(text) or OUTLOOK_RE.search(page.heading_text):
        return "outlook_and_guidance"
    if RISK_RE.search(text):
        return "risks_and_uncertainties"
    if PRODUCT_RE.search(text) or PRODUCT_RE.search(page.heading_text):
        return "product_and_business_mix"
    if STRATEGY_RE.search(text):
        return "strategy_and_technology"
    if OPERATIONS_RE.search(text):
        return "operations"
    if FINANCIAL_RE.search(text) or FINANCIAL_RE.search(page.heading_text):
        return "financial_performance"
    return "other_disclosures"


# --- digest builder -----------------------------------------------------------------------------

def build_document_digest(ticker: str, manifest_document: dict[str, Any], pages: list[dict[str, Any]],
                          semantic: list[dict[str, Any]] | None, analysis: list[dict[str, Any]] | None = None,
                          *, listing_url: str | None = None, announcement_year: int | None = None) -> dict[str, Any]:
    """Pure, deterministic digest of one archived document."""
    filename = str(manifest_document.get("filename") or "")
    page_count = int(manifest_document.get("page_count") or len(pages) or 0)
    company_name = str(manifest_document.get("company_name") or "")
    period = manifest_document.get("period")
    limitations: list[str] = []
    excluded: dict[str, int] = {"low_structure": 0, "decorative": 0, "notice": 0, "duplicate": 0, "foreign": 0}

    def in_document(record: dict[str, Any]) -> bool:
        try:
            page_number = int(record.get("page") or 0)
        except (TypeError, ValueError):
            return False
        return record.get("filename", filename) == filename and 1 <= page_number <= max(page_count, 1)

    valid_pages = [page for page in pages or [] if in_document({**page, "filename": filename})]
    semantic_records = []
    for record in semantic or []:
        if in_document(record):
            semantic_records.append(record)
        else:
            excluded["foreign"] += 1
    analysis_records = [record for record in analysis or [] if in_document(record)]
    excluded["foreign"] += len(analysis or []) - len(analysis_records)

    boilerplate = _boilerplate_lines(valid_pages)
    page_map = {page.number: page for page in (_Page(raw, boilerplate, company_name) for raw in valid_pages)}
    text_regions: dict[int, list[dict[str, Any]]] = {}
    for record in semantic_records:
        if record.get("evidence_type") == "text":
            text_regions.setdefault(int(record["page"]), []).append(record)

    # 1. structured facts from semantic evidence
    facts: list[_Fact] = []
    unstructured: list[tuple[dict[str, Any], _Page]] = []
    candidate_pages: set[int] = set()
    for record in semantic_records:
        page = page_map.get(int(record["page"]))
        kind = record.get("evidence_type")
        if kind == "decorative":
            excluded["decorative"] += 1
            continue
        if page is None or kind == "text":
            continue
        candidate_pages.add(page.number)
        new: list[_Fact] = []
        if kind == "table" and record.get("mapping_status") == "aligned" and record.get("verification_status") in ("verified", "partially_verified"):
            new = _table_facts(record, page, filename)
        elif kind == "chart" and record.get("mapping_status") in ("aligned", "source_aligned") and record.get("verification_status") in ("verified", "partially_verified"):
            chart = _chart_fact(record, page, filename)
            new = [chart] if chart else []
        if new:
            facts.extend(new)
        else:
            excluded["low_structure"] += 1
            unstructured.append((record, page))

    summary_mode = "deterministic"
    fallback_bullets: list[dict[str, Any]] = []
    if not semantic_records:
        summary_mode = "deterministic_page_text"
        limitations.append("此文件的 archive 缺少 semantic evidence；數值僅以 analysis 列文字呈現並標示待人工複核。")
        for record in analysis_records:
            if record.get("kind") != "table_or_metric_row" or not record.get("line"):
                continue
            page = page_map.get(int(record["page"]))
            line = _clean_line(record["line"])
            candidate_pages.add(int(record["page"]))
            fallback_bullets.append({
                "text": f"（待人工複核）{line}",
                "section_type": _classify_fact(_Fact(label=_row_label(line), source_label=line, page=int(record["page"]),
                                                     unit_text=None, basis=None,
                                                     section_hint=page.heading_text if page else "",
                                                     ref={"verification_status": "needs_review", "role": "primary"})),
                "refs": [_ref(filename, int(record["page"]), evidence_type="analysis_row", verification_status="needs_review",
                              extraction_method=record.get("extraction_method"), provider="deterministic", excerpt=line)],
            })

    # 2. dedup facts (metric identity + unit + basis + period/value agreement)
    merged: list[_Fact] = []
    for fact in sorted(facts, key=lambda item: 0 if item.refs[0]["evidence_type"] == "table" else 1):
        target = next((existing for existing in merged if existing.mergeable(fact)), None)
        if target is None:
            merged.append(fact)
        else:
            target.merge(fact)
            excluded["duplicate"] += 1

    # 3. corroborate low-structure regions whose numbers all appear in included facts
    included_values = {_num_key(cell["value_text"]) for fact in merged for cell in fact.cells}
    corroborated_pages: set[int] = set()
    direct_pages = {page for fact in merged for page in fact.pages}
    for record, page in unstructured:
        if page.number in direct_pages or page.number in corroborated_pages:
            continue
        ticks = page.tick_values()
        page_text = re.sub(r"(?<![A-Za-z\d])[1-4]Q\d{2}(?!\d)", " ", " ".join(page.lines))
        page_text = re.sub(r"(%|pts)(?=[A-Za-z])", r" ", page_text)
        tokens = [
            _num_key(token) for token in _numeric_tokens(page_text)
            if not re.fullmatch(r"\d", _norm_value(token)) and not re.fullmatch(r"(19|20)\d{2}", _norm_value(token))
        ]
        ticks = {_num_key(tick) for tick in ticks}
        tokens = [token for token in tokens if token not in ticks and token not in ("0", "0%")]
        hits = [token for token in tokens if token in included_values]
        if len(hits) >= 3 and len(hits) / max(len(tokens), 1) >= 0.6:
            corroborated_pages.add(page.number)
            for fact in merged:
                if any(_num_key(cell["value_text"]) in hits for cell in fact.cells) and page.number not in fact.pages:
                    fact.refs.append(_ref(filename, page.number, evidence_type=record.get("evidence_type") or "unknown",
                                          region_id=record.get("region_id"),
                                          verification_status=record.get("verification_status") or "needs_review",
                                          extraction_method=record.get("extraction_method"),
                                          provider=record.get("semantic_provider") or "deterministic",
                                          excerpt=str(record.get("source_text") or ""), role="corroborating"))
                    fact.pages.append(page.number)

    # 4. statements from verbatim page text
    notices: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    seen_statements: set[str] = set()
    for page in page_map.values():
        for statement in page.statements():
            key = _squash(statement)
            if key in seen_statements:
                excluded["duplicate"] += 1
                continue
            seen_statements.add(key)
            region = next((record for record in text_regions.get(page.number, [])
                           if key[:24] and key[:24] in _squash(record.get("source_text"))), None)
            ref = _ref(filename, page.number,
                       evidence_type="text" if region else "page_text",
                       region_id=region.get("region_id") if region else None,
                       verification_status=(region.get("verification_status") if region else None) or page.text_status,
                       extraction_method=(region.get("extraction_method") if region else None) or page.method,
                       provider=(region.get("semantic_provider") if region else None) or "pdf_text_layer",
                       excerpt=statement)
            if page.is_notice_page or FOOTNOTE_RE.match(statement) or NOTICE_STATEMENT_RE.search(statement):
                excluded["notice"] += 1
                notice_type = ("forward_looking_statement_notice" if page.is_notice_page and re.search(r"預測性|不確定性因素|forward[-\s]?looking|actual\s+results", statement, re.I)
                               else "legal_disclaimer" if page.is_notice_page else "footnote")
                notices.append({"notice_type": notice_type, "text": statement, "evidence_refs": [ref]})
                continue
            candidate_pages.add(page.number)
            statements.append({"text": statement, "section_type": _classify_statement(statement, page), "refs": [ref], "page": page.number})

    # 5. bullets per section, no truncation
    sections: dict[str, list[dict[str, Any]]] = {key: [] for key in SECTION_ORDER}
    counters: dict[str, int] = {}

    def add_bullet(section: str, bullet: dict[str, Any]) -> dict[str, Any]:
        counters[section] = counters.get(section, 0) + 1
        refs = bullet["evidence_refs"]
        primary = [ref["verification_status"] for ref in refs if ref["role"] == "primary"]
        status = _best_status(primary)
        bullet.update({
            "id": f"{section}-{counters[section]}",
            "pages": sorted({ref["page"] for ref in refs}),
            "verification_status": status,
            "confidence": _confidence(status),
            "low_confidence": status == "needs_review",
            "verification_summary": {name: sum(1 for ref in refs if ref["verification_status"] == name)
                                     for name in ("verified", "partially_verified", "needs_review")},
        })
        sections[section].append(bullet)
        return bullet

    fact_bullets: list[tuple[_Fact, dict[str, Any]]] = []
    for fact in merged:
        section = _classify_fact(fact)
        bullet = add_bullet(section, {
            "kind": "quantitative", "text": fact.text(), "label": fact.display_label, "metric_id": fact.metric_id,
            "basis": fact.basis, "unit_text": fact.unit_text,
            "cells": [{key: cell[key] for key in ("column", "value_text", "period", "kind")} | {"evidence_ref_index": cell["ref_index"]}
                      for cell in fact.cells],
            "evidence_refs": fact.refs,
        })
        fact_bullets.append((fact, bullet))
    for item in fallback_bullets:
        add_bullet(item["section_type"], {"kind": "quantitative", "text": item["text"], "evidence_refs": item["refs"]})
    statement_bullets = [
        (item, add_bullet(item["section_type"], {"kind": "statement", "text": item["text"], "evidence_refs": item["refs"]}))
        for item in statements
    ]

    # 6. key quantitative disclosures
    key_items: list[tuple[tuple, dict[str, Any]]] = []
    for fact, bullet in fact_bullets:
        current = [cell for cell in fact.cells if period and cell["period"] == period]
        level = next((cell for cell in current if cell["kind"] in ("level", "share")), None)
        if level is None:
            continue
        changes = [{"column": cell["column"], "value_text": cell["value_text"]} for cell in fact.cells
                   if cell["kind"].startswith(("qoq", "yoy")) and cell["period"] in (None, period)]
        section = bullet["id"].rsplit("-", 1)[0]
        rank = (CORE_METRICS.index(fact.metric_id) if fact.metric_id in CORE_METRICS and not (fact.basis or "").lower().startswith("non") else 99,
                {"outlook_and_guidance": 0, "product_and_business_mix": 1}.get(section, 2))
        key_items.append((rank, {
            "bullet_id": bullet["id"], "label": fact.display_label, "metric_id": fact.metric_id, "basis": fact.basis,
            "period": period, "column": level["column"], "value_text": level["value_text"],
            "unit_text": None if fact.unit_key in ("%", "pts") else fact.unit_text, "changes": changes,
            "section_type": section, "evidence_refs": [fact.refs[level["ref_index"]]],
        }))
    for item, bullet in statement_bullets:
        if item["section_type"] == "outlook_and_guidance" and _numeric_tokens(item["text"]):
            label, _, value = re.sub(r"^[•●‧・▪■◆\-–*]\s*", "", item["text"]).partition("：")
            if not value:
                label, _, value = label.partition(":")
            key_items.append(((50, 0), {
                "bullet_id": bullet["id"], "label": label.strip() if value else "營運展望", "metric_id": None, "basis": None,
                "period": None, "column": "guidance", "value_text": (value or label).strip(), "unit_text": None,
                "changes": [], "section_type": "outlook_and_guidance", "evidence_refs": bullet["evidence_refs"],
            }))
    key_items.sort(key=lambda pair: pair[0])
    key_disclosures = [item for _, item in key_items[:KEY_DISCLOSURE_LIMIT]]

    # 7. coverage
    content_pages = sorted(candidate_pages)
    covered = sorted({page for bullets in sections.values() for bullet in bullets for page in bullet["pages"]} & set(content_pages))
    uncovered = [page for page in content_pages if page not in covered]
    all_refs = [ref for bullets in sections.values() for bullet in bullets for ref in bullet["evidence_refs"]]
    included_count = sum(len(bullets) for bullets in sections.values())
    ratio = round(len(covered) / len(content_pages), 3) if content_pages else 0.0
    # complete means every content page is covered; any uncovered content page
    # makes it at best partial, and low coverage stays limited.
    if not content_pages or ratio < 0.5 or included_count < 5:
        coverage_status = "limited"
    elif uncovered:
        coverage_status = "partial"
    else:
        coverage_status = "complete"
    coverage_label = {"limited": "摘要涵蓋有限", "partial": "摘要涵蓋部分"}.get(coverage_status)
    warnings = []
    if coverage_label:
        warnings.append(f"{coverage_label} / Coverage {coverage_status}：{len(covered)}/{len(content_pages)} 個內容頁有可引用 evidence。")
    if uncovered:
        warnings.append(f"第 {', '.join(str(page) for page in uncovered)} 頁的圖表／區塊未通過結構化驗證，未納入摘要。")
    if corroborated_pages:
        limitations.append(f"第 {', '.join(str(page) for page in sorted(corroborated_pages))} 頁圖表未完整對齊，其數值已由其他頁表格交叉對應，圖表上的 QoQ／YoY 標註未納入。")
    coverage = {
        "page_count": page_count,
        "content_page_count": len(content_pages),
        "covered_content_pages": covered,
        "uncovered_content_pages": uncovered,
        "corroborated_pages": sorted(corroborated_pages),
        "pages_with_evidence": sorted({ref["page"] for ref in all_refs}),
        "evidence_count": len(semantic_records) + len(analysis_records),
        "included_evidence_count": included_count,
        "excluded_evidence_count": sum(excluded.values()),
        "excluded_by_reason": excluded,
        "rejected_foreign_records": excluded["foreign"],
        "verified_count": sum(1 for ref in all_refs if ref["verification_status"] == "verified"),
        "partially_verified_count": sum(1 for ref in all_refs if ref["verification_status"] == "partially_verified"),
        "needs_review_count": sum(1 for ref in all_refs if ref["verification_status"] == "needs_review"),
        "section_bullet_counts": {key: len(value) for key, value in sections.items() if value},
        "key_quantitative_total": len(key_items),
        "key_quantitative_truncated_count": max(0, len(key_items) - KEY_DISCLOSURE_LIMIT),
        "coverage_ratio": ratio,
        "coverage_status": coverage_status,
        "coverage_warnings": warnings,
    }

    # 8. deterministic overview
    dates = _conference_dates(manifest_document)
    iso_date = dates[0][0] if dates else None
    manifest_ref = _ref(filename, 1, evidence_type="manifest", verification_status="verified",
                        extraction_method="mops_listing_manifest", provider="MOPS",
                        excerpt=f"ticker={ticker}; period={period}; page_count={page_count}; conference_dates={manifest_document.get('conference_dates')}; iso_date={iso_date}")
    overview: list[dict[str, Any]] = []
    if coverage_label:
        overview.append({"text": f"{coverage_label}：本摘要僅涵蓋 {len(covered)}/{len(content_pages)} 個內容頁的可驗證 evidence，未涵蓋部分請查閱原始文件。",
                         "evidence_refs": [_ref(filename, 1, evidence_type="coverage_summary", verification_status="verified",
                                                extraction_method="digest_coverage", provider="deterministic",
                                                excerpt=f"covered_content_pages={len(covered)}; content_page_count={len(content_pages)}; uncovered_content_pages={uncovered}")],
                         "bullet_ids": []})
    doc_type = DOCUMENT_TYPE_ZH.get(str(manifest_document.get("document_type")), "法說會文件")
    identity = f"{company_name}（{ticker}）於公開資訊觀測站（MOPS）揭露之{period or '期間未驗證'} {doc_type}"
    identity += f"，日期 {iso_date}" if iso_date else ""
    overview.append({"text": f"{identity}，共 {page_count} 頁。", "evidence_refs": [manifest_ref], "bullet_ids": []})
    headline = sorted((item for item in key_disclosures if item["metric_id"] in CORE_METRICS and not (item["basis"] or "").lower().startswith("non")),
                      key=lambda item: CORE_METRICS.index(item["metric_id"]))
    seen_metrics: set[str] = set()
    headline_parts, headline_refs, headline_ids = [], [], []
    for item in headline:
        if item["metric_id"] in seen_metrics:
            continue
        seen_metrics.add(item["metric_id"])
        extras = [f"單位 {item['unit_text']}"] if item["unit_text"] else []
        extras += [f"{change['column']} {change['value_text']}" for change in item["changes"]]
        headline_parts.append(f"{item['label']} {item['value_text']}" + (f"（{'，'.join(extras)}）" if extras else ""))
        headline_refs += item["evidence_refs"]
        headline_ids.append(item["bullet_id"])
    if headline_parts:
        overview.append({"text": f"本期（{period}）財務數字：{'、'.join(headline_parts)}。", "evidence_refs": headline_refs, "bullet_ids": headline_ids})
    mix = [item for item in key_disclosures if item["section_type"] == "product_and_business_mix" and not re.search(r"^total$|合計|總計", item["label"], re.I)]
    if mix:
        overview.append({"text": f"{period} 產品／業務組合營收佔比：{'、'.join(f'{item['label']} {item['value_text']}' for item in mix)}。",
                         "evidence_refs": [ref for item in mix for ref in item["evidence_refs"]], "bullet_ids": [item["bullet_id"] for item in mix]})
    guidance = [bullet for bullet in sections["outlook_and_guidance"] if bullet["kind"] == "statement"]
    if guidance:
        heading = next((line for page in page_map.values() for line in page.headings if OUTLOOK_RE.search(line)), "營運展望")
        body = "；".join(re.sub(r"^[•●‧・▪■◆\-–*]\s*", "", bullet["text"]) for bullet in guidance)
        overview.append({"text": f"{heading}：{body}。".replace("。。", "。"), "evidence_refs": [ref for bullet in guidance for ref in bullet["evidence_refs"]],
                         "bullet_ids": [bullet["id"] for bullet in guidance]})
    bullet_pages = {bullet["id"]: bullet["pages"] for bullets in sections.values() for bullet in bullets}
    cited_pages = {page for sentence in overview for bullet_id in sentence["bullet_ids"] for page in bullet_pages.get(bullet_id, [])}
    other_headings: list[tuple[str, int]] = []
    for number in covered:
        page = page_map.get(number)
        if number in cited_pages or page is None or not page.title:
            continue
        heading = page.title
        if heading not in [item[0] for item in other_headings]:
            other_headings.append((heading, number))
    if other_headings:
        overview.append({"text": f"文件其他內容涵蓋：{'、'.join(item[0] for item in other_headings)}。",
                         "evidence_refs": [_ref(filename, number, evidence_type="page_text", verification_status=page_map[number].text_status,
                                                extraction_method=page_map[number].method, provider="pdf_text_layer", excerpt=heading)
                                           for heading, number in other_headings],
                         "bullet_ids": []})

    cover = page_map[min(page_map)] if page_map else None
    document_title = next((line for line in (cover.lines if cover else []) if _cjk_count(line) >= 4 and not NON_CONTENT_LINE_RE.search(line)), None)
    return {
        "digest_version": DIGEST_VERSION,
        "summary_mode": summary_mode,
        "ticker": ticker,
        "company": company_name,
        "document_title": document_title or filename,
        "period": period,
        "period_validation_status": manifest_document.get("period_validation_status"),
        "document_type": manifest_document.get("document_type"),
        "language": manifest_document.get("document_language") or manifest_document.get("language"),
        "conference_date": iso_date,
        "overview": overview,
        "sections": [
            {"section_type": key, "title_zh": SECTION_TITLES[key][0], "title_en": SECTION_TITLES[key][1], "bullets": sections[key]}
            for key in SECTION_ORDER if sections[key]
        ],
        "key_quantitative_disclosures": key_disclosures,
        "document_notices": notices,
        "coverage": coverage,
        "limitations": limitations + [
            "摘要僅重組官方文件既有 evidence；數字為原文照錄，未重新計算。",
            "本摘要描述單一官方文件內容，不含跨期文字分布比較。",
        ],
        "source": {
            "provider": "MOPS",
            "filename": filename,
            "sha256": manifest_document.get("sha256"),
            "page_count": page_count,
            "conference_dates": manifest_document.get("conference_dates") or [],
            "announcement_year": announcement_year,
            "listing_url": listing_url,
            # FileDownLoad is a POST form: kept as provenance only, never a GET link.
            "download_form": {
                "method": "POST",
                "description": "MOPS FileDownLoad (POST form)",
                "fields": manifest_document.get("download_fields") or {},
            },
        },
    }


# --- optional LLM overview --------------------------------------------------------------------------

_PERIOD_TOKEN_RE = re.compile(r"20\d{2}\s*-?\s*Q[1-4]|[1-4]Q\d{2}|第[一二三四1-4]季|20\d{2}\s*年|(?:January|February|March|April|May|June|July|August|September|October|November|December)", re.I)
_DIRECTION_WORDS = [
    "增加", "成長", "上升", "上揚", "提升", "下降", "下滑", "減少", "衰退", "改善", "轉弱", "轉強", "優於", "高於", "低於", "持平", "回升", "擴大", "縮小",
    "increase", "decrease", "grow", "growth", "rise", "decline", "drop", "improve", "weaken", "higher", "lower", "than", "vs", "versus", "flat",
]
_INTERPRETATION_WORDS = [
    "風險", "看好", "樂觀", "悲觀", "承壓", "強勁", "疲弱", "機會", "挑戰", "穩健", "亮眼", "不佳", "利多", "利空",
    "strong", "weak", "headwind", "tailwind", "robust", "risk", "optimistic", "pessimistic", "challenge", "opportunity",
]
_CONNECTIVE_WORDS = [
    "本季", "本期", "文件", "揭露", "包括", "包含", "以及", "其中", "分別", "主要", "內容", "另外", "此外", "顯示", "列出", "提供", "說明",
    "摘要", "官方", "簡報", "法說會", "資料", "數字", "財務", "項目", "部分", "相關", "為", "與", "及", "之", "的", "在", "於", "並", "共", "頁",
]
_OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "cited_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "cited_ids"],
            },
        },
    },
    "required": ["overview"],
}
_OVERVIEW_PROMPT = (
    "你是官方文件摘要的文字編輯。只能改寫使用者提供的 deterministic overview 句子，使其更通順。"
    "每一句必須在 cited_ids 列出所依據的 id。不得新增任何數字、期間、公司、產品、方向性描述（增加、下降、改善等）、"
    "比較關係或風險／展望解讀；數字必須逐字照抄。輸出 4 到 6 句。"
)


def _bigrams(text: str) -> set[str]:
    grams: set[str] = set()
    for run in re.findall(r"[一-鿿]+", text):
        grams.update(run[index:index + 2] for index in range(len(run) - 1))
        if len(run) == 1:
            grams.add(run)
    return grams


def validate_llm_overview(sentences: list[dict[str, Any]], sources: dict[str, str], *, allowed_terms: list[str]) -> list[str]:
    """Return rejection reasons; an empty list means every sentence is grounded."""
    reasons: list[str] = []
    if not 1 <= len(sentences) <= 6:
        reasons.append("sentence_count")
    connective_grams = set().union(*(_bigrams(word) for word in _CONNECTIVE_WORDS))
    allowed_latin = {word.lower() for term in allowed_terms for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", term)}
    for index, sentence in enumerate(sentences):
        text = _nfkc(sentence.get("text"))
        cited = [str(item) for item in sentence.get("cited_ids") or []]
        if not cited or any(item not in sources for item in cited):
            reasons.append(f"s{index}:citation")
            continue
        grounded = _nfkc(" ".join(sources[item] for item in cited))
        grounded_lower = grounded.lower()
        for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
            if token not in grounded:
                reasons.append(f"s{index}:number:{token}")
        for token in _PERIOD_TOKEN_RE.findall(text):
            if _squash(token).lower() not in _squash(grounded).lower():
                reasons.append(f"s{index}:period:{token}")
        for word in _DIRECTION_WORDS:
            if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, re.I) and word.lower() not in grounded_lower:
                reasons.append(f"s{index}:direction:{word}")
        for word in _INTERPRETATION_WORDS:
            if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, re.I) and word.lower() not in grounded_lower:
                reasons.append(f"s{index}:interpretation:{word}")
        grounded_latin = {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", grounded)}
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", text):
            if word.lower() not in grounded_latin and word.lower() not in allowed_latin:
                reasons.append(f"s{index}:entity:{word}")
        novel = _bigrams(text) - _bigrams(grounded) - connective_grams
        if novel:
            reasons.append(f"s{index}:unsupported_text:{''.join(sorted(novel))[:40]}")
    return reasons


class ConferenceDigestNarrator:
    """Optional LLM rephrasing of the deterministic overview (fail closed)."""

    def __init__(self, provider: Any | None = None) -> None:
        if provider is None:
            from app.services.gemini_financial_analyst import GeminiFinancialAnalyst

            provider = GeminiFinancialAnalyst()
        self.provider = provider

    @property
    def configured(self) -> bool:
        return bool(getattr(self.provider, "configured", False))

    def _generate(self, prompt: dict[str, Any]) -> dict[str, Any] | None:
        try:
            payload, _model = asyncio.run(self.provider.generate_structured(
                json.dumps(prompt, ensure_ascii=False), system_instruction=_OVERVIEW_PROMPT,
                schema=_OVERVIEW_SCHEMA, max_output_tokens=1200,
            ))
            return payload
        except Exception:
            return None
        finally:
            # The provider's async client is bound to the loop asyncio.run just closed.
            if hasattr(self.provider, "_client"):
                self.provider._client = None

    def apply(self, digest: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            digest["limitations"].append("LLM overview 未啟用或無法使用，使用 deterministic overview。")
            return digest
        sources: dict[str, str] = {}
        for index, sentence in enumerate(digest["overview"]):
            sources[f"overview-{index + 1}"] = sentence["text"] + " " + " ".join(ref["excerpt"] for ref in sentence["evidence_refs"])
        for section in digest["sections"]:
            for bullet in section["bullets"]:
                sources[bullet["id"]] = bullet["text"] + " " + " ".join(ref["excerpt"] for ref in bullet["evidence_refs"])
        prompt = {
            "overview": [{"id": key, "text": digest["overview"][int(key.split("-")[1]) - 1]["text"]} for key in sources if key.startswith("overview-")],
            "bullets": [{"id": key, "text": value} for key, value in sources.items() if not key.startswith("overview-")][:120],
        }
        payload = self._generate(prompt)
        sentences = (payload or {}).get("overview") if isinstance(payload, dict) else None
        if not isinstance(sentences, list):
            digest["limitations"].append("LLM overview 無法取得，使用 deterministic overview。")
            return digest
        allowed = [digest.get("company") or "", digest.get("ticker") or "", "MOPS"]
        reasons = validate_llm_overview(sentences, sources, allowed_terms=allowed)
        if reasons:
            digest["limitations"].append("LLM overview 未通過 evidence 驗證，已退回 deterministic overview。")
            digest["llm_validation"] = {"status": "rejected", "reasons": reasons[:20]}
            return digest
        refs_by_id = {key: [] for key in sources}
        for index, sentence in enumerate(digest["overview"]):
            refs_by_id[f"overview-{index + 1}"] = sentence["evidence_refs"]
        for section in digest["sections"]:
            for bullet in section["bullets"]:
                refs_by_id[bullet["id"]] = bullet["evidence_refs"]
        digest["deterministic_overview"] = digest["overview"]
        digest["overview"] = [
            {"text": sentence["text"], "bullet_ids": sentence["cited_ids"],
             "evidence_refs": [ref for key in sentence["cited_ids"] for ref in refs_by_id[key]][:12]}
            for sentence in sentences
        ]
        digest["summary_mode"] = "llm_overview_deterministic_sections"
        digest["llm_validation"] = {"status": "accepted", "reasons": []}
        return digest


def build_narrator_from_env() -> ConferenceDigestNarrator | None:
    if os.getenv("CONFERENCE_DIGEST_LLM_PROVIDER", "").strip().lower() != "gemini":
        return None
    narrator = ConferenceDigestNarrator()
    return narrator if narrator.configured else None


# --- service ----------------------------------------------------------------------------------------------

class ConferenceDocumentDigestService:
    """Select one archived document, hydrate only its artifacts, and digest it."""

    _cache: "OrderedDict[tuple, dict[str, Any]]" = OrderedDict()
    _cache_lock = threading.Lock()
    _cache_size = 64

    def __init__(self, archive_repo: Any, narrator: ConferenceDigestNarrator | None = None,
                 *, timeout_seconds: float | None = None) -> None:
        self.archive_repo = archive_repo
        self.narrator = narrator
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(
            os.getenv("CONFERENCE_DIGEST_TIMEOUT_SECONDS", "") or 8)

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache.clear()

    def digest_for(self, ticker: str, *, period: str | None = None,
                   conference_date: str | None = None) -> tuple[dict[str, Any] | None, str]:
        """Returns (digest, status); status is available | no_matching_archive |
        archive_unavailable | digest_timeout | digest_failed. Never raises."""
        if self.archive_repo is None:
            return None, "archive_unavailable"
        started = time.monotonic()
        try:
            selected = select_archive_document(self.archive_repo, ticker, period=period, conference_date=conference_date)
        except Exception:
            return None, "archive_unavailable"
        if selected is None:
            return None, "no_matching_archive"
        year, manifest, document = selected
        key = (ticker, document.get("filename"), document.get("sha256"), DIGEST_VERSION, self.narrator is not None)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return copy.deepcopy(self._cache[key]), "available"
        try:
            filename = document["filename"]
            pages = self.archive_repo.pages(ticker, year, filename)
            if time.monotonic() - started > self.timeout_seconds:
                return None, "digest_timeout"
            semantic = self.archive_repo.semantic(ticker, year, filename)
            analysis = self.archive_repo.analysis(ticker, year, filename) if not semantic else None
            if time.monotonic() - started > self.timeout_seconds:
                return None, "digest_timeout"
            digest = build_document_digest(ticker, {**document, "company_name": document.get("company_name") or manifest.get("company_name")},
                                           pages, semantic, analysis, listing_url=manifest.get("listing_url"), announcement_year=year)
            if self.narrator is not None:
                digest = self.narrator.apply(digest)
        except Exception:
            return None, "digest_failed"
        with self._cache_lock:
            self._cache[key] = copy.deepcopy(digest)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return digest, "available"


def conference_target(item: dict[str, Any]) -> tuple[str | None, str | None]:
    """(period, conference_date) used to match a conference record to an archive document."""
    year, quarter = item.get("fiscal_year"), item.get("quarter")
    if year and quarter:
        return f"{int(year)}Q{int(quarter)}", None
    value = str(item.get("conference_date") or "")[:10]
    try:
        date.fromisoformat(value)
    except ValueError:
        return None, None
    return None, value


def archive_identity(digest: dict[str, Any]) -> dict[str, Any]:
    source = digest.get("source") or {}
    return {
        "provider": "MOPS",
        "filename": source.get("filename"),
        "sha256": source.get("sha256"),
        "period": digest.get("period"),
        "conference_dates": source.get("conference_dates"),
        "document_type": digest.get("document_type"),
        "language": digest.get("language"),
        "digest_version": digest.get("digest_version"),
    }
