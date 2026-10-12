"""Literature-model data-integrity corrections (independent review of f83aa98, findings LIT-F01..F04).

- F01: explicit published zero vs absent line vs source-confirmed structural zero (``verified_zero``);
- F02: TW-GAAP statement identities ``verified`` / ``mismatch`` / ``incomplete`` gate the affected lines only;
- F03: disagreeing alias candidates are ``mapping_conflict`` (never first-in-list), permutation invariant;
- F04: t-2 balances from another filing need a verified overlapping year; the IFRS-transition opening balance is a
  flagged, validated exception for the first TIFRS year only.

FIXTURE tier: a synthetic TW-GAAP generator writes rows exactly like ``literature_extraction`` (and evaluates the real
``arithmetic_checks`` / ``covering_identities``), so a corrupted equation goes through the production gate. REAL tier
(skipped without the approved local archive): the reviewed 1785 matrix entries and a corrupted copy of the real
FY2012 original report.
"""

from __future__ import annotations

import random
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.input_snapshot import InputSnapshot
from app.services.financial_research.literature_comparison import compare, compute_models, freeze_literature_inputs
from app.services.financial_research.literature_extraction import (
    DEDUCTION_CODES,
    TWGAAP_PDF_EXTRACTOR_VERSION,
    arithmetic_checks,
    covering_identities,
    observation_id,
)
from app.services.financial_research.literature_inputs import (
    ISSUANCE_METRICS,
    MAPPINGS,
    ZERO_RULE_TWGAAP_EQUITY,
    FilingLines,
    assemble,
    prove_zero,
)
from app.services.financial_research.literature_method_registry import BENEISH_MODEL_ID, DECHOW_MODEL_ID
from tests.test_literature_models import (
    DATABASE,
    HAS_REAL,
    RAW,
    RETRO,
    ROOT,
    FakeStore,
    balance,
    filing,
    fixture_observations,
    literature_snapshot,
    obs,
    result_for,
)

MODELS = [BENEISH_MODEL_ID, DECHOW_MODEL_ID]

# ------------------------------------------------------------------------------------ synthetic TW-GAAP filings
# Leaves in thousand TWD per fiscal-year column; every subtotal / total is derived so all identities hold.
LEAVES = {
    2012: {"1100": 600, "1120": 90, "1140": 1700, "120X": 8000, "1310": 120, "1480": 170, "15XX": 8700,
           "2100": 1100, "2140": 450, "2160": 20, "2270": 900, "2420": 4500, "3110": 4000,
           "4100": 74000, "5000": 72400, "6100": 300, "6200": 590, "6300": 310, "7900": 1050, "8110": 170,
           "label:各項折舊": 640, "label:各項攤提": 120, "label:營業活動之淨現金流入": 900, "label:長期借款增加": 3000},
    2011: {"1100": 700, "1120": 130, "1140": 1900, "120X": 7500, "1310": 70, "1480": 230, "15XX": 7400,
           "2100": 1500, "2140": 560, "2160": 58, "2270": 1680, "2420": 1600, "3110": 3700,
           "4100": 71600, "5000": 69000, "6100": 280, "6200": 580, "6300": 350, "7900": 920, "8110": 110,
           "label:各項折舊": 560, "label:各項攤提": 110, "label:營業活動之淨現金流入": 700, "label:長期借款增加": 1700},
    2010: {"1100": 500, "1120": 85, "1140": 1890, "120X": 7300, "1310": 20, "1480": 167, "15XX": 5000,
           "2100": 2780, "2140": 420, "2160": 180, "2270": 40, "2420": 1700, "3110": 3000,
           "4100": 48700, "5000": 45800, "6100": 260, "6200": 600, "6300": 270, "7900": 1800, "8110": 190,
           "label:各項折舊": 420, "label:各項攤提": 90, "label:營業活動之淨現金流入": 600, "label:長期借款增加": 800},
}


def statement_column(leaves: dict[str, int]) -> dict[str, int]:
    column = dict(leaves)
    column["11XX"] = sum(column[c] for c in ("1100", "1120", "1140", "120X", "1310"))
    column["14XX"] = column["1480"]
    column["1XXX"] = column["11XX"] + column["14XX"] + column["15XX"]
    column["21XX"] = sum(column[c] for c in ("2100", "2140", "2160", "2270"))
    column["24XX"] = column["2420"]
    column["2XXX"] = column["21XX"] + column["24XX"]
    column["3XXX"] = column["1XXX"] - column["2XXX"]
    column["3350"] = column["3XXX"] - column["3110"] - column.get("3120", 0)
    column["5910"] = column["4100"] - column["5000"]
    column["6000"] = column["6100"] + column["6200"] + column["6300"]
    column["9600"] = column["7900"] - column["8110"]
    return column


