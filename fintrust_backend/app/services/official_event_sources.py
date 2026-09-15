from __future__ import annotations

import json
import re
import hashlib
import ssl
from http.cookiejar import CookieJar
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urljoin, urlencode, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener, urlopen

from app.official_event_models import (
    InvestorConferenceRecord,
    MaterialEventCategory,
    MaterialEventRecord,
    OfficialClaimType,
    OfficialDisclosureClaim,
)
from app.services.company_registry import get_company
from app.services.financial_analysis_service import UnsupportedCompanyError


MOPS_BASE = "https://mops.twse.com.tw/mops/web"
TWSE_MATERIAL_EVENTS_OPENAPI_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"

CONFERENCE_TOPIC_METRICS: dict[str, list[str]] = {
    "晶圓代工": ["capex_intensity", "free_cash_flow", "gross_margin", "operating_margin", "debt_ratio"],
    "IC 設計": ["rd_intensity", "revenue_growth_yoy", "inventory_growth_yoy", "cash_conversion_ratio"],
    "封裝測試": ["inventory_growth_yoy", "operating_cash_flow", "cash_conversion_ratio", "debt_ratio", "current_ratio"],
}

CONFERENCE_TOPIC_KEYWORDS: tuple[tuple[OfficialClaimType, tuple[str, ...], tuple[str, ...]], ...] = (
    ("capacity_or_capex", ("資本支出", "擴產", "產能", "建廠", "設備", "capex", "capacity"), ("capex_intensity", "free_cash_flow", "debt_ratio")),
    ("inventory_or_demand", ("庫存", "存貨", "需求", "去化", "客戶拉貨", "inventory", "demand"), ("inventory_growth_yoy", "revenue_growth_yoy", "cash_conversion_ratio")),
    ("revenue_or_orders", ("營收", "訂單", "接單", "客戶", "revenue", "orders"), ("revenue_growth_yoy", "gross_margin", "operating_margin")),
    ("outlook", ("展望", "財測", "預估", "guidance", "outlook", "forecast"), ("revenue_growth_yoy", "operating_margin", "cash_conversion_ratio")),
    ("rd_or_product", ("研發", "新產品", "產品組合", "r&d", "product mix", "roadmap"), ("rd_intensity", "gross_margin", "revenue_growth_yoy")),
    ("cash_flow_or_financing", ("現金流", "自由現金流", "負債", "借款", "cash flow", "debt"), ("free_cash_flow", "operating_cash_flow", "debt_ratio")),
)

MATERIAL_EVENT_KEYWORDS: tuple[tuple[MaterialEventCategory, tuple[str, ...], tuple[str, ...]], ...] = (
    ("capacity_or_capex", ("擴產", "產能", "資本支出", "建廠", "設備", "capex"), ("capex_intensity", "free_cash_flow", "debt_ratio")),
    ("inventory_or_demand", ("庫存", "存貨", "需求", "去化", "客戶拉貨", "inventory", "demand"), ("inventory_growth_yoy", "revenue_growth_yoy", "cash_conversion_ratio")),
    ("revenue_or_orders", ("營收", "訂單", "接單", "客戶", "revenue", "orders"), ("revenue_growth_yoy", "gross_margin", "operating_margin")),
    ("financial_outlook", ("展望", "財測", "預估", "forecast", "outlook", "guidance"), ("revenue_growth_yoy", "operating_margin", "cash_conversion_ratio")),
    ("financing_or_debt", ("借款", "公司債", "現金增資", "資金", "負債", "financing", "debt"), ("debt_ratio", "current_ratio", "free_cash_flow")),
    ("ma_or_investment", ("併購", "投資", "取得", "處分", "investment", "acquisition"), ("free_cash_flow", "debt_ratio", "capex_intensity")),
    ("operation_disruption", ("停工", "停產", "火災", "地震", "斷電", "營運", "disruption"), ("revenue_growth_yoy", "operating_cash_flow")),
    ("legal_or_penalty", ("訴訟", "裁罰", "罰款", "違反", "litigation", "penalty"), ("net_margin", "operating_cash_flow")),
    ("governance", ("董事", "總經理", "治理", "內控", "governance"), ("debt_ratio", "current_ratio")),
)

