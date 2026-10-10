"""Portable, deterministic research dataset package (ZIP) for one historical case.

Two explicit modes (package schema 1.2):

- ``retrospective``: everything currently recovered, including later
  restatements, later disclosures and current archival copies. Not suitable as
  input to a historical predictive backtest.
- ``strict_point_in_time`` (requires ``as_of``): only evidence verifiably public
  before the cutoff, in every dataset, raw file, contract and metadata field; see
  ``strict_package``. The build fails closed if any post-cutoff date remains.

The package needs no database, FinTrust code or cloud credentials. Given
unchanged inputs and the same ``generated_at`` the ZIP is byte-identical;
``content_digest`` is independent of ``generated_at``. A strict ZIP carries no
generation time at all (byte-identical for unchanged inputs); modern verification
metadata goes to the reviewer-only ``<package>.audit.json`` sidecar.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.case_registry import get_case
from app.services.historical_audit.conference_coverage import latest_coverage
from app.services.historical_audit.conference_package import build_conference_datasets
from app.services.historical_audit.evidence_export import (
    COMPARISON_FIELDS,
    COVERAGE_FIELDS,
    INVENTORY_FIELDS,
    SUMMARY_CONTRACT_VERSION,
    SUMMARY_FIELDS,
    TIMELINE_FIELDS,
    coverage_matrix,
    list_publication_timeline,
    list_restatement_comparisons,
    list_summary_observations,
    source_inventory,
)
from app.services.historical_audit.export import CONTRACT_VERSION, EXPORT_FIELDS, build_export_records
from app.services.historical_audit.models import TAIPEI, VersionPolicy, as_of_cutoff, iso, utc_now
from app.services.historical_audit.package_verify import CHECKSUMS, MANIFEST, PACKAGE_ROOT, _verify_files, safe_relative_path
from app.services.historical_audit.quality import eps_unit_investigation, quality_report, unmapped_concept_report
from app.services.historical_audit.repository import HistoricalAuditRepository
from app.services.historical_audit.strict_package import build_strict, leakage_check


PACKAGE_SCHEMA_VERSION = "1.2"
MODES = ("retrospective", "strict_point_in_time")
DOCS_ROOT = Path(__file__).resolve().parents[4] / "docs" / "data"
RETROSPECTIVE_CONTRACTS = (
    "HISTORICAL_FINANCIAL_FACTS_CONTRACT.md",
    "HISTORICAL_RESEARCH_PACKAGE_CONTRACT.md",
    "HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md",
    "HISTORICAL_PUBLICATION_TIMELINE.md",
)
# Case narrative documents describe later events, so strict packages ship only generic contracts.
STRICT_CONTRACTS = ("HISTORICAL_RESEARCH_PACKAGE_CONTRACT.md",)
CONFERENCE_CONTRACTS = ("JSD_INPUT_CONTRACT.md", "HISTORICAL_1785_CONFERENCE_COVERAGE.md")
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
VERSION_FIELDS = (
    "filing_version_id", "ticker", "period", "fiscal_year", "statement_scope", "statement_scope_evidence",
    "filing_version_type", "source_kind", "source_url", "content_hash", "content_length", "detected_format",
    "available_at", "availability_status", "availability_basis", "source_published_at", "document_dated_at",
    "retrieved_at", "validation_status", "quarantine_reason", "parser_version", "package_raw_path",
    "raw_evidence_included",
)
MISSING_FIELDS = ("fiscal_year", "evidence_kind", "status", "detail")
STRICT_FIELD_DEFINITIONS = """# Strict point-in-time field definitions

This package contains only evidence verifiably public before `manifest.parameters.as_of`
(a date means the end of that day, Asia/Taipei). Unknown availability is excluded.

- `data/financial_facts.*`: facts contract fields. `effective_available_at` is the earliest verified time:
  `filing_available_at` (the filing artifact itself) or `observation_available_at` (an official disclosure stating
  the identical value). With `artifact_reference_status = withheld_not_public_at_cutoff` the later filing artifact's
  identity is withheld; `availability_evidence_*` names the disclosure that dates the value.
