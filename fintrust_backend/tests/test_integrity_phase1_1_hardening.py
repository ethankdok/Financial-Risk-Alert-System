"""Phase 1.1 hardening (independent review of 0c51a74): CR-01 source identity, CR-02 freshness, CR-03 candidate
selection, CR-04 parser grouping and quote lineage, CR-06 F1 vs DSRI numerics. SYNTHETIC inputs only."""

from __future__ import annotations

import itertools
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services.integrity import alignment as al
from app.services.integrity import composer as cp
from app.services.integrity import financial_checks as fc
from app.services.integrity.adapters import ClaimsAdapter, FactsAdapter, derive_quote, load_registry
from app.services.integrity.contracts import AssessmentRequest
from tests.integrity_fixtures import (
    BASE_DATA,
    FakeBridge,
    FakeClaimService,
    FakeRepository,
    annual_rows,
    archive_for,
    fact,
    mops_url,
    registry_file,
    shift_result,
    statement,
    workbench,
)

T = "2454"
REVIEW_FORGERY = "https://evil.example/untrusted?functionName=t164sb01&year=114&season=4&report_id=C"


def collect(rows, ticker=T):
    return FactsAdapter(FakeRepository(rows)).collect(ticker)


class SourceIdentityTests(unittest.TestCase):  # CR-01
    def test_review_reproductions_are_refused(self) -> None:
        cases = {
            REVIEW_FORGERY: "host_not_allowlisted",
            mops_url(T, 2025).replace("https://", "http://"): "scheme_not_https",
            mops_url(T, 2025).replace("mopsov.twse.com.tw", "mopsov.twse.com.tw.evil.example"): "host_not_allowlisted",
            mops_url(T, 2025).replace("mopsov.twse.com.tw", "evil-mopsov.twse.com.tw"): "host_not_allowlisted",
            mops_url(T, 2025).replace("mopsov.twse.com.tw", "mopsov.twse.com.tw:8443"): "host_not_allowlisted",
            mops_url(T, 2025).replace("https://", "https://user@"): "host_not_allowlisted",
            mops_url("9999", 2025): "co_id_does_not_match_ticker",
            mops_url(T, 2025) + "&year=113": "duplicate_query_parameter:year",
            mops_url(T, 2025) + "&co_id=2454": "duplicate_query_parameter:co_id",
            mops_url(T, 2025) + "&extra=1": "unexpected_query_parameter:extra",
            mops_url(T, 2025).replace("&report_id=C", ""): "missing_query_parameter:report_id",
            mops_url(T, 2025).replace("year=114", "year=11X"): "malformed_or_implausible_roc_year",
            mops_url(T, 2025).replace("year=114", "year=999"): "malformed_or_implausible_roc_year",
            mops_url(T, 2025).replace("season=4", "season=5"): "malformed_season",
            mops_url(T, 2025).replace("report_id=C", "report_id=Z"): "unknown_report_id",
            mops_url(T, 2025).replace("t164sb01", "t164sb01x"): "function_not_allowlisted",
            mops_url(T, 2025).replace("/server-java/FileDownLoad", "/server-java/FileDownLoad/x"): "path_not_allowlisted",
            mops_url(T, 2025) + "#frag": "path_not_allowlisted",
            "": "missing_url",
        }
        for url, reason in cases.items():
            with self.subTest(url=url):
                identity = al.mops_filing_identity(url, ticker=T)
                self.assertEqual((identity["recognised"], identity["reason"]), (False, reason))
                self.assertIsNone(identity["scope"])
                self.assertIsNone(al.filing_policy("2025FY", url, ticker=T))
                self.assertEqual(al.derive_scope("unknown", url, ticker=T), ("unknown", "scope_not_recorded"))

    def test_legitimate_2330_and_2454_urls_still_recognised_on_both_hosts(self) -> None:
        for ticker, year in (("2330", 2024), ("2454", 2025)):
            for host in ("mopsov.twse.com.tw", "mops.twse.com.tw"):
                url = mops_url(ticker, year).replace("mopsov.twse.com.tw", host)
                identity = al.mops_filing_identity(url, ticker=ticker)
                self.assertTrue(identity["recognised"], (url, identity))
                self.assertEqual((identity["scope"], identity["filing_fiscal_year"], identity["co_id"]),
                                 ("consolidated", year, ticker))
                self.assertEqual(al.filing_policy(f"{year}FY", url, ticker=ticker), "as_filed_own_year")

    def test_untrusted_rows_are_quarantined_with_reasons_never_given_official_identity(self) -> None:
        rows = annual_rows(T, BASE_DATA)
        rows = [r for r in rows if (r["metric_code"], r["period"]) != ("revenue", "2025FY")]
        forged = fact(T, "revenue", "2025FY", 1100.0, url=REVIEW_FORGERY, scope="consolidated")
        wrong_company = fact(T, "accounts_receivable", "2025FY", 300.0, url=mops_url("9999", 2025))
        rows = [r for r in rows if (r["metric_code"], r["period"]) != ("accounts_receivable", "2025FY")]
        facts = collect(rows + [forged, wrong_company])
        self.assertNotIn(("revenue", 2025), facts["index"])
        self.assertNotIn(("accounts_receivable", 2025), facts["index"])
        reasons = sorted(e["reason"] for e in facts["excluded"])
        self.assertEqual(reasons, ["untrusted_source:co_id_does_not_match_ticker", "untrusted_source:host_not_allowlisted"])
        bad = next(r for r in facts["records"] if r["source_trust"] == "untrusted_source" and r["concept"] == "revenue")
        self.assertEqual((bad["independence"], bad["source_url"], bad["filing_policy"], bad["publisher"]),
                         ("unverified_source", None, None, None))
        self.assertEqual(bad["scope"], "unknown")  # a stored "consolidated" on an untrusted row is not believed
        f1 = fc.check_revenue_receivables(facts["index"])
        self.assertEqual((f1["period"], f1["freshness_status"]), ("2025FY", "latest_period_not_computable"))


