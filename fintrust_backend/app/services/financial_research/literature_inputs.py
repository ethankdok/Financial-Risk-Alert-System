"""Literature-model input contract: COMPUSTAT-item → Taiwan statement-line mapping, assembly and period panels.

Inputs are *line-level* official observations (see ``literature_extraction``): one value per statement line, filing
version, statement period and source artifact, each with its raw SHA-256 and locator. This module is pure: it maps
lines to the paper's COMPUSTAT items, assembles one value per (filing, period, metric) and serves the t / t-1 / t-2
panel a model needs. Nothing is fetched, filled or guessed here.

Mapping rules (mapping ``literature_input_mapping_v2``, DRAFT for the method owner):

- ``one_of``: the listed candidate lines (aliases) present in the filing/period. All present candidates must agree;
  candidates that disagree are ``mapping_conflict`` (finding LIT-F03) with every candidate and value in the reasons,
  never a first-in-list choice. No official taxonomy precedence is applied.
- ``sum``: the sum of the listed lines present, provided the statement ``anchor`` total is present for the same
  filing/period (so the statement was parsed). A listed line that the statement does not present is recorded in
  ``lines_not_presented`` (component-level presentation rule: the remaining presented lines are summed). ``required``
  lines must be present. If *no* listed line is presented the metric is ``not_presented`` — never ``computed/0``
  (finding LIT-F01) — unless the mapping names a zero-evidence rule of ``ZERO_POLICY_VERSION`` whose proof is
  verified for that filing/period (``verified_zero``). The frozen proof is re-derived from the current observations
  where it is used and must match field for field (finding R02); otherwise ``not_presented`` with a
  ``zero_evidence_invalid:<reason>`` reason. An anchor with several candidate lines follows the ``one_of`` agreement
  rule: every present candidate is gate- and value-checked (finding R01); disagreeing candidates are
  ``mapping_conflict`` with an ``anchor_conflict:<anchor>:...`` reason.
- ``difference``: ``minuend - subtrahend``, both required (each side follows the ``one_of`` agreement rule).
- a printed 0 or dash is an explicit published zero (``explicit_zero``); a missing required line is
  ``missing_input`` (never 0).

Typed evidence of every computed value: ``explicit_line``, ``explicit_zero``, ``presented_lines_sum``,
``derived_difference`` or ``verified_zero``. Non-computed statuses: ``missing_input``, ``not_presented``,
``anchor_missing``, ``ambiguous_version``, ``mapping_conflict``, ``source_identity_mismatch``,
``source_identity_incomplete``, ``missing_t_minus_2``, ``cross_filing_overlap_mismatch``,
``cross_filing_overlap_unverifiable``.

Source gate (``SOURCE_GATE_VERSION``, finding LIT-F02): a TW-GAAP PDF line is usable only when its page identity
(unit, ROC year, consolidated title) is verified and every statement identity covering the line for its fiscal-year
column is ``verified``; ``mismatch`` blocks it as ``source_identity_mismatch`` and ``incomplete`` as
``source_identity_incomplete``. Lines no catalogued identity covers (cash-flow labels) are admitted on the page
identity alone and flagged ``arithmetic_identity_not_available_for_line``. A TIFRS XBRL balance (instant) fact is
usable only when ``Assets = Liabilities + Equity`` is verified for that instant in the same filing.

Period panel rules (``literature_panel_v2``, finding LIT-F04): values for t and t-1 come from the fiscal-year-t filing
(current and comparative columns of one document). t-2 balances come from the comparative column of the
fiscal-year-(t-1) filing of the same version series and accounting framework, and only after the overlapping year t-1
has been verified: the metric's t-1 value in the year-t filing must equal its value in the year-(t-1) filing
(``cross_filing_overlap_mismatch`` otherwise; ``cross_filing_overlap_unverifiable`` if either side cannot be
assembled). The single exception is the first fiscal year of a framework (FY2013, IFRS adoption): the prior filing is
in another framework, so t-2 is the IFRS-transition opening balance of the year-t filing (flagged, and gated by the
same balance identity). Frameworks are never mixed inside one model-year.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.input_snapshot import digest, safe_official_url
from app.services.financial_research.literature_extraction import PDF_METHODS, XBRL_METHODS

MAPPING_VERSION = "literature_input_mapping_v2"
PANEL_VERSION = "literature_panel_v2"
# v2 of both (finding R02 / R01 of the df0fc44 review): zero proofs are re-derived at their point of use, and every
# present statement-anchor candidate is gate- and value-checked. Proof records name their rule_version, so a v1 proof
# is never accepted by v2 code; snapshots and runs built with v1 stay immutable and verify as method_version_changed.
ZERO_POLICY_VERSION = "literature_zero_evidence_policy_v2"
SOURCE_GATE_VERSION = "literature_source_gate_v2"
MAPPING_STATUS = "draft_mapping_needs_method_owner_review"
ZERO_RULE_TWGAAP_EQUITY = "twgaap_equity_section_exhaustive_enumeration"
# Zero-evidence rules approved for use by this DRAFT method (each one is documented in ZERO_RULES and tested); the
# method owner may withdraw a rule, which turns its metric back into ``not_presented``.
ZERO_RULES = {
    ZERO_RULE_TWGAAP_EQUITY: (
        "TW-GAAP preferred share capital (code 3120) is a verified zero for a balance-sheet column only when (1) the "
        "extraction identity 3XXX = sum of every printed equity code 3000-3999 is verified for that column, (2) the "
        "same equation re-computes exactly from the frozen observations, (3) every operand passes the source gate, and "
        "(4) no printed equity line has code 3120 or a label containing 特別股 (preferred). The equity section is then "
        "exhaustively enumerated, so an unprinted preferred-share balance would break the equation."),
}
ISSUANCE_METRICS = ("long_term_debt_issued", "stock_issued")  # absence of an issuance line is never a zero

# Statement totals proving the statement was parsed for a filing/period.
ANCHORS = {
    "TIFRS": {"current_assets": "CurrentAssets", "assets": "Assets", "current_liabilities": "CurrentLiabilities",
              "liabilities": "Liabilities", "equity": "Equity",
              "cash_flow_operating": ("CashFlowsFromUsedInOperatingActivities",
                                      "NetCashFlowsFromUsedInOperatingActivities")},
    "TW_GAAP": {"current_assets": "code:11XX", "assets": ("code:1XXX", "label:資產總計"), "current_liabilities": "code:21XX",
                "liabilities": "code:2XXX", "equity": "code:3XXX", "cash_flow_operating": ("label:營業活動之淨現金流入",
                                                                    "label:營業活動之淨現金流入(出)",
                                                                    "label:營業活動之淨現金流出")},
}


@dataclass(frozen=True)
class MetricMapping:
    metric: str
    description: str
    compustat: str
    context: str  # "instant" | "duration"
    tifrs: dict[str, Any]
    twgaap: dict[str, Any]
    note: str = ""


def _one(*lines: str) -> dict[str, Any]:
    return {"rule": "one_of", "lines": list(lines)}


def _sum(lines: list[str], anchor: str, required: list[str] | None = None, zero_rule: str | None = None) -> dict[str, Any]:
    rule = {"rule": "sum", "lines": lines, "anchor": anchor, "required": required or []}
    if zero_rule:
        rule["zero_evidence_rule"] = zero_rule
    return rule


def _diff(minuend: tuple[str, ...], subtrahend: tuple[str, ...]) -> dict[str, Any]:
    return {"rule": "difference", "minuend": list(minuend), "subtrahend": list(subtrahend)}


_CURRENT_FIN_ASSETS_TIFRS = [
    "CurrentFinancialAssetsAtFairvalueThroughProfitOrLoss", "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
    "CurrentAvailableForSaleFinancialAssets", "CurrentHeldToMaturityFinancialAssets",
    "CurrentFinancialAssetsAtAmortisedCost", "CurrentFinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
    "CurrentFinancialAssetsAtCost", "CurrentBondInvestmentsWithoutActiveMarket"]
_NONCURRENT_FIN_ASSETS_TIFRS = [
    "NoncurrentAvailableForSaleFinancialAssets", "NoncurrentFinancialAssetsAtFairValueThroughOtherComprehensiveIncome",
    "NoncurrentFinancialAssetsAtFairValueThroughProfitOrLoss", "NoncurrentFinancialAssetsAtFairvalueThroughProfitOrLoss",
    "NoncurrentFinancialAssetsAtCost", "NoncurrentHeldToMaturityFinancialAssets",
    "NoncurrentFinancialAssetsAtAmortisedCost", "NoncurrentBondInvestmentsWithoutActiveMarket"]

MAPPINGS: tuple[MetricMapping, ...] = (
    MetricMapping("sales", "Net sales / operating revenue", "12 (SALE)", "duration",
                  _one("OperatingRevenue", "Revenue"), _one("code:4100")),
    MetricMapping("cogs", "Cost of goods sold / operating costs", "41 (COGS)", "duration",
                  _one("OperatingCosts", "CostOfSales"), _one("code:5000"),
                  "TW-GAAP prints operating costs as a deduction; stored as a positive cost."),
    MetricMapping("receivables", "Receivables (notes, accounts, related parties, other receivables), net", "2 (RECT)",
                  "instant",
                  _sum(["NotesReceivableNet", "AccountsReceivableNet", "NotesReceivableDueFromRelatedPartiesNet",
                        "AccountsReceivableDueFromRelatedPartiesNet", "OtherReceivables",
                        "OtherReceivablesDueFromRelatedParties", "OtherCurrentReceivables"],
                       "current_assets", ["AccountsReceivableNet"]),
                  _sum(["code:1120", "code:1140", "code:1150", "code:1160", "code:1178", "code:1180"],
                       "current_assets", ["code:1140"]),
                  "Current-tax refund receivables are excluded (separate line); long-term receivables excluded."),
    MetricMapping("inventory", "Inventories", "3 (INVT)", "instant", _one("Inventories"), _one("code:120X", "code:1200")),
    MetricMapping("current_assets", "Total current assets", "4 (ACT)", "instant", _one("CurrentAssets"), _one("code:11XX")),
    MetricMapping("total_assets", "Total assets", "6 (AT)", "instant", _one("Assets"), _one("code:1XXX", "label:資產總計")),
    MetricMapping("ppe_net", "Property, plant and equipment, net", "8 (PPENT)", "instant",
                  _one("PropertyPlantAndEquipment"), _one("code:15XX"),
                  "TW-GAAP 15XX includes construction in progress and equipment prepayments; TIFRS presents "
                  "prepayments for equipment outside PPE. Never compared across frameworks."),
    MetricMapping("cash", "Cash and cash equivalents", "1 (CHE, cash part)", "instant",
                  _one("CashAndCashEquivalents"), _one("code:1100")),
    MetricMapping("short_term_investments", "Short-term investments (current financial assets)", "193 (IVST)",
                  "instant", _sum(_CURRENT_FIN_ASSETS_TIFRS, "current_assets"),
                  _sum(["code:1310", "code:1320", "code:1330", "code:1350", "code:1360"], "current_assets"),
                  "Hedging derivatives and 'other current financial assets' (restricted / time deposits) excluded."),
    MetricMapping("current_liabilities", "Total current liabilities", "5 (LCT)", "instant",
                  _one("CurrentLiabilities"), _one("code:21XX")),
    MetricMapping("total_liabilities", "Total liabilities", "181 (LT)", "instant", _one("Liabilities"), _one("code:2XXX")),
    MetricMapping("long_term_debt", "Long-term debt excluding current portion (borrowings, bonds, long-term notes)",
                  "9 (DLTT)", "instant",
                  _sum(["LongtermBorrowings", "BondsPayable", "NoncurrentPortionOfNoncurrentBondsIssued",
                        "LongtermNotesAndBillsPayable"], "liabilities"),
                  _sum(["code:2410", "code:2420", "code:2430"], "liabilities"),
                  "IFRS 16 lease liabilities are excluded (flagged where present)."),
    MetricMapping("current_maturities_ltd", "Current portion of long-term liabilities", "44 (DD1)", "instant",
                  _sum(["LongtermLiabilitiesCurrentPortion"], "current_liabilities"),
                  _sum(["code:2270"], "current_liabilities")),
    MetricMapping("short_term_debt", "Short-term borrowings and short-term notes/commercial paper", "34 (DLC, part)",
                  "instant",
                  _sum(["ShorttermBorrowings", "ShorttermNotesAndBillsPayable",
                        "CurrentCommercialPapersIssuedAndCurrentPortionOfNoncurrentCommercialPapersIssued"],
                       "current_liabilities"),
                  _sum(["code:2100", "code:2110"], "current_liabilities")),
    MetricMapping("income_tax_payable", "Current income tax payable", "71 (TXP)", "instant",
                  _sum(["CurrentTaxLiabilities"], "current_liabilities"),
                  _sum(["code:2160"], "current_liabilities")),
    MetricMapping("investments_and_advances", "Non-current financial-asset investments (excluding equity method)",
                  "32 (IVAO)", "instant", _sum(_NONCURRENT_FIN_ASSETS_TIFRS, "assets"),
                  _sum(["code:1430", "code:1440", "code:1450", "code:1460", "code:1480"], "assets"),
                  "Equity-method investments (COMPUSTAT 31) remain operating (NCO), as in RSST."),
    MetricMapping("preferred_stock", "Preferred share capital", "130 (PSTK)", "instant",
                  _diff(("CapitalStock", "IssuedCapital"), ("OrdinaryShare",)),
                  _sum(["code:3120"], "equity", zero_rule=ZERO_RULE_TWGAAP_EQUITY),
                  "TIFRS: share capital minus ordinary share capital (both printed). TW-GAAP: preferred line (3120); its "
                  "absence is a zero only under the equity-section exhaustive-enumeration proof (verified_zero), "
                  "otherwise not_presented."),
    MetricMapping("depreciation", "Depreciation (excluding amortization of intangibles)", "14 less 65", "duration",
                  _one("DepreciationExpense", "AdjustmentsForDepreciationExpense"),
                  _one("label:各項折舊(含出租資產)", "label:各項折舊(含出租資產及閒置資產)", "label:各項折舊",
                       "label:折舊費用"),
                  "Cash-flow add-back. From FY2019 (IFRS 16) it may include right-of-use depreciation (flagged)."),
    MetricMapping("amortization", "Amortization", "65", "duration",
                  _one("AmortizationExpense", "AdjustmentsForAmortisationExpense"),
                  _one("label:各項攤提", "label:攤銷費用")),
    MetricMapping("selling_expense", "Selling expenses", "189 (part)", "duration",
                  _one("SellingExpenses", "SellingExpense"), _one("code:6100")),
    MetricMapping("administrative_expense", "General and administrative expenses", "189 (part)", "duration",
                  _one("AdministrativeExpense"), _one("code:6200"),
                  "SG&A = selling + administrative; R&D is excluded (COMPUSTAT XSGA often includes R&D: method-owner decision)."),
    MetricMapping("earnings", "Income before extraordinary items (continuing operations, consolidated)", "18 (IB)",
                  "duration", _one("ProfitLossFromContinuingOperations"), _one("code:9600"),
                  "TW-GAAP FY2011-2012 present no discontinued or extraordinary items; consolidated total net income used."),
    MetricMapping("long_term_debt_issued", "Proceeds from long-term borrowing / bonds", "111 (DLTIS)", "duration",
                  _sum(["ProceedsFromLongTermDebt", "ProceedsFromIssuingBonds", "ProceedsFromIssueOfBondsPayable"],
                       "cash_flow_operating"),
                  _sum(["label:長期借款增加", "label:舉借長期借款", "label:發行應付公司債", "label:發行公司債",
                        "label:應付公司債(減少)增加", "label:應付公司債增加"], "cash_flow_operating"),
                  "A positive gross or net increase is evidence of issuance; a decrease or absent line is not evidence of "
                  "none (no zero-evidence rule: an absent line is not_presented, i.e. UNKNOWN)."),
    MetricMapping("stock_issued", "Proceeds from issuing shares", "108 (SSTK)", "duration",
                  _sum(["ProceedsFromIssuingShares", "ProceedsFromExerciseOfEmployeeShareOptions"], "cash_flow_operating"),
                  _sum(["label:現金增資", "label:員工認股權執行"], "cash_flow_operating"),
                  "Treasury-share sales are not counted as issuance. No zero-evidence rule: an absent line is "
                  "not_presented (UNKNOWN), never 0."),
)
MAPPING_INDEX = {m.metric: m for m in MAPPINGS}
LEASE_LINES = ("NoncurrentFinanceLeaseLiabilities", "NoncurrentLeaseLiabilities", "CurrentLeaseLiabilities",
               "LeaseLiabilities")


def period_key(context: str, year: int, *, opening: bool = False) -> str:
    if context == "instant":
        return f"I:{year}-01-01" if opening else f"I:{year}-12-31"
    return f"D:{year}-01-01/{year}-12-31"


def observation_period_key(obs: dict[str, Any]) -> str:
    if obs["period_type"] == "instant":
        return f"I:{obs['period_end']}"
    return f"D:{obs['period_start']}/{obs['period_end']}"


class FilingLines:
    """Line values of one filing artifact, indexed by (line_key, period_key); ambiguity, source identities and
    frozen zero-evidence records are explicit."""

    def __init__(self, observations: list[dict[str, Any]], zero_evidence: list[dict[str, Any]] | None = None) -> None:
        self.values: dict[tuple[str, str], dict[str, Any]] = {}
        self.conflicts: dict[tuple[str, str], list[str]] = {}
        self.by_id: dict[str, dict[str, Any]] = {}
        for obs in sorted(observations, key=lambda o: o["observation_id"]):
            self.by_id[obs["observation_id"]] = obs
            key = (obs["line_key"], observation_period_key(obs))
            current = self.values.get(key)
            if current is not None and current["value"] != obs["value"]:
                self.conflicts.setdefault(key, sorted({current["value"], obs["value"]}))
            elif current is None:
                self.values[key] = obs
        self.identities = self._xbrl_balance_identities()
        self.filing_version_id = next(iter(self.by_id.values()), {}).get("filing_version_id")
        # Frozen zero-evidence records by (metric, period). A record without a text metric/period can certify nothing
        # and is ignored; two records for one key are ambiguous and both are refused (finding R02).
        self.zero_evidence: dict[tuple[str, str], dict[str, Any]] = {}
        self.zero_evidence_duplicates: dict[tuple[str, str], int] = {}
        for record in zero_evidence or []:
            if not isinstance(record, dict):
                continue
            key = (record.get("metric"), record.get("period"))
            if not all(isinstance(part, str) for part in key):
                continue
            if key in self.zero_evidence:
                self.zero_evidence_duplicates[key] = self.zero_evidence_duplicates.get(key, 1) + 1
            self.zero_evidence[key] = record

    def _xbrl_balance_identities(self) -> dict[str, dict[str, Any]]:
        """``Assets = Liabilities + Equity`` for every XBRL instant of this filing (verified / mismatch / incomplete)."""
        periods = sorted({period for (_, period), obs in self.values.items()
                          if period.startswith("I:") and obs.get("extraction_method") in XBRL_METHODS})
        result = {}
        for period in periods:
            operands = {line: self.values.get((line, period)) for line in ("Assets", "Liabilities", "Equity")}
            unusable = sorted(line for line, obs in operands.items() if obs is None or (line, period) in self.conflicts)
            item: dict[str, Any] = {"identity": f"xbrl_balance_{period[2:]}", "rule": "Assets = Liabilities + Equity",
                                    "rule_version": SOURCE_GATE_VERSION, "period": period,
                                    "operands": {line: obs["value"] for line, obs in operands.items() if obs}}
            if unusable:
                item.update(status="incomplete", missing_operands=unusable)
            else:
                assets = dm.parse_decimal(operands["Assets"]["value"])
                computed = dm.add(dm.parse_decimal(operands["Liabilities"]["value"]),
                                  dm.parse_decimal(operands["Equity"]["value"]))
                item.update(status="verified" if assets == computed else "mismatch",
                            difference_twd=dm.text(dm.sub(computed, assets)))
            result[period] = item
        return result

    def get(self, line: str, period: str) -> tuple[dict[str, Any] | None, str | None]:
        if (line, period) in self.conflicts:
            return None, "conflicting_duplicate_line_values"
        return self.values.get((line, period)), None

    def present(self, line: str, period: str) -> bool:
        return (line, period) in self.values or (line, period) in self.conflicts

    def gate(self, obs: dict[str, Any]) -> tuple[str, str] | None:
        """``None`` when the observation may enter a model input, else ``(status, reason)`` (finding LIT-F02)."""
        method = obs.get("extraction_method")
        if method in PDF_METHODS:
            checks = obs.get("checks") or {}
            page = [name for name in ("unit", "fiscal_year", "scope") if checks.get(name) != "verified"]
            if page:
                return "source_identity_incomplete", f"{obs['line_key']}:page_identity_unverified:{','.join(page)}"
            identities = checks.get("identities")
            if identities is None:  # pre-v2 records carry no per-line identity coverage
                return "source_identity_incomplete", f"{obs['line_key']}:identity_coverage_not_recorded"
            mismatched = sorted(name for name, status in identities.items() if status == "mismatch")
            if mismatched:
                return "source_identity_mismatch", f"{obs['line_key']}:{','.join(mismatched)}:mismatch"
            unverified = sorted(f"{name}:{status}" for name, status in identities.items() if status != "verified")
            if unverified:
                return "source_identity_incomplete", f"{obs['line_key']}:{','.join(unverified)}"
            return None
        if method in XBRL_METHODS and obs.get("period_type") == "instant":
            item = self.identities.get(observation_period_key(obs))
            if item is None or item["status"] == "incomplete":
                return "source_identity_incomplete", f"{obs['line_key']}:xbrl_balance_identity_incomplete"
            if item["status"] == "mismatch":
                return "source_identity_mismatch", f"{obs['line_key']}:{item['identity']}:mismatch"
        return None

    @staticmethod
    def line_warnings(obs: dict[str, Any]) -> list[str]:
        if obs.get("extraction_method") in PDF_METHODS and not (obs.get("checks") or {}).get("identities"):
            return [f"arithmetic_identity_not_available_for_line:{obs['line_key']}"]
        return []


@dataclass
class MetricValue:
    metric: str
    value: Decimal | None
    status: str  # computed | see the module docstring for the typed non-computed statuses
    observations: list[dict[str, Any]] = field(default_factory=list)
    lines_not_presented: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_type: str | None = None
    zero_evidence: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)


def _agreeing(lines: FilingLines, candidates: list[str],
              period: str) -> tuple[list[dict[str, Any]], str, list[str], list[dict[str, Any]]]:
    """Alias agreement rule: every present candidate must pass the source gate and carry the same value
    (``mapping_conflict`` otherwise; list order never decides). Every candidate is inspected, and reasons are sorted,
    so neither the candidate nor the observation order changes the outcome. Returns (observations, status, reasons,
    candidates)."""
    found, ambiguous = [], []
    for line in candidates:
        obs, problem = lines.get(line, period)
        if problem:
            ambiguous.append(f"{line}:{problem}")
        elif obs is not None:
            found.append(obs)
    if ambiguous:
        return [], "ambiguous_version", sorted(ambiguous), []
    listed = [{"line_key": o["line_key"], "value": o["value"], "observation_id": o["observation_id"]} for o in found]
    if not found:
        return [], "missing_input", [], listed
    blocked = sorted(b for b in (lines.gate(obs) for obs in found) if b)
    if blocked:
        mismatch = any(status == "source_identity_mismatch" for status, _ in blocked)
        return [], "source_identity_mismatch" if mismatch else blocked[0][0], [reason for _, reason in blocked], listed
    if len({dm.parse_decimal(o["value"]) for o in found}) > 1:
        return [], "mapping_conflict", ["mapping_conflict:" + ";".join(sorted(f"{o['line_key']}={o['value']}"
                                                                              for o in found))], listed
    return found, "computed", [], listed


def _anchor(lines: FilingLines, framework: str, anchor: str,
            period: str) -> tuple[str | None, list[str], list[dict[str, Any]]]:
    """(status, reasons, candidates) when the statement anchor total is absent or unusable, else (None, [], []).

    Every present anchor candidate follows the alias agreement rule (finding R01): each must pass the source gate and
    all must carry the same value; a disagreement is ``mapping_conflict`` with an ``anchor_conflict:`` reason."""
    target = ANCHORS[framework][anchor]
    candidates = list(target) if isinstance(target, tuple) else [target]
    if not any(lines.present(c, period) for c in candidates):
        return "anchor_missing", [f"statement_anchor_{anchor}_not_present"], []
    _, status, reasons, listed = _agreeing(lines, candidates, period)
    if status == "computed":
        return None, [], []
    if status == "mapping_conflict":
        reasons = [f"anchor_conflict:{anchor}:{r.removeprefix('mapping_conflict:')}" for r in reasons]
    elif status != "ambiguous_version":
        reasons = [f"anchor:{r}" for r in reasons]
    return status, reasons, listed


def _rule(framework: str, metric: str) -> dict[str, Any]:
    mapping = MAPPING_INDEX[metric]
    return mapping.tifrs if framework == "TIFRS" else mapping.twgaap


def assemble(lines: FilingLines, framework: str, metric: str, period: str) -> MetricValue:
    rule = _rule(framework, metric)
    result = MetricValue(metric, None, "missing_input")
    if rule["rule"] == "one_of":
        found, status, reasons, result.candidates = _agreeing(lines, rule["lines"], period)
        if status != "computed":
            result.status, result.reasons = status, reasons or [f"no_line_for_{metric}"]
            return result
        result.value, result.status, result.observations = dm.parse_decimal(found[0]["value"]), "computed", found
        result.evidence_type = "explicit_zero" if result.value == 0 else "explicit_line"
        result.warnings = sorted({w for obs in found for w in lines.line_warnings(obs)})
        return result
    if rule["rule"] == "difference":
        parts = []
        for group in (rule["minuend"], rule["subtrahend"]):
            found, status, reasons, listed = _agreeing(lines, group, period)
            result.candidates += listed
            if status != "computed":
                result.status, result.reasons = status, reasons or [f"no_line_for_{metric}_component"]
                return result
            parts.append(found)
        result.value = dm.sub(dm.parse_decimal(parts[0][0]["value"]), dm.parse_decimal(parts[1][0]["value"]))
        result.status, result.observations = "computed", [*parts[0], *parts[1]]
        result.evidence_type = "derived_difference"
        return result
    # sum
    status, reasons, listed = _anchor(lines, framework, rule["anchor"], period)
    if status:
        result.status, result.reasons, result.candidates = status, reasons, listed
        return result
    total, used = Decimal(0), []
    for line in rule["lines"]:
        obs, problem = lines.get(line, period)
        if problem:
            result.status, result.reasons = "ambiguous_version", [f"{line}:{problem}"]
            return result
        if obs is None:
            if line in rule["required"]:
                result.reasons = [f"required_line_missing:{line}"]
                return result
            result.lines_not_presented.append(line)
            continue
        blocked = lines.gate(obs)
        if blocked:
            result.status, result.reasons = blocked[0], [blocked[1]]
            return result
        used.append(obs)
        total = dm.add(total, dm.parse_decimal(obs["value"]))
    if used:
        result.value, result.status, result.observations = total, "computed", used
        result.evidence_type = ("explicit_zero" if all(dm.parse_decimal(o["value"]) == 0 for o in used)
                                else "presented_lines_sum")
        result.warnings = sorted({w for obs in used for w in lines.line_warnings(obs)})
        return result
    # LIT-F01: no listed line presented. Never computed/0 unless a documented zero-evidence proof is verified, and
    # the frozen proof is re-derived from these observations here, at its point of use (finding R02).
    zero_rule = rule.get("zero_evidence_rule")
    reason = "zero_inference_not_permitted_for_metric"
    if zero_rule:
        proof, reason = check_zero_proof(lines, framework, metric, period, zero_rule)
        if proof is not None:
            result.value, result.status, result.evidence_type = Decimal(0), "computed", "verified_zero"
            result.zero_evidence = proof
            result.observations = [lines.by_id[o["observation_id"]] for o in proof["operands"]]
            return result
    result.status = "not_presented"
    result.reasons = [f"no_listed_line_presented:{'|'.join(rule['lines'])}", reason]
    return result


# Fields that tie a zero-evidence record to one rule version, filing, framework, metric and balance date.
_PROOF_IDENTITY_FIELDS = ("rule", "rule_version", "accounting_framework", "filing_version_id", "metric", "period")


def check_zero_proof(lines: FilingLines, framework: str, metric: str, period: str,
                     zero_rule: str) -> tuple[dict[str, Any] | None, str]:
    """Verify the frozen zero-evidence record of one filing/metric/period at its point of use (pure, finding R02).

    The record is accepted only when it is the single record for (metric, period), names the mapping's rule of the
    current ``ZERO_POLICY_VERSION`` for this framework and filing, carries a valid SHA-256 fingerprint of its own
    content, and equals — field for field, operands included — the proof ``prove_zero`` re-derives from the current
    observations, which must itself be ``verified``. Returns (re-derived record, "") or (None, reason); a stale,
    altered, cross-filing, cross-period, duplicate or malformed record fails closed and never raises."""
    key = (metric, period)
    if key in lines.zero_evidence_duplicates:
        return None, f"zero_evidence_invalid:duplicate_proof_records:{lines.zero_evidence_duplicates[key]}"
    proof = lines.zero_evidence.get(key)
    if proof is None:
        return None, f"zero_evidence_not_verified:{zero_rule}:not_evaluated"
    if proof.get("status") != "verified":
        return None, f"zero_evidence_not_verified:{zero_rule}:{proof.get('status')}"
    expected = {"rule": zero_rule, "rule_version": ZERO_POLICY_VERSION, "accounting_framework": framework,
                "filing_version_id": lines.filing_version_id, "metric": metric, "period": period}
    for name in _PROOF_IDENTITY_FIELDS:
        if proof.get(name) != expected[name] or (name == "rule" and zero_rule not in ZERO_RULES):
            return None, f"zero_evidence_invalid:{name}_differs"
    try:
        fingerprint_ok = proof.get("evidence_fingerprint") == digest(
            {k: v for k, v in proof.items() if k != "evidence_fingerprint"})
    except (TypeError, ValueError):
        return None, "zero_evidence_invalid:malformed_record"
    if not fingerprint_ok:
        return None, "zero_evidence_invalid:evidence_fingerprint_mismatch"
    recomputed = prove_zero(lines, framework, metric, period)
    if recomputed is None or recomputed["status"] != "verified":
        return None, f"zero_evidence_invalid:recomputed_status:{recomputed['status'] if recomputed else 'not_applicable'}"
    differing = sorted(k for k in set(proof) | set(recomputed) if proof.get(k) != recomputed.get(k))
    if differing:
        return None, f"zero_evidence_invalid:stale_or_altered:{','.join(differing)}"
    return recomputed, ""


def prove_zero(lines: FilingLines, framework: str, metric: str, period: str) -> dict[str, Any] | None:
    """Evaluate the metric's zero-evidence rule for one filing/period (pure). ``None`` when the mapping has no rule."""
    rule = _rule(framework, metric)
    name = rule.get("zero_evidence_rule")
    if name is None or rule["rule"] != "sum" or metric in ISSUANCE_METRICS:
        return None
    record: dict[str, Any] = {"metric": metric, "period": period, "rule": name, "rule_version": ZERO_POLICY_VERSION,
                              "accounting_framework": framework,
                              "filing_version_id": lines.filing_version_id,
                              "operands": [], "findings": []}
    if name != ZERO_RULE_TWGAAP_EQUITY or framework != "TW_GAAP":
        record["status"] = "rule_not_applicable"
    else:
        total, problem = lines.get("code:3XXX", period)
        members = sorted((obs for (line, p), obs in lines.values.items() if p == period and line.startswith("code:")
                          and line[5:].isdigit() and 3000 <= int(line[5:]) <= 3999), key=lambda o: o["line_key"])
        conflicted = sorted(line for (line, p) in lines.conflicts if p == period and line.startswith("code:3"))
        operands = ([total] if total else []) + members
        record["operands"] = [{"observation_id": o["observation_id"], "line_key": o["line_key"], "value": o["value"],
                               "published_value": o.get("published_value"), "locator": o.get("locator")}
                              for o in operands]
        blocked = [lines.gate(o) for o in operands]
        preferred = [o["line_key"] for o in members if o["line_key"] == "code:3120" or "特別股" in o["source_concept"]]
        if problem or conflicted:
            record.update(status="ambiguous", findings=[f for f in (problem, *conflicted) if f])
        elif total is None or not members:
            record.update(status="incomplete", findings=["equity_section_total_or_members_not_printed"])
        elif any(b and b[0] == "source_identity_mismatch" for b in blocked):
            record.update(status="mismatch", findings=[b[1] for b in blocked if b])
        elif any(blocked):
            record.update(status="incomplete", findings=[b[1] for b in blocked if b])
        else:
            enumerated = dm.add(*(dm.parse_decimal(o["value"]) for o in members))
            record.update(section_total_twd=total["value"], enumerated_sum_twd=dm.text(enumerated))
            if enumerated != dm.parse_decimal(total["value"]):
                record.update(status="mismatch", findings=["recomputed_equity_enumeration_differs"])
            elif preferred:
                record.update(status="preferred_line_present", findings=preferred)
            else:
                record.update(status="verified", findings=["equity_section_exhaustively_enumerated",
                                                           "no_preferred_share_line_printed"])
    record["evidence_fingerprint"] = digest({k: v for k, v in record.items() if k != "evidence_fingerprint"})
    return record