def _statement(key: str) -> str:
    if key.startswith("label:"):
        return "cash_flow_statement"
    return "balance_sheet" if key[0] in "123" else "income_statement"


def twgaap_filing(fid: str, year: int, *, corrupt: dict | None = None, drop: tuple = (), page_identity: dict | None = None,
                  vtype: str = "original") -> list[dict]:
    """Rows shaped like ``extract_twgaap_pdf`` output for a FY``year`` report (current + comparative column)."""
    rows = []
    for fiscal_year in (year, year - 1):
        column = statement_column(LEAVES[fiscal_year])
        column.update({k[1]: v for k, v in (corrupt or {}).items() if k[0] == fiscal_year})
        for key, thousands in sorted(column.items()):
            line_key = key if key.startswith("label:") else f"code:{key}"
            if (fiscal_year, line_key) in drop:
                continue
            statement = _statement(key)
            value = dm.text(Decimal(thousands) * 1000)
            printed = f"({thousands:,})" if key in DEDUCTION_CODES else f"{thousands:,}"
            period = ({"period_type": "instant", "period_start": None, "period_end": f"{fiscal_year}-12-31"}
                      if statement == "balance_sheet" else
                      {"period_type": "duration", "period_start": f"{fiscal_year}-01-01", "period_end": f"{fiscal_year}-12-31"})
            rows.append({"observation_id": observation_id(TWGAAP_PDF_EXTRACTOR_VERSION, fid, line_key, fiscal_year, value),
                         "ticker": "1785", "filing_version_id": fid, "filing_version_type": vtype,
                         "filing_fiscal_year": year, "source_kind": "official_pdf", "accounting_framework": "TW_GAAP",
                         "statement_scope": "consolidated", "statement": statement, "line_key": line_key,
                         "source_concept": f"{line_key} {'特別股股本' if key == '3120' else ''}".strip(), "value": value,
                         "published_value": printed, "published_unit": "TWD_thousand", "locator": "pdf_page=5",
                         "raw_sha256": "b" * 64, "source_url": None,
                         "extraction_method": "pdf_text_label" if key.startswith("label:") else "pdf_text_account_code",
                         "extractor_version": TWGAAP_PDF_EXTRACTOR_VERSION, "artifact_available_at": None,
                         "artifact_availability_status": "unverified", "pit_admitted": False, "pit_basis": "test",
                         "checks": {"unit": "verified", "fiscal_year": "verified", "scope": "verified",
                                    **(page_identity or {})}, **period})
    details = arithmetic_checks(rows, year)
    for row in rows:
        row["checks"] = {**row["checks"], "identities": covering_identities(row, details)}
    return rows


def twgaap_snapshot(f2012: list[dict], f2011: list[dict] | None = None, *, start=2011, end=2012):
    snapshot = InputSnapshot(ticker="1785", context=RETRO, start_year=start, end_year=end,
                             version_policy="original_only", backend_name="unit")
    versions = [filing("G2012", 2012, "original"), filing("G2011", 2011, "original")]
    observations = f2012 + (twgaap_filing("G2011", 2011) if f2011 is None else f2011)
    return freeze_literature_inputs(snapshot, versions, FakeStore(observations))


def statuses(result: dict) -> set[tuple[str, str, str]]:
    return {(m["metric"], m["relative_period"], m["status"]) for m in result["missing_inputs"]}


