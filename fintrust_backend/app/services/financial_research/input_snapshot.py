"""Frozen, digest-identified research inputs and the evidence policy that admits them.

Inputs come only from ``ResearchBackend`` (local SQLite or the cloud mirror). For ``STRICT_AS_OF`` the facts are the
reader's own point-in-time view (``as_of`` = cutoff − 1 µs, i.e. exactly ``effective_available_at < cutoff_at``) and
every admitted row is re-checked; nothing is ever topped up from the full dataset. Retrieval / creation times are
reviewer metadata: they are never part of a snapshot or its digest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.services.financial_research.modes import AnalysisContext, AnalysisMode, AnalysisRequestError
from app.services.historical_audit.models import parse_timestamp

SNAPSHOT_VERSION = "input_snapshot_v1"
VERSION_POLICIES = ("latest_available", "earliest_available", "original_only")
OFFICIAL_HOSTS = ("mopsov.twse.com.tw", "mops.twse.com.tw", "doc.twse.com.tw", "www.twse.com.tw", "www.tpex.org.tw",
                  "emops.twse.com.tw")
# Approved Phase 2C reference artifacts (SHA-256 verified by scripts/research_baseline.py, not re-hashed per request).
APPROVED_BASELINE = {
    "commit": "506b64cb62f9a31353d87444f0080fa6540cf759",
    "full_package": {"file": "fintrust_1785_2011_2025_full.zip",
                     "sha256": "171e3da165a081e7b6acb4183d7c43f8663b3f3c87810fdc89f2ecdc8b4f82eb"},
    "strict_package": {"file": "fintrust_1785_2011_2025_asof_2026-10-10.zip",
                       "sha256": "9f281d50b47a489ebbc1bdae12802384ebbc2b8d33258c51c0cecd40ed0c9e8c"},
    "strict_audit_sidecar": {"file": "fintrust_1785_2011_2025_asof_2026-10-10.audit.json",
                             "sha256": "bf6ba1dee48c083304b60e598337c3163e0acf30bda97327922c17323874255d"},
    "status": "approved_reference_not_rehashed_at_request_time",
}
REVIEWER_ONLY_FIELDS = ("retrieved_at", "created_at", "recorded_at", "generated_at")


def safe_official_url(url: Any) -> str | None:
    """Only https/http links to the official regulators' hosts are exposed; anything else is withheld."""
    if not url:
        return None
    parsed = urlparse(str(url))
    if parsed.scheme not in {"https", "http"} or parsed.hostname not in OFFICIAL_HOSTS:
        return None
    return str(url)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def evidence_tiers(row: dict[str, Any]) -> dict[str, str]:
    """E2 (verified notice observation) and E3 (verified filing artifact) are independent dimensions."""
    observation = ("E2_verified_notice_observation" if row.get("availability_scope") == "observation"
                   else "no_verified_observation")
    artifact = ("E3_verified_filing_artifact" if row.get("availability_status") == "verified"
                else "E0_artifact_publication_unverified")
    return {"observation_evidence_status": observation, "artifact_evidence_status": artifact}


def public_fact(row: dict[str, Any], context: AnalysisContext) -> dict[str, Any]:
    """Research view of one canonical fact; strict views withhold artifacts not public at the cutoff."""
    artifact_public = True
    if context.mode is AnalysisMode.STRICT_AS_OF:
        artifact_available = parse_timestamp(row.get("available_at")) if row.get("availability_status") == "verified" else None
        artifact_public = artifact_available is not None and artifact_available < context.cutoff_at
    fact = {
        "fact_id": row["fact_id"], "ticker": row["ticker"], "period": row["period"], "fiscal_year": row["fiscal_year"],
        "metric_code": row["metric_code"], "value": row["value_text"], "unit": row["unit"],
        "statement_type": row["statement_type"], "statement_scope": row["statement_scope"],
        "accounting_framework": row.get("accounting_framework") or "unknown",
        "filing_version_id": row["filing_version_id"], "filing_version_type": row["filing_version_type"],
        "quality_status": row["quality_status"], "taxonomy_concept": row.get("taxonomy_concept"),
        "effective_available_at": row.get("effective_available_at"), "availability_scope": row.get("availability_scope"),
        "availability_basis": row.get("observation_basis") if row.get("availability_scope") == "observation"
        else row.get("availability_basis"),
        "availability_evidence_kind": row.get("availability_evidence_kind"),
        "availability_evidence_ref": row.get("availability_evidence_ref"),
        "availability_evidence_hash": row.get("availability_evidence_hash"),
        "availability_evidence_url": safe_official_url(row.get("availability_evidence_url")),
        "point_in_time_eligible": bool(row.get("point_in_time_eligible")),
        **evidence_tiers(row),
    }
    if artifact_public:
        fact.update(artifact_reference_status="included", artifact_sha256=row.get("content_hash"),
                    artifact_url=safe_official_url(row.get("source_url")))
    else:
        fact.update(artifact_reference_status="withheld_not_public_at_cutoff", artifact_sha256=None, artifact_url=None)
    return fact


