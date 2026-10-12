"""Literature-model input hardening (independent review of df0fc44, findings R01 and R02).

- R01: a ``sum`` metric's statement anchor may have several candidate lines (TIFRS operating cash flow, TW-GAAP total
  assets and operating cash flow). Every present candidate must pass the source gate and carry the same value; a
  conflicting candidate is ``mapping_conflict`` (reason ``anchor_conflict:...``), never a first-candidate choice.
- R02: a frozen ``verified_zero`` proof is re-derived from the current filing observations at its point of use
  (``assemble``). A stale, altered, cross-filing, cross-period, wrong-version or duplicated proof is ``not_presented``
  with ``zero_evidence_invalid:<reason>`` and never raises.

Synthetic, official-shaped observations only (the generators of ``test_literature_data_integrity`` and
``test_literature_models``); nothing here reads or writes approved data.
"""

from __future__ import annotations

import copy
import random
import unittest
from decimal import Decimal
from unittest import mock

from app.services.financial_research.input_snapshot import digest
from app.services.financial_research.literature_comparison import compute_models
from app.services.financial_research.literature_inputs import (
    ANCHORS,
    SOURCE_GATE_VERSION,
    ZERO_POLICY_VERSION,
    ZERO_RULE_TWGAAP_EQUITY,
    FilingLines,
    assemble,
    prove_zero,
)
from app.services.financial_research.literature_method_registry import BENEISH_MODEL_ID, DECHOW_MODEL_ID
from tests.test_literature_data_integrity import LEAVES, statuses, twgaap_filing, twgaap_snapshot
from tests.test_literature_models import fixture_observations, literature_snapshot, obs, result_for

MODELS = [BENEISH_MODEL_ID, DECHOW_MODEL_ID]
DURATION_2015 = "D:2015-01-01/2015-12-31"
DURATION_2012 = "D:2012-01-01/2012-12-31"
PREFERRED_2012 = ("TW_GAAP", "preferred_stock", "I:2012-12-31")


def flow(fid: str, year: int, line: str, value) -> dict:
    """A TIFRS cash-flow (duration) XBRL observation."""
    return {**obs(fid, year, line, value), "period_type": "duration", "period_start": f"{year}-01-01"}


def twgaap_line(row_like: dict, line_key: str, value_twd: int, *, concept: str | None = None, **checks) -> dict:
    """An extra TW-GAAP PDF line next to ``row_like`` (same filing, column and page), with its own observation id."""
    return {**row_like, "observation_id": f"{row_like['observation_id']}_extra_{line_key}_{value_twd}",
            "line_key": line_key, "source_concept": concept or line_key, "value": str(value_twd),
            "published_value": f"{value_twd // 1000:,}",
            "checks": {"unit": "verified", "fiscal_year": "verified", "scope": "verified", "identities": {}, **checks}}


def row(rows: list[dict], line_key: str, period_end: str) -> dict:
    return next(r for r in rows if r["line_key"] == line_key and r["period_end"] == period_end)