class FreshnessTests(unittest.TestCase):  # CR-02
    STALE = {"revenue": {2023: 1000.0, 2024: 1000.0, 2025: 1100.0}, "accounts_receivable": {2023: 200.0, 2024: 200.0},
             "net_income": {2023: 100.0, 2024: 120.0, 2025: 150.0}, "operating_cash_flow": {2023: 130.0, 2024: 110.0}}

    def test_review_reproduction_latest_year_stays_top_level(self) -> None:
        index = collect(annual_rows(T, self.STALE))["index"]
        f1, f2 = fc.check_revenue_receivables(index), fc.check_net_income_cfo(index)
        for finding, status in ((f1, "not_computable"), (f2, "unavailable")):
            self.assertEqual((finding["period"], finding["status"], finding["review_queue"], finding["freshness_status"],
                              finding["latest_fact_fiscal_year"], finding["latest_period_status"]),
                             ("2025FY", status, "insufficient_evidence", "latest_period_not_computable", 2025, status))
            self.assertEqual(finding["reasons"][0], "latest_period_not_computable")
            self.assertEqual(finding["computed"], {})
            self.assertEqual(finding["last_computable"]["period"], "2024FY")
            self.assertFalse(finding["last_computable"]["is_current"])
        self.assertEqual(f2["last_computable"]["computed"]["direction"], "cfo_below_net_income")  # history kept

    def test_stale_history_neither_triggers_nor_clears_the_present_queue(self) -> None:
        stale_trigger = dict(self.STALE, accounts_receivable={2023: 200.0, 2024: 400.0})  # 2024 would be a divergence
        out = workbench(annual_rows("2303", stale_trigger)).assess(AssessmentRequest(ticker="2303", sections=["financial_checks"]))
        priority = out["investigation_priority"]
        self.assertEqual(priority["queue"], "insufficient_evidence")
        self.assertEqual(priority["triggered_by"], [])
        self.assertEqual(sorted(priority["stale_findings"]), ["F1_REVENUE_RECEIVABLES_ALIGNMENT:2025FY",
                                                              "F2_NET_INCOME_CFO_ALIGNMENT:2025FY"])
        checks = [n["check_id"] for n in out["next_checks"]]
        self.assertIn("B2B_LATEST_PERIOD_DATA", checks)
        self.assertNotIn("B2B_AR_TERMS", checks)
        self.assertNotIn("B2B_WORKING_CAPITAL", checks)
        self.assertEqual(out["freshness"]["latest_fact_fiscal_year"], 2025)

    def test_current_data_is_unchanged(self) -> None:
        index = collect(annual_rows(T, BASE_DATA))["index"]
        f1 = fc.check_revenue_receivables(index)
        self.assertEqual((f1["period"], f1["status"], f1["computed"]["gap"], f1["freshness_status"], f1["last_computable"]),
                         ("2025FY", "descriptive_divergence", "0.4", "current", None))
        f2 = fc.check_net_income_cfo(index)
        self.assertEqual((f2["review_queue"], f2["freshness_status"]), ("monitor", "current"))

    def test_latest_year_only_from_another_metric_still_counts(self) -> None:
        rows = annual_rows(T, BASE_DATA) + annual_rows(T, {"total_assets": {2026: 1.0}})
        f1 = fc.check_revenue_receivables(collect(rows)["index"])
        self.assertEqual((f1["period"], f1["freshness_status"]), ("2026FY", "latest_period_not_computable"))