# ------------------------------------------------------------------------------------------------ F01
class ZeroEvidenceTests(unittest.TestCase):
    def test_explicit_zero_absent_line_and_verified_structural_zero_are_distinct(self) -> None:
        # explicit published zero (a printed line with 0)
        explicit = FilingLines([obs("F2015", 2015, "CurrentAssets", 10), obs("F2015", 2015, "ShorttermBorrowings", 0),
                                obs("F2015", 2015, "CurrentLiabilities", 5), *balance("F2015", 2015, 10, 5, 5)])
        value = assemble(explicit, "TIFRS", "short_term_debt", "I:2015-12-31")
        self.assertEqual((value.status, value.value, value.evidence_type), ("computed", Decimal(0), "explicit_zero"))
        # absent line in a parsed statement: not_presented, never computed/0
        absent = FilingLines([obs("F2015", 2015, "CurrentAssets", 10), obs("F2015", 2015, "CurrentLiabilities", 5),
                              *balance("F2015", 2015, 10, 5, 5)])
        value = assemble(absent, "TIFRS", "short_term_debt", "I:2015-12-31")
        self.assertEqual((value.status, value.value), ("not_presented", None))
        self.assertIn("zero_inference_not_permitted_for_metric", value.reasons)
        # source-confirmed structural zero: verified equity enumeration without a preferred line
        rows = twgaap_filing("G2012", 2012)
        lines = FilingLines(rows, [prove_zero(FilingLines(rows), "TW_GAAP", "preferred_stock", "I:2012-12-31")])
        value = assemble(lines, "TW_GAAP", "preferred_stock", "I:2012-12-31")
        self.assertEqual((value.status, value.value, value.evidence_type), ("computed", Decimal(0), "verified_zero"))
        self.assertEqual(value.zero_evidence["rule"], ZERO_RULE_TWGAAP_EQUITY)
        self.assertEqual(value.zero_evidence["rule_version"], "literature_zero_evidence_policy_v2")
        self.assertEqual(len(value.zero_evidence["evidence_fingerprint"]), 64)
        self.assertEqual({o["line_key"] for o in value.observations}, {"code:3XXX", "code:3110", "code:3350"})

    def test_absent_sum_lines_never_score_through_the_full_engine(self) -> None:
        # the synthetic report presents no short-term-investment line at all: both models must stay unscored
        rows = fixture_observations(drop={"CurrentFinancialAssetsAtFairValueThroughProfitOrLoss"})
        for model_id in MODELS:
            result = result_for(literature_snapshot(rows), model_id)
            self.assertIsNone(result["score"], model_id)
            self.assertIn(("short_term_investments", "t", "not_presented"), statuses(result))

    def test_reviewer_repro_no_preferred_line_is_never_computed_zero(self) -> None:
        # the independent review's repro: only code:1XXX=10000 (TW-GAAP) -> previously computed/0
        only_assets = [row for row in twgaap_filing("G2012", 2012) if row["line_key"] == "code:1XXX"]
        lines = FilingLines(only_assets)
        value = assemble(lines, "TW_GAAP", "preferred_stock", "I:2012-12-31")
        self.assertNotEqual(value.status, "computed")
        self.assertIsNone(value.value)
        # equity total printed but the section is not enumerated (members missing): proof incomplete -> not_presented
        total_only = [row for row in twgaap_filing("G2012", 2012) if row["line_key"] in ("code:1XXX", "code:3XXX")]
        proof = prove_zero(FilingLines(total_only), "TW_GAAP", "preferred_stock", "I:2012-12-31")
        value = assemble(FilingLines(total_only, [proof]), "TW_GAAP", "preferred_stock", "I:2012-12-31")
        self.assertEqual((value.status, value.value), ("not_presented", None))
        self.assertTrue(any(r.startswith("zero_evidence_not_verified:") for r in value.reasons))

    def test_zero_proof_fails_closed_on_tampering_and_uses_a_printed_preferred_line(self) -> None:
        # a member value changed after extraction: the stored identity says verified but the re-computation differs
        rows = twgaap_filing("G2012", 2012)
        tampered = [{**r, "value": str(int(r["value"]) + 1000)} if r["line_key"] == "code:3110"
                    and r["period_end"] == "2012-12-31" else r for r in rows]
        proof = prove_zero(FilingLines(tampered), "TW_GAAP", "preferred_stock", "I:2012-12-31")
        self.assertEqual(proof["status"], "mismatch")
        value = assemble(FilingLines(tampered, [proof]), "TW_GAAP", "preferred_stock", "I:2012-12-31")
        self.assertEqual(value.status, "not_presented")
        # the extractor itself reports the broken equation: the gate blocks the proof's operands
        broken = twgaap_filing("G2012", 2012, corrupt={(2012, "3350"): 1})
        self.assertEqual(prove_zero(FilingLines(broken), "TW_GAAP", "preferred_stock", "I:2012-12-31")["status"],
                         "mismatch")
        # a printed preferred line is used as the value (never replaced by a zero proof)
        LEAVES[2012]["3120"] = 250
        try:
            with_preferred = twgaap_filing("G2012", 2012)
        finally:
            del LEAVES[2012]["3120"]
        lines = FilingLines(with_preferred, [prove_zero(FilingLines(with_preferred), "TW_GAAP", "preferred_stock",
                                                        "I:2012-12-31")])
        value = assemble(lines, "TW_GAAP", "preferred_stock", "I:2012-12-31")
        self.assertEqual((value.status, value.value, value.evidence_type), ("computed", Decimal(250000), "presented_lines_sum"))

    def test_issuance_absence_is_never_a_zero(self) -> None:
        for mapping in MAPPINGS:
            if mapping.metric in ISSUANCE_METRICS:
                self.assertNotIn("zero_evidence_rule", mapping.tifrs)
                self.assertNotIn("zero_evidence_rule", mapping.twgaap)
        rows = twgaap_filing("G2012", 2012, drop=((2012, "label:長期借款增加"), (2011, "label:長期借款增加")))
        value = assemble(FilingLines(rows), "TW_GAAP", "long_term_debt_issued", "D:2012-01-01/2012-12-31")
        self.assertEqual((value.status, value.value), ("not_presented", None))
        result = result_for(twgaap_snapshot(rows), DECHOW_MODEL_ID, 2012)
        issue = next(c for c in result["components"] if c["variable"] == "issue")
        self.assertEqual((issue["status"], issue["value"]), ("not_computable", None))
        self.assertIsNone(result["score"])

    def test_zero_evidence_is_frozen_into_the_input_digest(self) -> None:
        base = twgaap_snapshot(twgaap_filing("G2012", 2012))
        self.assertTrue(base.literature_zero_evidence)
        self.assertEqual({z["status"] for z in base.literature_zero_evidence}, {"verified"})
        self.assertEqual(base.identity()["literature_dependency_versions"]["zero_evidence_policy"],
                         "literature_zero_evidence_policy_v2")
        self.assertIn("literature_zero_evidence", base.dependency_digests())
        result = result_for(base, DECHOW_MODEL_ID, 2012)
        self.assertEqual(result["status"], "computed", result["missing_inputs"])
        self.assertIn("verified_zero", result["input_evidence_types"])
        self.assertEqual(len(result["zero_evidence_used"]), 2)  # preferred stock t and t-1
        # moving 3110 -> 3350 keeps every identity verified but changes the proof's operands and fingerprint
        LEAVES[2012]["3110"] += 1
        try:
            changed = twgaap_snapshot(twgaap_filing("G2012", 2012))
        finally:
            LEAVES[2012]["3110"] -= 1
        self.assertNotEqual(base.input_digest, changed.input_digest)
        self.assertNotEqual(base.dependency_digests()["literature_zero_evidence"],
                            changed.dependency_digests()["literature_zero_evidence"])


