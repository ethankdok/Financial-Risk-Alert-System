"""Identity checks for official conference documents: period, type, language.

A fiscal period is *validated* only from the document itself (its cover or
results agenda). Periods claimed by the source (MOPS summary text, URL path)
are compared against it, never used to relabel it: a disagreement quarantines
the document. Publication or conference dates are never turned into a fiscal
period. Document type comes from deterministic cover-text evidence; anything
not clearly established stays ``unknown``.

Company identity is data: nothing here branches on a ticker.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable

IDENTITY_VERSION = "conference-identity-v4"
DOCUMENT_TYPES = (
    "full_earnings_transcript",
    "earnings_presentation",
    "investor_presentation",
    "analyst_conference_presentation",
    "financial_results_release",
    "other_official_conference_document",
    "unknown",
)

_QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
_CJK_QUARTERS = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_Y = r"(20\d{2})"
_PERIOD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_Y + r"\s+(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter", re.I), "year_word"),
    (re.compile(r"(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+of)?\s*,?\s*" + _Y, re.I), "word_year"),
    (re.compile(_Y + r"\s*年\s*第\s*([一二三四1-4])\s*季"), "cjk"),
    (re.compile(r"(?<!\d)(1\d{2}|一[〇○零一二三四五六七八九]{2})\s*年\s*(?:度\s*)?第\s*([一二三四1-4])\s*季"), "roc"),
    (re.compile(r"(?<![0-9A-Za-z])([1-4])\s?Q\s?'?(\d{2}|20\d{2})(?![0-9])", re.I), "nq"),
    (re.compile(r"(?<![0-9A-Za-z])Q([1-4])\s*'?\s*(20\d{2}|\d{2})(?![0-9])", re.I), "qn"),
    (re.compile(_Y + r"\s*Q([1-4])(?![0-9])", re.I), "yq"),
]
# Outlook wording may follow after a short qualifier: 「營運展望」, "Company Guidance".
_OUTLOOK_AFTER = re.compile(
    r"^\s*(?:[一-鿿]{0,4}(?:展望|財測|指引)|(?:[A-Za-z]+\s+){0,2}(?:outlook|guidance|forecast))", re.I)
_OUTLOOK_BEFORE = re.compile(r"(?:outlook|guidance|forecast|展望|財測)\s*(?:for|of|：|:)?\s*$", re.I)
_URL_PERIOD = re.compile(r"(?<!\d)(20\d{2})[/_\-]?(?:Q|q)([1-4])(?!\d)|(?<![0-9A-Za-z])([1-4])Q(\d{2})(?![0-9])")

_TRANSCRIPT = re.compile(r"transcript|逐字稿|call\s+transcript", re.I)
# Transcript structure without the word "transcript": a call cover, prepared remarks and Q&A turns.
_CALL_COVER = re.compile(r"(?:earnings|conference)\s+call|電話會議", re.I)
_PREPARED = re.compile(r"prepared\s+remarks|致詞稿", re.I)
_QUESTION_TURN = re.compile(r"\bquestion\b|問題", re.I)
# Quarterly results wording; counts only together with a fiscal quarter on the cover.
_EARNINGS = re.compile(
    r"earnings\s+(?:conference|call|release|presentation)|quarterly\s+results|financial\s+(?:results|review)|"
    r"results\s+presentation|investor\s+conference|法人說明會|法說會|營運成果|業績發表|財務業績|營運報告|財務報告", re.I)
_RELEASE = re.compile(r"press\s+release|for\s+immediate\s+release|新聞稿|management\s+report|營運績效報告", re.I)
_INVESTOR = re.compile(
    r"investor\s+(?:presentation|day|update|meeting|conference)|corporate\s+presentation|company\s+(?:overview|introduction)|"
    r"公司簡介|投資人說明|公司介紹", re.I)
_INVITED = re.compile(r"受邀參加|應邀參加|invited|hosted\s+by", re.I)
_ANALYST = re.compile(r"conference|forum|summit|論壇|研討會", re.I)


_CJK_DIGITS = {"〇": "0", "○": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
               "六": "6", "七": "7", "八": "8", "九": "9"}


def _roc_year(value: str) -> int:
    """ROC year written with Arabic digits (114) or Chinese numerals (一一四)."""
    return int("".join(_CJK_DIGITS.get(char, char) for char in value))


# PDF font substitution sometimes yields the CJK stroke ㇐ (U+31D0) for 一.
_GLYPH_FIXES = str.maketrans({"㇐": "一"})


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").translate(_GLYPH_FIXES)).strip()


def _period(year: str | int, quarter: int | str) -> str:
    year_value = int(year)
    if year_value < 100:
        year_value += 2000
    return f"{year_value}Q{int(quarter)}"


def _match_period(kind: str, match: re.Match[str]) -> str:
    a, b = match.group(1), match.group(2)
    if kind == "year_word":
        return _period(a, _QUARTER_WORDS[b.lower()])
    if kind == "word_year":
        return _period(b, _QUARTER_WORDS[a.lower()])
    if kind == "cjk":
        return _period(a, _CJK_QUARTERS[b])
    if kind == "roc":
        return _period(_roc_year(a) + 1911, _CJK_QUARTERS[b])
    if kind == "nq":
        return _period(b, a)
    if kind in {"qn"}:
        return _period(b, a)
    return _period(a, b)  # yq


def find_periods(text: str) -> list[dict[str, Any]]:
    """All fiscal-quarter mentions with their role (reported vs outlook)."""
    collapsed = _collapse(text)
    found: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []
    for pattern, kind in _PERIOD_PATTERNS:
        for match in pattern.finditer(collapsed):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            taken.append(span)
            after = collapsed[span[1]:span[1] + 24]
            before = collapsed[max(0, span[0] - 16):span[0]]
            outlook = bool(_OUTLOOK_AFTER.search(after) or _OUTLOOK_BEFORE.search(before))
            found.append({"period": _match_period(kind, match), "text": match.group(0),
                          "role": "outlook" if outlook else "reported", "position": span[0]})
    return sorted(found, key=lambda item: item["position"])


def normalize_fiscal_period(text: str) -> str | None:
    """Single canonical YYYYQn for one explicit period expression, else None."""
    periods = {item["period"] for item in find_periods(text)}
    return periods.pop() if len(periods) == 1 else None


def _single_reported(text: str) -> tuple[str | None, list[str]]:
    reported = list(dict.fromkeys(item["period"] for item in find_periods(text) if item["role"] == "reported"))
    return (reported[0] if len(reported) == 1 else None), reported


def claimed_period_from_listing(summaries: Iterable[str]) -> tuple[str | None, list[str]]:
    """Reported period stated in MOPS summary text (outlook periods excluded)."""
    claims: list[str] = []
    for summary in summaries:
        _, reported = _single_reported(summary or "")
        claims.extend(reported)
    unique = list(dict.fromkeys(claims))
    return (unique[0] if len(unique) == 1 else None), unique


def period_from_url(url: str | None) -> str | None:
    match = _URL_PERIOD.search(url or "")
    if not match:
        return None
    if match.group(1):
        return _period(match.group(1), match.group(2))
    return _period(match.group(4), match.group(3))


def detect_document_period(pages: list[dict[str, Any]]) -> tuple[str | None, str, list[str]]:
    """Fiscal period printed on the cover (page 1), else the results agenda (page 2)."""
    for index, method in ((0, "pdf_cover_text"), (1, "pdf_second_page_reported_period")):
        if index >= len(pages):
            break
        single, reported = _single_reported(str(pages[index].get("text") or ""))
        if single:
            return single, method, reported
        if len(reported) > 1:
            return None, f"{method}_ambiguous", reported
    return None, "no_period_in_document", []


def classify_document_type(pages: list[dict[str, Any]], summaries: Iterable[str],
                           document_period: str | None) -> dict[str, Any]:
    cover = _collapse(" ".join(str(page.get("text") or "") for page in pages[:1]))
    agenda = _collapse(" ".join(str(page.get("text") or "") for page in pages[:2]))
    summary_text = _collapse(" ".join(summaries))
    if not agenda:
        return {"document_type": "unknown", "document_type_method": "no_extractable_text",
                "document_type_confidence": 0.0, "document_type_evidence": None}

    def result(kind: str, confidence: float, pattern: re.Pattern[str], text: str, source: str) -> dict[str, Any]:
        match = pattern.search(text)
        evidence = text[max(0, match.start() - 40):match.end() + 40] if match else None
        return {"document_type": kind, "document_type_method": f"deterministic_rules_v1:{source}",
                "document_type_confidence": confidence, "document_type_evidence": evidence}

    if _TRANSCRIPT.search(cover):
        return result("full_earnings_transcript", 0.9, _TRANSCRIPT, cover, "cover")
    full_text = " ".join(str(page.get("text") or "") for page in pages)
    questions = len(_QUESTION_TURN.findall(full_text))
    if _CALL_COVER.search(cover) and _PREPARED.search(full_text) and questions >= 3:
        found = result("full_earnings_transcript", 0.8, _CALL_COVER, cover, "call_structure")
        found["document_type_evidence"] = f"{found['document_type_evidence']} | prepared remarks + {questions} question turns"
        return found
    if _RELEASE.search(cover):
        return result("financial_results_release", 0.8, _RELEASE, cover, "cover")
    if _EARNINGS.search(cover) and document_period:
        return result("earnings_presentation", 0.9, _EARNINGS, cover, "cover")
    if _EARNINGS.search(agenda) and document_period:
        return result("earnings_presentation", 0.75, _EARNINGS, agenda, "cover_and_agenda")
    if _INVESTOR.search(cover):
        return result("investor_presentation", 0.75, _INVESTOR, cover, "cover")
    if _INVITED.search(summary_text) and _ANALYST.search(summary_text):
        return result("analyst_conference_presentation", 0.6, _INVITED, summary_text, "mops_summary")
    return {"document_type": "other_official_conference_document", "document_type_method": "deterministic_rules_v1:fallback",
            "document_type_confidence": 0.3, "document_type_evidence": cover[:120] or None}


def detect_language(declared: str | None, pages: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(str(page.get("text") or "") for page in pages)
    cjk = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    share = cjk / max(cjk + latin, 1)
    base = {"zh": "zh-Hant", "en": "en"}.get((declared or "").lower(), "unknown")
    if base == "en" and share > 0.25:
        language = "bilingual"
    elif base == "zh-Hant" and share < 0.05 and latin > 200:
        language = "en"
    else:
        language = base
    return {"language": language, "language_declared_by_source": declared,
            "language_cjk_share": round(share, 3)}


def assess_document_identity(
    pages: list[dict[str, Any]],
    *,
    language: str | None,
    summaries: Iterable[str] = (),
    source_pdf_url: str | None = None,
) -> dict[str, Any]:
    summaries = [s for s in summaries if s]
    document_period, method, document_candidates = detect_document_period(pages)
    listing_claim, listing_candidates = claimed_period_from_listing(summaries)
    url_claim = period_from_url(source_pdf_url)
    claims = {name: value for name, value in (("mops_listing_summary", listing_claim), ("source_url", url_claim)) if value}
    reasons: list[str] = []
    if document_period is None:
        status = "unconfirmed"
        reasons.append("fiscal_period_not_printed_in_document" if not document_candidates
                       else "multiple_reported_periods_in_document")
        confidence = 0.0
    elif any(value != document_period for value in claims.values()):
        status = "mismatch"
        reasons.append("source_period_disagrees_with_document")
        confidence = 0.0
    else:
        status = "verified"
        confidence = 0.95 if claims else 0.8
    identity = {
        "identity_version": IDENTITY_VERSION,
        "period": document_period if status == "verified" else None,
        "period_validation_status": status,
        "period_claimed_by_source": claims or None,
        "period_detected_in_document": document_period,
        "period_validation_method": "+".join([method, *claims]) if claims else method,
        "period_validation_confidence": confidence,
        "period_candidates": {"document": document_candidates, "mops_listing_summary": listing_candidates},
        "quarantined": status == "mismatch",
        "quarantine_reasons": reasons if status == "mismatch" else [],
        "identity_notes": reasons if status != "mismatch" else [],
    }
    identity.update(classify_document_type(pages, summaries, document_period))
    identity.update(detect_language(language, pages))
    return identity


def reconcile_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-document checks, fail-closed. Mutates and returns the list.

    * identical bytes (SHA-256) under different periods → quarantine all copies;
    * identical bytes under the same period → keep the first, mark the rest as duplicates;
    * different documents claiming the same ticker/period/type/language → quarantine all.
    """
    by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        if document.get("sha256"):
            by_sha[document["sha256"]].append(document)
    for group in by_sha.values():
        if len(group) < 2:
            continue
        periods = {doc.get("period_detected_in_document") for doc in group} | {
            value for doc in group for value in (doc.get("period_claimed_by_source") or {}).values()
        }
        periods.discard(None)
        if len(periods) > 1:
            for doc in group:
                _quarantine(doc, "sha256_reused_across_periods")
        else:
            for doc in group[1:]:
                doc["duplicate_of"] = group[0].get("filename")
    slots: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        if document.get("quarantined") or document.get("duplicate_of") or not document.get("period"):
            continue
        slots[(document.get("ticker"), document.get("period"), document.get("document_type"),
               document.get("language"))].append(document)
    for group in slots.values():
        if len({doc.get("sha256") for doc in group}) > 1:
            for doc in group:
                _quarantine(doc, "multiple_documents_same_period")
    return documents


def _quarantine(document: dict[str, Any], reason: str) -> None:
    document["quarantined"] = True
    reasons = document.setdefault("quarantine_reasons", [])
    if reason not in reasons:
        reasons.append(reason)