class CandidateSelectionTests(unittest.TestCase):  # CR-03
    def test_demo_and_real_same_amount_any_order_or_retrieval_time(self) -> None:
        base = [r for r in annual_rows(T, BASE_DATA) if (r["metric_code"], r["period"]) != ("revenue", "2025FY")]
        real = fact(T, "revenue", "2025FY", 1100.0, retrieved_at="2026-09-15T00:00:00+00:00")
        for demo_time in ("2026-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00"):
            demo = fact(T, "revenue", "2025FY", 1100.0, is_demo=True, retrieved_at=demo_time)
            for rows in itertools.permutations([real, demo]):
                with self.subTest(demo_time=demo_time, first=rows[0]["is_demo"]):
                    facts = collect(base + list(rows))
                    chosen = facts["index"][("revenue", 2025)]
                    self.assertFalse(chosen["is_demo"])
                    self.assertEqual(chosen["selection_policy"], "single_official_candidate")
                    self.assertIn("demo_fixture_value", [e["reason"] for e in facts["excluded"]])

    def test_identical_official_duplicates_select_deterministically_not_by_retrieval_time(self) -> None:
        one = fact(T, "revenue", "2025FY", 1100.0, retrieved_at="2026-01-01T00:00:00+00:00")
        two = fact(T, "revenue", "2025FY", 1100.0, retrieved_at="2026-09-01T00:00:00+00:00")
        picks = set()
        for rows in itertools.permutations([one, two]):
            facts = collect(list(rows))
            chosen = facts["index"][("revenue", 2025)]
            picks.add(chosen["evidence_id"])
            self.assertEqual(chosen["selection_policy"], "identical_official_observations_lowest_evidence_id")
            self.assertEqual(chosen["candidate_evidence_ids"], sorted(chosen["candidate_evidence_ids"]))
            self.assertEqual(len(chosen["candidate_evidence_ids"]), 2)
            self.assertTrue(any(e["reason"].startswith("duplicate_of:") for e in facts["excluded"]))
        self.assertEqual(len(picks), 1)

    def test_same_amount_from_incompatible_filings_fails_closed(self) -> None:
        own = fact(T, "revenue", "2024FY", 1000.0)
        comparative = fact(T, "revenue", "2024FY", 1000.0, url=mops_url(T, 2025))  # later filing's comparative column
        facts = collect([own, comparative])
        self.assertNotIn(("revenue", 2024), facts["index"])
        self.assertEqual(facts["quality"][0]["issue"], "incompatible_candidate_versions")
        self.assertEqual(len(facts["quality"][0]["evidence_ids"]), 2)

    def test_conflicting_official_values_keep_every_source_id(self) -> None:
        facts = collect([fact(T, "revenue", "2025FY", 1100.0), fact(T, "revenue", "2025FY", 1200.0, retrieved_at="2026-10-01")])
        self.assertEqual(facts["quality"][0]["issue"], "conflicting_duplicate_values")
        self.assertEqual(len(facts["quality"][0]["evidence_ids"]), 2)

    def test_untrusted_row_claiming_mops_source_kind_is_not_official(self) -> None:
        row = fact(T, "revenue", "2025FY", 1100.0, url=REVIEW_FORGERY, source_kind="mops_xbrl")
        facts = collect([row])
        self.assertEqual(facts["index"], {})
        self.assertEqual(facts["excluded"][0]["reason"], "untrusted_source:host_not_allowlisted")

    def test_listing_at_read_limit_fails_closed(self) -> None:
        with mock.patch.object(FactsAdapter, "FACT_LIMIT", 3):
            facts = collect(annual_rows(T, BASE_DATA))
        self.assertTrue(facts["truncated"])
        self.assertEqual(facts["index"], {})
        self.assertEqual(facts["quality"][0]["issue"], "fact_listing_at_read_limit_possible_truncation")