# ------------------------------------------------------------------------------------------------ F02
class SourceIdentityGateTests(unittest.TestCase):
    def test_clean_original_reports_score_both_models(self) -> None:
        snapshot = twgaap_snapshot(twgaap_filing("G2012", 2012))
        for model_id in MODELS:
            self.assertEqual(result_for(snapshot, model_id, 2012)["status"], "computed", model_id)
        self.assertEqual(result_for(snapshot, BENEISH_MODEL_ID, 2011)["status"], "computed")

    def test_extractor_distinguishes_verified_mismatch_and_incomplete(self) -> None:
        clean = arithmetic_checks(twgaap_filing("G2012", 2012), 2012)
        self.assertEqual({item["status"] for item in clean.values()}, {"verified"})
        broken = arithmetic_checks(twgaap_filing("G2012", 2012, corrupt={(2012, "2XXX"): 1}), 2012)
        self.assertEqual(broken["balance_2012"]["status"], "mismatch")
        self.assertEqual(broken["balance_2012"]["difference_twd"],
                         dm.text(Decimal((1 - statement_column(LEAVES[2012])["2XXX"]) * 1000)))
        self.assertEqual(broken["balance_2011"]["status"], "verified")  # the other column is not blocked
        incomplete = arithmetic_checks(twgaap_filing("G2012", 2012, drop=((2012, "code:5910"),)), 2012)
        self.assertEqual(incomplete["gross_profit_2012"]["status"], "incomplete")
        self.assertEqual(incomplete["gross_profit_2012"]["missing_operands"], ["total:code:5910"])
        for key in ("pdf_page", "period_end", "unit", "statement_scope", "raw_sha256", "rule", "rule_version"):
            self.assertIn(key, broken["balance_2012"])

    def test_broken_balance_identity_never_reaches_a_published_score(self) -> None:
        snapshot = twgaap_snapshot(twgaap_filing("G2012", 2012, corrupt={(2012, "2XXX"): 1}))
        for model_id in MODELS:
            result = result_for(snapshot, model_id, 2012)
            self.assertIsNone(result["score"], model_id)
            self.assertIn(("total_assets", "t", "source_identity_mismatch"), statuses(result))
        # FY2011 uses the FY2011 report only: its verified facts remain usable
        self.assertEqual(result_for(snapshot, BENEISH_MODEL_ID, 2011)["status"], "computed")
        # the corrupted line itself is not usable either
        value = assemble(FilingLines(twgaap_filing("G2012", 2012, corrupt={(2012, "2XXX"): 1})), "TW_GAAP",
                         "total_liabilities", "I:2012-12-31")
        self.assertEqual(value.status, "source_identity_mismatch")
        self.assertIn("balance_2012", value.reasons[0])

    def test_inconsistent_gross_profit_blocks_sales_and_costs(self) -> None:
        snapshot = twgaap_snapshot(twgaap_filing("G2012", 2012, corrupt={(2012, "5910"): 1599}))
        beneish = result_for(snapshot, BENEISH_MODEL_ID, 2012)
        dechow = result_for(snapshot, DECHOW_MODEL_ID, 2012)
        self.assertIsNone(beneish["score"])
        self.assertIsNone(dechow["score"])
        self.assertIn(("sales", "t", "source_identity_mismatch"), statuses(beneish))
        self.assertIn(("cogs", "t", "source_identity_mismatch"), statuses(beneish))
        self.assertIn(("sales", "t", "source_identity_mismatch"), statuses(dechow))
        # balance-sheet lines of the same column are not blocked by an income-statement identity
        lines = FilingLines(twgaap_filing("G2012", 2012, corrupt={(2012, "5910"): 1599}))
        self.assertEqual(assemble(lines, "TW_GAAP", "total_assets", "I:2012-12-31").status, "computed")

    def test_incomplete_identity_and_unverified_page_identity_block_only_their_lines(self) -> None:
        rows = twgaap_filing("G2012", 2012, drop=((2012, "code:5910"),))
        value = assemble(FilingLines(rows), "TW_GAAP", "sales", "D:2012-01-01/2012-12-31")
        self.assertEqual(value.status, "source_identity_incomplete")
        self.assertEqual(assemble(FilingLines(rows), "TW_GAAP", "selling_expense", "D:2012-01-01/2012-12-31").status,
                         "computed")
        unit = twgaap_filing("G2012", 2012, page_identity={"unit": "unit_unverified"})
        self.assertEqual(assemble(FilingLines(unit), "TW_GAAP", "cash", "I:2012-12-31").status,
                         "source_identity_incomplete")
        # a pre-v2 record (no per-line identity coverage) is never admitted
        legacy = [{**row, "checks": {k: v for k, v in row["checks"].items() if k != "identities"}}
                  for row in twgaap_filing("G2012", 2012)]
        self.assertEqual(assemble(FilingLines(legacy), "TW_GAAP", "cash", "I:2012-12-31").status,
                         "source_identity_incomplete")

    def test_cash_flow_lines_without_an_identity_are_flagged(self) -> None:
        value = assemble(FilingLines(twgaap_filing("G2012", 2012)), "TW_GAAP", "depreciation", "D:2012-01-01/2012-12-31")
        self.assertEqual(value.status, "computed")
        self.assertIn("arithmetic_identity_not_available_for_line:label:各項折舊", value.warnings)

    def test_xbrl_balance_identity_gates_instants(self) -> None:
        rows = fixture_observations(overrides={"Equity": 551})  # FY2015: 1200 != 650 + 551
        result = result_for(literature_snapshot(rows), BENEISH_MODEL_ID)
        self.assertIsNone(result["score"])
        self.assertIn(("total_assets", "t", "source_identity_mismatch"), statuses(result))
        no_equity = [o for o in fixture_observations() if not (o["line_key"] == "Equity" and o["period_end"] == "2015-12-31")]
        result = result_for(literature_snapshot(no_equity), BENEISH_MODEL_ID)
        self.assertIn(("total_assets", "t", "source_identity_incomplete"), statuses(result))


