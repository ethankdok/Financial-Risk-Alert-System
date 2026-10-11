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
from app.services.financial_research.literature_store import (
    DEFAULT_LITERATURE_DATABASE,
    LiteratureInputStore,
    LiteratureInputsUnavailable,
)
from app.services.financial_research.modes import AnalysisContext, AnalysisMode, AnalysisRequestError
from app.services.financial_research.pdf_evidence import EXTRACTOR_VERSION as PDF_EXTRACTOR_VERSION
from app.services.financial_research.pdf_evidence import ArchivePdfEvidenceProvider
from app.services.financial_research.restatement_bridge import build_bridge
from app.services.financial_research.source_reconciliation import freeze_dependencies, reconcile
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
LITERATURE_RESULT_KINDS = ("literature_models", "literature_comparison")
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
    literature_database: str = DEFAULT_LITERATURE_DATABASE

    @classmethod
    def from_env(cls) -> "ResearchConfig":
        return cls(database=os.getenv("HISTORICAL_RESEARCH_DATABASE_PATH", DEFAULT_DATABASE),
                   raw_root=os.getenv("HISTORICAL_RESEARCH_RAW_ROOT", DEFAULT_RAW_ROOT),
                   conference_root=os.getenv("HISTORICAL_RESEARCH_CONFERENCE_ROOT", DEFAULT_CONFERENCE_ROOT),
                   literature_database=os.getenv("LITERATURE_INPUTS_DATABASE_PATH", DEFAULT_LITERATURE_DATABASE))