class ParserGroupingTests(unittest.TestCase):  # CR-04 shared parser
    def parse(self, text):
        from app.services.claim_parser import extract_claim

        parsed = extract_claim(text, ticker_hint=T)
        return parsed.claimed_value, parsed.claimed_value_text, parsed.unit

    def test_grouped_numbers_negatives_and_malformed_grouping(self) -> None:
        cases = {
            "聯發科2024年營收530,586百萬元": (530586.0, "530,586", "百萬"),
            "聯發科2024年營收新台幣5,305.86億元": (5305.86, "5,305.86", "億"),
            "聯發科2024年營收530586百萬元": (530586.0, "530586", "百萬"),
            "聯發科2024年營收1,234,567元": (1234567.0, "1,234,567", "元"),
            "聯發科2024年稅後淨利-1,234.5億元": (-1234.5, "-1,234.5", "億"),
            "聯發科2024年營收5,30.5億元": (None, None, None),
            "聯發科2024年營收12,3456億元": (None, None, None),
            "台積電2024年營收28943.1億元": (28943.1, "28943.1", "億"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_percentages_untouched(self) -> None:
        from app.services.claim_parser import extract_claim

        parsed = extract_claim("台積電2024年毛利率56.1%", ticker_hint="2330")
        self.assertEqual((parsed.claimed_value, parsed.unit), (56.1, "%"))

    def test_newly_parsable_grouped_claim_is_verified_correctly(self) -> None:
        from app.claim_verification_models import ClaimVerifyRequest
        from app.services.claim_evidence_adapter import ClaimEvidenceAdapter
        from app.services.claim_verification_service import ClaimVerificationService
        from app.services.pipeline_evidence_repository import PipelineEvidenceRepository

        repo = FakeRepository(annual_rows(T, {"revenue": {2024: 530585886000.0}}))
        service = ClaimVerificationService(ClaimEvidenceAdapter(fact_repository=PipelineEvidenceRepository(repo),
                                                                conference_repository=None, event_repository=repo), llm=None)
        verdict = lambda text: service.verify(ClaimVerifyRequest(company_code=T, claim=text)).verdict  # noqa: E731
        self.assertEqual(verdict("聯發科2024年營收新台幣5,305.86億元"), "supported")  # was a false "conflicting" (305.86)
        self.assertEqual(verdict("聯發科2024年營收530,586百萬元"), "supported")       # was 586
        self.assertEqual(verdict("聯發科2024年營收6,000億元"), "conflicting")
        self.assertEqual(verdict("聯發科2024年營收5,30.5億元"), "insufficient_evidence")


class QuoteLineageTests(unittest.TestCase):  # CR-04 pinned statements
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.entry = statement()
        self.page = f"{self.entry['context_excerpt']}\n{self.entry['excerpt']}\nother line"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_verified_lineage_records_every_step(self) -> None:
        quote = derive_quote(self.entry, self.page)
        self.assertEqual(quote["result"], "verified")
        self.assertEqual((quote["original_token"], quote["header_unit"], quote["extracted_value_twd"],
                          quote["normalized_claim_value_twd"]), ("1,000", "NT$ millions", "1000000000", "1000000000"))
        self.assertTrue(quote["yoy_check"]["column_1_is_current_year"])

    def test_ambiguity_and_disagreement_are_never_supported(self) -> None:
        q = self.entry["quote_extraction"]
        cases = {
            "ambiguous_row_label": (self.entry, self.page + "\nNet Sales 2,000 900 122.2%", "inconclusive"),
            "printed_token_differs_from_registry": (dict(self.entry, quote_extraction=dict(q, original_token="1,001")),
                                                    self.page, "inconclusive"),
            "normalized_claim_differs_from_source": (dict(self.entry, expected_parse=dict(self.entry["expected_parse"],
                                                                                           value="1001")), self.page,
                                                     "inconclusive"),
            "yoy_column_order_not_confirmed": (self.entry, self.page.replace("11.1%", "-10.0%"), "inconclusive"),
            "ambiguous_header_units": (self.entry, self.page + "\n(In NT$ billions)", "inconclusive"),
            "row_label_not_found": (self.entry, self.page.replace("Net Sales 1,000", "Revenue 1,000"), "insufficient"),
            "no_quote_extraction_spec": ({k: v for k, v in self.entry.items() if k != "quote_extraction"}, self.page,
                                         "insufficient"),
        }
        for reason, (entry, page, result) in cases.items():
            with self.subTest(reason=reason):
                quote = derive_quote(entry, page)
                self.assertEqual((quote["result"], quote["reason"]), (result, reason))

    def test_verifier_is_not_consulted_when_lineage_fails(self) -> None:
        service = FakeClaimService("supported")
        entry = dict(self.entry, expected_parse=dict(self.entry["expected_parse"], value="1001"))
        registry = registry_file(Path(self.tmp.name), [entry])
        check = ClaimsAdapter(archive_for(entry), service, registry).assess("2303", {})["checks"][0]
        self.assertEqual((check["verdict"], check["reason_code"]),
                         ("inconclusive", "quote_extraction_inconclusive:normalized_claim_differs_from_source"))
        self.assertEqual(service.received, [])

    def test_every_real_pinned_statement_declares_its_lineage(self) -> None:
        for entry in load_registry()["statements"]:
            spec = entry["quote_extraction"]
            self.assertTrue(spec["row_label"] and spec["original_token"] and spec["header_unit_excerpt"])
            self.assertEqual(spec["column_position"], 1)
            self.assertIn(spec["column_label"], entry["expected_parse"]["period"])


class ResearchPrecisionTests(unittest.TestCase):  # CR-06 / CR-05
    def test_f1_gap_is_not_dsri(self) -> None:
        rows = annual_rows(T, {"revenue": {2024: 1000.0, 2025: 1100.0}, "accounts_receivable": {2024: 200.0, 2025: 250.0}})
        c = fc.check_revenue_receivables(collect(rows)["index"])["computed"]
        self.assertEqual((c["gap"], c["receivables_to_revenue_relative_change"]), ("0.15", "0.136364"))

    def test_f2_reports_both_sign_conventions(self) -> None:
        f2 = fc.check_net_income_cfo(collect(annual_rows(T, BASE_DATA))["index"])
        self.assertEqual((f2["computed"]["net_income_minus_cfo_twd"], f2["computed"]["cfo_minus_net_income_twd"]), ("60", "-60"))
        self.assertIn("sign_convention", f2["heuristic"])

    def test_response_states_assumptions_and_contract_v2(self) -> None:
        out = workbench(bridge=FakeBridge(shift_result())).assess(AssessmentRequest(ticker="2303"))
        self.assertEqual(out["contract_version"], "integrity_workbench_contract_v2")
        self.assertTrue(any("report_id=C" in a for a in out["assumptions"]))
        self.assertTrue(any("12 月 31 日" in a for a in out["assumptions"]))
        self.assertEqual(out["method_versions"]["review_queue_rule"], cp.QUEUE_RULE_VERSION)


if __name__ == "__main__":
    unittest.main()


class StalePageTests(unittest.TestCase):  # CR-02 in the browser page
    @unittest.skipUnless(__import__("shutil").which("node"), "node not installed")
    def test_stale_latest_year_is_shown_prominently_and_history_is_labelled(self) -> None:
        from tests.test_integrity_phase1_api import render

        wb = workbench(annual_rows("2303", FreshnessTests.STALE))
        preview = json_roundtrip(wb.assess(AssessmentRequest(ticker="2303")))
        companies = {"companies": [{"ticker": "2303", "name": "SYNTHETIC", "subindustry": "x", "persisted_snapshot": True}]}
        out = render({"companies": companies, "preview": preview, "ticker": "2303"})
        self.assertIn("最新年度 2025FY 無法計算：本項不產生目前的查核結論。", out["overview"])
        self.assertIn("歷史觀察（非目前結論）：2024FY", out["overview"])
        self.assertIn("最新年度不可計算的檢查 2 項", out["summary"])
        self.assertIn("資料不足", out["summary"])
        self.assertNotIn("需要補件確認", out["summary"])


def json_roundtrip(value):
    import json

    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
