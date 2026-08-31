from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlencode
from urllib.request import Request, urlopen

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


def _extract_first_date(text: str) -> str | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    year = int(match.group("year"))
    if year < 1911:
        year += 1911
    return f"{year:04d}-{int(match.group('month')):02d}-{int(match.group('day')):02d}"


def _preview_text(text: str, *, limit: int = 800) -> str:
    return _strip_tags(text)[:limit]


def _current_roc_year() -> int:
    return datetime.now(timezone.utc).year - 1911


def _decode_response(raw: bytes) -> str:
    for encoding in ("utf-8", "big5", "cp950"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


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
        params["year"] = str(year)
    return f"{MOPS_BASE}/t05st01?{urlencode(params)}"


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


def _mops_request(url: str, *, params: dict[str, str] | None = None, method: str = "GET", timeout_seconds: float = 10.0) -> str:
    data = None
    target_url = url
    if method == "GET" and params:
        target_url = f"{url}?{urlencode(params)}"
    if method == "POST":
        data = urlencode(params or {}).encode("utf-8")
    request = Request(
        target_url,
        data=data,
        headers={
            "User-Agent": "FinTrustAlert-MIS-Project/0.1 (+https://github.com/UnaLu027/fintrust-alert)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": investor_conference_query_url(str((params or {}).get("co_id", ""))),
        },
        method=method,
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - official public disclosure page
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
    return {
        "strategy": strategy,
        "url": url,
        "status": "error" if error else "fetched",
        "error": error,
        "html_length": len(html or ""),
        "text_length": len(text),
        "score": _html_score(html or "", company_name) if html else 0,
        "has_table": "<table" in (html or "").casefold(),
        "anchor_count": len(ANCHOR_RE.findall(html or "")),
        "contains_company_name": bool(company_name and company_name in text),
        "contains_conference_keywords": any(keyword in text for keyword in ("法人說明會", "法說會", "簡報", "影音")),
        "contains_no_data_phrase": any(no_data in text for no_data in ("查無資料", "無符合條件", "無資料")),
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
        "Phase 4 已開始解析 MOPS 法說會 HTML/table row；PDF / 簡報全文解析與影音逐字稿仍待下一步接入。",
        "法說會內容屬管理層展望，僅能作為官方文字證據，仍需與年度財報指標交叉檢查。",
    ]
    if not links:
        limitations.append("本筆法說會列未偵測到附件連結；保留 row text preview 供 parser debug 與人工覆核。")
    return InvestorConferenceRecord(
        ticker=company.ticker,
        company_name=company.name,
        subindustry=company.subindustry,
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
        "Phase 4 目前支援 MOPS 法說會頁面 HTML preview、table row 與附件連結偵測；PDF / 簡報全文解析與影音逐字稿仍待下一步接入。",
        "法說會內容屬管理層展望，僅能作為官方文字證據，仍需與年度財報指標交叉檢查。",
    ]
    if not links:
        limitations.append("本次 HTML 未偵測到 PDF / 簡報 / 影音附件連結；保留 MOPS 查詢入口與 debug 檔供下一步調整 POST/table parser。")
    page_record = InvestorConferenceRecord(
        ticker=company.ticker,
        company_name=company.name,
        subindustry=company.subindustry,
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
        try:
            variants = fetch_investor_conference_html_variants(company.ticker)
            if debug_dir is not None:
                write_investor_conference_debug_files(company.ticker, variants, debug_dir)
            best = _best_html_variant(variants)
            if best is None:
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
            return [
                _metadata_only_conference_record(
                    company.ticker,
                    max_items=max_items,
                    extra_limitations=[f"即時抓取 MOPS 法說會頁面失敗：{exc}"],
                    status="error",
                )
            ]
    return [_metadata_only_conference_record(company.ticker, max_items=max_items)]


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
        "目前為 Phase 4 metadata MVP：先保存 MOPS 法說會查詢入口與子產業關聯指標，尚未解析 PDF 或影音逐字稿。",
        "正式 scraper 需依 MOPS 表單與各公司申報附件欄位補充文件 URL、日期與簡報文字。",
    ]
    if extra_limitations:
        limitations.extend(extra_limitations)
    return InvestorConferenceRecord(
        ticker=company.ticker,
        company_name=company.name,
        subindustry=company.subindustry,
        title=f"{company.name} 法人說明會資料查詢入口",
        source_url=url,
        status=status,  # type: ignore[arg-type]
        document_extract_status="metadata_only",
        extracted_topics=topics[:max_items],
        related_metrics=related_metrics,
        source_evidence=topics[:max_items],
        limitations=limitations,
    )


def classify_material_event(title: str, raw_text: str | None = None) -> tuple[MaterialEventCategory, list[str], bool]:
    text = f"{title} {raw_text or ''}".casefold()
    for category, keywords, metrics in MATERIAL_EVENT_KEYWORDS:
        if any(keyword.casefold() in text for keyword in keywords):
            return category, list(metrics), True
    return "other", [], False


def build_material_event_metadata(
    ticker: str,
    *,
    year: int | None = None,
    title: str | None = None,
    raw_text: str | None = None,
) -> list[MaterialEventRecord]:
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
            limitations=["重大訊息目前為 keyword classification MVP，後續需以公告全文與 Gemini 摘要校驗。"],
        )
    ] if risk_related else []
    return [
        MaterialEventRecord(
            ticker=company.ticker,
            company_name=company.name,
            subindustry=company.subindustry,
            title=event_title,
            category=category,
            source_url=source_url,
            status="metadata_only",
            raw_text=raw_text,
            related_metrics=related_metrics,
            risk_related=risk_related,
            disclosure_claims=claims,
            limitations=[
                "目前為 Phase 5 metadata MVP：先保存 MOPS 重大訊息查詢入口與事件分類規則，尚未批次解析歷史公告清單。",
                "事件分類使用保守關鍵字與子產業指標對應，後續需以 MOPS 實際公告文字與 Gemini 摘要校驗。",
            ],
        )
    ]
