"""SYNTHETIC test fixtures for the Integrity Workbench (never shown as a real company's result).

Fake repository / archive / bridge / claim service mirroring the read interfaces the workbench uses. The fake
repository records every method call so tests can prove the workbench only reads.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.services.analysis_repository import financial_fact_from_row
from app.services.integrity.service import IntegrityWorkbench

SYNTHETIC = "SYNTHETIC TEST FIXTURE"
READ_METHODS = {"list_facts", "get_latest_snapshot", "list_investor_conferences", "list_material_events",
                "get_fact", "list_metrics", "get_official_event_sync_status", "list_runs"}


def mops_url(ticker: str, year: int, report_id: str = "C", season: int = 4) -> str:
    return (f"https://mopsov.twse.com.tw/server-java/FileDownLoad?functionName=t164sb01&step=9&co_id={ticker}"
            f"&year={year - 1911}&season={season}&report_id={report_id}")


def fact(ticker: str, metric: str, period: str, value: Any, *, unit: str = "新台幣元", url: str | None = None,
         scope: str = "unknown", is_demo: bool = False, source_kind: str = "mops_xbrl",
         retrieved_at: str = "2026-09-15T03:27:22+00:00", analysis_type: str = "historical") -> dict[str, Any]:
    year = int(period[:4])
    return {"fact_id": f"{ticker}:{metric}:{period}:{value}", "ticker": ticker, "company_name": SYNTHETIC,
            "subindustry": "synthetic", "analysis_type": analysis_type, "period": period, "metric_code": metric,
            "value": value, "unit": unit, "source_kind": source_kind,
            "source_url": url if url is not None else mops_url(ticker, year), "taxonomy_concept": metric,
            "retrieved_at": retrieved_at, "statement_scope": scope, "filed_at": None, "is_demo": int(is_demo),
            "source_field": None}


def annual_rows(ticker: str, data: dict[str, dict[int, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    return [fact(ticker, metric, f"{year}FY", value, **kwargs) for metric, years in data.items()
            for year, value in years.items()]


BASE_DATA = {  # SYNTHETIC numbers: AR +50%, revenue +10% in 2025 → gap 40 pp
    "revenue": {2023: 1000.0, 2024: 1000.0, 2025: 1100.0},
    "accounts_receivable": {2023: 200.0, 2024: 200.0, 2025: 300.0},
    "net_income": {2023: 100.0, 2024: 120.0, 2025: 150.0},
    "operating_cash_flow": {2023: 130.0, 2024: 110.0, 2025: 90.0},
    "total_assets": {2023: 5000.0, 2024: 5200.0, 2025: 5600.0},
}


class FakeRepository:
    def __init__(self, rows: list[dict[str, Any]], *, snapshot: Any = None, events: list[Any] | None = None,
                 fail: bool = False) -> None:
        self.rows = rows
        self.snapshot = snapshot
        self.events = events or []
        self.fail = fail
        self.calls: list[str] = []

    def __getattr__(self, name: str):  # any non-read method is recorded and refused
        def refused(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"write or unexpected method called: {name}")
        return refused

    def list_facts(self, ticker: str, limit: int = 500, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append("list_facts")
        if self.fail:
            raise OSError("synthetic backend outage")
        return [copy.deepcopy(r) for r in self.rows if r["ticker"] == ticker][:limit]

    def get_fact(self, ticker: str, metric: str, period: str):
        self.calls.append("get_fact")
        rows = [r for r in self.rows if (r["ticker"], r["metric_code"], r["period"]) == (ticker, metric, period)]
        return financial_fact_from_row(rows[0]) if rows else None

    def list_metrics(self, ticker: str, limit: int = 1000, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append("list_metrics")
        return []

    def get_latest_snapshot(self, ticker: str):
        self.calls.append("get_latest_snapshot")
        if self.fail:
            raise OSError("synthetic backend outage")
        return self.snapshot if any(r["ticker"] == ticker for r in self.rows) else None

    def list_investor_conferences(self, ticker: str) -> list[Any]:
        self.calls.append("list_investor_conferences")
        return []

    def list_material_events(self, ticker: str) -> list[Any]:
        self.calls.append("list_material_events")
        return list(self.events)

    def get_official_event_sync_status(self, *args: Any, **kwargs: Any):
        self.calls.append("get_official_event_sync_status")
        return None


class FakeArchive:
    """Conference archive with one document and page texts (read interface of the PDF archive repository)."""

    def __init__(self, documents: dict[tuple[str, int, str], dict[str, Any]] | None = None) -> None:
        self.documents = documents or {}

    def document(self, ticker: str, year: int, filename: str):
        entry = self.documents.get((ticker, year, filename))
        return {"filename": filename, "sha256": entry["sha256"], "period_validation_status": "verified"} if entry else None

    def pages(self, ticker: str, year: int, filename: str):
        entry = self.documents.get((ticker, year, filename))
        return [{"page": number, "text": text} for number, text in (entry or {}).get("pages", {}).items()]

    def available_years(self, ticker: str) -> list[int]:
        return sorted({y for t, y, _ in self.documents if t == ticker}, reverse=True)

    def latest_manifest(self, ticker: str, year: int):
        return None


class FakeClaimResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return copy.deepcopy(self.payload)


class FakeClaimService:
    """Returns a scripted ClaimVerifyResponse-shaped payload and records the claims it received."""

    def __init__(self, verdict: str = "supported", *, metric: str = "revenue", period: str = "2024FY",
                 value_text: str = "1000", unit: str = "百萬", reason: str = "value_match") -> None:
        self.verdict, self.metric, self.period, self.value_text, self.unit, self.reason = (
            verdict, metric, period, value_text, unit, reason)
        self.received: list[str] = []

    def verify(self, request):
        self.received.append(request.claim)
        return FakeClaimResponse({
            "verdict": self.verdict, "reason_code": self.reason,
            "structured_claim": {"metric_or_topic": self.metric, "period": self.period, "value": float(self.value_text),
                                 "value_text": self.value_text, "unit": self.unit, "claim_type": "numeric_metric"},
            "evidence": [{"evidence_id": f"fact:x:{self.metric}:{self.period}", "relation": "supports", "decisive": True,
                          "source_type": "financial_fact", "source_title": "MOPS XBRL", "period": self.period,
                          "metric": self.metric, "value": "1e9", "unit": "新台幣元", "page": None, "document": None,
                          "document_sha256": None, "verification_status": "verified",
                          "source_reference": "javascript:alert(1)", "comparison": None}],
        })


class FakeBridge:
    def __init__(self, result: dict[str, Any] | None = None, *, configured: bool = True, error: bool = False) -> None:
        self.result = result
        self.conference_repository = object() if configured else None
        self.error = error

    def analyze(self, ticker: str, *args: Any):
        if self.error:
            raise RuntimeError("synthetic bridge failure")
        return copy.deepcopy(self.result)


def shift_result(ticker: str = "2303", **overrides: Any) -> dict[str, Any]:
    result = {
        "ticker": ticker, "company": SYNTHETIC, "period_1": "2025Q2", "period_2": "2025Q3",
        "document_type": "earnings_presentation", "language": "en", "analysis_status": "complete",
        "metrics": {"jsd": 0.123456, "cosine_similarity": 0.876543},
        "calibration": {"status": "unavailable", "reason": "no_matching_profile"},
        "drift_result": "尚無相符歷史校準，不判定漂移等級",
        "source_documents": [
            {"period": "2025Q2", "document": "a.pdf", "document_type": "earnings_presentation", "language": "en",
             "source_url": "https://mopsov.twse.com.tw/x", "source_page": None, "sha256": "a" * 64, "text_length": 9000},
            {"period": "2025Q3", "document": "b.pdf", "document_type": "earnings_presentation", "language": "en",
             "source_url": "https://evil.example/x", "source_page": None, "sha256": "b" * 64, "text_length": 9100}],
        "method": {"method_version": "earnings-en-full-pairwise-tfidf-v1", "calculator_module_sha256": "c" * 64},
        "limitations": [], "warning": "JSD warning",
    }
    result.update(overrides)
    return result


def registry_file(tmp: Path, statements: list[dict[str, Any]]) -> Path:
    path = tmp / "issuer_statements.json"
    path.write_text(json.dumps({"registry_version": "synthetic", "statements": statements}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def statement(ticker: str = "2303", **overrides: Any) -> dict[str, Any]:
    entry = {"statement_id": f"{ticker}-synthetic-revenue", "ticker": ticker, "archive_year": 2025,
             "document": "syn.pdf", "document_sha256": "d" * 64, "document_type": "earnings_presentation",
             "language": "en", "page": 3, "published_on": "2025-02-07", "published_on_basis": "synthetic",
             "statement_kind": "issuer_presentation_table_unaudited", "context_excerpt": "(In NT$ millions)",
             "excerpt": "Net Sales 1,000 900 11.1%", "normalized_claim": "SYNTHETIC 2024年營收1000百萬元",
             "normalization": "synthetic", "expected_parse": {"metric": "revenue", "period": "2024FY",
                                                              "value": "1000", "unit": "百萬"}}
    entry.update(overrides)
    return entry


def archive_for(entry: dict[str, Any], *, sha: str | None = None, page_text: str | None = None) -> FakeArchive:
    text = page_text if page_text is not None else f"{entry['context_excerpt']}\n{entry['excerpt']}\nother line"
    return FakeArchive({(entry["ticker"], entry["archive_year"], entry["document"]):
                        {"sha256": sha or entry["document_sha256"], "pages": {entry["page"]: text}}})


def workbench(rows: list[dict[str, Any]] | None = None, *, bridge: Any = None, archive: Any = None,
              claim_service: Any = None, registry: Path | None = None, literature_database: str | None = None,
              repository: FakeRepository | None = None, nfm_records: list[dict[str, Any]] | None = None
              ) -> IntegrityWorkbench:
    repo = repository or FakeRepository(rows if rows is not None else annual_rows("2303", BASE_DATA))
    wb = IntegrityWorkbench(repo, jsd_bridge=bridge, conference_repository=archive, claim_service=claim_service,
                            literature_database=literature_database, nfm_records=nfm_records)
    if registry is not None:
        wb.claims.registry_path = registry
    return wb