class ResearchService:
    def __init__(self, config: ResearchConfig | None = None, *, backend: Any = None, repository: Any = None,
                 conference_repository: Any = "auto", pdf_provider: Any = "auto",
                 literature_store: Any = "auto") -> None:
        self.config = config or ResearchConfig.from_env()
        self._repository = repository
        self._backend = backend
        self._conference = conference_repository
        self._pdf = pdf_provider
        self._literature = literature_store

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

    @property
    def literature_store(self):
        """Read-only literature-input sidecar, or ``None`` when this deployment has none (``source_unavailable``)."""
        if self._literature == "auto":
            try:
                self._literature = LiteratureInputStore(self.config.literature_database, read_only=True,
                                                        protected=(self.config.database,))
            except LiteratureInputsUnavailable:
                self._literature = None
        return self._literature

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
                "literature_inputs_available": check(lambda: self.literature_store is not None),
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
        snapshot = build_snapshot(self.backend, ticker, context, start_year=start, end_year=end,
                                  version_policy=version_policy)
        if context.mode is AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
            # every reconciliation dependency (summaries, PDF evidence) is frozen into the digest up front
            freeze_dependencies(snapshot, self.backend, self.pdf_provider)
        return snapshot

    def bridge(self, ticker: str, context: AnalysisContext, *, scope: str = "all") -> dict[str, Any]:
        case = self.case(ticker)
        snapshot = self.snapshot(ticker, context, start_year=case.coverage_start_year, end_year=case.coverage_end_year)
        return build_bridge(snapshot, scope=scope)

    def features(self, ticker: str, context: AnalysisContext, *, start_year: int | None, end_year: int | None,
                 version_policy: str) -> tuple[Any, dict[str, Any]]:
        snapshot = self.snapshot(ticker, context, start_year=start_year, end_year=end_year, version_policy=version_policy)
        if context.mode is AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
            result = compute_features(snapshot)
            result["source_value_gap"] = reconcile(snapshot)
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
        return reconcile(snapshot)

    def text(self, ticker: str, context: AnalysisContext) -> dict[str, Any]:
        case = self.case(ticker)
        from app.services.historical_audit.conference_coverage import latest_coverage

        try:
            coverage = latest_coverage(self.repository, ticker)
        except Exception:  # noqa: BLE001 - coverage table absent in a mirror-only deployment
            coverage = []
        return text_readiness(self.conference_repository, ticker, context, start_year=case.coverage_start_year,
                              end_year=case.coverage_end_year, coverage_rows=coverage)

    # ------------------------------------------------------------ literature models (Beneish 1999 / Dechow 2011)
    def literature_registry(self) -> dict[str, Any]:
        from app.services.financial_research.literature_inputs import mapping_payload
        from app.services.financial_research.literature_method_registry import registry_payload

        return {**registry_payload(), "input_mapping": mapping_payload(),
                "inputs_available": self.literature_store is not None}

    def literature_snapshot(self, ticker: str, context: AnalysisContext, *, start_year: int | None,
                            end_year: int | None, version_policy: str):
        from app.services.financial_research.literature_comparison import check_request, freeze_literature_inputs

        check_request(context, version_policy)
        start, end = self._years(ticker, start_year, end_year)
        snapshot = build_snapshot(self.backend, ticker, context, start_year=start, end_year=end,
                                  version_policy="latest_available" if version_policy != "original_only"
                                  else "original_only", include_comparisons=False, include_disclosed=False)
        snapshot.version_policy = version_policy
        versions = self.backend.list_filing_versions(ticker, start - 2, end)
        return freeze_literature_inputs(snapshot, versions, self.literature_store)

    def literature_coverage(self, ticker: str, context: AnalysisContext, *, version_policy: str,
                            start_year: int | None = None, end_year: int | None = None) -> dict[str, Any]:
        from app.services.financial_research.literature_comparison import coverage_matrix

        snapshot = self.literature_snapshot(ticker, context, start_year=start_year, end_year=end_year,
                                            version_policy=version_policy)
        store = self.literature_store
        diagnostics = store.list_diagnostics(ticker) if store is not None else []
        return coverage_matrix(snapshot, [{k: v for k, v in d.items() if k != "source_url"}
                                          | {"source_url": safe_official_url(d.get("source_url"))} for d in diagnostics])

    def literature_compute(self, ticker: str, context: AnalysisContext, *, model_ids: list[str],
                           start_year: int | None, end_year: int | None, version_policy: str) -> dict[str, Any]:
        from app.services.financial_research.literature_comparison import compute_models

        snapshot = self.literature_snapshot(ticker, context, start_year=start_year, end_year=end_year,
                                            version_policy=version_policy)
        return compute_models(snapshot, model_ids)

    def literature_compare(self, ticker: str, context: AnalysisContext, *, start_year: int | None,
                           end_year: int | None, version_policy: str) -> dict[str, Any]:
        from app.services.financial_research.literature_comparison import compare, compute_models
        from app.services.financial_research.literature_method_registry import BENEISH_MODEL_ID, DECHOW_MODEL_ID

        snapshot = self.literature_snapshot(ticker, context, start_year=start_year, end_year=end_year,
                                            version_policy=version_policy)
        computed = compute_models(snapshot, [BENEISH_MODEL_ID, DECHOW_MODEL_ID])
        return {**compare(computed), "models": computed}

    def literature_run(self, result_kind: str, ticker: str, context: AnalysisContext, *, start_year: int | None,
                       end_year: int | None, version_policy: str, parameters: dict[str, Any]):
        from app.services.financial_research import literature_comparison as lcmp
        from app.services.financial_research.literature_extraction import EXTRACTOR_VERSION
        from app.services.financial_research.literature_inputs import MAPPING_VERSION, PANEL_VERSION
        from app.services.financial_research.literature_method_registry import (
            BENEISH_MODEL_ID,
            DECHOW_MODEL_ID,
            REGISTRY_VERSION,
        )

        snapshot = self.literature_snapshot(ticker, context, start_year=start_year, end_year=end_year,
                                            version_policy=version_policy)
        if result_kind == "literature_comparison":
            model_ids = [BENEISH_MODEL_ID, DECHOW_MODEL_ID]
            computed = lcmp.compute_models(snapshot, model_ids)
            output = {**lcmp.compare(computed), "models": computed}
        else:
            model_ids = sorted(set(parameters.get("model_ids") or []))
            output = lcmp.compute_models(snapshot, model_ids)
        method_ids = [*model_ids, lcmp.METHOD_VERSION, REGISTRY_VERSION, MAPPING_VERSION, PANEL_VERSION,
                      EXTRACTOR_VERSION]
        return snapshot, output, method_ids, {"model_ids": model_ids, "statement_scope": "consolidated"}

    # ------------------------------------------------------------ runs
    def build_run(self, result_kind: str, ticker: str, context: AnalysisContext, *, start_year: int | None = None,
                  end_year: int | None = None, version_policy: str = "latest_available", scope: str = "all",
                  supersedes_run_id: str | None = None, git_commit: str | None = None,
                  parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compute one result kind and wrap it as an immutable, digest-identified run (not yet persisted)."""
        return self._build(result_kind, ticker, context, start_year=start_year, end_year=end_year,
                           version_policy=version_policy, scope=scope, supersedes_run_id=supersedes_run_id,
                           git_commit=git_commit, parameters=parameters)[1]

    def _build(self, result_kind: str, ticker: str, context: AnalysisContext, *, start_year: int | None,
               end_year: int | None, version_policy: str, scope: str, supersedes_run_id: str | None,
               git_commit: str | None, parameters: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
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
                method_ids += [source_reconciliation.METHOD_VERSION, PDF_EXTRACTOR_VERSION]
            parameters = {"statement_scope": "consolidated"}
        elif result_kind == "restatement_bridge":
            case = self.case(ticker)
            snapshot = self.snapshot(ticker, context, start_year=case.coverage_start_year, end_year=case.coverage_end_year)
            output = build_bridge(snapshot, scope=scope)
            method_ids, parameters = [restatement_bridge.METHOD_VERSION], {"scope": scope}
        elif result_kind == "source_reconciliation":
            snapshot = self.snapshot(ticker, context, start_year=start_year, end_year=end_year,
                                     version_policy=version_policy)
            output = reconcile(snapshot)
            method_ids, parameters = [source_reconciliation.METHOD_VERSION, PDF_EXTRACTOR_VERSION], {}
        elif result_kind in LITERATURE_RESULT_KINDS:
            snapshot, output, method_ids, parameters = self.literature_run(
                result_kind, ticker, context, start_year=start_year, end_year=end_year,
                version_policy=version_policy, parameters=parameters or {})
        else:
            raise AnalysisRequestError("result_kind_invalid", f"unknown result kind {result_kind}")
        return snapshot, build_run(result_kind=result_kind, method_version="+".join(method_ids), method_ids=method_ids,
                                   approval_status=APPROVAL_STATUS, snapshot=snapshot.describe(), parameters=parameters,
                                   output=output, supersedes_run_id=supersedes_run_id, git_commit=git_commit)

    def verify_run(self, stored: dict[str, Any]) -> dict[str, Any]:
        """Recompute a persisted run from its recorded snapshot identity and compare digests (read-only).

        Distinguishes (finding F06):

        - ``reproducible``: same method version, same input digest, same output digest;
        - ``method_version_changed``: the run was produced by a method version this build no longer implements
          (``legacy_method_not_reproducible``); ``source_inputs_unchanged`` then states whether the archived base
          inputs (facts, restatement comparisons, disclosed values) are still byte-identical, so a method upgrade is
          never reported as a change of the approved historical data;
        - ``inputs_changed_since_run``: same method version, different input digest (a genuine source change);
        - ``output_differs_for_same_input``: same method and inputs, different output (determinism failure).

        Stored runs are never rewritten; a method upgrade produces a new run id.
        """
        from app.services.financial_research.modes import build_context

        snapshot = stored["snapshot"]
        context = build_context(snapshot["analysis_mode"], snapshot.get("cutoff_at"))
        rebuilt_snapshot, rebuilt = self._build(
            stored["result_kind"], stored["ticker"], context, start_year=snapshot["start_year"],
            end_year=snapshot["end_year"], version_policy=snapshot["version_policy"],
            scope=stored["parameters"].get("scope", "all"), supersedes_run_id=stored.get("supersedes_run_id"),
            git_commit=None, parameters=stored.get("parameters"))
        same_method = rebuilt["method_version"] == stored["method_version"]
        same_input = rebuilt["input_digest"] == stored["input_digest"]
        same_output = rebuilt["output_digest"] == stored["output_digest"]
        result = {"run_id": stored["run_id"], "recomputed_run_id": rebuilt["run_id"],
                  "stored_method_version": stored["method_version"], "current_method_version": rebuilt["method_version"],
                  "method_version_matches": same_method,
                  "input_digest_matches": same_input, "output_digest_matches": same_output,
                  "stored_input_digest": stored["input_digest"], "current_input_digest": rebuilt["input_digest"]}
        if not same_method:
            base = getattr(rebuilt_snapshot, "base_input_digest", None)
            unchanged = stored["input_digest"] in (rebuilt["input_digest"], base()) if base else None
            result.update(status="method_version_changed", legacy_method_not_reproducible=True,
                          source_inputs_unchanged=unchanged,
                          note=("The stored run was produced by a retired method version; it stays append-only and "
                                "auditable. Recomputing it requires the legacy method, which this build does not "
                                "implement. A current-method run has a new run id."))
        elif not same_input:
            result.update(status="inputs_changed_since_run", legacy_method_not_reproducible=False,
                          source_inputs_unchanged=False)
        elif not same_output:
            result.update(status="output_differs_for_same_input", legacy_method_not_reproducible=False,
                          source_inputs_unchanged=True)
        else:
            result.update(status="reproducible", legacy_method_not_reproducible=False, source_inputs_unchanged=True)
        return result
