"""Deterministic parsers for official historical evidence formats.

Each parser targets one real official format observed in Phase 1B:

- TPEx announcement pages (``www.tpex.org.tw/storage/eb_data/…htm``, Big5)
- MOPS material-information listing / detail pages (``ajax_t05st01``, UTF-8)
- the "重編前/重編後" before-and-after tables inside a MOPS restatement notice
- the TWSE electronic-document archive listing (``doc.twse.com.tw t57sb01``, Big5)
- the TPEx quarterly financial summary workbook (``O_YYYYQn.xls``)

Parsers never infer missing values; anything they cannot read is reported.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.historical_audit.models import TAIPEI


class EvidenceParseError(ValueError):
    pass


def decode_html(content: bytes, *, preferred: tuple[str, ...] = ("utf-8", "cp950")) -> str:
    for encoding in preferred:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode(preferred[-1], errors="replace")


def html_to_text(markup: str) -> str:
    """Tag-stripped text with line structure preserved (``<br>``/rows become newlines)."""
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", "", markup, flags=re.I)
    text = re.sub(r"<br\s*/?>|</tr>|</p>|</pre>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def flat_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def roc_date(text: str) -> date:
    """'105年12月29日', '105/12/29' or '1051229' (ROC) → Gregorian date."""
    match = re.search(r"(\d{2,3})\s*[年/.]\s*(\d{1,2})\s*[月/.]\s*(\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        compact = re.fullmatch(r"(\d{3})(\d{2})(\d{2})", text.strip())
        if not compact:
            raise EvidenceParseError(f"Not an ROC date: {text!r}")
        year, month, day = (int(part) for part in compact.groups())
    return date(year + 1911, month, day)


def taipei_timestamp(day: date, hhmmss: str) -> datetime:
    clean = hhmmss.replace(":", "").strip()
    if not re.fullmatch(r"\d{6}", clean):
        raise EvidenceParseError(f"Not an HHMMSS time: {hhmmss!r}")
    return datetime(day.year, day.month, day.day, int(clean[:2]), int(clean[2:4]), int(clean[4:]), tzinfo=TAIPEI)


def parse_number(token: str) -> Decimal:
    raw = token.strip()
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace(",", "").replace("$", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise EvidenceParseError(f"Not a number: {token!r}") from exc
    return -value if negative else value


# --------------------------------------------------------------------- TPEx
@dataclass
class TpexAnnouncement:
    announcement_no: str
    issued_on: date
    subject: str
    text: str


def parse_tpex_announcement(content: bytes) -> TpexAnnouncement:
    text = html_to_text(decode_html(content, preferred=("cp950", "utf-8")))
    flat = flat_text(text)
    number = re.search(r"發文字號：?(證櫃\S{1,3}字第\d+號)", flat)
    issued = re.search(r"發文日期：?中華民國(\d{2,3}年\d{1,2}月\d{1,2}日)", flat)
    subject = re.search(r"主旨：(.+?)依據：", flat)
    if not (number and issued and subject):
        raise EvidenceParseError("Not a recognisable TPEx announcement (發文字號/發文日期/主旨 missing).")
    return TpexAnnouncement(number.group(1), roc_date(issued.group(1)), subject.group(1), text)


# --------------------------------------------------------------------- MOPS
@dataclass
class MaterialListingRow:
    ticker: str
    spoke_date: date
    spoke_time: str
    seq_no: str
    title: str

    @property
    def published_at(self) -> datetime:
        return taipei_timestamp(self.spoke_date, self.spoke_time)


_LISTING_ROW = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.I)
_LISTING_IDENTITY = re.compile(
    r"seq_no\.value='(\d+)';document\.t05st01_fm\.spoke_time\.value='(\d+)';"
    r"document\.t05st01_fm\.spoke_date\.value='(\d+)';document\.t05st01_fm\.co_id\.value='(\w+)'"
)


def parse_mops_material_listing(content: bytes, *, ticker: str) -> list[MaterialListingRow]:
    markup = decode_html(content)
    if "主旨" not in markup or "t05st01_fm" not in markup:
        raise EvidenceParseError("Not a MOPS material-information listing (no 主旨 header / detail form).")
    rows: list[MaterialListingRow] = []
    for row in _LISTING_ROW.findall(markup):
        identity = _LISTING_IDENTITY.search(row)
        if not identity:
            continue
        seq_no, spoke_time, spoke_date, co_id = identity.groups()
        if co_id != ticker:
            continue
        cells = [html_to_text(cell).replace("\n", "") for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)]
        title = cells[4] if len(cells) > 4 else ""
        rows.append(MaterialListingRow(
            ticker=co_id,
            spoke_date=date(int(spoke_date[:4]), int(spoke_date[4:6]), int(spoke_date[6:])),
            spoke_time=spoke_time.zfill(6),
            seq_no=seq_no,
            title=title,
        ))
    return rows


@dataclass
class MaterialDetail:
    ticker: str
    seq_no: str
    published_at: datetime
    subject: str
    clause: str | None
    fact_date: date | None
    body: str
    text: str


def parse_mops_material_detail(content: bytes, *, ticker: str) -> MaterialDetail:
    text = html_to_text(decode_html(content))
    flat = flat_text(text)
    if "公開資訊觀測站" not in flat or f"{ticker}" not in flat:
        raise EvidenceParseError("Not a MOPS material-information detail page for this ticker.")
    seq = re.search(r"序號(\d+)發言日期", flat)
    spoke = re.search(r"發言日期(\d{2,3}/\d{1,2}/\d{1,2})發言時間(\d{2}:\d{2}:\d{2})", flat)
    subject = re.search(r"主旨(.+?)符合條款", flat)
    if not (seq and spoke and subject):
        raise EvidenceParseError("MOPS detail page lacks 序號/發言日期/發言時間/主旨.")
    clause = re.search(r"符合條款第(\d+)款", flat)
    fact = re.search(r"事實發生日(\d{2,3}/\d{1,2}/\d{1,2})", flat)
    # The body follows a line that is exactly "說明" (a subject may also end with 說明).
    body_match = re.search(r"(?:^|\n)說明\n([\s\S]+?)(?:\n以上資料均由各公司|$)", text)
    return MaterialDetail(
        ticker=ticker,
        seq_no=seq.group(1),
        published_at=taipei_timestamp(roc_date(spoke.group(1)), spoke.group(2)),
        subject=subject.group(1),
        clause=clause.group(1) if clause else None,
        fact_date=roc_date(fact.group(1)) if fact else None,
        body=body_match.group(1) if body_match else "",
        text=text,
    )


# ----------------------------------------------- restatement before / after
# label → (canonical metric, sign factor applied to the disclosed value).
COMPARISON_LABELS: dict[str, tuple[str, int]] = {
    "流動資產合計": ("current_assets", 1),
    "資產總計": ("total_assets", 1),
    "流動負債合計": ("current_liabilities", 1),
    "負債總計": ("total_liabilities", 1),
    "股東權益總計": ("equity", 1),
    "權益總計": ("equity", 1),
    "營業收入淨額": ("revenue", 1),
    "營業收入": ("revenue", 1),
    "營業成本": ("cost_of_goods_sold", -1),
    "營業毛利": ("gross_profit", 1),
    "營業毛利淨額": ("gross_profit", 1),
    "營業淨利": ("operating_income", 1),
    "合併總淨利": ("net_income", 1),
    "本期淨利": ("net_income", 1),
}
# Labels that differ between the 重編前 and 重編後 tables for the same line.
_PAIRED_LABELS = {
    "營業外收益合計": "營業外收入及利益合計",
    "營業外費損合計": "營業外費用及損失合計",
}

_SECTION = re.compile(r"^(重編前|重編後)-(合併)?(資產負債|損益/綜合損益)簡表")
_PERIOD_TOKEN = re.compile(r"^(\d{2,3})(?:\.12\.31|年)$")
_NUMBER_TOKEN = re.compile(r"^\(?-?[\d,]+\)?$")


@dataclass
class ComparisonCell:
    side: str
    statement: str
    fiscal_year: int
    label: str
    value: Decimal
    unit: str


@dataclass
class ComparisonRow:
    statement: str
    fiscal_year: int
    pre_label: str | None
    post_label: str | None
    pre_value: Decimal | None
    post_value: Decimal | None
    unit: str
    canonical_metric: str | None
    sign_factor: int

    @property
    def difference(self) -> Decimal | None:
        if self.pre_value is None or self.post_value is None:
            return None
        return self.post_value - self.pre_value


def parse_restatement_comparison(body: str) -> list[ComparisonRow]:
    """Pairs the 重編前 / 重編後 summary tables of a MOPS restatement notice."""
    cells: list[ComparisonCell] = []
    side = statement = None
    unit = "TWD_thousand"
    periods: list[int] = []
    for line in body.splitlines():
        line = line.strip()
        section = _SECTION.match(line)
        if section:
            side = "pre" if section.group(1) == "重編前" else "post"
            statement = "balance_sheet" if section.group(3) == "資產負債" else "income_statement"
            if "單位:仟元" not in line.replace("：", ":"):
                raise EvidenceParseError(f"Unexpected unit in section header: {line}")
            periods = []
            continue
        if side is None or not line or set(line) <= {"-", " "}:
            continue
        tokens = line.split()
        if all(_PERIOD_TOKEN.match(token) for token in tokens):
            periods = [int(_PERIOD_TOKEN.match(token).group(1)) + 1911 for token in tokens]
            continue
        if not periods:
            continue
        numbers = [token for token in tokens if _NUMBER_TOKEN.match(token)]
        label = "".join(token for token in tokens if not _NUMBER_TOKEN.match(token))
        if not label or len(numbers) != len(periods):
            if label.startswith(("6.", "7.")):  # end of the "與前次公告財務報告之主要差異" item
                side = None
                continue
            raise EvidenceParseError(f"Row does not match its period header: {line!r} ({periods})")
        for year, number in zip(periods, numbers):
            cells.append(ComparisonCell(side, statement, year, label, parse_number(number), unit))
    if not cells:
        raise EvidenceParseError("No 重編前/重編後 tables found.")

    pre = {(c.statement, c.fiscal_year, c.label): c for c in cells if c.side == "pre"}
    post = {(c.statement, c.fiscal_year, c.label): c for c in cells if c.side == "post"}
    rows: list[ComparisonRow] = []
    used_post: set[tuple[str, int, str]] = set()
    for key, cell in pre.items():
        post_label = _PAIRED_LABELS.get(cell.label, cell.label)
        partner = post.get((key[0], key[1], post_label))
        if partner is not None:
            used_post.add((key[0], key[1], post_label))
        metric, sign = COMPARISON_LABELS.get(cell.label, (None, 1))
        rows.append(ComparisonRow(key[0], key[1], cell.label, partner.label if partner else None,
                                  cell.value, partner.value if partner else None, cell.unit, metric, sign))
    for key, cell in post.items():
        if key in used_post:
            continue
        metric, sign = COMPARISON_LABELS.get(cell.label, (None, 1))
        rows.append(ComparisonRow(key[0], key[1], None, cell.label, None, cell.value, cell.unit, metric, sign))
    return sorted(rows, key=lambda row: (row.statement, row.fiscal_year, row.pre_label or row.post_label or ""))


# ------------------------------------------------------- TWSE e-documents
@dataclass
class EbookListingRow:
    ticker: str
    data_year_label: str
    fiscal_year: int
    quarter: int | None
    data_type: str
    detail: str
    remark: str
    filename: str
    file_size: int
    uploaded_at: datetime
    correction: str

    @property
    def statement_scope(self) -> str:
        if "合併" in self.detail:
            return "consolidated"
        if "個體" in self.detail or "母公司" in self.detail:
            return "individual"
        return "unknown"

    @property
    def accounting_framework(self) -> str:
        return "TIFRS" if "IFRS" in self.detail.upper() else "TW_GAAP"

    @property
    def version_label(self) -> str:
        """Revision status exactly as the archive labels this file."""
        if "重編前" in self.remark:
            return "original"
        if "重編" in self.detail or "重編後" in self.remark:
            return "restated"
        return "unknown_revision"


_QUARTERS = {"第一季": 1, "第二季": 2, "第三季": 3, "第四季": 4}


def parse_twse_ebook_listing(content: bytes, *, ticker: str) -> list[EbookListingRow]:
    markup = decode_html(content, preferred=("cp950", "utf-8"))
    if "上傳日期" not in markup or "電子檔案" not in markup:
        raise EvidenceParseError("Not a TWSE e-document listing (上傳日期/電子檔案 header missing).")
    rows: list[EbookListingRow] = []
    for row in _LISTING_ROW.findall(markup):
        cells = [html_to_text(cell).replace("\n", " ").strip() for cell in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)]
        if len(cells) < 11 or cells[0] != ticker:
            continue
        year_label = cells[1]
        year = re.search(r"(\d{2,3})\s*年", year_label)
        quarter = next((q for name, q in _QUARTERS.items() if name in year_label), None)
        uploaded = re.fullmatch(r"(\d{2,3}/\d{1,2}/\d{1,2})\s+(\d{2}:\d{2}:\d{2})", cells[9])
        if not (year and uploaded and cells[7].lower().endswith(".pdf")):
            raise EvidenceParseError(f"Unrecognised e-document row: {cells}")
        rows.append(EbookListingRow(
            ticker=ticker,
            data_year_label=year_label,
            fiscal_year=int(year.group(1)) + 1911,
            quarter=quarter,
            data_type=cells[2],
            detail=cells[5],
            remark=cells[6],
            filename=cells[7],
            file_size=int(cells[8].replace(",", "")),
            uploaded_at=taipei_timestamp(roc_date(uploaded.group(1)), uploaded.group(2)),
            correction=cells[10],
        ))
    return rows


# --------------------------------------------------- TPEx quarterly summary
@dataclass
class SummaryColumn:
    source_label: str
    sub_label: str
    role: str  # current_period | prior_year_comparative | period_end
    fiscal_year: int | None


@dataclass
class SummaryValue:
    source_label: str
    source_metric_code: str
    role: str
    fiscal_year: int
    value: Decimal
    published_unit: str


@dataclass
class TpexSummaryRow:
    ticker: str
    company: str
    sheet: str
    report_fiscal_year: int
    report_quarter: int
    accounting_framework: str
    values: list[SummaryValue] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)


# Published header (first line) → (source metric code, published unit).
SUMMARY_COLUMNS: dict[str, tuple[str, str]] = {
    "營業收入": ("tpex_operating_revenue", "TWD_thousand"),
    "營業利益": ("tpex_operating_income", "TWD_thousand"),
    "營業外收支淨額": ("tpex_non_operating_net", "TWD_thousand"),
    "稅前淨利（淨損）": ("tpex_profit_before_tax", "TWD_thousand"),
    "稅後純益": ("tpex_net_income_after_tax", "TWD_thousand"),
    "本期末股本": ("tpex_capital_stock_end", "TWD_thousand"),
    "每股稅後純益": ("tpex_eps", "TWD/share"),
    "每股": ("tpex_book_value_per_share", "TWD/share"),
    "淨值佔": ("tpex_equity_to_total_assets", "as_published"),
    "流動": ("tpex_current_ratio", "as_published"),
}


def _cell_decimal(raw: Any) -> Decimal:
    if isinstance(raw, float):
        return Decimal(int(raw)) if raw.is_integer() else Decimal(repr(raw))
    return parse_number(str(raw))


def _first_line(value: Any) -> str:
    return str(value or "").replace("\r", "").split("\n")[0].strip()


def parse_tpex_summary_xls(content: bytes, *, ticker: str) -> TpexSummaryRow:
    try:
        import xlrd
    except ImportError as exc:  # research-only dependency, see requirements-historical-audit.txt
        raise EvidenceParseError("xlrd is required to read TPEx .xls summaries.") from exc
    book = xlrd.open_workbook(file_contents=content)
    for sheet in book.sheets():
        if sheet.nrows < 9:
            continue
        period_cell = next((str(v) for v in sheet.row_values(2) if "民國" in str(v)), "")
        period = re.search(r"民國(\d{2,3})年1-(\d{1,2})月", period_cell)
        unit_cell = " ".join(str(v) for v in sheet.row_values(2))
        if not period or "千元" not in unit_cell:
            raise EvidenceParseError(f"Sheet {sheet.name!r}: unrecognised period/unit header.")
        report_year = int(period.group(1)) + 1911
        report_quarter = {"3": 1, "6": 2, "9": 3, "12": 4}.get(period.group(2))
        if report_quarter is None:
            raise EvidenceParseError(f"Unexpected cumulative period 1-{period.group(2)}月.")
        headers, subs = sheet.row_values(4), sheet.row_values(6)
        columns: dict[int, SummaryColumn] = {}
        current = ""
        for index in range(2, sheet.ncols):
            if _first_line(headers[index]):
                current = _first_line(headers[index])
            sub = _first_line(subs[index])
            year = re.match(r"(\d{2,3})年1-\d{1,2}月", sub)
            if year:
                fiscal = int(year.group(1)) + 1911
                role = "current_period" if fiscal == report_year else "prior_year_comparative" if fiscal == report_year - 1 else None
                if role is None:
                    raise EvidenceParseError(f"Column year {fiscal} inconsistent with report year {report_year}.")
                columns[index] = SummaryColumn(current, sub, role, fiscal)
            elif sub.startswith("增減"):
                continue  # derived percentage change; not an observation
            elif not sub:
                columns[index] = SummaryColumn(current, "", "period_end", report_year)
        for row_index in range(8, sheet.nrows):
            row = sheet.row_values(row_index)
            if str(row[0]).strip() != ticker:
                continue
            framework = "TIFRS" if report_year >= 2013 else "TW_GAAP"
            result = TpexSummaryRow(ticker, str(row[1]).strip(), sheet.name, report_year, report_quarter, framework)
            for index, column in columns.items():
                spec = next((spec for prefix, spec in SUMMARY_COLUMNS.items() if column.source_label.startswith(prefix)), None)
                if spec is None:
                    result.unreadable.append(f"unknown column {column.source_label!r}")
                    continue
                raw = row[index]
                if raw in ("", None) or (isinstance(raw, str) and raw.strip() in {"", "-", "--"}):
                    result.unreadable.append(f"{spec[0]}:{column.role}:empty")
                    continue
                result.values.append(SummaryValue(
                    source_label=column.source_label,
                    source_metric_code=spec[0],
                    role=column.role,
                    fiscal_year=column.fiscal_year or report_year,
                    value=_cell_decimal(raw),
                    published_unit=spec[1],
                ))
            return result
    raise EvidenceParseError(f"Ticker {ticker} not found in TPEx summary workbook.")


# ------------------------------------------------------------------ MOPS annual board-approval notice
# 「本公司民國XXX年度合併財務報告業經董事會決議通過」 (MOPS clause 31): numbered lines stating key figures of the
# approved report, each 「<label>(仟元|元):<amount>」. The label table is fixed; ``canonical`` is None where the
# line has no exact canonical metric (e.g. equity attributable to owners of the parent is not total ``equity``).
BOARD_REPORT_LABELS: dict[str, str | None] = {
    "營業收入": "revenue",
    "營業毛利(毛損)": "gross_profit",
    "營業利益(損失)": "operating_income",
    "稅前淨利(淨損)": None,
    "本期淨利(淨損)": "net_income",
    "歸屬於母公司業主淨利(損)": None,
    "基本每股盈餘(損失)": "eps",
    "期末總資產": "total_assets",
    "期末總負債": "total_liabilities",
    "期末歸屬於母公司業主之權益": None,
}
_BOARD_LINE = re.compile(r"^\d{1,2}\.(?:1月1日累計至本期止)?(.+?)\((仟元|元)\)[:：](\(?-?[\d,]+(?:\.\d+)?\)?)$")
_BOARD_PERIOD = re.compile(r"(\d{2,3})/(\d{2})/(\d{2})\s*~\s*(\d{2,3})/(\d{2})/(\d{2})")


@dataclass(frozen=True)
class BoardReportItem:
    label: str
    canonical_metric: str | None
    value: Decimal
    published_unit: str  # TWD_thousand | TWD/share


@dataclass(frozen=True)
class BoardReport:
    period_start: date
    period_end: date
    items: tuple[BoardReportItem, ...]

    @property
    def annual_fiscal_year(self) -> int | None:
        if (self.period_start.month, self.period_start.day, self.period_end.month, self.period_end.day) == (1, 1, 12, 31) \
                and self.period_start.year == self.period_end.year:
            return self.period_start.year
        return None


def parse_board_financial_report(body: str) -> BoardReport:
    """Key figures of a MOPS annual/interim financial-report board-approval notice (fails closed)."""
    text = body.replace("：", ":")
    period = _BOARD_PERIOD.search(re.sub(r"\s+", "", text))
    if not period:
        raise EvidenceParseError("Board-approval notice states no reporting period (起訖日期).")
    numbers = [int(part) for part in period.groups()]
    start = date(numbers[0] + 1911, numbers[1], numbers[2])
    end = date(numbers[3] + 1911, numbers[4], numbers[5])
    items: list[BoardReportItem] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", "", raw)
        match = _BOARD_LINE.match(line)
        if not match:
            continue
        label, unit, amount = match.groups()
        if label not in BOARD_REPORT_LABELS:
            raise EvidenceParseError(f"Unsupported board-approval line label {label!r}.")
        if unit == "仟元" and BOARD_REPORT_LABELS[label] == "eps" or unit == "元" and BOARD_REPORT_LABELS[label] != "eps":
            raise EvidenceParseError(f"Unexpected unit {unit} for {label}.")
        negative = amount.startswith("(") or amount.startswith("-")
        value = Decimal(amount.strip("()").lstrip("-").replace(",", ""))
        items.append(BoardReportItem(label, BOARD_REPORT_LABELS[label], -value if negative else value,
                                     "TWD/share" if unit == "元" else "TWD_thousand"))
    labels = [item.label for item in items]
    if len(labels) != len(set(labels)) or not {"營業收入", "期末總資產"} <= set(labels):
        raise EvidenceParseError("Board-approval notice lacks the expected key-figure lines or repeats one.")
    return BoardReport(start, end, tuple(items))
