"""Phase 2+3 F4 integration tests: synthetic only, no store/network writes."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import unittest

from app.services.integrity.contracts import Finding
from app.services.integrity.nfm_evidence_bridge import check_revenue_nfm_strict

_URL = "https://mopsov.twse.com.tw/server-java/FileDownLoad?co_id=2454"
_DATE = "2026-04-10T08:00:00+08:00"


def financial_index():
    def revenue(year, value, digest):
        return {
            "ticker": "2454", "fiscal_period": f"{year}FY",
            "period_type": "annual", "concept": "revenue",
            "value": value, "value_twd": value, "unit": "TWD",
            "scope": "consolidated", "filing_policy": "as_filed_own_year",
            "filing_version": f"mops:{year}:C", "source_url": _URL,
            "source_sha256": digest, "source_document_verified": True,
            "source_trust": "validated_mops_filing",
            "effective_available_at": _DATE,
            "evidence_id": f"financial:{year}", "is_demo": False,
        }
    return {
        ("revenue", 2024): revenue(2024, "1000", "a" * 64),
        ("revenue", 2025): revenue(2025, "1100", "b" * 64),
    }


def nonfinancial():
    def employees(year, amount, digest):
        return {
            "ticker": "2454", "measure": "employees",
            "fiscal_year": year, "value": amount, "unit": "persons",
            "scope": "consolidated", "period_basis": "year_end_stock",
            "measurement_policy": "all_employees_year_end",
            "verified_source": True, "source_document_verified": True,
            "document_identity_verified": True, "scale_related": True,
            "source_url": "https://mops.twse.com.tw/report/employees",
            "source_sha256": digest, "filing_version_id": f"mops:{year}:employees",
            "published_at": _DATE,
        }
    return [employees(2024, "200", "c" * 64), employees(2025, "210", "d" * 64)]


def run(idx=None, nfm=None, cutoff=None):
    return check_revenue_nfm_strict(
        financial_index() if idx is None else idx,
        nonfinancial() if nfm is None else nfm,
        ticker="2454", cutoff_at=cutoff,
    )


class StrictF4Tests(unittest.TestCase):
    def test_computed_only_with_four_provenance_gated_records(self):
        out = run()
        self.assertEqual(out["status"], "descriptive_gap")
        self.assertEqual(out["implementation_tier"], "implemented")
        self.assertEqual(out["review_queue"], None)
        self.assertEqual(out["computed"]["growth_difference"], "0.05")
        self.assertEqual(out["computed"]["growth_difference_percentage_points"], "5")
        self.assertEqual(len(out["inputs"]["nfm_sources"]), 2)
        self.assertEqual(out["not_independent_of"], ["issuer_self_reported_financial_data"])
        Finding.model_validate(out)

    def test_empty_research_inputs_do_not_change_phase11_availability(self):
        r = run(nfm=[])
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["reasons"], ["no_verified_nonfinancial_measure_series"])
        self.assertEqual(r["implementation_tier"], "readiness_only")
        Finding.model_validate(r)

    def test_validated_url_alone_never_upgrades_facts(self):
        idx = financial_index()
        idx[("revenue", 2025)].pop("source_sha256")
        self.assertEqual(run(idx)["status"], "not_computable")
        idx = financial_index()
        idx[("revenue", 2025)]["source_document_verified"] = False
        self.assertEqual(run(idx)["status"], "not_comparable")

    def test_issuer_company_mismatch_is_not_silently_filtered(self):
        nfm = nonfinancial()
        nfm[1]["ticker"] = "2330"
        self.assertEqual(run(nfm=nfm)["reasons"], ["nonfinancial_company_identity_mismatch"])

    def test_unsupported_period_policy_and_units_are_refused(self):
        nfm = nonfinancial()
        nfm[1]["period_basis"] = "annual_flow"
        self.assertEqual(run(nfm=nfm)["reasons"], ["unsupported_nonfinancial_period_basis"])
        nfm = nonfinancial()
        nfm[1]["unit"] = "FTE"
        self.assertEqual(run(nfm=nfm)["status"], "not_comparable")

    def test_missing_document_attestation_is_not_trusted(self):
        for flag in ("verified_source", "source_document_verified",
                     "document_identity_verified", "scale_related"):
            nfm = nonfinancial()
            nfm[1][flag] = False
            with self.subTest(flag=flag):
                self.assertEqual(run(nfm=nfm)["status"], "not_comparable")

    def test_duplicate_filing_version_conflict_is_not_silently_overwritten(self):
        nfm = nonfinancial()
        dup = deepcopy(nfm[1])
        dup["filing_version_id"] = "restatement"
        nfm.append(dup)
        self.assertIn("ambiguous_filing_versions", run(nfm=nfm)["reasons"][0])

    def test_duplicate_identical_observation_is_allowed(self):
        nfm = nonfinancial()
        nfm.append(deepcopy(nfm[1]))
        self.assertEqual(run(nfm=nfm)["status"], "descriptive_gap")

    def test_absent_latest_year_cannot_borrow_stale_results(self):
        idx = financial_index()
        idx[("revenue", 2026)] = {**idx[("revenue", 2025)], "fiscal_period": "2026FY"}
        self.assertEqual(run(idx)["period"], "2026FY")
        self.assertEqual(run(idx)["status"], "not_computable")

    def test_cutoff_excludes_documents_first_published_at_cutoff(self):
        out = run(cutoff=datetime(2026, 4, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(out["status"], "not_computable")
        self.assertTrue(out["reasons"][0].startswith("source_unavailable_at_cutoff:"))

    def test_cutoff_requires_full_known_publication_instant(self):
        idx = financial_index()
        idx[("revenue", 2024)]["effective_available_at"] = "2026-04-01"
        out = run(idx, cutoff=datetime(2026, 5, 1, tzinfo=timezone.utc))
        self.assertIn("publication_time_unknown", out["reasons"][0])

    def test_cutoff_before_all_records_is_computable(self):
        self.assertEqual(
            run(cutoff=datetime(2026, 5, 1, tzinfo=timezone.utc))["status"],
            "descriptive_gap",
        )

    def test_two_measures_need_explicit_selection(self):
        nfm = nonfinancial()
        nfm.append({**nfm[0], "measure": "capacity"})
        self.assertEqual(run(nfm=nfm)["status"], "not_comparable")

    def test_invalid_year_is_not_server_error(self):
        nfm = nonfinancial()
        nfm[0]["fiscal_year"] = "twenty twenty four"
        self.assertEqual(run(nfm=nfm)["reasons"], ["invalid_nonfinancial_observation"])


if __name__ == "__main__":
    unittest.main()