# ------------------------------------------------------------------------------------------------ F03
class MappingConflictTests(unittest.TestCase):
    def test_disagreeing_aliases_fail_closed_without_a_first_alias_value(self) -> None:
        rows = fixture_observations(overrides={"OperatingRevenue": 1000}) + [obs("F2015", 2015, "Revenue", 2000)]
        lines = FilingLines([o for o in rows if o["filing_version_id"] == "F2015"])
        value = assemble(lines, "TIFRS", "sales", "D:2015-01-01/2015-12-31")
        self.assertEqual((value.status, value.value), ("mapping_conflict", None))
        self.assertIn("OperatingRevenue=1000", value.reasons[0])
        self.assertIn("Revenue=2000", value.reasons[0])
        self.assertEqual({c["line_key"] for c in value.candidates}, {"OperatingRevenue", "Revenue"})
        result = result_for(literature_snapshot(rows), BENEISH_MODEL_ID)
        self.assertIsNone(result["score"])
        self.assertIn(("sales", "t", "mapping_conflict"), statuses(result))

    def test_conflict_is_permutation_invariant(self) -> None:
        a = fixture_observations(overrides={"OperatingRevenue": 1000}) + [obs("F2015", 2015, "Revenue", 2000)]
        b = fixture_observations(overrides={"OperatingRevenue": 2000}) + [obs("F2015", 2015, "Revenue", 1000)]
        reference = None
        for rows in (a, b):
            for seed in range(3):
                shuffled = rows[:]
                random.Random(seed).shuffle(shuffled)
                lines = FilingLines([o for o in shuffled if o["filing_version_id"] == "F2015"])
                value = assemble(lines, "TIFRS", "sales", "D:2015-01-01/2015-12-31")
                self.assertEqual(value.status, "mapping_conflict")
                status = result_for(literature_snapshot(shuffled), BENEISH_MODEL_ID)["status"]
                reference = reference or status
                self.assertEqual(status, reference)
        digests = {literature_snapshot(sorted(a, key=lambda o: o["observation_id"])).input_digest,
                   literature_snapshot(list(reversed(a))).input_digest}
        self.assertEqual(len(digests), 1)

    def test_agreeing_aliases_are_all_recorded_and_in_the_digest(self) -> None:
        rows = fixture_observations() + [obs("F2015", 2015, "Revenue", 1200)]
        result = result_for(literature_snapshot(rows), BENEISH_MODEL_ID)
        self.assertEqual(result["status"], "computed")
        sales = next(i for c in result["components"] if c["variable"] == "SGI" for i in c["inputs"]
                     if i["metric"] == "sales" and i["relative_period"] == "t")
        self.assertEqual({o["line_key"] for o in sales["source_observations"]}, {"OperatingRevenue", "Revenue"})
        self.assertEqual(len(sales["alias_candidates"]), 2)
        changed = fixture_observations() + [obs("F2015", 2015, "Revenue", 1201)]
        self.assertNotEqual(literature_snapshot(rows).input_digest, literature_snapshot(changed).input_digest)


