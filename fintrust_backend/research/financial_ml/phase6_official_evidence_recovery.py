"""Phase6: archive official case evidence and prepare original-filing recovery.

A judicial ruling MAY provide retrospective outcome evidence; it does NOT prove
when information first became known or that the model had original filings.
No issuer-year outcome (0 or 1) is automatically admitted.
Official HTTP retrieval is explicit opt-in, bounded and idempotent.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .phase1_case_registry import validate

ROOT_SEED = Path(__file__).with_name("phase1_case_sources_seed.json")
MAX_BYTES = 12_000_000
OFFICIAL_HOSTS = frozenset({"judgment.judicial.gov.tw", "www.sfipc.org.tw"})
FINAL_HOLDOUT = "1785"
CASE_NAME_ALIASES = {
 "3027": ("盛達電業","盛達公司"),
 "8299": ("群聯電子","群聯公司"),
 "6452": ("康友公司","康友-KY","康友製藥"),
}
REVIEW_COLUMNS = (
    "case_id", "ticker", "company", "fiscal_year", "event_evidence_status",
    "official_sources_total", "official_sources_archived",
    "official_sources_text_company_confirmed", "legal_status",
    "original_filing_before_correction_archived",
    "original_filing_sha256", "original_filing_publication_at",
    "first_public_disclosure_verified_at", "later_judgment_document_date",
    "outcome_label", "outcome_label_research_approved",
    "eligible_historical_asof_training", "evidence_review_notes",
)
SOURCE_COLUMNS = (
    "case_id", "ticker", "source_id", "kind", "url",
    "source_document_date", "collection_status",
    "raw_sha256", "raw_file", "bytes", "fetched_at_utc",
    "company_name_visible_in_document", "filing_version_proven",
    "original_publication_time_proven", "legal_finality_proven",
    "label_admitted", "error_category"
)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.fragments.append(data)


def safe_url(url):
    parts = urlparse(url)
    if parts.scheme != "https" or parts.hostname not in OFFICIAL_HOSTS:
        raise ValueError("non_official_source_url")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("official_source_url_userinfo_or_port")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url, *, timeout=18):
    safe_url(url)
    opener = build_opener(SafeRedirect())
    req = Request(url, headers={
        "User-Agent": "FinancialMLAcademicEvidenceAudit/1.0 (offline-source-vintage-research)",
        "Accept": "text/html,application/xhtml+xml,text/plain"
    })
    with opener.open(req, timeout=timeout) as response:
        safe_url(response.geturl())
        if response.status != 200:
            raise ValueError("http_non_200")
        length=response.headers.get("Content-Length")
        if length and int(length)>MAX_BYTES:
            raise ValueError("source_exceeds_size_cap")
        body=response.read(MAX_BYTES+1)
        if not 500<=len(body)<=MAX_BYTES:
            raise ValueError("source_undersize_or_oversize")
        content_type=response.headers.get("Content-Type","").lower()
        if not any(kind in content_type for kind in ("text/html","text/plain","application/xhtml+xml")):
            raise ValueError("unexpected_official_content_type")
        return body, response.geturl(), content_type


def visible_document(raw):
    """Decode official pages with UTF-8 or traditional Big5/CP950; preserve bytes."""
    charset_match = re.search(rb"charset\s*=\s*['\"]?([A-Za-z0-9_-]+)",raw[:8192],re.I)
    declared = charset_match.group(1).decode("ascii") if charset_match else None
    candidates = ([declared] if declared else [])+["utf-8-sig","utf-8","cp950","big5"]
    for encoding in candidates:
        try:
            html=raw.decode(encoding,"strict")
        except (UnicodeError,LookupError):
            continue
        parser=PageText()
        parser.feed(html)
        body=" ".join(parser.fragments) if parser.fragments else html
        return unicodedata.normalize("NFKC",re.sub(r"\s+"," ",body)).strip()
    return ""


def company_mentioned(text, case):
    """Document identities use explicit aliases, not only the stock display name."""
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    alternatives = CASE_NAME_ALIASES.get(str(case["ticker"]), (case["company"],))
    return any(re.sub(r"\s+", "", unicodedata.normalize("NFKC",name)) in normalized
               for name in alternatives)


def archive_official(case,source,folder,*,retrieve=False,fetcher=http_get):
    """Fail closed; never replace an existing official-looking archive."""
    source_id=source["source_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",source_id):
        raise ValueError("unsafe_source_id")
    if source["kind"]!="SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE":
        safe_url(source["url"])
    path=Path(folder)/case["case_id"]
    dest=path/(source_id+".html")
    receipt=path/(source_id+".json")
    state={
        "case_id":case["case_id"],"ticker":case["ticker"],
        "source_id":source_id,"kind":source["kind"],
        "url":source["url"],"source_document_date":source["source_document_date"],
        "collection_status":"NOT_YET_ARCHIVED",
        "raw_sha256":"","raw_file":"","bytes":0,"fetched_at_utc":"",
        "company_name_visible_in_document":"false",
        "filing_version_proven":"false","original_publication_time_proven":"false",
        "legal_finality_proven":"false","label_admitted":"false",
        "error_category":""
    }
    if source["kind"]=="SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE":
        return {**state,"collection_status":"SECONDARY_EXCLUDED"}
    if dest.is_symlink() or receipt.is_symlink():
        raise ValueError("symlink_source_archive_forbidden")
    if receipt.exists() or dest.exists():
        if not dest.is_file() or not receipt.is_file():
            return {**state,"collection_status":"BROKEN_PRIOR_ARCHIVE_REQUIRES_REVIEW"}
        raw=dest.read_bytes()
        meta=json.loads(receipt.read_text(encoding="utf-8"))
        digest=hashlib.sha256(raw).hexdigest()
        if (meta.get("sha256")!=digest or meta.get("url")!=source["url"] or
                meta.get("source_id")!=source_id):
            return {**state,"collection_status":"ARCHIVE_TAMPER_OR_IDENTITY_CONFLICT"}
        state.update(collection_status="CACHED_BYTE_ARCHIVE_NEEDS_MANUAL_REVIEW",
                     raw_sha256=digest,raw_file=str(dest),bytes=len(raw),
                     fetched_at_utc=meta.get("fetched_at_utc",""))
        state["company_name_visible_in_document"]=str(
            company_mentioned(visible_document(raw),case)
        ).lower()
        return state
    if not retrieve:
        return state
    try:
        body,final_url,content_type=fetcher(source["url"])
        safe_url(final_url)
        if final_url!=source["url"]:
            # Court print URLs should be stable; redirects are recorded for
            # manual review instead of uncritically accepting site navigation.
            raise ValueError("unexpected_official_redirect")
        readable=visible_document(body)
        # Reject generic anti-bot/login/result-not-found pages masquerading as proof.
        present=company_mentioned(readable,case)
        if not present:
            return {**state,"collection_status":"DOCUMENT_IDENTITY_UNVERIFIED_NOT_SAVED",
                    "error_category":"company_name_absent_from_visible_text"}
        checksum=hashlib.sha256(body).hexdigest()
        fetched=datetime.now(timezone.utc).isoformat()
        path.mkdir(parents=True,exist_ok=True)
        if dest.exists() or receipt.exists():
            raise ValueError("concurrent_archive_race_forbidden")
        metadata={
            "schema":"phase6_official_source_receipt_v1",
            "source_id":source_id,"case_id":case["case_id"],
            "url":source["url"],"final_url":final_url,
            "content_type":content_type,"fetched_at_utc":fetched,
            "sha256":checksum,"bytes":len(body),
            "method":"HTTPS_RETRIEVED_BUT_DOCUMENT_FACTS_UNREVIEWED",
            "source_publication_at":None,
            "first_case_disclosure_at":None,
            "period_specific_label_approved":False
        }
        dest.write_bytes(body)
        receipt.write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
        state.update(collection_status="HTTPS_ARCHIVED_WITH_SHA_NEEDS_FACT_REVIEW",
                     raw_sha256=checksum,raw_file=str(dest),bytes=len(body),
                     fetched_at_utc=fetched,company_name_visible_in_document="true")
        return state
    except (OSError,ValueError,TimeoutError) as exc:
        return {**state,"collection_status":"RETRIEVAL_FAILED_NO_LABEL",
                "error_category":type(exc).__name__+":"+str(exc)[:90]}


def write_csv(path,columns,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(seed_file,output,*,retrieve=False,pace_seconds=2.0,fetcher=http_get):
    if not 0<=pace_seconds<=60:
        raise ValueError("invalid_official_fetch_interval")
    seed_path=Path(seed_file)
    seed=json.loads(seed_path.read_text(encoding="utf-8"))
    cases=validate(seed)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    states=[]
    reviews=[]
    for case in cases:
        evidence=[]
        for source in case["sources"]:
            state=archive_official(case,source,output/"official_case_bytes",
                                   retrieve=retrieve,fetcher=fetcher)
            states.append(state)
            evidence.append(state)
            if retrieve and state["collection_status"] in (
                    "HTTPS_ARCHIVED_WITH_SHA_NEEDS_FACT_REVIEW",):
                if pace_seconds:
                    time.sleep(pace_seconds)
        primary=[s for s in evidence
                 if s["collection_status"]!="SECONDARY_EXCLUDED"]
        archived=[s for s in primary if s["raw_sha256"]]
        all_archived=bool(primary) and len(archived)==len(primary)
        seen=sum(s["company_name_visible_in_document"]=="true" for s in archived)
        for year in case["affected_fiscal_years"]:
            reviews.append({
                "case_id":case["case_id"],"ticker":case["ticker"],
                "company":case["company"],"fiscal_year":year,
                "event_evidence_status":(
                    "OFFICIAL_DOCUMENTS_ARCHIVED_PENDING_PERIOD_AND_CASE_OUTCOME_REVIEW"
                    if all_archived else "OFFICIAL_DOCUMENT_ARCHIVE_INCOMPLETE"),
                "official_sources_total":len(primary),
                "official_sources_archived":len(archived),
                "official_sources_text_company_confirmed":seen,
                "legal_status":case["legal_status"],
                "original_filing_before_correction_archived":"false",
                "original_filing_sha256":"",
                "original_filing_publication_at":"",
                "first_public_disclosure_verified_at":"",
                "later_judgment_document_date":case["legal_evidence_document_date"],
                "outcome_label":"UNKNOWN",
                "outcome_label_research_approved":"false",
                "eligible_historical_asof_training":"false",
                "evidence_review_notes":(
                    "Archive original MOPS financial statement first submitted; "
                    "locate earliest market disclosure and revised financial reports; "
                    "read exact court findings and annex period; record source "
                    "SHA and verified filing publication timestamp."
                )
            })
    write_csv(output/"official_case_source_register.csv",SOURCE_COLUMNS,states)
    write_csv(output/"taiwan_misstatement_review_queue.csv",REVIEW_COLUMNS,reviews)
    status_counts={}
    for entry in states:
        status_counts[entry["collection_status"]]=(
            status_counts.get(entry["collection_status"],0)+1)
    report={
        "status":"PHASE6_OFFICIAL_CASE_EVIDENCE_ARCHIVE_AND_ORIGINAL_FILING_REVIEW_GATE",
        "candidate_case_count":len(cases),
        "case_year_review_rows":len(reviews),
        "official_source_urls_expected":sum(
            s["kind"]!="SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE"
            for c in cases for s in c["sources"]),
        "source_collection_statuses":dict(sorted(status_counts.items())),
        "per_source_diagnostics":[{"ticker":r["ticker"],"source_id":r["source_id"],
          "collection_status":r["collection_status"],
          "error_category":r.get("error_category","")} for r in states],
        "official_source_bytes_archived":sum(bool(s["raw_sha256"]) for s in states),
        "original_pre_restatement_filing_count_verified":0,
        "earliest_public_revelation_times_verified":0,
        "case_year_positive_labels_approved":0,
        "reviewed_negative_labels_approved":0,
        "eligible_supervised_training_rows":0,
        "photocopy_or_pdf_versions_claimed_original":0,
        "holdout_1785_untouched":True,
        "foreign_and_synthetic_data_auto_admitted":False,
        "network_enabled":retrieve,"production_db_writes":0,
        "seed_sha256":hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        "requirements_for_actual_positive_and_ex_ante_use":[
            "Verify exact affected fiscal quarters in archived judicial/official source paragraphs",
            "Find and archive original MOPS statement PDF/iXBRL as originally published, with SHA",
            "Archive earliest public notice/discovery plus its timestamp independently",
            "Separate later court findings from labels known on each historical training date",
            "Conduct independent method owner review; never auto promote to 1 or 0",
            "Keep 1785 original pre-2016 source and outcome inaccessible for development"
        ],
        "warning":"HTTPS file retrieval and company-text presence are NOT enough to "
                  "approve any company-period outcome label or reconstruct first "
                  "available original filing and publication time."
    }
    (output/"phase6_evidence_readiness.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description="Official Taiwan evidence retrieval, immutable SHA, no automatic labels")
    parser.add_argument("--seed-file",default=str(ROOT_SEED))
    parser.add_argument("--output",required=True)
    parser.add_argument("--retrieve-official",action="store_true")
    parser.add_argument("--pace-seconds",type=float,default=2.0)
    opt=parser.parse_args(argv)
    print(json.dumps(run(opt.seed_file,opt.output,
                         retrieve=opt.retrieve_official,
                         pace_seconds=opt.pace_seconds),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