ANCHOR_RE = re.compile(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
DATE_RE = re.compile(r"(?P<year>20\d{2}|1\d{2})[./\-年](?P<month>\d{1,2})[./\-月](?P<day>\d{1,2})")
TIME_RE = re.compile(r"(?P<hour>[0-2]?\d):(?P<minute>[0-5]\d)(?::(?P<second>[0-5]\d))?")
ROC_COMPACT_DATE_RE = re.compile(r"^(?P<year>\d{3})(?P<month>\d{2})(?P<day>\d{2})$")
TWSE_CONFERENCE_KEYWORDS = (
    "法人說明會",
    "法說會",
    "投資人說明會",
    "investor conference",
    "earnings conference",
    "conference call",
)
DOCUMENT_KEYWORDS = (
    "pdf", "ppt", "pptx", "簡報", "法人", "法說", "video", "影音", "錄影", "錄音", "下載", "download", "presentation"
)
LIVE_DEBUG_LIMIT = 1200


def _require_company(ticker: str):
    company = get_company(ticker)
    if company is None:
        raise UnsupportedCompanyError("MVP 僅分析已登錄的半導體公司；請先將公司加入 semiconductor registry。")
    return company


def _strip_tags(value: str) -> str:
    return SPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", value))).strip()


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _canonical_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def _stable_hash(*parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _extract_first_date(text: str) -> str | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    year = int(match.group("year"))
    if year < 1911:
        year += 1911
    return f"{year:04d}-{int(match.group('month')):02d}-{int(match.group('day')):02d}"


def _extract_first_time(text: str) -> str | None:
    match = TIME_RE.search(text)
    if not match:
        return None
    second = match.group("second") or "00"
    return f"{int(match.group('hour')):02d}:{int(match.group('minute')):02d}:{int(second):02d}"


def _parse_twse_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = ROC_COMPACT_DATE_RE.match(text)
    if match:
        return f"{int(match.group('year')) + 1911:04d}-{int(match.group('month')):02d}-{int(match.group('day')):02d}"
    return _extract_first_date(text)


def _parse_twse_time(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    digits = digits.zfill(6)
    if len(digits) > 6:
        digits = digits[-6:]
    return f"{int(digits[:2]):02d}:{int(digits[2:4]):02d}:{int(digits[4:6]):02d}"


def _preview_text(text: str, *, limit: int = 800) -> str:
    return _strip_tags(text)[:limit]


def _is_blocked_by_source_text(text: str) -> bool:
    normalized = text.casefold()
    return (
        "for security reasons" in normalized
        or "location.href = location.origin" in normalized
        or "無法呈現" in text
        or "無法顯示" in text
    )


def _current_roc_year() -> int:
    return datetime.now(timezone.utc).year - 1911


def _decode_response(raw: bytes) -> str:
    for encoding in ("utf-8", "big5", "cp950"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _verified_ssl_context():
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return None


def _public_request_json(url: str, *, timeout_seconds: float = 10.0) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": "FinTrustAlert-MIS-Project/0.1 (+https://github.com/UnaLu027/fintrust-alert)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=timeout_seconds, context=_verified_ssl_context()) as response:  # noqa: S310 - official public OpenAPI endpoint
        raw = response.read()
    return json.loads(_decode_response(raw))


def _twse_field(row: dict[str, Any], *names: str) -> str:
    normalized = {str(key).strip(): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name.strip())
        if value is not None:
            return str(value).strip()
    return ""


def _claim_from_keyword(
    *,
    claim_type: OfficialClaimType,
    text: str,
    metrics: tuple[str, ...],
    source_url: str,
    confidence: float,
) -> OfficialDisclosureClaim:
    return OfficialDisclosureClaim(
        claim_type=claim_type,
        text=text,
        related_metrics=list(metrics),
        evidence_source=source_url,
        confidence=confidence,
        limitations=["此為官方揭露文字的保守主題抽取；仍需搭配年度財報數字與後續 Gemini 摘要確認語意。"],
    )


def infer_official_claims(text: str, *, source_url: str) -> list[OfficialDisclosureClaim]:
    normalized = text.casefold()
    claims: list[OfficialDisclosureClaim] = []
    for claim_type, keywords, metrics in CONFERENCE_TOPIC_KEYWORDS:
        matched = [keyword for keyword in keywords if keyword.casefold() in normalized]
        if not matched:
            continue
        claims.append(
            _claim_from_keyword(
                claim_type=claim_type,
                text=f"官方揭露文字提及：{', '.join(matched[:3])}",
                metrics=metrics,
                source_url=source_url,
                confidence=0.72,
            )
        )
    return claims


def infer_conference_topics(text: str, subindustry: str) -> list[str]:
    normalized = text.casefold()
    topics: list[str] = []
    if any(keyword.casefold() in normalized for keyword in ("展望", "guidance", "outlook", "forecast")):
        topics.append("近期營運展望")
    if any(keyword.casefold() in normalized for keyword in ("資本支出", "擴產", "產能", "capex")):
        topics.append("資本支出與產能規劃")
    if any(keyword.casefold() in normalized for keyword in ("庫存", "存貨", "需求", "inventory", "demand")):
        topics.append("庫存、需求與產品去化")
    if any(keyword.casefold() in normalized for keyword in ("研發", "新產品", "r&d", "roadmap")):
        topics.append("研發投入與產品路線")
    if any(keyword.casefold() in normalized for keyword in ("現金流", "負債", "cash flow", "debt")):
        topics.append("現金流與財務結構")
    if not topics:
        topics = [
            "近期營運展望",
            "資本支出與產能規劃" if subindustry == "晶圓代工" else "產品組合與需求變化",
            "庫存、現金流與財務結構",
        ]
    return _dedupe(topics)


def investor_conference_query_url(ticker: str) -> str:
    params = urlencode({"co_id": ticker, "firstin": "true", "step": "1"})
    return f"{MOPS_BASE}/t100sb07_1?{params}"


def material_event_query_url(ticker: str, year: int | None = None) -> str:
    params = {"co_id": ticker, "firstin": "true", "step": "1"}
    if year is not None:
        params["year"] = str(year - 1911 if year > 1911 else year)
    return f"{MOPS_BASE}/t05st01?{urlencode(params)}"


def investor_conference_identity(record: InvestorConferenceRecord) -> str:
    return record.event_id or _stable_hash(
        "investor_conference",
        record.ticker,
        record.conference_date,
        _canonical_url(record.document_url or record.source_url),
        record.title,
    )


def material_event_identity(record: MaterialEventRecord) -> str:
    return record.event_id or _stable_hash(
        "material_event",
        record.ticker,
        record.event_date,
        record.event_time,
        _canonical_url(record.detail_url or record.source_url),
        record.title,
    )


def _conference_query_params(ticker: str, *, year: int | None = None) -> dict[str, str]:
    params = {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "TYPEK": "all",
        "inpuType": "co_id",
        "co_id": ticker,
    }
    if year is not None:
        params["year"] = str(year)
    return params


def _mops_headers(*, referer: str) -> dict[str, str]:
    return {
        "User-Agent": "FinTrustAlert-MIS-Project/0.1 (+https://github.com/UnaLu027/fintrust-alert)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": referer,
    }


def _mops_opener():
    handlers = [HTTPCookieProcessor(CookieJar())]
    context = _verified_ssl_context()
    if context is not None:
        handlers.append(HTTPSHandler(context=context))
    return build_opener(*handlers)


def _mops_request(url: str, *, params: dict[str, str] | None = None, method: str = "GET", timeout_seconds: float = 10.0) -> str:
    data = None
    target_url = url
    if method == "GET" and params:
        target_url = f"{url}?{urlencode(params)}"
    if method == "POST":
        data = urlencode(params or {}).encode("utf-8")
    opener = _mops_opener()
    landing = Request(
        f"{MOPS_BASE}/mops",
        headers=_mops_headers(referer="https://mops.twse.com.tw/"),
        method="GET",
    )
    try:
        with opener.open(landing, timeout=min(timeout_seconds, 5.0)) as response:
            response.read(512)
    except Exception:
        pass
    request = Request(
        target_url,
        data=data,
        headers=_mops_headers(referer=f"{MOPS_BASE}/mops"),
        method=method,
    )
    with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310 - official public disclosure page
        raw = response.read()
    return _decode_response(raw)


def _html_score(html: str, company_name: str) -> int:
    text = _strip_tags(html)
    lowered = f"{text} {html}".casefold()
    score = min(len(text), 2000) // 40
    if "<table" in html.casefold():
        score += 30
    if ANCHOR_RE.search(html):
        score += 20
    if company_name and company_name.casefold() in lowered:
        score += 40
    if any(keyword.casefold() in lowered for keyword in ("法人說明會", "法說會", "簡報", "影音", "presentation")):
        score += 60
    if any(keyword.casefold() in lowered for keyword in DOCUMENT_KEYWORDS):
        score += 30
    if any(no_data in text for no_data in ("查無資料", "無符合條件", "無資料")):
        score -= 40
    return score


def _summarize_html_variant(*, strategy: str, url: str, html: str | None = None, error: str | None = None, company_name: str = "") -> dict[str, Any]:
    text = _strip_tags(html or "")
    blocked = bool(text and _is_blocked_by_source_text(text))
    return {
        "strategy": strategy,
        "url": url,
        "status": "error" if error else "blocked_by_source" if blocked else "fetched",
        "error": error,
        "html_length": len(html or ""),
        "text_length": len(text),
        "score": -100 if blocked else _html_score(html or "", company_name) if html else 0,
        "has_table": "<table" in (html or "").casefold(),
        "anchor_count": len(ANCHOR_RE.findall(html or "")),
        "contains_company_name": bool(company_name and company_name in text),
        "contains_conference_keywords": any(keyword in text for keyword in ("法人說明會", "法說會", "簡報", "影音")),
        "contains_no_data_phrase": any(no_data in text for no_data in ("查無資料", "無符合條件", "無資料")),
        "blocked_by_source": blocked,
        "text_preview": text[:LIVE_DEBUG_LIMIT],
    }


def fetch_investor_conference_html_variants(ticker: str, *, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    company = _require_company(ticker)
    roc_year = _current_roc_year()
    attempts: list[tuple[str, str, str, dict[str, str]]] = [
        ("get_entry", "GET", f"{MOPS_BASE}/t100sb07_1", _conference_query_params(ticker)),
        ("get_ajax_current_year", "GET", f"{MOPS_BASE}/ajax_t100sb07_1", _conference_query_params(ticker, year=roc_year)),
        ("post_ajax_current_year", "POST", f"{MOPS_BASE}/ajax_t100sb07_1", _conference_query_params(ticker, year=roc_year)),
        ("get_ajax_previous_year", "GET", f"{MOPS_BASE}/ajax_t100sb07_1", _conference_query_params(ticker, year=roc_year - 1)),
        ("get_ajax_no_year", "GET", f"{MOPS_BASE}/ajax_t100sb07_1", _conference_query_params(ticker)),
    ]
    variants: list[dict[str, Any]] = []
    for strategy, method, endpoint, params in attempts:
        final_url = f"{endpoint}?{urlencode(params)}" if method == "GET" else endpoint
        try:
            html = _mops_request(endpoint, params=params, method=method, timeout_seconds=timeout_seconds)
            variants.append({**_summarize_html_variant(strategy=strategy, url=final_url, html=html, company_name=company.name), "html": html})
        except Exception as exc:  # pragma: no cover - live MOPS availability is external
            variants.append(_summarize_html_variant(strategy=strategy, url=final_url, error=str(exc), company_name=company.name))
    return variants


def _best_html_variant(variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    fetched = [variant for variant in variants if variant.get("status") == "fetched" and variant.get("html")]
    if not fetched:
        return None
    return max(fetched, key=lambda item: int(item.get("score") or 0))


def write_investor_conference_debug_files(ticker: str, variants: list[dict[str, Any]], debug_dir: str | Path) -> dict[str, Any]:
    directory = Path(debug_dir)
    directory.mkdir(parents=True, exist_ok=True)
    html_files: list[str] = []
    sanitized_variants: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        html = str(variant.get("html") or "")
        if html:
            html_path = directory / f"mops-conference-{ticker}-{index:02d}-{variant['strategy']}.html"
            html_path.write_text(html, encoding="utf-8")
            html_files.append(str(html_path))
        sanitized_variants.append({key: value for key, value in variant.items() if key != "html"})
    best = _best_html_variant(variants)
    summary = {
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "best_strategy": best.get("strategy") if best else None,
        "best_score": best.get("score") if best else 0,
        "html_files": html_files,
        "variants": sanitized_variants,
        "next_parser_hint": (
            "best variant has table or conference keywords; inspect saved HTML and extend table/link parser"
            if best and (best.get("has_table") or best.get("contains_conference_keywords"))
            else "MOPS returned shell/no data/error; inspect query params or use ajax/post variant captured here"
        ),
    }
    summary_path = directory / f"mops-conference-{ticker}-debug.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["debug_summary_file"] = str(summary_path)
    return summary


def fetch_investor_conference_html(ticker: str, *, timeout_seconds: float = 10.0) -> str:
    variants = fetch_investor_conference_html_variants(ticker, timeout_seconds=timeout_seconds)
    best = _best_html_variant(variants)
    if best is None:
        raise RuntimeError("MOPS 法說會 live fetch did not return usable HTML.")
    return str(best["html"])


def _extract_document_links(html: str, source_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for href, label_html in ANCHOR_RE.findall(html):
        label = _strip_tags(label_html)
        absolute = urljoin(source_url, href)
        link_text = f"{label} {href}".casefold()
        if any(keyword.casefold() in link_text for keyword in DOCUMENT_KEYWORDS):
            links.append((absolute, label or absolute))
    for raw_url in URL_RE.findall(html):
        if any(keyword.casefold() in raw_url.casefold() for keyword in DOCUMENT_KEYWORDS):
            links.append((raw_url, raw_url))
    return list(dict.fromkeys(links))


def _extract_links(html: str, source_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for href, label_html in ANCHOR_RE.findall(html):
        label = _strip_tags(label_html)
        absolute = urljoin(source_url, href)
        links.append((absolute, label or absolute))
    return list(dict.fromkeys(links))


def _extract_table_rows(html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_html in TR_RE.findall(html):
        cells = [_strip_tags(cell) for cell in CELL_RE.findall(row_html)]
        cells = [cell for cell in cells if cell]
        if not cells:
            continue
        row_text = " ".join(cells)
        if len(row_text) < 8:
            continue
        rows.append({"cells": cells, "row_html": row_html, "row_text": row_text})
    return rows


def _row_looks_like_conference(row: dict[str, Any], company_name: str, ticker: str) -> bool:
    text = str(row.get("row_text") or "")
    lowered = text.casefold()
    if company_name and company_name in text:
        return True
    if ticker and ticker in text and any(keyword in text for keyword in ("法說", "法人", "簡報", "影音", "說明會")):
        return True
    if any(keyword.casefold() in lowered for keyword in ("法人說明會", "法說會", "presentation", "簡報", "影音")):
        return True
    return bool(_extract_document_links(str(row.get("row_html") or ""), investor_conference_query_url(ticker)))


def _record_from_conference_text(
    *,
    ticker: str,
    text: str,
    row_html: str,
    source: str,
    title: str,
    max_items: int,
) -> InvestorConferenceRecord:
    company = _require_company(ticker)
    related_metrics = CONFERENCE_TOPIC_METRICS.get(company.subindustry, [])
    topics = infer_conference_topics(text, company.subindustry)
    claims = infer_official_claims(text, source_url=source)
    links = _extract_document_links(row_html, source)[:max_items]
    document_url = links[0][0] if links else None
    document_title = links[0][1] if links else None
    status = "available" if links or claims or len(text) >= 40 else "metadata_only"
    extract_status = "document_link_found" if links else "html_preview" if status == "available" else "metadata_only"
    limitations = [
        "系統已支援 MOPS 法說會資料取得、官方附件解析、文件文字抽取、topics / claims 整理與持久化。",
        "法說會內容屬管理層展望，僅能作為官方文字證據，仍需與年度財報指標交叉檢查。",
    ]
    if not links:
        limitations.append("本筆法說會列未偵測到附件連結；保留 row text preview 供 parser debug 與人工覆核。")
    return InvestorConferenceRecord(
        event_id=_stable_hash("investor_conference", company.ticker, _extract_first_date(text), _canonical_url(document_url or source), title),
        ticker=company.ticker,
        company_name=company.name,
        subindustry=company.subindustry,
        source_name="mops",
        conference_date=_extract_first_date(text),
        title=title,
        source_url=source,
        document_url=document_url,
        status=status,  # type: ignore[arg-type]
        document_extract_status=extract_status,  # type: ignore[arg-type]
        document_title=document_title,
        document_text_preview=text[:800] if extract_status == "html_preview" else None,
        document_text_length=len(text) if text else None,
        source_evidence=_dedupe([label for _, label in links] + topics + ([text[:160]] if text else [])),
        extracted_topics=topics[:max_items],
        related_metrics=related_metrics,
        disclosure_claims=claims,
        summary=(
            "已從 MOPS 法說會 HTML/table row 偵測到官方文字或附件線索，可補充近期展望、產能、庫存與需求訊息。"
            if status == "available"
            else None
        ),
        limitations=limitations,
        retrieved_at=datetime.now(timezone.utc),
    )


def parse_investor_conference_html(
    ticker: str,
    html: str,
    *,
    source_url: str | None = None,
    max_items: int = 3,
) -> list[InvestorConferenceRecord]:
    company = _require_company(ticker)
    source = source_url or investor_conference_query_url(company.ticker)
    page_text = _strip_tags(html)
    records: list[InvestorConferenceRecord] = []
    rows = _extract_table_rows(html)
    for row in rows:
        if not _row_looks_like_conference(row, company.name, company.ticker):
            continue
        cells = list(row["cells"])
        title = next(
            (cell for cell in cells if any(keyword in cell for keyword in ("法說", "法人", "簡報", "說明會"))),
            f"{company.name} 法人說明會資料",
        )
        records.append(
            _record_from_conference_text(
                ticker=company.ticker,
                text=str(row["row_text"]),
                row_html=str(row["row_html"]),
                source=source,
                title=title,
                max_items=max_items,
            )
        )
        if len(records) >= max_items:
            break
    if records and any(record.status == "available" for record in records):
        return records

    page_preview = _preview_text(html)
    related_metrics = CONFERENCE_TOPIC_METRICS.get(company.subindustry, [])
    topics = infer_conference_topics(page_text, company.subindustry)
    claims = infer_official_claims(page_text, source_url=source)
    links = _extract_document_links(html, source)[:max_items]
    document_url = links[0][0] if links else None
    document_title = links[0][1] if links else None
    has_useful_preview = bool(page_preview and any(keyword in page_preview for keyword in (company.name, "法人說明會", "法說會", "簡報", "影音")))
    status = "available" if links or claims or has_useful_preview else "metadata_only"
    extract_status = "document_link_found" if links else "html_preview" if has_useful_preview else "metadata_only"
    limitations = [
        "系統已支援 MOPS 法說會資料取得、官方附件解析、文件文字抽取、topics / claims 整理與持久化。",
        "法說會內容屬管理層展望，僅能作為官方文字證據，仍需與年度財報指標交叉檢查。",
    ]
    if not links:
        limitations.append("本次 HTML 未偵測到 PDF / 簡報 / 影音附件連結；保留 MOPS 查詢入口與 debug 檔供下一步調整 POST/table parser。")
    page_record = InvestorConferenceRecord(
        event_id=_stable_hash("investor_conference", company.ticker, _extract_first_date(page_text), _canonical_url(document_url or source), f"{company.name} 法人說明會資料"),
        ticker=company.ticker,
        company_name=company.name,
        subindustry=company.subindustry,
        source_name="mops",
        conference_date=_extract_first_date(page_text),
        title=f"{company.name} 法人說明會資料",
        source_url=source,
        document_url=document_url,
        status=status,  # type: ignore[arg-type]
        document_extract_status=extract_status,  # type: ignore[arg-type]
        document_title=document_title,
        document_text_preview=page_preview if extract_status == "html_preview" else None,
        document_text_length=len(page_text) if page_text else None,
        source_evidence=_dedupe([label for _, label in links] + topics),
        extracted_topics=topics[:max_items],
        related_metrics=related_metrics,
        disclosure_claims=claims,
        summary=(
            "已從法說會頁面偵測到官方附件或主題線索，可作為年度財報之外的較即時官方文字證據。"
            if status == "available"
            else None
        ),
        limitations=limitations,
        retrieved_at=datetime.now(timezone.utc),
    )
    if page_record.status == "available":
        return [page_record, *records[: max_items - 1]] if records else [page_record]
    return records or [page_record]


def build_investor_conference_metadata(
    ticker: str,
    *,
    max_items: int = 3,
    fetch_live: bool = False,
    html: str | None = None,
    debug_dir: str | Path | None = None,
) -> list[InvestorConferenceRecord]:
    company = _require_company(ticker)
    url = investor_conference_query_url(company.ticker)
    if html is not None:
        return parse_investor_conference_html(company.ticker, html, source_url=url, max_items=max_items)
    if fetch_live:
        twse_records: list[InvestorConferenceRecord] = []
        try:
            twse_records = build_twse_investor_conference_metadata(company.ticker, max_items=max_items)
        except Exception:
            twse_records = []
        try:
            from app.services.official_company_ir_sources import build_official_ir_fallback_metadata

            ir_records, _debug = build_official_ir_fallback_metadata(company.ticker, max_items=max_items, debug_dir=debug_dir)
            combined = _dedupe_conference_records([*twse_records, *ir_records])
            if combined:
                return combined[:max_items]
        except Exception:
            if twse_records:
                return twse_records[:max_items]
        try:
            variants = fetch_investor_conference_html_variants(company.ticker)
            if debug_dir is not None:
                write_investor_conference_debug_files(company.ticker, variants, debug_dir)
            best = _best_html_variant(variants)
            if best is None:
                errors = [str(variant.get("error")) for variant in variants if variant.get("status") == "error"]
                blocked = [variant for variant in variants if variant.get("status") == "blocked_by_source"]
                if blocked and len(blocked) == len(variants):
                    return [
                        _metadata_only_conference_record(
                            company.ticker,
                            max_items=max_items,
                            extra_limitations=["MOPS live fetch 被來源安全機制阻擋；保留 persisted previous evidence 或 metadata 查詢入口。"],
                            status="blocked_by_source",
                        )
                    ]
                if errors and len(errors) == len(variants):
                    return [
                        _metadata_only_conference_record(
                            company.ticker,
                            max_items=max_items,
                            extra_limitations=[f"MOPS live fetch 全部失敗：{errors[0]}"],
                            status="error",
                        )
                    ]
                return [
                    _metadata_only_conference_record(
                        company.ticker,
                        max_items=max_items,
                        extra_limitations=["MOPS live fetch 完成但沒有可解析 HTML；請查看 mops-conference debug JSON。"],
                        status="needs_manual_review",
                    )
                ]
            return parse_investor_conference_html(company.ticker, str(best["html"]), source_url=url, max_items=max_items)
        except Exception as exc:  # pragma: no cover - live MOPS availability is external
            if twse_records:
                return twse_records[:max_items]
            return [
                _metadata_only_conference_record(
                    company.ticker,
                    max_items=max_items,
                    extra_limitations=[f"即時抓取 MOPS 法說會頁面失敗：{exc}"],
                    status="error",
                )
            ]
    return [_metadata_only_conference_record(company.ticker, max_items=max_items)]


def _dedupe_conference_records(records: list[InvestorConferenceRecord]) -> list[InvestorConferenceRecord]:
    deduped: dict[str, InvestorConferenceRecord] = {}
    for record in records:
        deduped.setdefault(investor_conference_identity(record), record)
    return list(deduped.values())


def _metadata_only_conference_record(
    ticker: str,
    *,
    max_items: int = 3,
    extra_limitations: list[str] | None = None,
    status: str = "metadata_only",
) -> InvestorConferenceRecord:
    company = _require_company(ticker)
    url = investor_conference_query_url(company.ticker)
    related_metrics = CONFERENCE_TOPIC_METRICS.get(company.subindustry, [])
    topics = [
        "近期營運展望",
        "資本支出與產能規劃" if company.subindustry == "晶圓代工" else "產品組合與需求變化",
        "庫存、現金流與財務結構",
    ]
    limitations = [
        "系統已支援 MOPS 法說會資料取得、官方附件解析、文件文字抽取、topics / claims 整理與持久化。",
        "若 MOPS 回傳來源安全機制頁面、附件不存在或文件格式無法解析，系統會保留來源狀態與既有 persisted evidence。",
    ]
    if extra_limitations:
        limitations.extend(extra_limitations)
    return InvestorConferenceRecord(
        event_id=_stable_hash("investor_conference", company.ticker, None, _canonical_url(url), f"{company.name} 法人說明會資料查詢入口"),
        ticker=company.ticker,
        company_name=company.name,
        subindustry=company.subindustry,
        source_name="mops",
        title=f"{company.name} 法人說明會資料查詢入口",
        source_url=url,
        status=status,  # type: ignore[arg-type]
        document_extract_status="metadata_only",
        extracted_topics=topics[:max_items],
        related_metrics=related_metrics,
        source_evidence=topics[:max_items],
        limitations=limitations,
        retrieved_at=datetime.now(timezone.utc),
    )


def classify_material_event(title: str, raw_text: str | None = None) -> tuple[MaterialEventCategory, list[str], bool]:
    title_text = title.casefold()
    body_text = (raw_text or "").casefold()
    best: tuple[int, int, MaterialEventCategory, tuple[str, ...]] | None = None
    for category, keywords, metrics in MATERIAL_EVENT_KEYWORDS:
        title_hits = sum(1 for keyword in keywords if keyword.casefold() in title_text)
        body_hits = sum(1 for keyword in keywords if keyword.casefold() in body_text)
        score = title_hits * 3 + body_hits
        if score <= 0:
            continue
        candidate = (score, title_hits, category, metrics)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is not None:
        return best[2], list(best[3]), True
    return "other", [], False


def fetch_twse_material_event_rows(*, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    payload = _public_request_json(TWSE_MATERIAL_EVENTS_OPENAPI_URL, timeout_seconds=timeout_seconds)
    if not isinstance(payload, list):
        raise RuntimeError("TWSE material-information OpenAPI did not return a JSON list.")
    return [row for row in payload if isinstance(row, dict)]


def filter_twse_material_event_rows(ticker: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    company = _require_company(ticker)
    return [row for row in rows if _twse_field(row, "公司代號") == company.ticker]


def _twse_openapi_raw_text(row: dict[str, Any]) -> str:
    parts = [
        f"出表日期：{_twse_field(row, '出表日期')}",
        f"發言日期：{_twse_field(row, '發言日期')}",
        f"發言時間：{_twse_field(row, '發言時間')}",
        f"公司代號：{_twse_field(row, '公司代號')}",
        f"公司名稱：{_twse_field(row, '公司名稱')}",
        f"符合條款：{_twse_field(row, '符合條款')}",
        f"事實發生日：{_twse_field(row, '事實發生日')}",
        f"主旨：{_twse_field(row, '主旨')}",
        f"說明：{_twse_field(row, '說明')}",
    ]
    return "\n".join(part for part in parts if not part.endswith("："))


def parse_twse_material_event_rows(
    ticker: str,
    rows: list[dict[str, Any]],
    *,
    max_items: int = 5,
) -> list[MaterialEventRecord]:
    company = _require_company(ticker)
    records: list[MaterialEventRecord] = []
    for row in filter_twse_material_event_rows(company.ticker, rows):
        title = _twse_field(row, "主旨") or f"{company.name} TWSE 重大訊息"
        description = _twse_field(row, "說明")
        clause = _twse_field(row, "符合條款")
        announcement_date = _parse_twse_date(_twse_field(row, "發言日期"))
        announcement_time = _parse_twse_time(_twse_field(row, "發言時間"))
        fact_date = _parse_twse_date(_twse_field(row, "事實發生日"))
        raw_text = _twse_openapi_raw_text(row)
        category, related_metrics, risk_related = classify_material_event(title, description)
        records.append(
            MaterialEventRecord(
                event_id=_stable_hash("material_event", "twse_openapi", company.ticker, announcement_date, announcement_time, fact_date, clause, title),
                ticker=company.ticker,
                company_name=_twse_field(row, "公司名稱") or company.name,
                subindustry=company.subindustry,
                event_date=fact_date or announcement_date,
                event_time=announcement_time,
                title=title,
                category=category,
                source_name="twse_openapi",
                source_url=TWSE_MATERIAL_EVENTS_OPENAPI_URL,
                status="available",
                raw_text=_preview_text(raw_text, limit=1800),
                related_metrics=related_metrics,
                risk_related=risk_related,
                summary=f"TWSE OpenAPI 上市公司每日重大訊息；符合條款：{clause or '未提供'}；發言日期：{announcement_date or '未提供'}。",
                disclosure_claims=_claims_for_material_event(
                    category=category,
                    title=title,
                    raw_text=description or raw_text,
                    related_metrics=related_metrics,
                    source_url=TWSE_MATERIAL_EVENTS_OPENAPI_URL,
                    risk_related=risk_related,
                ),
                limitations=[
                    "此筆資料來自 TWSE OpenAPI 上市公司每日重大訊息；若當日 feed 未含該公司，系統才會回到 MOPS fallback。",
                    "OpenAPI feed 不提供 MOPS 明細頁 URL；系統保留發言日期、發言時間、符合條款、事實發生日與說明全文。",
                ],
                retrieved_at=datetime.now(timezone.utc),
            )
        )
        if len(records) >= max_items:
            break
    return records


def build_twse_material_event_metadata(ticker: str, *, max_items: int = 5) -> list[MaterialEventRecord]:
    return parse_twse_material_event_rows(ticker, fetch_twse_material_event_rows(), max_items=max_items)


def is_persistable_investor_conference(record: InvestorConferenceRecord) -> bool:
    """Return True only for real official conference records, not source diagnostics."""
    return bool(
        record.status == "available"
        and record.ticker
        and investor_conference_identity(record)
        and record.conference_date
        and record.title
        and record.source_name
        and record.source_url
    )


def is_persistable_material_event(record: MaterialEventRecord) -> bool:
    """Return True only for real official material events, not query-entry placeholders."""
    if record.status != "available":
        return False
    if "歷史重大訊息查詢入口" in record.title:
        return False
    return bool(
        record.ticker
        and material_event_identity(record)
        and record.event_date
        and record.title
        and record.source_name
        and record.source_url
    )


def build_twse_investor_conference_metadata(ticker: str, *, max_items: int = 3) -> list[InvestorConferenceRecord]:
    company = _require_company(ticker)
    rows = filter_twse_material_event_rows(company.ticker, fetch_twse_material_event_rows())
    records: list[InvestorConferenceRecord] = []
    for row in rows:
        title = _twse_field(row, "主旨")
        description = _twse_field(row, "說明")
        text = f"{title}\n{description}"
        if not any(keyword.casefold() in text.casefold() for keyword in TWSE_CONFERENCE_KEYWORDS):
            continue
        conference_date = _parse_twse_date(_twse_field(row, "事實發生日")) or _parse_twse_date(_twse_field(row, "發言日期"))
        conference_time = _parse_twse_time(_twse_field(row, "發言時間"))
        topics = infer_conference_topics(text, company.subindustry)
        claims = infer_official_claims(text, source_url=TWSE_MATERIAL_EVENTS_OPENAPI_URL)
        records.append(
            InvestorConferenceRecord(
                event_id=_stable_hash("investor_conference", "twse_openapi", company.ticker, conference_date, conference_time, _twse_field(row, "符合條款"), title),
                ticker=company.ticker,
                company_name=_twse_field(row, "公司名稱") or company.name,
                subindustry=company.subindustry,
                conference_date=conference_date,
                title=title or f"{company.name} 法人說明會公告",
                source_name="twse_openapi",
                source_url=TWSE_MATERIAL_EVENTS_OPENAPI_URL,
                status="available",
                document_extract_status="html_preview",
                document_text_preview=_preview_text(_twse_openapi_raw_text(row), limit=800),
                document_text_length=len(_twse_openapi_raw_text(row)),
                extracted_topics=topics[:max_items],
                related_metrics=CONFERENCE_TOPIC_METRICS.get(company.subindustry, []),
                disclosure_claims=claims,
                source_evidence=_dedupe([title, _twse_field(row, "符合條款"), *topics]),
                summary="TWSE OpenAPI 重大訊息 feed 偵測到法說會相關官方公告；後續以公司官方 IR 文件補足 presentation / transcript。",
                limitations=[
                    "TWSE OpenAPI 用於偵測法說會公告；presentation / transcript 文件仍以公司官方 IR 或 MOPS 附件補足。",
                ],
                retrieved_at=datetime.now(timezone.utc),
            )
        )
        if len(records) >= max_items:
            break
    return records


def _material_event_query_params(ticker: str, *, year: int | None = None) -> dict[str, str]:
    params = {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "TYPEK": "all",
        "co_id": ticker,
    }
    if year is not None:
        params["year"] = str(year - 1911 if year > 1911 else year)
    return params


def fetch_material_event_html_variants(
    ticker: str,
    *,
    year: int | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    company = _require_company(ticker)
    params = _material_event_query_params(company.ticker, year=year)
    attempts: list[tuple[str, str, str, dict[str, str]]] = [
        ("get_entry", "GET", f"{MOPS_BASE}/t05st01", params),
        ("get_ajax", "GET", f"{MOPS_BASE}/ajax_t05st01", params),
        ("post_ajax", "POST", f"{MOPS_BASE}/ajax_t05st01", params),
    ]
    variants: list[dict[str, Any]] = []
    for strategy, method, endpoint, attempt_params in attempts:
        final_url = f"{endpoint}?{urlencode(attempt_params)}" if method == "GET" else endpoint
        try:
            html = _mops_request(endpoint, params=attempt_params, method=method, timeout_seconds=timeout_seconds)
            text = _strip_tags(html)
            blocked = _is_blocked_by_source_text(text)
            variants.append({
                "strategy": strategy,
                "url": final_url,
                "status": "blocked_by_source" if blocked else "fetched",
                "html_length": len(html),
                "text_length": len(text),
                "score": -100 if blocked else _html_score(html, company.name) + (50 if "重大訊息" in text else 0),
                "has_table": "<table" in html.casefold(),
                "anchor_count": len(ANCHOR_RE.findall(html)),
                "contains_company_name": company.name in text,
                "contains_material_event_keywords": "重大訊息" in text or "公告" in text,
                "contains_no_data_phrase": any(no_data in text for no_data in ("查無資料", "無符合條件", "無資料")),
                "blocked_by_source": blocked,
                "text_preview": text[:LIVE_DEBUG_LIMIT],
                "html": html,
            })
        except Exception as exc:  # pragma: no cover - live MOPS availability is external
            variants.append({
                "strategy": strategy,
                "url": final_url,
                "status": "error",
                "error": str(exc),
                "html_length": 0,
                "text_length": 0,
                "score": 0,
            })
    return variants


def fetch_material_event_html(
    ticker: str,
    *,
    year: int | None = None,
    timeout_seconds: float = 10.0,
) -> str:
    variants = fetch_material_event_html_variants(ticker, year=year, timeout_seconds=timeout_seconds)
    best = _best_html_variant(variants)
    if best is None:
        raise RuntimeError("MOPS 重大訊息 live fetch did not return usable HTML.")
    return str(best["html"])


def _event_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query.get("seq_no") or query.get("spoke_date"):
        return _stable_hash("mops_detail", parsed.path, query.get("co_id"), query.get("spoke_date"), query.get("spoke_time"), query.get("seq_no"))
    return None


def _row_looks_like_material_event(row: dict[str, Any], company_name: str, ticker: str) -> bool:
    text = str(row.get("row_text") or "")
    if any(header in text for header in ("公司代號", "公司名稱", "主旨", "序號")) and "重大訊息" not in text:
        return False
    if ticker in text or (company_name and company_name in text):
        return True
    return any(keyword in text for keyword in ("重大訊息", "公告", "董事會", "取得", "處分", "背書保證"))


def _material_title_from_cells(cells: list[str], company_name: str, ticker: str) -> str:
    candidates = [
        cell
        for cell in cells
        if cell
        and ticker not in cell
        and company_name not in cell
        and not DATE_RE.fullmatch(cell)
        and not TIME_RE.fullmatch(cell)
        and cell not in {"詳細資料", "查詢", "公告", "重大訊息"}
    ]
    if not candidates:
        return f"{company_name} 重大訊息"
    return max(candidates, key=len)[:180]


def parse_material_event_detail_html(html: str, *, max_chars: int = 1800) -> str | None:
    text = _strip_tags(html)
    if not text:
        return None
    markers = ("主旨", "符合條款", "事實發生日", "說明")
    if any(marker in text for marker in markers):
        return text[:max_chars]
    return text[:max_chars] if len(text) >= 40 else None


def fetch_material_event_detail_text(
    detail_url: str,
    *,
    timeout_seconds: float = 10.0,
    max_chars: int = 1800,
) -> tuple[str | None, str | None]:
    try:
        html = _mops_request(detail_url, timeout_seconds=timeout_seconds)
    except Exception as exc:  # pragma: no cover - live MOPS availability is external
        return None, str(exc)
    return parse_material_event_detail_html(html, max_chars=max_chars), None


def _claims_for_material_event(
    *,
    category: MaterialEventCategory,
    title: str,
    raw_text: str | None,
    related_metrics: list[str],
    source_url: str,
    risk_related: bool,
) -> list[OfficialDisclosureClaim]:
    if not risk_related:
        return []
    claim_type: OfficialClaimType = "other"
    if category in {"capacity_or_capex", "inventory_or_demand", "revenue_or_orders"}:
        claim_type = category
    if category == "financial_outlook":
        claim_type = "outlook"
    if category == "financing_or_debt":
        claim_type = "cash_flow_or_financing"
    return [
        OfficialDisclosureClaim(
            claim_type=claim_type,
            text=_preview_text(raw_text or title, limit=260),
            related_metrics=related_metrics,
            evidence_source=source_url,
            confidence=0.72,
            limitations=["重大訊息分類使用既有保守關鍵字分類器；不改變 deterministic 財報規則結果。"],
        )
    ]


def parse_material_event_list_html(
    ticker: str,
    html: str,
    *,
    source_url: str | None = None,
    max_items: int = 5,
    fetch_details: bool = False,
) -> list[MaterialEventRecord]:
    company = _require_company(ticker)
    source = source_url or material_event_query_url(company.ticker)
    records: list[MaterialEventRecord] = []
    for row in _extract_table_rows(html):
        if not _row_looks_like_material_event(row, company.name, company.ticker):
            continue
        cells = list(row["cells"])
        row_text = str(row["row_text"])
        links = _extract_links(str(row.get("row_html") or ""), source)
        detail_url = next((url for url, label in links if "t05st01" in url or "detail" in label.casefold() or "詳細" in label), links[0][0] if links else None)
        title = _material_title_from_cells(cells, company.name, company.ticker)
        detail_text = None
        detail_error = None
        if fetch_details and detail_url:
            detail_text, detail_error = fetch_material_event_detail_text(detail_url)
        official_text = detail_text or row_text
        category, related_metrics, risk_related = classify_material_event(title, official_text)
        event_date = _extract_first_date(row_text)
        event_time = _extract_first_time(row_text)
        record = MaterialEventRecord(
            event_id=_event_id_from_url(detail_url or "") or _stable_hash("material_event", company.ticker, event_date, event_time, _canonical_url(detail_url or source), title),
            ticker=company.ticker,
            company_name=company.name,
            subindustry=company.subindustry,
            event_date=event_date,
            event_time=event_time,
            title=title,
            category=category,
            source_name="mops",
            source_url=source,
            detail_url=detail_url,
            status="available",
            raw_text=_preview_text(official_text, limit=1800),
            related_metrics=related_metrics,
            risk_related=risk_related,
            summary=("已解析 MOPS 重大訊息清單" + ("與公告明細。" if detail_text else "。")),
            disclosure_claims=_claims_for_material_event(
                category=category,
                title=title,
                raw_text=official_text,
                related_metrics=related_metrics,
                source_url=detail_url or source,
                risk_related=risk_related,
            ),
            limitations=(
                ["MOPS 明細頁抓取失敗；已保存清單列文字與 detail_url。", detail_error]
                if detail_error
                else ["重大訊息為近期官方揭露，只作為 recent official context，不改變年度財報規則判斷。"]
            ),
            retrieved_at=datetime.now(timezone.utc),
        )
        records.append(record)
        if len(records) >= max_items:
            break
    return records


def build_material_event_metadata(
    ticker: str,
    *,
    year: int | None = None,
    title: str | None = None,
    raw_text: str | None = None,
    fetch_live: bool = False,
    html: str | None = None,
    fetch_details: bool = False,
    max_items: int = 5,
) -> list[MaterialEventRecord]:
    company = _require_company(ticker)
    source_url = material_event_query_url(company.ticker, year=year)
    if html is not None:
        parsed = parse_material_event_list_html(company.ticker, html, source_url=source_url, max_items=max_items, fetch_details=fetch_details)
        return parsed or _metadata_only_material_event_record(company.ticker, year=year, title=title, raw_text=raw_text)
    if fetch_live:
        try:
            twse_records = build_twse_material_event_metadata(company.ticker, max_items=max_items)
            if year is not None:
                twse_records = [record for record in twse_records if (record.event_date or "").startswith(str(year))]
            if twse_records:
                return twse_records
        except Exception:
            pass
        try:
            variants = fetch_material_event_html_variants(company.ticker, year=year)
            best = _best_html_variant(variants)
            if best is None:
                errors = [str(variant.get("error")) for variant in variants if variant.get("status") == "error"]
                blocked = [variant for variant in variants if variant.get("status") == "blocked_by_source"]
                if blocked and len(blocked) == len(variants):
                    return _metadata_only_material_event_record(
                        company.ticker,
                        year=year,
                        title=title,
                        raw_text=raw_text,
                        status="blocked_by_source",
                        extra_limitations=["MOPS live fetch 被來源安全機制阻擋；保留 persisted previous evidence 或 metadata 查詢入口。"],
                    )
                if errors and len(errors) == len(variants):
                    return _metadata_only_material_event_record(
                        company.ticker,
                        year=year,
                        title=title,
                        raw_text=raw_text,
                        status="error",
                        extra_limitations=[f"MOPS live fetch 全部失敗：{errors[0]}"],
                    )
                return _metadata_only_material_event_record(
                    company.ticker,
                    year=year,
                    title=title,
                    raw_text=raw_text,
                    status="needs_manual_review",
                    extra_limitations=["MOPS live fetch 完成但沒有解析到重大訊息列；請檢查 MOPS HTML/table parser。"],
                )
            parsed = parse_material_event_list_html(company.ticker, str(best["html"]), source_url=source_url, max_items=max_items, fetch_details=fetch_details)
            if parsed:
                return parsed
            return _metadata_only_material_event_record(
                company.ticker,
                year=year,
                title=title,
                raw_text=raw_text,
                status="needs_manual_review",
                extra_limitations=["MOPS live fetch 完成但沒有解析到重大訊息列；請檢查 MOPS HTML/table parser。"],
            )
        except Exception as exc:  # pragma: no cover - live MOPS availability is external
            return _metadata_only_material_event_record(
                company.ticker,
                year=year,
                title=title,
                raw_text=raw_text,
                status="error",
                extra_limitations=[f"即時抓取 MOPS 重大訊息頁面失敗：{exc}"],
            )
    return _metadata_only_material_event_record(company.ticker, year=year, title=title, raw_text=raw_text)


def _metadata_only_material_event_record(
    ticker: str,
    *,
    year: int | None = None,
    title: str | None = None,
    raw_text: str | None = None,
    status: str = "metadata_only",
    extra_limitations: list[str] | None = None,
) -> MaterialEventRecord:
    company = _require_company(ticker)
    source_url = material_event_query_url(company.ticker, year=year)
    event_title = title or f"{company.name} 歷史重大訊息查詢入口"
    category, related_metrics, risk_related = classify_material_event(event_title, raw_text)
    claims = [
        OfficialDisclosureClaim(
            claim_type="capacity_or_capex" if category == "capacity_or_capex" else "other",
            text=event_title,
            related_metrics=related_metrics,
            evidence_source=source_url,
            confidence=0.68 if risk_related else 0.45,
            limitations=["重大訊息使用保守 keyword classification；後續可再以公告全文與 Gemini 摘要校驗。"],
        )
    ] if risk_related else []
    return [
        MaterialEventRecord(
            ticker=company.ticker,
            company_name=company.name,
            subindustry=company.subindustry,
            event_id=_stable_hash("material_event", company.ticker, year, _canonical_url(source_url), event_title),
            title=event_title,
            category=category,
            source_name="mops",
            source_url=source_url,
            status=status,  # type: ignore[arg-type]
            raw_text=raw_text,
            related_metrics=related_metrics,
            risk_related=risk_related,
            disclosure_claims=claims,
            limitations=[
                "系統已支援 MOPS 重大訊息列表／明細取得、事件分類、stable identity、去重與持久化。",
                "若 MOPS live source 受到來源安全機制限制，系統會保留來源狀態並優先提供既有 persisted evidence。",
                "事件分類使用保守關鍵字與子產業指標對應，後續需以 MOPS 實際公告文字與 Gemini 摘要校驗。",
                *(extra_limitations or []),
            ],
            retrieved_at=datetime.now(timezone.utc),
        )
    ]
