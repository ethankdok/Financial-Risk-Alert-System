from __future__ import annotations

import json
import re
from urllib.parse import unquote
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from app.official_event_models import InvestorConferenceRecord
from app.services.company_registry import get_company
from app.services.official_event_sources import (
    CONFERENCE_TOPIC_METRICS,
    _dedupe,
    _stable_hash,
    infer_conference_topics,
    infer_official_claims,
    parse_investor_conference_html,
)

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
LIVE_DEBUG_LIMIT = 1200
BLOCKED_ERROR_MARKERS = ("403", "forbidden", "access denied")

# Official company IR pages are a stable official source for conference documents
# when exchange HTML pages are blocked or do not expose attachments directly.
OFFICIAL_IR_FALLBACK_URLS: dict[str, list[str]] = {
    "2330": [
        "https://investor.tsmc.com/english/quarterly-results/2026/q2",
        "https://investor.tsmc.com/english/quarterly-results/2026/q1",
        "https://investor.tsmc.com/chinese/quarterly-results/2026/q2",
        "https://investor.tsmc.com/chinese/quarterly-results/2026/q1",
        "https://investor.tsmc.com/english",
        "https://pr.tsmc.com/english/events/investor-meetings",
    ],
    "2303": [
        "https://www.umc.com/en/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q2",
        "https://www.umc.com/en/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q1",
        "https://www.umc.com/zh-TW/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q2",
        "https://www.umc.com/zh-TW/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q1",
        "https://www.umc.com/en/IR/ir_overview",
        "https://www.umc.com/zh-TW/IR/ir_overview",
        "https://www.umc.com/en/IR_Event/ir_events",
    ],
    "2454": [
        "https://www.mediatek.com/investor-relations/financial-information",
        "https://www.mediatek.com/investor-relations/ir-events",
        "https://www.mediatek.com/zh-tw/investor-relations/financial-information",
    ],
    "3711": [
        "https://ase.aseglobal.com/about-ase/financials/financial-data/",
        "https://www.aseglobal.com/",
    ],
}

# Search-index fallback is deliberately narrow and source-labelled. It is used only
# when official company sites return 403 to Codespaces but the official document
# landing page / document URL is already known from official search results. It
# keeps the demo progressing while preserving the blocked-source limitation.
SEEDED_OFFICIAL_IR_INDEX: dict[str, list[dict[str, str]]] = {
    "2330": [
        {
            "title": "TSMC 2026 Q2 Quarterly Results / Earnings Conference",
            "source_url": "https://investor.tsmc.com/english/quarterly-results/2026/q2",
            "document_url": "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-07/547d1696765e05ce3adb81c108ce1c8c1682b80c/TSMC%202Q26%20Transcript.pdf",
            "document_title": "TSMC 2Q26 Earnings Conference Transcript",
            "evidence_text": (
                "TSMC 2026 second quarter quarterly results page lists Presentation Material, "
                "Earnings Conference Transcript, Video Webcast Replay, net revenue guidance, "
                "gross margin guidance, operating margin guidance, capital expenditure discussion, "
                "capacity planning and outlook topics."
            ),
        },
        {
            "title": "TSMC 2026 Q1 Quarterly Results / Earnings Conference",
            "source_url": "https://investor.tsmc.com/english/quarterly-results/2026/q1",
            "document_url": "https://investor.tsmc.com/english/quarterly-results/2026/q1",
            "document_title": "TSMC 1Q26 Quarterly Results Page",
            "evidence_text": (
                "TSMC 2026 first quarter quarterly results page lists Presentation Material, "
                "Earnings Conference Transcript, quarterly guidance, revenue outlook, margin outlook, "
                "capital expenditure and capacity topics."
            ),
        },
    ],
    "2303": [
        {
            "title": "UMC 2026 Q2 Quarterly Results / Investor Conference",
            "source_url": "https://www.umc.com/en/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q2",
            "document_url": "https://www.umc.com/en/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q2",
            "document_title": "2Q 2026 Investors Conference Presentation Material",
            "evidence_text": (
                "UMC 2Q 2026 quarterly results page lists Financial Results, Investors Conference "
                "Presentation Material, Earnings Release and Investor Conference Call Details, "
                "teleconference webcast and replay, revenue, demand, capacity and outlook topics."
            ),
        },
        {
            "title": "UMC 2026 Q1 Quarterly Results / Investor Conference",
            "source_url": "https://www.umc.com/en/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q1",
            "document_url": "https://www.umc.com/en/Download/quarterly_results/QuarterlyResultsDetail/2026/2026Q1",
            "document_title": "1Q 2026 Investors Conference Presentation Material",
            "evidence_text": (
                "UMC 1Q 2026 quarterly results page lists Financial Results, Investors Conference "
                "Presentation Material, Earnings Release and Investor Conference Call Details, "
                "teleconference webcast and replay, revenue, demand and financial outlook topics."
            ),
        },
    ],
}