# ------------------------------------------------------------------------------------------------ F04
class CrossFilingCoherenceTests(unittest.TestCase):
    def test_overlap_mismatch_rejects_t_minus_2_and_names_metric_period_and_versions(self) -> None:
        rows = [{**o, "value": "105"} if (o["filing_version_id"], o["line_key"], o["period_end"])
                == ("F2014", "AccountsReceivableNet", "2014-12-31") else o for o in fixture_observations()]
        dechow = result_for(literature_snapshot(rows), DECHOW_MODEL_ID)
        self.assertIsNone(dechow["score"])
        self.assertIn(("receivables", "t-2", "cross_filing_overlap_mismatch"), statuses(dechow))
        reason = next(r for m in dechow["missing_inputs"] if m["status"] == "cross_filing_overlap_mismatch"
                      for r in m["reasons"])
        for text in ("receivables", "I:2014-12-31", "FY2015(restated)=100", "FY2014(restated)=105", "difference=-5"):
            self.assertIn(text, reason)
        # Beneish uses t and t-1 of the year-t filing only
        self.assertEqual(result_for(literature_snapshot(rows), BENEISH_MODEL_ID)["status"], "computed")

    def test_same_framework_different_version_needs_the_same_overlap(self) -> None:
        versions = [filing("F2015", 2015, "restated"), filing("F2014", 2014, "original")]
        rows = [{**o, "filing_version_type": "original"} if o["filing_version_id"] == "F2014" else o
                for o in fixture_observations()]
        snapshot = InputSnapshot(ticker="1785", context=RETRO, start_year=2015, end_year=2015,
                                 version_policy="latest_available", backend_name="unit")
        snapshot = freeze_literature_inputs(snapshot, versions, FakeStore(rows))
        dechow = result_for(snapshot, DECHOW_MODEL_ID)
        self.assertEqual(dechow["status"], "computed")
        self.assertIn("cross_filing_version_types:restated/original", dechow["validation_warnings"])
        self.assertIn("cross_filing_overlap_verified:total_assets:I:2014-12-31", dechow["validation_warnings"])
        changed = [{**o, "value": "1010"} if (o["filing_version_id"], o["line_key"], o["period_end"])
                   == ("F2014", "Assets", "2014-12-31") else o for o in rows]
        changed = [{**o, "value": "560"} if (o["filing_version_id"], o["line_key"], o["period_end"])
                   == ("F2014", "Equity", "2014-12-31") else o for o in changed]  # keep the balance identity true
        snapshot = freeze_literature_inputs(InputSnapshot(ticker="1785", context=RETRO, start_year=2015, end_year=2015,
                                                          version_policy="latest_available", backend_name="unit"),
                                            versions, FakeStore(changed))
        self.assertIn(("total_assets", "t-2", "cross_filing_overlap_mismatch"),
                      statuses(result_for(snapshot, DECHOW_MODEL_ID)))

    def test_unverifiable_overlap_is_not_computable(self) -> None:
        rows = [o for o in fixture_observations() if not (o["filing_version_id"] == "F2014"
                                                          and o["line_key"] == "AccountsReceivableNet"
                                                          and o["period_end"] == "2014-12-31")]
        self.assertIn(("receivables", "t-2", "cross_filing_overlap_unverifiable"),
                      statuses(result_for(literature_snapshot(rows), DECHOW_MODEL_ID)))

    def test_ifrs_transition_opening_balance_only_for_the_first_tifrs_year(self) -> None:
        def transition_rows(fid: str, year: int, *, opening_equity=500):
            rows = [{**o, "filing_version_id": fid, "filing_fiscal_year": year,
                     "observation_id": o["observation_id"].replace("F2015", fid),
                     "period_end": o["period_end"].replace("2015", str(year)).replace("2014", str(year - 1)),
                     "period_start": (o["period_start"] or "").replace("2015", str(year)).replace("2014", str(year - 1))
                     or None} for o in fixture_observations() if o["filing_version_id"] == "F2015"]
            opening = [{**o, "period_end": f"{year - 1}-01-01"} for o in
                       (obs(fid, year - 2, "AccountsReceivableNet", 80), obs(fid, year - 2, "CurrentAssets", 380),
                        *balance(fid, year - 2, 900, 400, opening_equity))]
            for row in opening:
                row["observation_id"] += "_opening"
            return rows + opening

        def run(year: int, rows: list[dict]):
            snapshot = InputSnapshot(ticker="1785", context=RETRO, start_year=year, end_year=year,
                                     version_policy="latest_available", backend_name="unit")
            snapshot = freeze_literature_inputs(snapshot, [filing(f"F{year}", year)], FakeStore(rows))
            return result_for(snapshot, DECHOW_MODEL_ID, year)

        first = run(2013, transition_rows("F2013", 2013))  # FY2012 is TW-GAAP: FY2013 is the first TIFRS year
        self.assertEqual(first["status"], "computed", first["missing_inputs"])
        self.assertIn("ifrs_transition_opening_balance_used_as_prior_year_end", first["validation_warnings"])
        self.assertIn("framework_transition:FY2012=TW_GAAP->FY2013=TIFRS", first["validation_warnings"])
        # the opening balance passes the same source gate (balance identity at 2012-01-01)
        broken = run(2013, transition_rows("F2013", 2013, opening_equity=501))
        self.assertIn(("total_assets", "t-2", "source_identity_mismatch"), statuses(broken))
        # a later year never falls back to an opening balance when its prior filing is missing
        later = run(2015, transition_rows("F2015", 2015))
        self.assertIsNone(later["score"])
        self.assertIn(("receivables", "t-2", "missing_t_minus_2"), statuses(later))
        self.assertNotIn("ifrs_transition_opening_balance_used_as_prior_year_end", later["validation_warnings"])

    def test_cross_filing_results_are_order_independent(self) -> None:
        rows = [{**o, "value": "105"} if (o["filing_version_id"], o["line_key"], o["period_end"])
                == ("F2014", "AccountsReceivableNet", "2014-12-31") else o for o in fixture_observations()]
        reference = compute_models(literature_snapshot(rows), MODELS)["results"]
        for seed in range(3):
            shuffled = rows[:]
            random.Random(seed).shuffle(shuffled)
            snapshot = literature_snapshot(shuffled, versions=[filing("F2014", 2014), filing("F2015", 2015)])
            self.assertEqual(compute_models(snapshot, MODELS)["results"], reference)