# ------------------------------------------------------------------------------------------------------- R01
class AnchorCandidateTests(unittest.TestCase):
    def tifrs_lines(self, *extra: dict) -> FilingLines:
        base = [flow("F2015", 2015, "ProceedsFromIssuingShares", 50)]
        return FilingLines(base + list(extra))

    def test_reviewer_repro_conflicting_cash_flow_anchors_never_compute(self) -> None:
        lines = self.tifrs_lines(flow("F2015", 2015, "CashFlowsFromUsedInOperatingActivities", 100),
                                 flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 200))
        value = assemble(lines, "TIFRS", "stock_issued", DURATION_2015)
        self.assertEqual((value.status, value.value, value.evidence_type), ("mapping_conflict", None, None))
        self.assertEqual(value.reasons, ["anchor_conflict:cash_flow_operating:CashFlowsFromUsedInOperatingActivities=100;"
                                         "NetCashFlowsFromUsedInOperatingActivities=200"])
        self.assertEqual({(c["line_key"], c["value"]) for c in value.candidates},
                         {("CashFlowsFromUsedInOperatingActivities", "100"),
                          ("NetCashFlowsFromUsedInOperatingActivities", "200")})
        self.assertEqual(value.observations, [])

    def test_agreeing_single_and_missing_anchor_candidates(self) -> None:
        agreeing = self.tifrs_lines(flow("F2015", 2015, "CashFlowsFromUsedInOperatingActivities", 100),
                                    flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 100))
        single_first = self.tifrs_lines(flow("F2015", 2015, "CashFlowsFromUsedInOperatingActivities", 100))
        single_second = self.tifrs_lines(flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 200))
        for lines in (agreeing, single_first, single_second):
            value = assemble(lines, "TIFRS", "stock_issued", DURATION_2015)
            self.assertEqual((value.status, value.value, value.evidence_type),
                             ("computed", Decimal(50), "presented_lines_sum"))
            self.assertEqual([o["line_key"] for o in value.observations], ["ProceedsFromIssuingShares"])
        missing = assemble(self.tifrs_lines(), "TIFRS", "stock_issued", DURATION_2015)
        self.assertEqual((missing.status, missing.value), ("anchor_missing", None))
        self.assertEqual(missing.reasons, ["statement_anchor_cash_flow_operating_not_present"])

    def test_conflicting_duplicate_anchor_observation_is_ambiguous(self) -> None:
        lines = self.tifrs_lines(flow("F2015", 2015, "CashFlowsFromUsedInOperatingActivities", 100),
                                 flow("F2015", 2015, "CashFlowsFromUsedInOperatingActivities", 101),
                                 flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 100))
        value = assemble(lines, "TIFRS", "stock_issued", DURATION_2015)
        self.assertEqual((value.status, value.value), ("ambiguous_version", None))
        self.assertEqual(value.reasons, ["CashFlowsFromUsedInOperatingActivities:conflicting_duplicate_line_values"])
        # a conflicting duplicate on the *second* candidate is found as well (not only the first present one)
        lines = self.tifrs_lines(flow("F2015", 2015, "CashFlowsFromUsedInOperatingActivities", 100),
                                 flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 100),
                                 flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 101))
        value = assemble(lines, "TIFRS", "stock_issued", DURATION_2015)
        self.assertEqual((value.status, value.value), ("ambiguous_version", None))
        self.assertEqual(value.reasons, ["NetCashFlowsFromUsedInOperatingActivities:conflicting_duplicate_line_values"])

    def test_outcome_is_invariant_to_observation_and_candidate_order(self) -> None:
        rows = [flow("F2015", 2015, "ProceedsFromIssuingShares", 50),
                flow("F2015", 2015, "CashFlowsFromUsedInOperatingActivities", 100),
                flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 200)]
        reference = assemble(FilingLines(rows), "TIFRS", "stock_issued", DURATION_2015)
        anchors = ANCHORS["TIFRS"]["cash_flow_operating"]
        for order in (anchors, tuple(reversed(anchors))):
            with mock.patch.dict(ANCHORS["TIFRS"], {"cash_flow_operating": order}):
                for seed in range(4):
                    shuffled = rows[:]
                    random.Random(seed).shuffle(shuffled)
                    value = assemble(FilingLines(shuffled), "TIFRS", "stock_issued", DURATION_2015)
                    self.assertEqual((value.status, value.value, value.reasons),
                                     (reference.status, reference.value, reference.reasons))
                    self.assertEqual(sorted(c["line_key"] for c in value.candidates),
                                     sorted(c["line_key"] for c in reference.candidates))

    def test_twgaap_total_assets_anchor_candidates(self) -> None:
        rows = twgaap_filing("G2012", 2012)
        assets = row(rows, "code:1XXX", "2012-12-31")
        agreeing = rows + [twgaap_line(assets, "label:資產總計", int(assets["value"]))]
        value = assemble(FilingLines(agreeing), "TW_GAAP", "investments_and_advances", "I:2012-12-31")
        self.assertEqual((value.status, value.value), ("computed", Decimal(170000)))
        conflicting = rows + [twgaap_line(assets, "label:資產總計", int(assets["value"]) + 1000)]
        value = assemble(FilingLines(conflicting), "TW_GAAP", "investments_and_advances", "I:2012-12-31")
        self.assertEqual((value.status, value.value), ("mapping_conflict", None))
        self.assertTrue(value.reasons[0].startswith("anchor_conflict:assets:code:1XXX="), value.reasons)
        # an otherwise valid first candidate followed by a candidate the source gate rejects
        gated = rows + [twgaap_line(assets, "label:資產總計", int(assets["value"]), unit="unit_unverified")]
        value = assemble(FilingLines(gated), "TW_GAAP", "investments_and_advances", "I:2012-12-31")
        self.assertEqual((value.status, value.value), ("source_identity_incomplete", None))
        self.assertEqual(value.reasons, ["anchor:label:資產總計:page_identity_unverified:unit"])
        # no anchor candidate at all
        no_anchor = [r for r in rows if not (r["line_key"] == "code:1XXX" and r["period_end"] == "2012-12-31")]
        value = assemble(FilingLines(no_anchor), "TW_GAAP", "investments_and_advances", "I:2012-12-31")
        self.assertEqual((value.status, value.value), ("anchor_missing", None))

    def test_twgaap_operating_cash_flow_anchor_candidates(self) -> None:
        rows = twgaap_filing("G2012", 2012)
        anchor = row(rows, "label:營業活動之淨現金流入", "2012-12-31")
        same = rows + [twgaap_line(anchor, "label:營業活動之淨現金流入(出)", int(anchor["value"]))]
        value = assemble(FilingLines(same), "TW_GAAP", "long_term_debt_issued", DURATION_2012)
        self.assertEqual((value.status, value.value), ("computed", Decimal(3000000)))
        conflict = rows + [twgaap_line(anchor, "label:營業活動之淨現金流出", int(anchor["value"]) - 5000)]
        value = assemble(FilingLines(conflict), "TW_GAAP", "long_term_debt_issued", DURATION_2012)
        self.assertEqual((value.status, value.value), ("mapping_conflict", None))
        self.assertIn("label:營業活動之淨現金流出=895000", value.reasons[0])
        gated = rows + [twgaap_line(anchor, "label:營業活動之淨現金流入(出)", int(anchor["value"]),
                                    identities={"cash_flow_x": "mismatch"})]
        value = assemble(FilingLines(gated), "TW_GAAP", "long_term_debt_issued", DURATION_2012)
        self.assertEqual((value.status, value.value), ("source_identity_mismatch", None))

    def test_conflicting_anchor_blocks_the_full_dechow_score_and_nothing_else(self) -> None:
        rows = fixture_observations() + [flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 200)]
        dechow = result_for(literature_snapshot(rows), DECHOW_MODEL_ID)
        self.assertIsNone(dechow["score"])
        # the positive 250 issuance line is no longer evidence: its cash-flow statement anchor is in conflict
        self.assertIn(("issuance_evidence", "t", "issuance_absence_not_evidenced"), statuses(dechow))
        issue = next(c for c in dechow["components"] if c["variable"] == "issue")
        self.assertEqual(issue["evidence"], [])
        self.assertIn(("mapping_conflict", "long_term_debt_issued"),
                      {(r["code"], r.get("metric")) for r in issue["reasons"]})
        # Beneish reads no cash-flow-anchored sum and keeps the hand-calculated value
        self.assertEqual(result_for(literature_snapshot(rows), BENEISH_MODEL_ID)["score"], "-2.243743")
        agreeing = fixture_observations() + [flow("F2015", 2015, "NetCashFlowsFromUsedInOperatingActivities", 100)]
        self.assertEqual(result_for(literature_snapshot(agreeing), DECHOW_MODEL_ID)["status"],
                         result_for(literature_snapshot(), DECHOW_MODEL_ID)["status"])

    def test_one_of_alias_rule_and_non_anchor_inputs_are_unchanged(self) -> None:
        rows = fixture_observations(overrides={"OperatingRevenue": 1000}) + [obs("F2015", 2015, "Revenue", 2000)]
        value = assemble(FilingLines([o for o in rows if o["filing_version_id"] == "F2015"]), "TIFRS", "sales",
                         DURATION_2015)
        self.assertEqual((value.status, value.value), ("mapping_conflict", None))
        self.assertEqual(value.reasons, ["mapping_conflict:OperatingRevenue=1000;Revenue=2000"])
        reference = literature_snapshot()
        self.assertEqual(result_for(reference, BENEISH_MODEL_ID)["score"], "-2.243743")
        self.assertEqual(reference.identity()["literature_dependency_versions"]["source_gate"], SOURCE_GATE_VERSION)
        self.assertEqual(SOURCE_GATE_VERSION, "literature_source_gate_v2")


