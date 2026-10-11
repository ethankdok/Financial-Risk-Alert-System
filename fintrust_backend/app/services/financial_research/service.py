"""Research service facade: read-only wiring of the approved archive for the API, CLI and tests.

The approved historical SQLite is opened with ``mode=ro`` (``ReadOnlyHistoricalAuditRepository``): the research
layer cannot migrate, insert or update it. Derived results go only to the separate append-only result store.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.financial_research import RESEARCH_LAYER_VERSION
from app.services.financial_research.case_knowledge import knowledge
from app.services.financial_research.feature_registry import registry_payload
from app.services.financial_research.financial_features import compute_features
from app.services.financial_research.input_snapshot import APPROVED_BASELINE, build_snapshot, safe_official_url
from app.services.financial_research.literature_models import model_readiness
from app.services.financial_research.modes import AnalysisContext, AnalysisMode, AnalysisRequestError
from app.services.financial_research.pdf_evidence import ArchivePdfEvidenceProvider
from app.services.financial_research.restatement_bridge import build_bridge
from app.services.financial_research.source_reconciliation import reconcile
from app.services.financial_research.text_evidence_bridge import build_conference_repository, text_readiness
from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.case_registry import UnknownHistoricalCaseError, load_cases
from app.services.historical_audit.models import parse_timestamp
from app.services.historical_audit.repository import HistoricalAuditRepository, assert_isolated_database
from app.services.historical_audit.research_access import LocalResearchBackend

DEFAULT_DATABASE = "./data/historical_audit/historical_audit.sqlite3"
DEFAULT_RAW_ROOT = "./data/historical_audit/raw"
DEFAULT_CONFERENCE_ROOT = "./data/historical-conference-pdfs"
MAX_YEAR_SPAN = 15
EVIDENCE_TIERS = {
    "official_listing": "E1_official_listing_metadata",
    "verified_official_quote": "E2_verified_notice_quote",
    "verified_official": "E2_verified_official_document",
}


class ResearchDatasetUnavailable(RuntimeError):
    """The approved research dataset is not present in this deployment (maps to HTTP 503)."""


class ReadOnlyHistoricalAuditRepository(HistoricalAuditRepository):
    """Opens the approved archive read-only; never initializes or migrates."""

    def __init__(self, database_path: str) -> None:  # noqa: D107 - deliberately skips the migrating constructor
        assert_isolated_database(database_path)
        if not Path(database_path).is_file():
            raise ResearchDatasetUnavailable("historical research dataset is not available in this deployment")
        self.database_path = database_path

    def initialize(self) -> None:  # pragma: no cover - guarded
        raise PermissionError("read-only research repository")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(f"file:{Path(self.database_path).resolve().as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


@dataclass
class ResearchConfig:
    database: str = DEFAULT_DATABASE
    raw_root: str = DEFAULT_RAW_ROOT
    conference_root: str = DEFAULT_CONFERENCE_ROOT

    @classmethod
    def from_env(cls) -> "ResearchConfig":
        return cls(database=os.getenv("HISTORICAL_RESEARCH_DATABASE_PATH", DEFAULT_DATABASE),
                   raw_root=os.getenv("HISTORICAL_RESEARCH_RAW_ROOT", DEFAULT_RAW_ROOT),
                   conference_root=os.getenv("HISTORICAL_RESEARCH_CONFERENCE_ROOT", DEFAULT_CONFERENCE_ROOT))


class ResearchService:
    def __init__(self, config: ResearchConfig | None = None, *, backend: Any = None, repository: Any = None,
                 conference_repository: Any = "auto", pdf_provider: Any = "auto") -> None:
        self.config = config or ResearchConfig.from_env()
        self._repository = repository
        self._backend = backend
        self._conference = conference_repository
        self._pdf = pdf_provider

    # ------------------------------------------------------------ wiring
    @property
    def repository(self):
        if self._repository is None:
            self._repository = ReadOnlyHistoricalAuditRepository(self.config.database)
        return self._repository

    @property
    def backend(self):
        if self._backend is None:
            self._backend = LocalResearchBackend(self.repository)
        return self._backend

    @property
    def conference_repository(self):
        if self._conference == "auto":
            self._conference = build_conference_repository(self.config.conference_root)
        return self._conference

    @property
    def pdf_provider(self):
        if self._pdf == "auto":
            root = Path(self.config.raw_root)
            self._pdf = ArchivePdfEvidenceProvider(self.repository, RawEvidenceArchive(root)) if root.is_dir() else None
        return self._pdf

    def health(self) -> dict[str, Any]:
        def check(fn):
            try:
                return bool(fn())
            except Exception:  # noqa: BLE001 - readiness probe
                return False
        return {"research_layer_version": RESEARCH_LAYER_VERSION,
                "dataset_available": check(lambda: self.repository.is_initialized()),
                "conference_archive_available": check(lambda: self.conference_repository is not None),
                "pdf_evidence_available": check(lambda: self.pdf_provider is not None),
                "approved_baseline_commit": APPROVED_BASELINE["commit"]}

    # ------------------------------------------------------------ cases
    def case(self, ticker: str):
        cases = load_cases()
        if ticker not in cases:
            raise UnknownHistoricalCaseError(f"{ticker} is not a registered historical research case.")
        return cases[ticker]

    def cases(self) -> list[dict[str, Any]]:
        return [self._case_summary(case) for case in load_cases().values()]

    def _case_summary(self, case) -> dict[str, Any]:
        info = knowledge(case.ticker) or {}
        return {"ticker": case.ticker, "case_id": case.case_id, "company_name": case.company_name,
                "english_name": case.english_name, "market": case.market,
                "priority_event_period": {"start_year": case.default_start_year, "end_year": case.default_end_year},
                "research_coverage": {"start_year": case.coverage_start_year, "end_year": case.coverage_end_year},
                "production_universe": False, "case_type": "historical_audit_research_case",
                "supported_modes": [mode.value for mode in AnalysisMode],
                "strict_feasibility_note": info.get("strict_feasibility_note")}

    def case_overview(self, ticker: str) -> dict[str, Any]:
        case = self.case(ticker)
        start, end = case.coverage_start_year, case.coverage_end_year
        facts = self.backend.list_facts(ticker, start, end)
        pit = [f for f in facts if f["point_in_time_eligible"]]
        info = knowledge(ticker) or {}
        events_all = self.backend.list_publication_events(ticker)
        timeline: dict[str, dict[str, Any]] = {}
        for event in events_all:  # a listing row and its verified notice can share one event_key: prefer verified
            current = timeline.get(event["event_key"])
            if current is None or (current["verification_status"] == "official_listing"
                                   and event["verification_status"] != "official_listing"):
                timeline[event["event_key"]] = event
        events = []
        for event in info.get("key_events", []):
            row = timeline.get(event["event_key"])
            events.append({**event, "publication_at": row["publication_at"] if row else None,
                           "publication_precision": row["publication_precision"] if row else None,
                           "available_from": row["available_from"] if row else None,
                           "content_hash": row["content_hash"] if row else None,
                           "evidence_tier": EVIDENCE_TIERS.get(row["verification_status"]) if row else "not_in_archive",
                           "source_url": safe_official_url(row["source_url"]) if row else None})
        return {**self._case_summary(case),
                "coverage": {"canonical_facts": len(facts), "fiscal_years_with_facts": sorted({f["fiscal_year"] for f in facts}),
                             "point_in_time_eligible_facts": len(pit),
                             "restatement_comparisons": len(self.backend.list_restatement_comparisons(ticker)),
                             "disclosed_values": len(self.backend.list_disclosed_values(ticker)),
                             "publication_events": len(events_all), "distinct_event_keys": len(timeline),
                             "filing_versions": len(self.backend.list_filing_versions(ticker, start, end))},
                "key_events": events, "hypotheses": info.get("hypotheses", []),
                "hypothesis_source": info.get("hypothesis_source"),
                "external_references": info.get("external_references", []),
                "approved_baseline": APPROVED_BASELINE}

    def _years(self, ticker: str, start_year: int | None, end_year: int | None) -> tuple[int, int]:
        case = self.case(ticker)
        start = case.coverage_start_year if start_year is None else start_year
        end = case.coverage_end_year if end_year is None else end_year
        if not case.coverage_start_year <= start <= end <= case.coverage_end_year:
            raise AnalysisRequestError("year_range_invalid",
                                       f"years must lie within {case.coverage_start_year}–{case.coverage_end_year}.")
        if end - start + 1 > MAX_YEAR_SPAN:
            raise AnalysisRequestError("year_range_too_large", f"at most {MAX_YEAR_SPAN} fiscal years per request.")
        return start, end

    # ------------------------------------------------------------ timeline
    def timeline(self, ticker: str, context: AnalysisContext, *, evidence_tier: str | None = None,
                 limit: int = 200, offset: int = 0) -> dict[str, Any]:
        self.case(ticker)
        rows = []
        for event in self.backend.list_publication_events(ticker):
            available = parse_timestamp(event["available_from"])
            if not context.admits(available):
                continue
            tier = EVIDENCE_TIERS.get(event["verification_status"], "E0_unverified")
            if evidence_tier and not tier.startswith(evidence_tier):
                continue
            rows.append({"event_key": event["event_key"], "event_type": event["event_type"], "title": event["title"],
                         "publication_at": event["publication_at"], "publication_precision": event["publication_precision"],
                         "available_from": event["available_from"], "issuer": event["issuer"],
                         "affected_periods": [p for p in event["affected_periods"].split(",") if p],
                         "verification_status": event["verification_status"], "evidence_tier": tier,
                         "source_document_included": tier != "E1_official_listing_metadata",
                         "content_hash": event["content_hash"], "source_url": safe_official_url(event["source_url"])})
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["evidence_tier"]] = counts.get(row["evidence_tier"], 0) + 1
        return {**context.as_dict(), "ticker": ticker, "total": len(rows), "tier_counts": counts,
                "limit": limit, "offset": offset, "events": rows[offset:offset + limit],
                "tier_definitions": {
                    "E1_official_listing_metadata": "Official listing entry and its stated time; the detailed notice bytes are not archived.",
                    "E2_verified_notice_quote": "Archived official notice bytes; the quoted text and time were verified.",
                    "E2_verified_official_document": "Archived official regulator document (date precision)."}}

    # ------------------------------------------------------------ research
    def snapshot(self, ticker: str, context: AnalysisContext, *, start_year: int | None = None,
                 end_year: int | None = None, version_policy: str = "latest_available"):
        start, end = self._years(ticker, start_year, end_year)
        return build_snapshot(self.backend, ticker, context, start_year=start, end_year=end, version_policy=version_policy)

    def bridge(self, ticker: str, context: AnalysisContext, *, scope: str = "all") -> dict[str, Any]:
        case = self.case(ticker)
        snapshot = self.snapshot(ticker, context, start_year=case.coverage_start_year, end_year=case.coverage_end_year)
        return build_bridge(snapshot, scope=scope)

    def features(self, ticker: str, context: AnalysisContext, *, start_year: int | None, end_year: int | None,
                 version_policy: str) -> tuple[Any, dict[str, Any]]:
        snapshot = self.snapshot(ticker, context, start_year=start_year, end_year=end_year, version_policy=version_policy)
        if context.mode is AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
            result = compute_features(snapshot)
            result["source_value_gap"] = reconcile(snapshot, self.backend, pdf_provider=self.pdf_provider)
        else:
            result = compute_features(snapshot)
        result["literature_models"] = model_readiness(snapshot)
        return snapshot, result

    def feature_registry(self, ticker: str, context: AnalysisContext) -> dict[str, Any]:
        snapshot = self.snapshot(ticker, context)
        return {**registry_payload(), **context.as_dict(), "ticker": ticker,
                "literature_models": model_readiness(snapshot)}

    def discrepancies(self, ticker: str, context: AnalysisContext) -> dict[str, Any]:
        snapshot = self.snapshot(ticker, context)
        return reconcile(snapshot, self.backend, pdf_provider=self.pdf_provider)

    def text(self, ticker: str, context: AnalysisContext) -> dict[str, Any]:
        case = self.case(ticker)
        from app.services.historical_audit.conference_coverage import latest_coverage

        try:
            coverage = latest_coverage(self.repository, ticker)
        except Exception:  # noqa: BLE001 - coverage table absent in a mirror-only deployment
            coverage = []
        return text_readiness(self.conference_repository, ticker, context, start_year=case.coverage_start_year,
                              end_year=case.coverage_end_year, coverage_rows=coverage)

    # ------------------------------------------------------------ runs
    def build_run(self, result_kind: str, ticker: str, context: AnalysisContext, *, start_year: int | None = None,
                  end_year: int | None = None, version_policy: str = "latest_available", scope: str = "all",
                  supersedes_run_id: str | None = None, git_commit: str | None = None) -> dict[str, Any]:
        """Compute one result kind and wrap it as an immutable, digest-identified run (not yet persisted)."""
        from app.services.financial_research import restatement_bridge, source_reconciliation
        from app.services.financial_research.feature_registry import APPROVAL_STATUS, REGISTRY_VERSION
        from app.services.financial_research.financial_features import ENGINE_VERSION
        from app.services.financial_research.literature_models import GATE_VERSION
        from app.services.financial_research.result_store import build_run

        if result_kind == "financial_signals":
            snapshot, output = self.features(ticker, context, start_year=start_year, end_year=end_year,
                                             version_policy=version_policy)
            method_ids = [ENGINE_VERSION, REGISTRY_VERSION, GATE_VERSION]
            if context.mode is AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
                method_ids.append(source_reconciliation.METHOD_VERSION)
            parameters = {"statement_scope": "consolidated"}
        elif result_kind == "restatement_bridge":
            case = self.case(ticker)
            snapshot = self.snapshot(ticker, context, start_year=case.coverage_start_year, end_year=case.coverage_end_year)
            output = build_bridge(snapshot, scope=scope)
            method_ids, parameters = [restatement_bridge.METHOD_VERSION], {"scope": scope}
        elif result_kind == "source_reconciliation":
            snapshot = self.snapshot(ticker, context, start_year=start_year, end_year=end_year,
                                     version_policy=version_policy)
            output = reconcile(snapshot, self.backend, pdf_provider=self.pdf_provider)
            method_ids, parameters = [source_reconciliation.METHOD_VERSION], {}
        else:
            raise AnalysisRequestError("result_kind_invalid", f"unknown result kind {result_kind}")
        return build_run(result_kind=result_kind, method_version="+".join(method_ids), method_ids=method_ids,
                         approval_status=APPROVAL_STATUS, snapshot=snapshot.describe(), parameters=parameters,
                         output=output, supersedes_run_id=supersedes_run_id, git_commit=git_commit)