# ------------------------------------------------------------------------------------------------ page renderer
@unittest.skipUnless(shutil.which("node"), "node is required to execute the page renderer")
class TypedEvidenceRenderTests(unittest.TestCase):
    def test_typed_statuses_zero_proof_and_overlap_are_visible(self) -> None:
        from tests.test_research_ui_chain import render

        def page(snapshot, year):
            computed = compute_models(snapshot, MODELS)
            data = {**compare(computed), "models": computed}
            return render({"literature": data, "literatureYear": {"data": data, "year": year}})

        zero = page(twgaap_snapshot(twgaap_filing("G2012", 2012)), 2012)
        self.assertIn("經證明之 0（權益區段完整列舉）", zero["literatureYear"])
        self.assertIn("twgaap_equity_section_exhaustive_enumeration", zero["literatureYear"])
        self.assertIn("重疊年度 I:2011-12-31：verified", zero["literatureYear"])
        conflict = page(literature_snapshot(fixture_observations(overrides={"OperatingRevenue": 1000})
                                            + [obs("F2015", 2015, "Revenue", 2000)]), 2015)
        self.assertIn("同義科目數值不一致（不依順序選取）", conflict["literature"])
        overlap = page(literature_snapshot([{**o, "value": "105"} if (o["filing_version_id"], o["line_key"],
                                                                      o["period_end"]) == ("F2014", "AccountsReceivableNet",
                                                                                           "2014-12-31") else o
                                            for o in fixture_observations()]), 2015)
        self.assertIn("t−2 跨申報重疊年度不一致", overlap["literature"])
        broken = page(twgaap_snapshot(twgaap_filing("G2012", 2012, corrupt={(2012, "2XXX"): 1})), 2012)
        self.assertIn("原始報表恆等式不符（阻擋）", broken["literature"])
        for view in (*zero.values(), *conflict.values(), *overlap.values(), *broken.values()):
            self.assertNotIn("低風險", view)


