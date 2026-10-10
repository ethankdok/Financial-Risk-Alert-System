"""Portable, deterministic research dataset package (ZIP) for one historical case.

The package needs no database, FinTrust code or cloud credentials: CSV/JSON
datasets, SHA-256-verified original evidence, explicit missing-evidence rows,
contracts and a standard-library verifier. Given unchanged inputs and the same
``generated_at``, the ZIP is byte-identical; across different ``generated_at``
values ``content_digest`` stays identical (logical reproducibility).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.case_registry import get_case
from app.services.historical_audit.evidence_export import (
    COMPARISON_FIELDS,
    COVERAGE_FIELDS,
    INVENTORY_FIELDS,
    SUMMARY_FIELDS,
    TIMELINE_FIELDS,
    coverage_matrix,
    list_publication_timeline,
    list_restatement_comparisons,
    list_summary_observations,
    source_inventory,
)
from app.services.historical_audit.export import CONTRACT_VERSION, EXPORT_FIELDS, build_export_records
from app.services.historical_audit.models import VersionPolicy, iso, utc_now
from app.services.historical_audit.package_verify import (
    CHECKSUMS,
    MANIFEST,
    PACKAGE_ROOT,
    safe_relative_path,
)
from app.services.historical_audit.quality import eps_unit_investigation, quality_report, unmapped_concept_report
from app.services.historical_audit.repository import HistoricalAuditRepository


PACKAGE_SCHEMA_VERSION = "1.0"
DOCS_ROOT = Path(__file__).resolve().parents[4] / "docs" / "data"
CONTRACT_DOCS = (
    "HISTORICAL_FINANCIAL_FACTS_CONTRACT.md",
    "HISTORICAL_RESEARCH_PACKAGE_CONTRACT.md",
    "HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md",
    "HISTORICAL_PUBLICATION_TIMELINE.md",
)
CONFERENCE_CONTRACT = "JSD_INPUT_CONTRACT.md"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
VERSION_FIELDS = (
    "filing_version_id", "ticker", "period", "fiscal_year", "statement_scope", "statement_scope_evidence",
    "filing_version_type", "source_kind", "source_url", "content_hash", "content_length", "detected_format",
    "available_at", "availability_status", "availability_basis", "source_published_at", "document_dated_at",
    "retrieved_at", "validation_status", "quarantine_reason", "parser_version", "package_raw_path",
    "raw_evidence_included",
)
MISSING_FIELDS = ("fiscal_year", "evidence_kind", "status", "detail")
CONFERENCE_INDEX_FIELDS = (
    "ticker", "announcement_year", "filename", "period", "document_type", "language", "sha256",
    "jsd_ready", "readiness_issues", "package_raw_path", "raw_evidence_included",
)
_EXTENSION_BY_FORMAT = {"xbrl_instance": "xml", "inline_xbrl": "html", "zip": "zip", "pdf": "pdf",
                        "xls": "xls", "html": "html"}


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
    conference_years: list[int] | None = None


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
    if category in {"official_original_filing", "official_restated_filing", "official_filing_unknown_revision"}:
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

    # ------------------------------------------------------------- build
    def build(self, parameters: PackageParameters, output_zip: str | Path, *,
              generated_at: datetime | None = None) -> dict[str, Any]:
        case = self.repository.get_case(parameters.ticker) or get_case(parameters.ticker)
        builder = _Builder()
        missing: list[dict[str, Any]] = []
        warnings: list[str] = []
        p = parameters

        facts = build_export_records(self.repository, p.ticker, p.start_year, p.end_year,
                                     as_of=p.as_of, version_policy=p.version_policy)
        builder.add("data/financial_facts.csv", _csv_bytes(facts, EXPORT_FIELDS), "dataset")
        builder.add("data/financial_facts.json", _json_bytes({
            "contract": "fintrust.historical_financial_facts", "contract_version": CONTRACT_VERSION,
            "fields": list(EXPORT_FIELDS), "record_count": len(facts), "records": facts}), "dataset")

        versions = self.repository.list_filing_versions(p.ticker, p.start_year, p.end_year)
        version_rows = []
        for version in versions:
            row = {name: version.get(name) for name in VERSION_FIELDS}
            raw_path = self._include_raw(builder, version["raw_storage_path"], version["content_hash"],
                                         "financial_filings", version["period"], p, missing, version["fiscal_year"],
                                         f"{version['source_kind']} {version['filing_version_type']} {version['statement_scope']}")
            row["package_raw_path"] = raw_path
            row["raw_evidence_included"] = raw_path is not None
            version_rows.append(row)
        builder.add("data/filing_versions.csv", _csv_bytes(version_rows, VERSION_FIELDS), "dataset")

        summaries = [r for r in list_summary_observations(self.repository, p.ticker, as_of=p.as_of)
                     if p.start_year <= r["fiscal_year"] <= p.end_year]
        builder.add("data/historical_summaries.csv", _csv_bytes(summaries, SUMMARY_FIELDS), "dataset")
        comparisons = [r for r in list_restatement_comparisons(self.repository, p.ticker, as_of=p.as_of)
                       if p.start_year <= r["fiscal_year"] <= p.end_year]
        builder.add("data/restatement_comparisons.csv", _csv_bytes(comparisons, COMPARISON_FIELDS), "dataset")
        timeline = list_publication_timeline(self.repository, p.ticker)
        builder.add("data/publication_timeline.csv", _csv_bytes(timeline, TIMELINE_FIELDS), "dataset")
        inventory = source_inventory(self.repository, p.ticker)
        builder.add("data/source_inventory.csv", _csv_bytes(inventory, INVENTORY_FIELDS), "dataset")
        coverage = coverage_matrix(self.repository, p.ticker, p.start_year, p.end_year)
        builder.add("data/coverage_matrix.csv", _csv_bytes(coverage, COVERAGE_FIELDS), "dataset")

        with self.repository.connect() as connection:
            documents = [dict(row) for row in connection.execute(
                "SELECT * FROM historical_source_documents WHERE ticker = ? ORDER BY source_key, content_hash",
                (p.ticker,)).fetchall()]
            attempts = [dict(row) for row in connection.execute(
                """SELECT fiscal_year, status, source_url, error FROM historical_acquisition_attempts
                WHERE ticker = ? AND fiscal_year BETWEEN ? AND ? AND status != 'available'
                GROUP BY fiscal_year, status, source_url ORDER BY fiscal_year""",
                (p.ticker, p.start_year, p.end_year)).fetchall()]
        version_hashes = {v["content_hash"] for v in versions}
        for document in documents:
            if document["content_hash"] in version_hashes:
                continue  # already included as a filing artifact
            self._include_raw(builder, document["raw_storage_path"], document["content_hash"],
                              _evidence_folder(document["source_category"]), document["source_key"], p, missing,
                              None, document["source_key"])
        for attempt in attempts:
            missing.append({"fiscal_year": attempt["fiscal_year"], "evidence_kind": "acquisition_attempt",
                            "status": attempt["status"],
                            "detail": f"{attempt['source_url'] or '(offline archive reprocess)'}: {attempt['error'] or ''}".strip()})
        for row in coverage:
            for gap in filter(None, (row["remaining_gaps"] or "").split("; ")):
                missing.append({"fiscal_year": row["fiscal_year"], "evidence_kind": "coverage_gap",
                                "status": "unresolved", "detail": gap})

        conference = self._conference(builder, p, missing, warnings)

        report = quality_report(self.repository, self.archive, p.ticker, p.start_year, p.end_year)
        report["eps_unit_investigation"] = eps_unit_investigation(self.repository, self.archive, p.ticker)
        report["unmapped_concepts"] = unmapped_concept_report(self.repository, p.ticker, p.start_year, p.end_year)
        builder.add("validation/quality_report.json", _json_bytes(report), "validation")
        builder.add("data/missing_evidence.csv", _csv_bytes(
            sorted(missing, key=lambda m: (m["fiscal_year"] or 0, m["evidence_kind"], m["detail"])), MISSING_FIELDS),
            "dataset")

        verifier = Path(__file__).with_name("package_verify.py").read_bytes()
        builder.add("validation/verify_package.py", verifier, "validation")
        for name in CONTRACT_DOCS + ((CONFERENCE_CONTRACT,) if conference["included"] else ()):
            path = DOCS_ROOT / name
            if path.is_file():
                builder.add(f"contracts/{name}", path.read_bytes(), "contract")
            else:
                warnings.append(f"contract document not found: {name}")

        counts = {
            "financial_facts": len(facts),
            "financial_facts_point_in_time_eligible": sum(1 for f in facts if f["point_in_time_eligible"]),
            "filing_versions": len(version_rows),
            "filing_versions_raw_included": sum(1 for r in version_rows if r["raw_evidence_included"]),
            "historical_summaries": len(summaries),
            "restatement_comparisons": len(comparisons),
            "publication_events": len(timeline),
            "source_inventory": len(inventory),
            "missing_evidence_rows": len(missing),
            "conference_documents": conference["documents"],
        }
        readme = self._readme(case, p, counts, conference, warnings)
        builder.add("README.md", readme.encode("utf-8"), "readme")

        checksum_lines = "".join(
            f"{hashlib.sha256(builder.files[path]).hexdigest()}  {path}\n" for path in sorted(builder.files))
        checksums = checksum_lines.encode("utf-8")
        content_digest = hashlib.sha256(checksums).hexdigest()
        manifest = {
            "package": PACKAGE_ROOT,
            "package_schema_version": PACKAGE_SCHEMA_VERSION,
            "generator": "fintrust_backend/app/services/historical_audit/research_package.py",
            "generated_at": iso(generated_at or utc_now()),
            "parameters": {
                "ticker": p.ticker, "start_year": p.start_year, "end_year": p.end_year, "as_of": p.as_of,
                "version_policy": p.version_policy, "include_raw_evidence": p.include_raw_evidence,
                "include_conference": p.include_conference,
            },
            "case": {"ticker": case.ticker, "company": case.company_name, "market": case.market},
            "contracts": {"historical_financial_facts": CONTRACT_VERSION, "research_package": PACKAGE_SCHEMA_VERSION},
            "counts": counts,
            "completeness": {
                "status": "partial" if missing else "complete",
                "conference_evidence": conference["status"],
                "notes": warnings,
            },
            "checksums_sha256": content_digest,
            "content_digest": content_digest,
            "files": [
                {"path": path, "sha256": hashlib.sha256(builder.files[path]).hexdigest(),
                 "bytes": len(builder.files[path]), "category": builder.categories[path]}
                for path in sorted(builder.files)
            ],
        }
        builder.files[CHECKSUMS] = checksums
        builder.files[MANIFEST] = _json_bytes(manifest)
        self._write_zip(builder.files, Path(output_zip))
        return {"output": str(output_zip), "content_digest": content_digest, "files": len(builder.files),
                "counts": counts, "completeness": manifest["completeness"]}

    # ---------------------------------------------------------- helpers
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

    def _conference(self, builder: _Builder, p: PackageParameters, missing: list[dict[str, Any]],
                    warnings: list[str]) -> dict[str, Any]:
        result = {"included": False, "status": "not_requested", "documents": 0}
        if not p.include_conference:
            return result
        if self.conference_repository is None:
            result["status"] = "unavailable_no_archive_configured"
            missing.append({"fiscal_year": None, "evidence_kind": "conference_pdf", "status": "unavailable",
                            "detail": "no conference PDF archive configured"})
            return result
        from app.services.conference_jsd_corpus_adapter import CORPUS_FIELDS, build_records, to_corpus_rows

        years = p.conference_years or self.conference_repository.available_years(p.ticker)
        if not years:
            result["status"] = "unavailable_for_ticker"
            missing.append({"fiscal_year": None, "evidence_kind": "conference_pdf", "status": "unavailable",
                            "detail": f"no archived MOPS conference PDFs for {p.ticker}"})
            return result
        records = build_records(self.conference_repository, p.ticker, years)
        index_rows = []
        for record in records:
            year = record.provenance["announcement_year"]
            filename = record.provenance["filename"]
            raw_path = None
            source = (self.conference_root / p.ticker / str(year) / filename) if self.conference_root else None
            if p.include_raw_evidence and source is not None and source.is_file():
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() == record.record["sha256"]:
                    raw_path = f"raw_evidence/conference_pdfs/{p.ticker}/{year}/{record.record['sha256']}.pdf"
                    builder.add(raw_path, data, "conference_raw_evidence")
                else:
                    missing.append({"fiscal_year": year, "evidence_kind": "conference_pdf", "status": "failed_integrity",
                                    "detail": filename})
            elif p.include_raw_evidence:
                missing.append({"fiscal_year": year, "evidence_kind": "conference_pdf", "status": "missing_locally",
                                "detail": filename})
            index_rows.append({
                "ticker": p.ticker, "announcement_year": year, "filename": filename,
                "period": record.record["period"], "document_type": record.record["document_type"],
                "language": record.record["language"], "sha256": record.record["sha256"],
                "jsd_ready": record.jsd_ready, "readiness_issues": ";".join(record.readiness_issues),
                "package_raw_path": raw_path, "raw_evidence_included": raw_path is not None,
            })
        index_rows.sort(key=lambda row: (row["announcement_year"], row["filename"]))
        builder.add("conference/conference_documents.csv", _csv_bytes(index_rows, CONFERENCE_INDEX_FIELDS), "conference")
        corpus = sorted(to_corpus_rows(records), key=lambda row: (row["period"] or "", row["sha256"]))
        builder.add("conference/conference_corpus.csv", _csv_bytes(corpus, tuple(CORPUS_FIELDS)), "conference")
        warnings.append("conference/ holds text evidence for JSD research; it is not financial-statement data")
        result.update(included=True, status="included", documents=len(index_rows))
        return result

    @staticmethod
    def _readme(case, p: PackageParameters, counts: dict[str, int], conference: dict[str, Any],
                warnings: list[str]) -> str:
        lines = [
            f"# FinTrust historical research dataset — {case.ticker} {case.company_name} ({case.market})",
            "",
            f"Fiscal years {p.start_year}–{p.end_year}; as_of: {p.as_of or 'none (all versions, eligibility flagged)'}; "
            f"version policy: {p.version_policy}. Package schema {PACKAGE_SCHEMA_VERSION}.",
            "",
            "Verify first: `python validation/verify_package.py <this zip or extracted folder>` (standard library only).",
            "",
            "## Contents",
            "",
            "| Path | Content |",
            "|---|---|",
            f"| `data/financial_facts.csv/json` | {counts['financial_facts']} filing-derived facts "
            f"({counts['financial_facts_point_in_time_eligible']} point-in-time eligible); contract `contracts/HISTORICAL_FINANCIAL_FACTS_CONTRACT.md` |",
            f"| `data/filing_versions.csv` | {counts['filing_versions']} filing artifacts with original/restated/unknown status and artifact-level availability |",
            f"| `data/historical_summaries.csv` | {counts['historical_summaries']} TPEx summary observations (summary values only, not filings) |",
            f"| `data/restatement_comparisons.csv` | {counts['restatement_comparisons']} 重編前/重編後 rows from official notices |",
            f"| `data/publication_timeline.csv` | {counts['publication_events']} official publication events |",
            "| `data/source_inventory.csv` | every archived source with category and SHA-256 |",
            "| `data/coverage_matrix.csv` | per-year evidence coverage and remaining gaps |",
            f"| `data/missing_evidence.csv` | {counts['missing_evidence_rows']} explicitly missing / unverified items (never filled with invented data) |",
            "| `raw_evidence/financial_filings/` | original official XBRL/PDF filings, named by SHA-256 |",
            "| `raw_evidence/regulatory_disclosures/` | TPEx / MOPS / TWSE notices and listings |",
            "| `raw_evidence/official_summaries/` | TPEx 上櫃公司季報 workbooks |",
            "| `validation/` | quality report, checksums, verifier |",
            "",
            "## For case research (Yu-Jing)",
            "",
            "`filing_versions.csv` (original vs restated artifacts), `restatement_comparisons.csv`, "
            "`publication_timeline.csv`, `coverage_matrix.csv`, `missing_evidence.csv` and the original documents in `raw_evidence/`.",
            "",
            "## For quantitative research (Ethan)",
            "",
            "`financial_facts.*` with `point_in_time_eligible`, `effective_available_at` and "
            "`availability_evidence_*`; filter with the documented cutoffs. Pre-event (before 2016-05-13) "
            "strict queries currently have no verified inputs.",
            "",
        ]
        if conference["included"]:
            lines += ["## Conference text (JSD research)", "",
                      f"`conference/` holds {conference['documents']} conference documents (text corpus and index) under "
                      "`contracts/JSD_INPUT_CONTRACT.md`. Text evidence is not interchangeable with financial observations.", ""]
        else:
            lines += [f"Conference PDFs: {conference['status']}.", ""]
        if warnings:
            lines += ["## Notes", ""] + [f"- {item}" for item in warnings] + [""]
        return "\n".join(lines)

    @staticmethod
    def _write_zip(files: dict[str, bytes], output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(files):
                info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/{path}", date_time=FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16  # regular file, rw-r--r--
                info.create_system = 3
                archive.writestr(info, files[path], compresslevel=6)
        temporary.replace(output)