# ------------------------------------------------------------------------------------------------------- R02
class ZeroProofVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = twgaap_filing("G2012", 2012)
        self.proof = prove_zero(FilingLines(self.rows), *PREFERRED_2012)
        self.assertEqual(self.proof["status"], "verified")

    def check(self, rows: list[dict], proofs: list, expected_reason: str) -> None:
        value = assemble(FilingLines(rows, proofs), *PREFERRED_2012)
        self.assertEqual((value.status, value.value, value.evidence_type, value.zero_evidence),
                         ("not_presented", None, None, None))
        self.assertEqual(value.observations, [])
        self.assertIn(expected_reason, value.reasons)

    def forged(self, **changes) -> dict:
        record = {**copy.deepcopy(self.proof), **changes}
        record["evidence_fingerprint"] = digest({k: v for k, v in record.items() if k != "evidence_fingerprint"})
        return record

    def test_valid_proof_is_verified_zero_with_its_operands(self) -> None:
        value = assemble(FilingLines(self.rows, [self.proof]), *PREFERRED_2012)
        self.assertEqual((value.status, value.value, value.evidence_type), ("computed", Decimal(0), "verified_zero"))
        self.assertEqual(value.zero_evidence, self.proof)
        self.assertEqual(value.zero_evidence["rule_version"], ZERO_POLICY_VERSION)
        self.assertEqual(ZERO_POLICY_VERSION, "literature_zero_evidence_policy_v2")
        self.assertEqual([o["observation_id"] for o in value.observations],
                         [o["observation_id"] for o in self.proof["operands"]])

    def test_reviewer_repro_tampered_operands_total_and_fingerprint(self) -> None:
        tampered = {**copy.deepcopy(self.proof), "operands": [], "section_total_twd": "123456789",
                    "evidence_fingerprint": "0" * 64}
        self.check(self.rows, [tampered], "zero_evidence_invalid:evidence_fingerprint_mismatch")
        self.check(self.rows, [{**self.proof, "evidence_fingerprint": "0" * 64}],
                   "zero_evidence_invalid:evidence_fingerprint_mismatch")
        # a self-consistent forgery (fingerprint re-signed) is caught by the re-derivation; the re-signed fingerprint
        # necessarily differs from the re-derived one as well
        stale = "zero_evidence_invalid:stale_or_altered:evidence_fingerprint,"
        self.check(self.rows, [self.forged(operands=[])], stale + "operands")
        self.check(self.rows, [self.forged(section_total_twd="123456789")], stale + "section_total_twd")
        altered = copy.deepcopy(self.proof["operands"])
        altered[1]["value"] = str(int(altered[1]["value"]) + 1)
        self.check(self.rows, [self.forged(operands=altered)], stale + "operands")
        renamed = copy.deepcopy(self.proof["operands"])
        renamed[0]["observation_id"] = "lobs2_forged"
        self.check(self.rows, [self.forged(operands=renamed)], stale + "operands")
        self.check(self.rows, [self.forged(findings=[])], stale + "findings")

    def test_reviewer_repro_missing_referenced_observation_never_raises(self) -> None:
        dropped = [r for r in self.rows if not (r["line_key"] == "code:3350" and r["period_end"] == "2012-12-31")]
        self.check(dropped, [self.proof], "zero_evidence_invalid:recomputed_status:mismatch")

    def test_changed_operand_values_with_the_same_ids_are_stale(self) -> None:
        # one member changed: the equity enumeration no longer holds
        changed = [{**r, "value": str(int(r["value"]) + 1000)} if r["line_key"] == "code:3110"
                   and r["period_end"] == "2012-12-31" else r for r in self.rows]
        self.check(changed, [self.proof], "zero_evidence_invalid:recomputed_status:mismatch")
        # two members moved by the same amount: the enumeration still holds, but the frozen operands are stale
        moved = [{**r, "value": str(int(r["value"]) + (1000 if r["line_key"] == "code:3110" else -1000))}
                 if r["line_key"] in ("code:3110", "code:3350") and r["period_end"] == "2012-12-31" else r
                 for r in self.rows]
        self.assertEqual(prove_zero(FilingLines(moved), *PREFERRED_2012)["status"], "verified")
        self.check(moved, [self.proof], "zero_evidence_invalid:stale_or_altered:evidence_fingerprint,operands")

    def test_wrong_identity_fields_are_rejected(self) -> None:
        cases = {"rule_version": "literature_zero_evidence_policy_v1", "rule": "some_other_rule",
                 "filing_version_id": "G2011", "accounting_framework": "TIFRS", "metric": "preferred_stock_x",
                 "period": "I:2011-12-31", "status": "verified_by_caller"}
        for field_name, wrong in cases.items():
            with self.subTest(field_name):
                # a re-signed forgery; a record filed under another metric/period never reaches this lookup at all
                value = assemble(FilingLines(self.rows, [self.forged(**{field_name: wrong})]), *PREFERRED_2012)
                self.assertEqual((value.status, value.value), ("not_presented", None))
                self.assertTrue(any(r.startswith(("zero_evidence_invalid:", "zero_evidence_not_verified:"))
                                    for r in value.reasons), value.reasons)
        self.check(self.rows, [self.forged(rule_version="literature_zero_evidence_policy_v1")],
                   "zero_evidence_invalid:rule_version_differs")
        self.check(self.rows, [self.forged(filing_version_id="G2011")], "zero_evidence_invalid:filing_version_id_differs")
        self.check(self.rows, [self.forged(accounting_framework="TIFRS")],
                   "zero_evidence_invalid:accounting_framework_differs")
        self.check(self.rows, [self.forged(rule="some_other_rule")], "zero_evidence_invalid:rule_differs")

    def test_proof_from_another_filing_or_period_is_rejected(self) -> None:
        other_period = prove_zero(FilingLines(self.rows), "TW_GAAP", "preferred_stock", "I:2011-12-31")
        self.assertEqual(other_period["status"], "verified")
        moved = {**other_period, "period": "I:2012-12-31"}  # relabelled without re-signing
        self.check(self.rows, [moved], "zero_evidence_invalid:evidence_fingerprint_mismatch")
        relabelled = {**other_period, "period": "I:2012-12-31"}  # relabelled and re-signed: operands are FY2011's
        relabelled["evidence_fingerprint"] = digest({k: v for k, v in relabelled.items() if k != "evidence_fingerprint"})
        value = assemble(FilingLines(self.rows, [relabelled]), *PREFERRED_2012)
        self.assertEqual((value.status, value.value), ("not_presented", None))
        stale = next(r for r in value.reasons if r.startswith("zero_evidence_invalid:stale_or_altered:"))
        self.assertIn("operands", stale.split(":")[-1].split(","))
        # the same rows filed under another filing version produce a valid proof for *that* filing only
        foreign_rows = [{**r, "filing_version_id": "G9999", "observation_id": r["observation_id"] + "_g9999"}
                        for r in self.rows]
        foreign = prove_zero(FilingLines(foreign_rows), *PREFERRED_2012)
        self.assertEqual(foreign["status"], "verified")
        self.check(self.rows, [foreign], "zero_evidence_invalid:filing_version_id_differs")

    def test_equity_line_or_preferred_line_added_after_the_proof(self) -> None:
        total = row(self.rows, "code:3XXX", "2012-12-31")
        extra_member = self.rows + [twgaap_line(total, "code:3140", 0)]
        self.check(extra_member, [self.proof], self._stale_after(extra_member))
        preferred = self.rows + [twgaap_line(total, "code:3130", 0, concept="code:3130 特別股股本")]
        self.check(preferred, [self.proof], "zero_evidence_invalid:recomputed_status:preferred_line_present")

    def _stale_after(self, rows: list[dict]) -> str:
        recomputed = prove_zero(FilingLines(rows), *PREFERRED_2012)
        self.assertEqual(recomputed["status"], "verified")
        differing = sorted(k for k in set(self.proof) | set(recomputed) if self.proof.get(k) != recomputed.get(k))
        self.assertIn("operands", differing)
        return "zero_evidence_invalid:stale_or_altered:" + ",".join(differing)

    def test_duplicate_and_malformed_proof_records_fail_closed(self) -> None:
        self.check(self.rows, [self.proof, copy.deepcopy(self.proof)], "zero_evidence_invalid:duplicate_proof_records:2")
        self.check(self.rows, [self.proof, self.forged(section_total_twd="1")],
                   "zero_evidence_invalid:duplicate_proof_records:2")
        for malformed in (None, "verified", 7, [], {}, {"metric": "preferred_stock"}, {"metric": ["x"], "period": {}}):
            with self.subTest(malformed=malformed):
                self.check(self.rows, [malformed],
                           "zero_evidence_not_verified:twgaap_equity_section_exhaustive_enumeration:not_evaluated")
        for broken in ({**self.proof, "operands": None}, {**self.proof, "operands": [None, 3]},
                       {**self.proof, "evidence_fingerprint": None}, {**self.proof, "status": None},
                       {k: v for k, v in self.proof.items() if k != "operands"},
                       {**self.proof, "findings": {"a": object()}}):
            with self.subTest(broken=sorted(broken)):
                value = assemble(FilingLines(self.rows, [broken]), *PREFERRED_2012)
                self.assertEqual((value.status, value.value), ("not_presented", None))

    def test_explicit_printed_zero_is_kept_and_issuance_is_never_zero(self) -> None:
        LEAVES[2012]["3120"] = 0
        try:
            rows = twgaap_filing("G2012", 2012)
        finally:
            del LEAVES[2012]["3120"]
        value = assemble(FilingLines(rows, [prove_zero(FilingLines(rows), *PREFERRED_2012)]), *PREFERRED_2012)
        self.assertEqual((value.status, value.value, value.evidence_type), ("computed", Decimal(0), "explicit_zero"))
        self.assertIsNone(value.zero_evidence)
        dropped = twgaap_filing("G2012", 2012, drop=((2012, "label:長期借款增加"),))
        value = assemble(FilingLines(dropped, [self.proof]), "TW_GAAP", "long_term_debt_issued", DURATION_2012)
        self.assertEqual((value.status, value.value), ("not_presented", None))
        self.assertIn("zero_inference_not_permitted_for_metric", value.reasons)

    def test_full_dechow_panel_with_tampered_snapshot_proofs(self) -> None:
        snapshot = twgaap_snapshot(twgaap_filing("G2012", 2012))
        self.assertEqual(result_for(snapshot, DECHOW_MODEL_ID, 2012)["status"], "computed")
        for mutate in (lambda z: z.update(operands=[]), lambda z: z.update(evidence_fingerprint="0" * 64),
                       lambda z: z.update(rule_version="literature_zero_evidence_policy_v1"),
                       lambda z: z.update(section_total_twd="123456789"), lambda z: z.pop("operands")):
            tampered = copy.deepcopy(snapshot)
            for record in tampered.literature_zero_evidence:
                if record["filing_version_id"] == "G2012":
                    mutate(record)
            result = result_for(tampered, DECHOW_MODEL_ID, 2012)
            self.assertIsNone(result["score"])
            self.assertIn(("preferred_stock", "t", "not_presented"), statuses(result))
            reasons = [r for m in result["missing_inputs"] if m["metric"] == "preferred_stock" for r in m["reasons"]]
            self.assertTrue(any("zero_evidence_invalid:" in r for r in reasons), reasons)
            self.assertNotIn("verified_zero", result["input_evidence_types"])
        # the stored observations disappear but the proof stays: no KeyError, just not computable
        missing = copy.deepcopy(snapshot)
        missing.literature_observations = [o for o in missing.literature_observations
                                           if not (o["filing_version_id"] == "G2012" and o["line_key"] == "code:3350")]
        result = result_for(missing, DECHOW_MODEL_ID, 2012)
        self.assertIsNone(result["score"])

    def test_proofs_and_digests_are_order_independent(self) -> None:
        reference = twgaap_snapshot(twgaap_filing("G2012", 2012))
        results = compute_models(reference, MODELS)["results"]
        for seed in range(3):
            shuffled = twgaap_filing("G2012", 2012)
            random.Random(seed).shuffle(shuffled)
            prior = twgaap_filing("G2011", 2011)
            random.Random(seed + 10).shuffle(prior)
            snapshot = twgaap_snapshot(shuffled, prior)
            self.assertEqual(snapshot.input_digest, reference.input_digest)
            self.assertEqual(snapshot.literature_zero_evidence, reference.literature_zero_evidence)
            self.assertEqual(compute_models(snapshot, MODELS)["results"], results)
        dechow = next(r for r in results[DECHOW_MODEL_ID] if r["fiscal_year"] == 2012)
        self.assertEqual(dechow["status"], "computed")
        self.assertEqual(len(dechow["zero_evidence_used"]), 2)
        self.assertEqual({z["rule"] for z in reference.literature_zero_evidence}, {ZERO_RULE_TWGAAP_EQUITY})


if __name__ == "__main__":
    unittest.main()