def zero_evidence_records(lines: FilingLines, framework: str) -> list[dict[str, Any]]:
    """Zero-evidence records for every metric with a zero rule and every balance date of one filing (pure)."""
    periods = sorted({period for (_, period) in lines.values if period.startswith("I:")})
    records = [prove_zero(lines, framework, mapping.metric, period) for mapping in MAPPINGS for period in periods]
    return [r for r in records if r is not None]


# ------------------------------------------------------------------------------------------------- panels
REL_OFFSETS = {"t": 0, "t-1": 1, "t-2": 2}
_MISSING_STATUSES = ("missing_input", "anchor_missing")


@dataclass
class PanelValue:
    metric: str
    relative: str
    fiscal_year: int
    value: Decimal | None
    status: str
    filing_version_id: str | None
    period: str
    observations: list[dict[str, Any]]
    lines_not_presented: list[str]
    reasons: list[str]
    warnings: list[str]
    evidence_type: str | None = None
    zero_evidence: dict[str, Any] | None = None
    cross_filing_overlap: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def provenance(self) -> dict[str, Any]:
        return {"metric": self.metric, "relative_period": self.relative, "fiscal_year": self.fiscal_year,
                "status": self.status, "value_twd": dm.text(self.value), "evidence_type": self.evidence_type,
                "filing_version_id": self.filing_version_id,
                "period": self.period, "lines_not_presented": self.lines_not_presented, "reasons": self.reasons,
                "warnings": self.warnings, "zero_evidence": self.zero_evidence,
                "cross_filing_overlap": self.cross_filing_overlap, "alias_candidates": self.candidates,
                "source_observations": [{key: obs.get(key) for key in (
                    "observation_id", "line_key", "source_concept", "value", "published_value", "published_unit",
                    "raw_sha256", "locator", "extraction_method", "extractor_version", "filing_version_type")}
                    | {"source_url": safe_official_url(obs.get("source_url"))} for obs in self.observations]}