IR_KEYWORDS = (
    "investor conference",
    "earnings conference",
    "conference call",
    "presentation material",
    "presentation",
    "transcript",
    "webcast",
    "financial results",
    "quarterly results",
    "quarterly_results",
    "guidance",
    "法人說明會",
    "法說會",
    "簡報",
    "逐字稿",
    "影音",
    "財務暨營運報告說明會",
)
MEDIATEK_QUARTERLY_DOC_RE = re.compile(
    r'<a\s+href="(?P<url>https://www\.mediatek\.com/hubfs/MediaTek%20Assets/Pdfs/Quarterly%20Earnings%20Release/'
    r'(?P<year>\d{4})/Quarterly%20Earnings%20Release-(?P=year)Q(?P<quarter>[1-4])/(?P<file>[^"]+))"[^>]*>\s*</a>\s*<span>(?P<label>[^<]+)</span>',
    re.IGNORECASE,
)
MEDIATEK_INVITATION_DATE_RE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<day>\d{1,2})\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _strip_tags(value: str) -> str:
    return SPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", value))).strip()


def fetch_official_ir_html(url: str, *, timeout_seconds: float = 12.0) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "FinTrustAlert-MIS-Project/0.1 (+https://github.com/UnaLu027/fintrust-alert)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - official public IR page
        raw = response.read()
    for encoding in ("utf-8", "big5", "cp950"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _score_official_ir_html(html: str, company_name: str) -> int:
    text = _strip_tags(html)
    lowered = f"{text} {html}".casefold()
    score = min(len(text), 2000) // 50
    if company_name and company_name.casefold() in lowered:
        score += 30
    score += sum(25 for keyword in IR_KEYWORDS if keyword.casefold() in lowered)
    if any(ext in lowered for ext in (".pdf", "ppt", "download", "presentation", "transcript", "quarterly_results")):
        score += 35
    return score


def _summarize_ir_variant(*, url: str, html: str | None = None, error: str | None = None, company_name: str = "") -> dict[str, Any]:
    text = _strip_tags(html or "")
    lowered = text.casefold()
    return {
        "url": url,
        "status": "error" if error else "fetched",
        "error": error,
        "html_length": len(html or ""),
        "text_length": len(text),
        "score": _score_official_ir_html(html or "", company_name) if html else 0,
        "contains_company_name": bool(company_name and company_name.casefold() in lowered),
        "contains_ir_keywords": any(keyword.casefold() in lowered for keyword in IR_KEYWORDS),
        "text_preview": text[:LIVE_DEBUG_LIMIT],
    }


def _best_variant(variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    fetched = [variant for variant in variants if variant.get("status") == "fetched" and variant.get("html")]
    if not fetched:
        return None
    return max(fetched, key=lambda item: int(item.get("score") or 0))


def _all_variants_blocked(variants: list[dict[str, Any]]) -> bool:
    if not variants:
        return False
    errors = [str(variant.get("error") or "").casefold() for variant in variants if variant.get("status") == "error"]
    return len(errors) == len(variants) and any(
        any(marker in error for marker in BLOCKED_ERROR_MARKERS) for error in errors
    )


def _mediatek_conference_date_from_docs(docs: list[dict[str, str]]) -> str | None:
    for item in docs:
        haystack = unquote(f"{item.get('url', '')} {item.get('label', '')} {item.get('file', '')}")
        match = MEDIATEK_INVITATION_DATE_RE.search(haystack)
        if not match:
            continue
        month = MONTHS[match.group("month").casefold()]
        return f"{int(match.group('year')):04d}-{month:02d}-{int(match.group('day')):02d}"
    return None


def _preferred_mediatek_document(docs: list[dict[str, str]]) -> dict[str, str] | None:
    preferred = ("Transcript", "Presentation", "Earnings call invitation", "Press Release", "Financial Statements")
    for label in preferred:
        for item in docs:
            if item.get("label") == label:
                return item
    return docs[0] if docs else None


def parse_mediatek_quarterly_earnings_html(
    html: str,
    *,
    max_items: int = 3,
    source_url: str = "https://www.mediatek.com/investor-relations/financial-information",
) -> list[InvestorConferenceRecord]:
    company = get_company("2454")
    if company is None:
        raise ValueError("Unsupported company for MediaTek official IR parser: 2454")
    grouped: dict[tuple[int, int], list[dict[str, str]]] = {}
    for match in MEDIATEK_QUARTERLY_DOC_RE.finditer(html):
        year = int(match.group("year"))
        quarter = int(match.group("quarter"))
        grouped.setdefault((year, quarter), []).append(
            {
                "url": match.group("url"),
                "label": _strip_tags(match.group("label")),
                "file": match.group("file"),
            }
        )

    records: list[InvestorConferenceRecord] = []
    for (year, quarter), docs in sorted(grouped.items(), reverse=True):
        if not any((item.get("label") or "").casefold() in {"earnings call invitation", "presentation", "transcript"} for item in docs):
            continue
        preferred = _preferred_mediatek_document(docs)
        if preferred is None:
            continue
        labels = [item["label"] for item in docs]
        evidence_text = (
            f"MediaTek {year} Q{quarter} quarterly earnings release page lists "
            f"{', '.join(labels)} for the investor conference, including official presentation/transcript materials where available. "
            "The company IR source is used as official recent conference evidence with revenue, financial results, operating report and outlook context."
        )
        topics = infer_conference_topics(evidence_text, company.subindustry)
        claims = infer_official_claims(evidence_text, source_url=source_url)
        records.append(
            InvestorConferenceRecord(
                event_id=_stable_hash("investor_conference", "company_official_ir", company.ticker, year, quarter, preferred["url"]),
                ticker=company.ticker,
                company_name=company.name,
                subindustry=company.subindustry,
                fiscal_year=year,
                quarter=quarter,
                conference_date=_mediatek_conference_date_from_docs(docs),
                title=f"MediaTek {year} Q{quarter} Results - Investors Conference",
                source_name="company_official_ir",
                source_url=source_url,
                document_url=preferred["url"],
                status="available",
                document_extract_status="document_link_found",
                document_title=preferred["label"],
                document_text_preview=evidence_text[:800],
                document_text_length=len(evidence_text),
                source_evidence=_dedupe([*labels, *(item["url"] for item in docs), *topics]),
                extracted_topics=topics[:max_items],
                related_metrics=CONFERENCE_TOPIC_METRICS.get(company.subindustry, []),
                disclosure_claims=claims,
                summary="已從 MediaTek 官方 IR quarterly earnings release 頁面取得 investor conference 文件連結與官方文字脈絡。",
                limitations=[
                    "此筆資料來自 company_official_ir，不標示為 MOPS；MOPS 可用時仍作為額外官方來源。",
                    "頁面 parser 保留 presentation/transcript/press release/financial statements URL；PDF 文字抽取由既有 document extraction service 處理。",
                ],
                retrieved_at=datetime.now(timezone.utc),
            )
        )
        if len(records) >= max_items:
            break
    return records


def _seeded_official_records(
    ticker: str,
    *,
    max_items: int,
    blocked_reason: str,
) -> list[InvestorConferenceRecord]:
    company = get_company(ticker)
    if company is None:
        raise ValueError(f"Unsupported company for official IR fallback: {ticker}")
    records: list[InvestorConferenceRecord] = []
    for item in SEEDED_OFFICIAL_IR_INDEX.get(company.ticker, [])[:max_items]:
        text = item["evidence_text"]
        topics = infer_conference_topics(text, company.subindustry)
        claims = infer_official_claims(text, source_url=item["source_url"])
        records.append(
            InvestorConferenceRecord(
                ticker=company.ticker,
                company_name=company.name,
                subindustry=company.subindustry,
                title=item["title"],
                source_name="company_official_ir",
                source_url=item["source_url"],
                document_url=item.get("document_url"),
                status="available",
                document_extract_status="document_link_found" if item.get("document_url") else "html_preview",
                document_title=item.get("document_title"),
                document_text_preview=text[:800],
                document_text_length=len(text),
                extracted_topics=topics[:max_items],
                related_metrics=CONFERENCE_TOPIC_METRICS.get(company.subindustry, []),
                disclosure_claims=claims,
                source_evidence=[item["document_title"], *topics, text[:160]],
                summary=(
                    "官方公司 IR 網站在 Codespaces 直抓回 403；因此暫使用已知官方 IR 搜尋索引與官方 URL 作為可展示證據，"
                    "並保留 blocked-source limitation。"
                ),
                limitations=[
                    blocked_reason,
                    "此為 search-index fallback：保留官方頁面 / 文件 URL 與摘要，不代表已成功下載 PDF 全文。",
                    "下一步需在非封鎖環境、人工上傳文件，或以授權代理服務補做 PDF / transcript 全文抽取。",
                ],
            )
        )
    return records


def _preview_record_from_ir_page(
    *,
    ticker: str,
    source_url: str,
    html: str,
    max_items: int,
) -> InvestorConferenceRecord:
    company = get_company(ticker)
    if company is None:
        raise ValueError(f"Unsupported company for official IR fallback: {ticker}")
    text = _strip_tags(html)
    topics = infer_conference_topics(text, company.subindustry)
    claims = infer_official_claims(text, source_url=source_url)
    if not claims and any(keyword.casefold() in text.casefold() for keyword in IR_KEYWORDS):
        # Keep this as a broad official-IR claim so Gemini/rules cannot overstate it.
        claims = infer_official_claims("營收 展望 presentation conference", source_url=source_url)
    return InvestorConferenceRecord(
        ticker=company.ticker,
        company_name=company.name,
        subindustry=company.subindustry,
        title=f"{company.name} 公司官方 IR 法說會／Investor Conference 頁面",
        source_name="company_official_ir",
        source_url=source_url,
        status="available",
        document_extract_status="html_preview",
        document_text_preview=text[:800] if text else None,
        document_text_length=len(text) if text else None,
        extracted_topics=topics[:max_items],
        related_metrics=CONFERENCE_TOPIC_METRICS.get(company.subindustry, []),
        disclosure_claims=claims,
        source_evidence=topics[:max_items] + ([text[:160]] if text else []),
        summary="已從公司官方 IR 頁面取得 investor conference 相關官方文字 preview。",
        limitations=[
            "此筆資料來自 company_official_ir，不標示為 MOPS；MOPS 可用時仍作為額外官方來源。",
            "若頁面未直接提供文件連結，系統保留 HTML preview 與官方 IR URL。",
        ],
        retrieved_at=datetime.now(timezone.utc),
    )


def build_official_ir_fallback_metadata(
    ticker: str,
    *,
    max_items: int = 3,
    debug_dir: str | Path | None = None,
) -> tuple[list[InvestorConferenceRecord], dict[str, Any]]:
    company = get_company(ticker)
    if company is None:
        raise ValueError(f"Unsupported company for official IR fallback: {ticker}")
    urls = OFFICIAL_IR_FALLBACK_URLS.get(company.ticker, [])
    variants: list[dict[str, Any]] = []
    for url in urls:
        try:
            html = fetch_official_ir_html(url)
            variants.append({**_summarize_ir_variant(url=url, html=html, company_name=company.name), "html": html})
        except Exception as exc:  # pragma: no cover - external site availability varies
            variants.append(_summarize_ir_variant(url=url, error=str(exc), company_name=company.name))

    if debug_dir is not None:
        directory = Path(debug_dir)
        directory.mkdir(parents=True, exist_ok=True)
        sanitized = [{key: value for key, value in variant.items() if key != "html"} for variant in variants]
        (directory / f"official-ir-{company.ticker}-debug.json").write_text(
            json.dumps(
                {
                    "ticker": company.ticker,
                    "company_name": company.name,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "variants": sanitized,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    best = _best_variant(variants)
    blocked_by_source = _all_variants_blocked(variants)
    debug = {
        "ticker": company.ticker,
        "source_kind": "official_company_ir_fallback",
        "best_url": best.get("url") if best else None,
        "best_score": best.get("score") if best else 0,
        "variant_count": len(variants),
        "available": bool(best),
        "blocked_by_source": blocked_by_source,
        "fallback_mode": "live_html" if best else None,
    }
    if company.ticker == "2454":
        mediatek_records: list[InvestorConferenceRecord] = []
        for variant in variants:
            if variant.get("status") != "fetched" or not variant.get("html"):
                continue
            mediatek_records.extend(
                parse_mediatek_quarterly_earnings_html(
                    str(variant["html"]),
                    max_items=max_items,
                    source_url=str(variant["url"]),
                )
            )
        if mediatek_records:
            deduped: dict[str, InvestorConferenceRecord] = {}
            for record in mediatek_records:
                deduped.setdefault(record.event_id or record.document_url or record.title, record)
            debug.update(
                {
                    "available": True,
                    "fallback_mode": "company_official_ir_quarterly_earnings",
                    "best_url": next(iter(deduped.values())).source_url,
                    "best_score": max(int(variant.get("score") or 0) for variant in variants),
                    "record_count": len(deduped),
                }
            )
            return list(deduped.values())[:max_items], debug
    if best is None:
        if blocked_by_source and company.ticker in SEEDED_OFFICIAL_IR_INDEX:
            blocked_reason = "公司官方 IR 網站在 Codespaces live fetch 回傳 403 Forbidden；改用官方 search-index fallback。"
            seeded_records = _seeded_official_records(company.ticker, max_items=max_items, blocked_reason=blocked_reason)
            debug.update(
                {
                    "available": bool(seeded_records),
                    "fallback_mode": "seeded_official_search_index_after_403",
                    "best_url": seeded_records[0].source_url if seeded_records else None,
                    "best_score": 75 if seeded_records else 0,
                    "seeded_record_count": len(seeded_records),
                }
            )
            return seeded_records, debug
        return [], debug

    records = parse_investor_conference_html(
        company.ticker,
        str(best["html"]),
        source_url=str(best["url"]),
        max_items=max_items,
    )
    available_records = [record for record in records if record.status == "available"]
    if available_records:
        enriched: list[InvestorConferenceRecord] = []
        for record in available_records[:max_items]:
            limitations = list(record.limitations)
            limitations.append("此筆資料來自 company_official_ir；MOPS 可用時仍作為額外官方來源。")
            enriched.append(record.model_copy(update={"source_name": "company_official_ir", "limitations": limitations}))
        return enriched, debug

    text = _strip_tags(str(best["html"]))
    if any(keyword.casefold() in text.casefold() for keyword in IR_KEYWORDS):
        return [_preview_record_from_ir_page(ticker=company.ticker, source_url=str(best["url"]), html=str(best["html"]), max_items=max_items)], debug
    return [], debug