# ------------------------------------------------------------------------------------------------ REAL tier
@unittest.skipUnless(HAS_REAL, "approved local 1785 archive not present")
class RealDataIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from scripts.ingest_literature_inputs import run

        from app.services.financial_research.service import ResearchConfig, ResearchService

        cls.tmp = tempfile.TemporaryDirectory()
        cls.store_path = str(Path(cls.tmp.name) / "literature_inputs.sqlite3")
        run("1785", database=str(DATABASE), raw_root=str(RAW), store_path=cls.store_path, dry_run=False)
        cls.service = ResearchService(ResearchConfig(database=str(DATABASE), raw_root=str(RAW),
                                                     conference_root=str(ROOT / "data" / "historical-conference-pdfs"),
                                                     literature_database=cls.store_path))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def matrix(self, policy: str) -> dict:
        return self.service.literature_coverage("1785", RETRO, version_policy=policy, start_year=2011, end_year=2025)

    def test_reviewed_latest_source_empty_entries_are_not_presented(self) -> None:
        rows = self.matrix("latest_available")["rows"]
        empty = {(r["fiscal_year"], r["formula_component"]) for r in rows
                 if r["readiness"] == "complete" and not r["sources"]}
        self.assertEqual(empty, set())
        not_presented = {(r["fiscal_year"], r["formula_component"]) for r in rows if r["input_status"] == "not_presented"}
        self.assertEqual(not_presented, {(y, "stock_issued") for y in (2013, 2014, 2015, 2016, 2023, 2024, 2025)}
                         | {(2018, "long_term_debt_issued")})

    def test_reviewed_original_preferred_stock_entries_are_verified_zero(self) -> None:
        matrix = self.matrix("original_only")
        preferred = [r for r in matrix["rows"] if r["formula_component"] == "preferred_stock" and r["readiness"] == "complete"]
        self.assertEqual(sorted((r["fiscal_year"], r["relative_period"]) for r in preferred),
                         [(2011, "t"), (2011, "t-1"), (2012, "t"), (2012, "t-1")])
        for row in preferred:
            self.assertEqual(row["evidence_type"], "verified_zero")
            self.assertEqual(row["zero_evidence"]["status"], "verified")
            self.assertEqual(row["zero_evidence"]["section_total_twd"], row["zero_evidence"]["enumerated_sum_twd"])
            self.assertTrue(row["sources"])
        computed = self.service.literature_compute("1785", RETRO, model_ids=MODELS, start_year=2011, end_year=2012,
                                                   version_policy="original_only")
        dechow = {r["fiscal_year"]: r for r in computed["results"][DECHOW_MODEL_ID]}
        self.assertEqual(dechow[2012]["score"], "0.892005")
        self.assertIn("verified_zero", dechow[2012]["input_evidence_types"])

    def test_real_original_report_identities_are_all_verified(self) -> None:
        diagnostics = [d for d in self.service.literature_store.list_diagnostics("1785")
                       if d.get("extractor_version") == TWGAAP_PDF_EXTRACTOR_VERSION and d.get("arithmetic_checks")]
        self.assertEqual(sorted(d["fiscal_year"] for d in diagnostics), [2011, 2012])
        for diagnostic in diagnostics:
            self.assertEqual(len(diagnostic["arithmetic_checks"]), 20)
            self.assertEqual(set(diagnostic["arithmetic_checks"].values()), {"verified"})
            self.assertEqual(diagnostic["failed_identities"], [])

    def test_corrupted_copy_of_the_real_fy2012_report_never_scores(self) -> None:
        observations = self.service.literature_store.list_observations("1785")
        fy2012 = [o for o in observations if o["filing_fiscal_year"] == 2012 and o["extractor_version"]
                  == TWGAAP_PDF_EXTRACTOR_VERSION]
        corrupted = [{**o, "value": str(int(o["value"]) + 1000)} if o["line_key"] == "code:3XXX"
                     and o["period_end"] == "2012-12-31" else o for o in fy2012]
        details = arithmetic_checks(corrupted, 2012)
        self.assertEqual(details["balance_2012"]["status"], "mismatch")
        self.assertEqual(details["equity_enumeration_2012"]["status"], "mismatch")
        rebuilt = [{**o, "checks": {**o["checks"], "identities": covering_identities(o, details)}} for o in corrupted]
        others = [o for o in observations if o not in fy2012]

        class Store:
            def list_observations(self, ticker, **_):
                return others + rebuilt

        snapshot = self.service.literature_snapshot("1785", RETRO, start_year=2011, end_year=2012,
                                                    version_policy="original_only")
        snapshot = freeze_literature_inputs(snapshot, self.service.backend.list_filing_versions("1785", 2009, 2012),
                                            Store())
        results = compute_models(snapshot, MODELS)["results"]
        beneish = {r["fiscal_year"]: r for r in results[BENEISH_MODEL_ID]}
        dechow = {r["fiscal_year"]: r for r in results[DECHOW_MODEL_ID]}
        self.assertIsNone(beneish[2012]["score"])
        self.assertIsNone(dechow[2012]["score"])
        self.assertEqual(beneish[2011]["score"], "-1.730106")  # FY2011 report is verified and stays usable


if __name__ == "__main__":
    unittest.main()