class Panel:
    """Model-year view: ``value(metric, 't-1')`` with full provenance and explicit missing reasons."""

    def __init__(self, year: int, framework: str, filings: dict[int, dict[str, Any] | None],
                 lines: dict[str, FilingLines], filing_problems: dict[int, str],
                 frameworks: dict[int, str] | None = None) -> None:
        self.year, self.framework = year, framework
        self.filings, self.lines, self.filing_problems = filings, lines, filing_problems
        self.frameworks = frameworks or {}
        self.used: list[PanelValue] = []

    def is_framework_transition_year(self) -> bool:
        """True only for the first fiscal year of this framework (the prior year is in another, known framework)."""
        prior = self.frameworks.get(self.year - 1)
        return prior not in (None, "unknown", self.framework)

    def _assemble(self, filing_year: int, metric: str, period: str) -> tuple[dict[str, Any] | None, Any]:
        filing = self.filings.get(filing_year)
        if filing is None:
            return None, f"FY{filing_year}_filing:{self.filing_problems.get(filing_year, 'no_filing')}"
        if filing["accounting_framework"] != self.framework:
            return None, f"FY{filing_year}_filing:accounting_regime_break"
        return filing, assemble(self.lines[filing["filing_version_id"]], self.framework, metric, period)

    def _from(self, metric: str, relative: str, target_year: int, filing: dict[str, Any], period: str,
              assembled: MetricValue, flags: list[str], *, t_minus_2: bool) -> PanelValue:
        if assembled.status == "computed":
            return PanelValue(metric, relative, target_year, assembled.value, "computed", filing["filing_version_id"],
                              period, assembled.observations, assembled.lines_not_presented, [],
                              assembled.warnings + flags, assembled.evidence_type, assembled.zero_evidence,
                              candidates=assembled.candidates)
        status = "missing_t_minus_2" if t_minus_2 and assembled.status in _MISSING_STATUSES else assembled.status
        return PanelValue(metric, relative, target_year, None, status, None, "", [], assembled.lines_not_presented,
                          [f"FY{filing['fiscal_year']}_filing:{r}" for r in assembled.reasons], [],
                          candidates=assembled.candidates)

    def _missing(self, metric: str, relative: str, target_year: int, status: str, reasons: list[str],
                 overlap: dict[str, Any] | None = None) -> PanelValue:
        return PanelValue(metric, relative, target_year, None, status, None, "", [], [], reasons, [],
                          cross_filing_overlap=overlap)

    def value(self, metric: str, relative: str) -> PanelValue:
        mapping = MAPPING_INDEX[metric]
        target_year = self.year - REL_OFFSETS[relative]
        if relative in ("t", "t-1"):
            period = period_key(mapping.context, target_year)
            filing, assembled = self._assemble(self.year, metric, period)
            result = (self._missing(metric, relative, target_year, "missing_input", [assembled]) if filing is None
                      else self._from(metric, relative, target_year, filing, period, assembled, [], t_minus_2=False))
        elif mapping.context != "instant":
            result = self._missing(metric, relative, target_year, "missing_t_minus_2", ["t-2_defined_only_for_balances"])
        elif self.is_framework_transition_year():
            period = period_key("instant", target_year + 1, opening=True)
            filing, assembled = self._assemble(self.year, metric, period)
            flags = ["ifrs_transition_opening_balance_used_as_prior_year_end",
                     f"framework_transition:FY{self.year - 1}={self.frameworks.get(self.year - 1)}"
                     f"->FY{self.year}={self.framework}"]
            result = (self._missing(metric, relative, target_year, "missing_t_minus_2", [assembled]) if filing is None
                      else self._from(metric, relative, target_year, filing, period, assembled, flags, t_minus_2=True))
        else:
            result = self._cross_filing(metric, relative, target_year)
        self.used.append(result)
        return result

    def _cross_filing(self, metric: str, relative: str, target_year: int) -> PanelValue:
        """t-2 from the year-(t-1) filing, admitted only after the overlapping year t-1 agrees (finding LIT-F04)."""
        prior_year = self.year - 1
        period = period_key("instant", target_year)
        prior, prior_value = self._assemble(prior_year, metric, period)
        if prior is None:
            return self._missing(metric, relative, target_year, "missing_t_minus_2", [prior_value])
        if prior_value.status != "computed":
            return self._from(metric, relative, target_year, prior, period, prior_value, [], t_minus_2=True)
        current = self.filings[self.year]
        overlap_period = period_key("instant", prior_year)
        in_current = assemble(self.lines[current["filing_version_id"]], self.framework, metric, overlap_period)
        in_prior = assemble(self.lines[prior["filing_version_id"]], self.framework, metric, overlap_period)
        overlap: dict[str, Any] = {
            "metric": metric, "overlap_period": overlap_period, "check_version": PANEL_VERSION,
            "accounting_framework": self.framework,
            "year_t_filing": {"filing_version_id": current["filing_version_id"], "fiscal_year": self.year,
                              "filing_version_type": current.get("filing_version_type"),
                              "statement_scope": current.get("statement_scope"),
                              "status": in_current.status, "value_twd": dm.text(in_current.value)},
            "year_t_minus_1_filing": {"filing_version_id": prior["filing_version_id"], "fiscal_year": prior_year,
                                      "filing_version_type": prior.get("filing_version_type"),
                                      "statement_scope": prior.get("statement_scope"),
                                      "status": in_prior.status, "value_twd": dm.text(in_prior.value)}}
        label = (f"overlap:{metric}:{overlap_period}:FY{self.year}({current.get('filing_version_type')})="
                 f"{dm.text(in_current.value)}:FY{prior_year}({prior.get('filing_version_type')})={dm.text(in_prior.value)}")
        if current.get("statement_scope") != prior.get("statement_scope"):
            overlap["status"] = "scope_differs"
            return self._missing(metric, relative, target_year, "cross_filing_overlap_unverifiable",
                                 [f"{label}:statement_scope_differs"], overlap)
        if in_current.status != "computed" or in_prior.status != "computed":
            overlap["status"] = "unverifiable"
            return self._missing(metric, relative, target_year, "cross_filing_overlap_unverifiable",
                                 [f"{label}:FY{self.year}_status={in_current.status}:"
                                  f"FY{prior_year}_status={in_prior.status}"], overlap)
        if in_current.value != in_prior.value:
            overlap.update(status="mismatch", difference_twd=dm.text(dm.sub(in_current.value, in_prior.value)))
            return self._missing(metric, relative, target_year, "cross_filing_overlap_mismatch",
                                 [f"{label}:difference={overlap['difference_twd']}:unexplained"], overlap)
        overlap["status"] = "verified"
        flags = [f"t-2_from_FY{prior_year}_filing", f"cross_filing_overlap_verified:{metric}:{overlap_period}"]
        if current.get("filing_version_type") != prior.get("filing_version_type"):
            flags.append(f"cross_filing_version_types:{current.get('filing_version_type')}/"
                         f"{prior.get('filing_version_type')}")
        result = self._from(metric, relative, target_year, prior, period, prior_value, flags, t_minus_2=True)
        result.cross_filing_overlap = overlap
        return result


def lease_flags(lines: FilingLines, period: str) -> list[str]:
    return [f"ifrs16_lease_liability_excluded_from_debt:{line}" for line in LEASE_LINES
            if (obs := lines.get(line, period)[0]) is not None and dm.parse_decimal(obs["value"]) not in (None, Decimal(0))]


def mapping_payload() -> dict[str, Any]:
    return {"mapping_version": MAPPING_VERSION, "panel_version": PANEL_VERSION, "mapping_status": MAPPING_STATUS,
            "zero_evidence_policy_version": ZERO_POLICY_VERSION, "zero_evidence_rules": ZERO_RULES,
            "source_gate_version": SOURCE_GATE_VERSION, "anchors": ANCHORS,
            "metrics": [{"metric": m.metric, "description": m.description, "compustat_item": m.compustat,
                         "context": m.context, "tifrs": m.tifrs, "tw_gaap": m.twgaap, "note": m.note} for m in MAPPINGS],
            "rules": __doc__}


def fiscal_year_end(year: int) -> date:
    return date(year, 12, 31)