- `data/filing_versions.csv`: only artifacts whose own availability is verified before the cutoff.
- `data/source_inventory.csv`: only single-publication official notices published before the cutoff.
- `data/restatement_comparisons.csv`: rows disclosed before the cutoff.
- Every timestamp is expressed in Asia/Taipei (`+08:00`). Filing, observation, disclosure, effective and event
  times are separate fields; none of them is a retrieval or generation time.
- `data/publication_timeline.csv`: events public before the cutoff (`available_from`).
- `data/historical_summaries.csv`: TPEx summary values whose report period ended before the cutoff and whose exact
  value was stated by a contemporaneous official disclosure (`pit_evidence_*`); `evidence_type =
  official_disclosed_observation`, the later workbook reference is withheld.
- Modern verification metadata (generation and retrieval times, archive-wide exclusion counts) is kept outside the
  package in a reviewer-only audit report bound to the package SHA-256; it is not research input.
- Documents whose public availability before the cutoff is not verified are not included.
"""


class ResearchPackageError(RuntimeError):
    pass


@dataclass
class PackageParameters:
    ticker: str
    start_year: int
    end_year: int
    as_of: str | None = None
    version_policy: VersionPolicy = "all"
    include_raw_evidence: bool = True
    include_conference: bool = False
    include_context_years: bool = False
    mode: str | None = None

    def resolved_mode(self) -> str:
        mode = self.mode or ("strict_point_in_time" if self.as_of else "retrospective")
        if mode not in MODES:
            raise ResearchPackageError(f"Unknown package mode {mode}")
        if mode == "strict_point_in_time" and not self.as_of:
            raise ResearchPackageError("strict_point_in_time packages require as_of")
        if mode == "retrospective" and self.as_of:
            raise ResearchPackageError("as_of filtering is only offered in strict_point_in_time mode")
        return mode


@dataclass
class _Builder:
    files: dict[str, bytes] = field(default_factory=dict)
    categories: dict[str, str] = field(default_factory=dict)

    def add(self, path: str, data: bytes, category: str) -> None:
        path = safe_relative_path(path)
        if path in self.files and self.files[path] != data:
            raise ResearchPackageError(f"Conflicting content for {path}")
        self.files[path] = data
        self.categories[path] = category


def _csv_bytes(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for row in rows:
        writer.writerow(["" if row.get(name) is None else
                         ("true" if row.get(name) is True else "false" if row.get(name) is False else row.get(name))
                         for name in fields])
    return buffer.getvalue().encode("utf-8")


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")


def _evidence_folder(category: str) -> str:
    if category in {"official_original_filing", "official_restated_filing", "official_filing_unknown_revision",
                    "official_filing_pdf"}:
        return "financial_filings"
    if category == "official_historical_summary":
        return "official_summaries"
    return "regulatory_disclosures"


class ResearchPackageBuilder:
    def __init__(self, repository: HistoricalAuditRepository, archive: RawEvidenceArchive,
                 *, conference_repository: Any | None = None, conference_root: Path | None = None) -> None:
        self.repository = repository
        self.archive = archive
        self.conference_repository = conference_repository
        self.conference_root = Path(conference_root) if conference_root else None

    def build(self, parameters: PackageParameters, output_zip: str | Path, *,
              generated_at: datetime | None = None, audit_path: str | Path | None = None) -> dict[str, Any]:
        mode = parameters.resolved_mode()
        strict = mode == "strict_point_in_time"
        case = self.repository.get_case(parameters.ticker) or get_case(parameters.ticker)
        builder = _Builder()
        audit: dict[str, Any] | None = None
        if strict:
            counts, completeness, extra, audit = self._strict(builder, parameters)
        else:
            counts, completeness, extra = self._retrospective(builder, parameters)
        builder.add("validation/verify_package.py", Path(__file__).with_name("package_verify.py").read_bytes(), "validation")
        readme = self._readme(case, parameters, mode, counts, completeness)
        builder.add("README.md", readme.encode("utf-8"), "readme")

        checksums = "".join(f"{hashlib.sha256(builder.files[p]).hexdigest()}  {p}\n" for p in sorted(builder.files)).encode("utf-8")
        content_digest = hashlib.sha256(checksums).hexdigest()
        manifest = {
            "package": PACKAGE_ROOT,
            "package_schema_version": PACKAGE_SCHEMA_VERSION,
            "mode": mode,
            "suitable_for_historical_backtest": mode == "strict_point_in_time",
            "cutoff_utc": iso(as_of_cutoff(parameters.as_of)) if strict else None,
            # Exclusive cutoff expressed in Asia/Taipei, the time zone of every model-facing timestamp (schema 1.2).
            "cutoff_taipei": as_of_cutoff(parameters.as_of).astimezone(TAIPEI).isoformat() if strict else None,
            "generator": "fintrust_backend/app/services/historical_audit/research_package.py",
            # Strict packages carry no modern timestamp; it lives in the reviewer-only audit report.
            "generated_at": None if strict else iso(generated_at or utc_now()),
            "parameters": {
                "ticker": parameters.ticker, "start_year": parameters.start_year, "end_year": parameters.end_year,
                "as_of": parameters.as_of, "version_policy": parameters.version_policy,
                "include_raw_evidence": parameters.include_raw_evidence,
                "include_conference": parameters.include_conference,
                "include_context_years": parameters.include_context_years,
            },
            "case": {"ticker": case.ticker, "company": case.company_name, "market": case.market},
            "contracts": {"historical_financial_facts": CONTRACT_VERSION, "historical_summaries": SUMMARY_CONTRACT_VERSION,
                          "research_package": PACKAGE_SCHEMA_VERSION},
            "counts": counts,
            "completeness": completeness,
            **extra,
            "integrity": {"raw_evidence_sha256_verified_at_build": True},
            "checksums_sha256": content_digest,
            "content_digest": content_digest,
            "files": [{"path": p, "sha256": hashlib.sha256(builder.files[p]).hexdigest(), "bytes": len(builder.files[p]),
                       "category": builder.categories[p]} for p in sorted(builder.files)],
        }
        builder.files[CHECKSUMS] = checksums
        builder.files[MANIFEST] = _json_bytes(manifest)
        _verify_files(dict(builder.files))  # full semantic verification before anything is written (fail closed)
        output = Path(output_zip)
        self._write_zip(builder.files, output)
        result = {"output": str(output_zip), "mode": mode, "content_digest": content_digest, "files": len(builder.files),
                  "counts": counts, "completeness": completeness, **extra}
        if audit is not None:
            audit.update({
                "audit_report": "reviewer-only modern verification metadata; NOT a research input",
                "package_file": output.name, "package_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "content_digest": content_digest, "generated_at": iso(generated_at or utc_now()),
            })
            target = Path(audit_path) if audit_path else output.with_name(output.name.removesuffix(".zip") + ".audit.json")
            target.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
            result["audit_path"] = str(target)
            result["excluded_by_cutoff"] = audit["excluded_by_cutoff"]
        return result

    # ------------------------------------------------------ retrospective
    def _retrospective(self, builder: _Builder, p: PackageParameters):
        missing: list[dict[str, Any]] = []
        facts = build_export_records(self.repository, p.ticker, p.start_year, p.end_year, version_policy=p.version_policy)
        builder.add("data/financial_facts.csv", _csv_bytes(facts, EXPORT_FIELDS), "dataset")
        builder.add("data/financial_facts.json", _json_bytes({
            "contract": "fintrust.historical_financial_facts", "contract_version": CONTRACT_VERSION,
            "mode": "retrospective", "fields": list(EXPORT_FIELDS), "record_count": len(facts), "records": facts}), "dataset")

        versions = self.repository.list_filing_versions(p.ticker, p.start_year, p.end_year)
        version_rows = []
        for version in versions:
            row = {name: version.get(name) for name in VERSION_FIELDS}
            raw_path = self._include_raw(builder, version["raw_storage_path"], version["content_hash"], "financial_filings",
                                         version["period"], p, missing, version["fiscal_year"],
                                         f"{version['source_kind']} {version['filing_version_type']} {version['statement_scope']}")
            row["package_raw_path"] = raw_path
            row["raw_evidence_included"] = raw_path is not None
            version_rows.append(row)
        builder.add("data/filing_versions.csv", _csv_bytes(version_rows, VERSION_FIELDS), "dataset")

        summaries = [r for r in list_summary_observations(self.repository, p.ticker) if p.start_year <= r["fiscal_year"] <= p.end_year]
        builder.add("data/historical_summaries.csv", _csv_bytes(summaries, SUMMARY_FIELDS), "dataset")
        comparisons = [r for r in list_restatement_comparisons(self.repository, p.ticker) if p.start_year <= r["fiscal_year"] <= p.end_year]
        builder.add("data/restatement_comparisons.csv", _csv_bytes(comparisons, COMPARISON_FIELDS), "dataset")
        timeline = list_publication_timeline(self.repository, p.ticker)
        builder.add("data/publication_timeline.csv", _csv_bytes(timeline, TIMELINE_FIELDS), "dataset")
        inventory = source_inventory(self.repository, p.ticker)
        builder.add("data/source_inventory.csv", _csv_bytes(inventory, INVENTORY_FIELDS), "dataset")
        coverage = coverage_matrix(self.repository, p.ticker, p.start_year, p.end_year)
        builder.add("data/coverage_matrix.csv", _csv_bytes(coverage, COVERAGE_FIELDS), "dataset")

        with self.repository.connect() as connection:
            documents = [dict(row) for row in connection.execute(
                "SELECT * FROM historical_source_documents WHERE ticker = ? ORDER BY source_key, content_hash", (p.ticker,)).fetchall()]
            attempts = [dict(row) for row in connection.execute(
                """SELECT fiscal_year, status, source_url, error FROM historical_acquisition_attempts
                WHERE ticker = ? AND fiscal_year BETWEEN ? AND ? AND status != 'available'
                GROUP BY fiscal_year, status, source_url ORDER BY fiscal_year""", (p.ticker, p.start_year, p.end_year)).fetchall()]
        version_hashes = {v["content_hash"] for v in versions}
        for document in documents:
            if document["content_hash"] in version_hashes:
                continue
            self._include_raw(builder, document["raw_storage_path"], document["content_hash"],
                              _evidence_folder(document["source_category"]), document["source_key"], p, missing, None,
                              document["source_key"])
        for attempt in attempts:
            missing.append({"fiscal_year": attempt["fiscal_year"], "evidence_kind": "acquisition_attempt", "status": attempt["status"],
                            "detail": f"{attempt['source_url'] or '(offline archive reprocess)'}: {attempt['error'] or ''}".strip()})
        for row in coverage:
            for gap in filter(None, (row["remaining_gaps"] or "").split("; ")):
                missing.append({"fiscal_year": row["fiscal_year"], "evidence_kind": "coverage_gap", "status": "unresolved", "detail": gap})

        conference = self._conference(builder, p, missing)
        report = quality_report(self.repository, self.archive, p.ticker, p.start_year, p.end_year)
        report["eps_unit_investigation"] = eps_unit_investigation(self.repository, self.archive, p.ticker)
        report["unmapped_concepts"] = unmapped_concept_report(self.repository, p.ticker, p.start_year, p.end_year)
        report["conference"] = conference
        builder.add("validation/quality_report.json", _json_bytes(report), "validation")
        builder.add("data/missing_evidence.csv", _csv_bytes(
            sorted(missing, key=lambda m: (m["fiscal_year"] or 0, m["evidence_kind"], m["detail"] or "")), MISSING_FIELDS), "dataset")
        notes = self._contracts(builder, RETROSPECTIVE_CONTRACTS + (CONFERENCE_CONTRACTS if conference["status"] == "included" else ()))
        counts = {
            "financial_facts": len(facts),
            "financial_facts_point_in_time_eligible": sum(1 for f in facts if f["point_in_time_eligible"]),
            "filing_versions": len(version_rows),
            "filing_versions_raw_included": sum(1 for r in version_rows if r["raw_evidence_included"]),
            "historical_summaries": len(summaries), "restatement_comparisons": len(comparisons),
            "publication_events": len(timeline), "source_inventory": len(inventory),
            "missing_evidence_rows": len(missing),
            "raw_evidence_files": sum(1 for path in builder.files if path.startswith("raw_evidence/")),
        }
        completeness = {"status": "partial" if missing else "complete", "conference_evidence": conference["status"], "notes": notes}
        return counts, completeness, {"conference": conference}

    def _conference(self, builder: _Builder, p: PackageParameters, missing: list[dict[str, Any]]) -> dict[str, Any]:
        if not p.include_conference:
            return {"status": "not_requested"}
        if self.conference_repository is None:
            missing.append({"fiscal_year": None, "evidence_kind": "conference_pdf", "status": "unavailable",
                            "detail": "no conference PDF archive configured"})
            return {"status": "unavailable_no_archive_configured"}
        # The JSD corpus adapter resolves company profiles through company_registry, which falls back to the
        # production company master when DATASTORE_BACKEND=firestore. Research packaging must stay local.
        backend = os.getenv("DATASTORE_BACKEND", "sqlite").strip().lower()
        if backend != "sqlite":
            raise ResearchPackageError(f"Conference packaging requires DATASTORE_BACKEND=sqlite (got {backend!r})")
        stats = build_conference_datasets(
            add=builder.add, csv_bytes=_csv_bytes, repository=self.conference_repository, root=self.conference_root,
            ticker=p.ticker, start_year=p.start_year, end_year=p.end_year, include_context=p.include_context_years,
            include_raw=p.include_raw_evidence, coverage_rows=latest_coverage(self.repository, p.ticker),
            archive=self.archive, missing=missing)
        if stats["documents"] == 0:
            missing.append({"fiscal_year": None, "evidence_kind": "conference_pdf", "status": "unavailable",
                            "detail": f"no archived official conference documents for {p.ticker} in the requested years"})
        return stats

    # -------------------------------------------------------------- strict
    def _strict(self, builder: _Builder, p: PackageParameters):
        cutoff = as_of_cutoff(p.as_of)
        result = build_strict(add=builder.add, csv_bytes=_csv_bytes, json_bytes=_json_bytes, repository=self.repository,
                              archive=self.archive, params=p, cutoff=cutoff, include_raw=p.include_raw_evidence)
        conference_excluded = 0
        if p.include_conference and self.conference_repository is not None:
            for year in self.conference_repository.available_years(p.ticker):
                conference_excluded += len((self.conference_repository.latest_manifest(p.ticker, year) or {}).get("documents", []))
        builder.add("contracts/STRICT_FIELD_DEFINITIONS.md", STRICT_FIELD_DEFINITIONS.encode("utf-8"), "contract")
        self._contracts(builder, STRICT_CONTRACTS)
        counts = {
            "financial_facts": len(result["facts"]),
            "financial_facts_point_in_time_eligible": len(result["facts"]),
            "facts_with_withheld_later_artifact": result["withheld_artifact_facts"],
            "filing_versions": len(result["versions"]),
            "historical_summaries": len(result["summaries"]),
            "restatement_comparisons": len(result["comparisons"]),
            "publication_events": len(result["timeline"]),
            "source_inventory": len(result["inventory"]),
            "raw_evidence_files": sum(1 for path in builder.files if path.startswith("raw_evidence/")),
        }
        builder.add("validation/quality_report.json", _json_bytes({
            "mode": "strict_point_in_time", "leakage_check": "passed",
            "semantic_verification": "passed", "counts": counts,
            "raw_evidence_policy": "verified-public filing artifacts and single-publication notices only",
        }), "validation")
        problems = leakage_check(builder.files, cutoff)
        if problems:
            raise ResearchPackageError(f"Strict package would leak post-cutoff information: {problems[:5]}")
        completeness = {"status": "point_in_time_subset"}
        audit = {
            "cutoff_utc": iso(cutoff), "parameters": {"ticker": p.ticker, "as_of": p.as_of,
                                                      "start_year": p.start_year, "end_year": p.end_year},
            "excluded_by_cutoff": {**result["excluded"], "conference_documents": conference_excluded},
            "summary_observation_review": result["summary_review"],
            "raw_evidence_provenance": result["provenance"],
        }
        return counts, completeness, {"leakage_check": "passed"}, audit

    # ------------------------------------------------------------ helpers
    def _contracts(self, builder: _Builder, names: tuple[str, ...]) -> list[str]:
        notes = []
        for name in names:
            path = DOCS_ROOT / name
            if path.is_file():
                builder.add(f"contracts/{name}", path.read_bytes(), "contract")
            else:
                notes.append(f"contract document not found: {name}")
        return notes

    def _include_raw(self, builder: _Builder, raw_path: str, content_hash: str, folder: str, group: str,
                     p: PackageParameters, missing: list[dict[str, Any]], fiscal_year: int | None, label: str) -> str | None:
        if not p.include_raw_evidence:
            return None
        suffix = PurePosixPath(raw_path).suffix.lstrip(".").lower() or "bin"
        package_path = f"raw_evidence/{folder}/{p.ticker}/{group}/{content_hash}.{suffix}"
        try:
            data = self.archive.read(raw_path)  # verifies SHA-256 against the content-addressed name
        except FileNotFoundError:
            missing.append({"fiscal_year": fiscal_year, "evidence_kind": "raw_artifact", "status": "missing_locally",
                            "detail": f"{label}: {raw_path}"})
            return None
        except (RuntimeError, ValueError) as exc:
            missing.append({"fiscal_year": fiscal_year, "evidence_kind": "raw_artifact", "status": "failed_integrity",
                            "detail": f"{label}: {exc}"})
            return None
        if hashlib.sha256(data).hexdigest() != content_hash:
            missing.append({"fiscal_year": fiscal_year, "evidence_kind": "raw_artifact", "status": "failed_integrity",
                            "detail": f"{label}: content hash differs from the database record"})
            return None
        builder.add(package_path, data, "raw_evidence")
        return package_path

    @staticmethod
    def _readme(case, p: PackageParameters, mode: str, counts: dict[str, Any], completeness: dict[str, Any]) -> str:
        if mode == "strict_point_in_time":
            return "\n".join([
                f"# FinTrust historical research dataset — {case.ticker} {case.company_name} ({case.market}) — STRICT POINT-IN-TIME",
                "",
                f"Cutoff: {p.as_of} (end of day, Asia/Taipei). Fiscal years {p.start_year}–{p.end_year}. Version policy: {p.version_policy}.",
                "",
                "Only evidence verifiably public before the cutoff is included, in every file. Evidence whose public",
                "availability before the cutoff cannot be verified is not included. Field semantics: `contracts/STRICT_FIELD_DEFINITIONS.md`.",
                "",
                f"Financial observations: {counts['financial_facts']} ({counts['facts_with_withheld_later_artifact']} dated by an official "
                "disclosure; filing-artifact identity not included). "
                f"Summary observations: {counts['historical_summaries']}. "
                f"Restatement comparison rows: {counts['restatement_comparisons']}. Filing artifacts: {counts['filing_versions']}.",
                "",
                "Verify: `python validation/verify_package.py <zip or folder>` (also re-checks the cutoff).",
                "",
            ])
        lines = [
            f"# FinTrust historical research dataset — {case.ticker} {case.company_name} ({case.market}) — RETROSPECTIVE",
            "",
            f"Fiscal years {p.start_year}–{p.end_year}; version policy {p.version_policy}. Package schema {PACKAGE_SCHEMA_VERSION}.",
            "",
            "**Retrospective package: it contains later restatements, later disclosures and current archival copies. Do not",
            "use it as the input of a historical predictive backtest; use a strict point-in-time package instead.**",
            "",
            "Verify first: `python validation/verify_package.py <this zip or extracted folder>` (standard library only).",
            "",
            "| Path | Content |",
            "|---|---|",
            f"| `data/financial_facts.csv/json` | {counts['financial_facts']} filing facts ({counts['financial_facts_point_in_time_eligible']} with verified availability) |",
            f"| `data/filing_versions.csv` | {counts['filing_versions']} filing artifacts (original / restated / unknown) |",
            f"| `data/historical_summaries.csv` | {counts['historical_summaries']} TPEx summary observations (not filings) |",
            f"| `data/restatement_comparisons.csv` | {counts['restatement_comparisons']} 重編前/重編後 rows |",
            f"| `data/publication_timeline.csv` | {counts['publication_events']} official publication events |",
            "| `data/source_inventory.csv`, `data/coverage_matrix.csv`, `data/missing_evidence.csv` | inventory, coverage, explicit gaps |",
            "| `data/conference_*.csv`, `conference/` | official investor-conference documents, page text and coverage (text evidence, not financial data) |",
            "| `raw_evidence/` | original official files named by SHA-256 |",
            "| `validation/`, `contracts/` | quality report, checksums, verifier, data contracts |",
            "",
            f"Conference evidence: {completeness['conference_evidence']}.",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _write_zip(files: dict[str, bytes], output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(files):
                info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/{path}", date_time=FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                info.create_system = 3
                archive.writestr(info, files[path], compresslevel=6)
        temporary.replace(output)