@dataclass
class InputSnapshot:
    ticker: str
    context: AnalysisContext
    start_year: int
    end_year: int
    version_policy: str
    backend_name: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    comparisons: list[dict[str, Any]] = field(default_factory=list)
    disclosed_values: list[dict[str, Any]] = field(default_factory=list)
    # CURRENT_EVIDENCE_RECONCILIATION only: frozen by source_reconciliation.freeze_dependencies() so the
    # reconciliation never queries data that is not part of the digest. Never populated for PIT/model inputs.
    summary_observations: list[dict[str, Any]] = field(default_factory=list)
    pdf_evidence: list[dict[str, Any]] = field(default_factory=list)
    dependency_versions: dict[str, str] = field(default_factory=dict)
    reconciliation_frozen: bool = False

    def identity(self) -> dict[str, Any]:
        identity = {"snapshot_version": SNAPSHOT_VERSION, "ticker": self.ticker, **self.context.as_dict(),
                    "start_year": self.start_year, "end_year": self.end_year, "version_policy": self.version_policy}
        if self.reconciliation_frozen:
            identity["reconciliation_dependency_versions"] = dict(sorted(self.dependency_versions.items()))
        return identity

    def _payload(self) -> dict[str, Any]:
        payload = {"identity": self.identity(), "facts": self.facts, "comparisons": self.comparisons,
                   "disclosed_values": self.disclosed_values}
        if self.reconciliation_frozen:
            payload.update(summary_observations=self.summary_observations, pdf_evidence=self.pdf_evidence)
        return payload

    @property
    def input_digest(self) -> str:
        """SHA-256 of the canonical inputs (values, identities, evidence hashes, times) — no reviewer metadata.

        For reconciliation snapshots this includes the frozen summary rows and PDF evidence (content, identity and
        parser version), so any change to a reconciliation dependency changes the digest and the run id."""
        return digest(self._payload())

    def dependency_digests(self) -> dict[str, str]:
        return {name: digest(value) for name, value in self._payload().items() if name != "identity"}

    def describe(self) -> dict[str, Any]:
        description = {**self.identity(), "backend": self.backend_name, "input_digest": self.input_digest,
                       "fact_count": len(self.facts), "comparison_count": len(self.comparisons),
                       "disclosed_value_count": len(self.disclosed_values), "approved_baseline": APPROVED_BASELINE}
        if self.reconciliation_frozen:
            description.update(summary_observation_count=len(self.summary_observations),
                               pdf_evidence_count=len(self.pdf_evidence), dependency_digests=self.dependency_digests())
        return description


def _comparison_view(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in (
        "period", "fiscal_year", "statement_scope", "accounting_framework", "statement_type", "pre_label", "post_label",
        "canonical_metric", "sign_factor", "pre_restatement_value", "post_restatement_value", "difference",
        "published_unit", "disclosed_at", "availability_status", "announcement_key", "content_hash")} | {
        "source_url": safe_official_url(row.get("source_url"))}


def _disclosed_view(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in (
        "disclosure_kind", "period", "fiscal_year", "statement_scope", "accounting_framework", "source_label",
        "canonical_metric", "value", "published_unit", "normalized_value", "normalized_unit", "disclosed_at",
        "availability_status", "dated_facts", "announcement_key", "content_hash")} | {
        "source_url": safe_official_url(row.get("source_url"))}


def build_snapshot(backend: Any, ticker: str, context: AnalysisContext, *, start_year: int, end_year: int,
                   version_policy: str, include_comparisons: bool = True,
                   include_disclosed: bool = True) -> InputSnapshot:
    if version_policy not in VERSION_POLICIES:
        raise AnalysisRequestError("version_policy_invalid",
                                   f"version_policy must be one of {', '.join(VERSION_POLICIES)} (explicit, no default).")
    if start_year > end_year:
        raise AnalysisRequestError("year_range_invalid", "start_year must not exceed end_year.")
    strict = context.mode is AnalysisMode.STRICT_AS_OF
    rows = backend.list_facts(ticker, start_year, end_year, as_of=context.reader_as_of if strict else None,
                              version_policy=version_policy)
    if strict:
        for row in rows:  # defense in depth: the reader must already have enforced this
            available = parse_timestamp(row.get("effective_available_at"))
            if available is None or not available < context.cutoff_at:
                raise AssertionError(f"strict reader returned {row['fact_id']} not available before the cutoff")
    facts = [public_fact(row, context) for row in rows if row.get("source_kind") != "test_fixture"]
    snapshot = InputSnapshot(ticker=ticker, context=context, start_year=start_year, end_year=end_year,
                             version_policy=version_policy, backend_name=getattr(backend, "backend_name", "unknown"),
                             facts=facts)
    as_of = context.reader_as_of if strict else None
    if include_comparisons:
        snapshot.comparisons = [_comparison_view(r) for r in backend.list_restatement_comparisons(ticker, as_of=as_of)]
    if include_disclosed:
        snapshot.disclosed_values = [_disclosed_view(r) for r in backend.list_disclosed_values(ticker, as_of=as_of)
                                     if start_year <= r["fiscal_year"] <= end_year]
    return snapshot


def latest_time(values: list[str | None]) -> str | None:
    instants: list[datetime] = [t for t in (parse_timestamp(v) for v in values) if t is not None]
    return max(instants).isoformat() if instants else None
