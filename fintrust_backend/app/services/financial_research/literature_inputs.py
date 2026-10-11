"""Literature-model input contract: COMPUSTAT-item → Taiwan statement-line mapping, assembly and period panels.

Inputs are *line-level* official observations (see ``literature_extraction``): one value per statement line, filing
version, statement period and source artifact, each with its raw SHA-256 and locator. This module is pure: it maps
lines to the paper's COMPUSTAT items, assembles one value per (filing, period, metric) and serves the t / t-1 / t-2
panel a model needs. Nothing is fetched, filled or guessed here.

Mapping rules (mapping ``literature_input_mapping_v1``, DRAFT for the method owner):

- ``one_of``: the first listed line present in the filing/period (priority order); a disagreeing alternate is
  recorded as a warning.
- ``sum``: the sum of the listed lines present, provided the statement ``anchor`` total is present for the same
  filing/period (so the statement was parsed). A listed line that the statement does not present is recorded in
  ``lines_not_presented`` (statement-line absence, not a filled zero). ``required`` lines must be present.
- ``difference``: ``minuend - subtrahend``, both required.
- a reported 0 is a real value; a missing required line is ``missing_input`` (never 0).

Period panel rules (``literature_panel_v1``): values for t and t-1 come from the fiscal-year-t filing (current and
comparative columns of one document); t-2 balances come from the comparative column of the fiscal-year-(t-1) filing
of the same version series and accounting framework, or else from the IFRS-transition opening balance sheet of the
fiscal-year-t filing (flagged). Frameworks are never mixed inside one model-year.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.input_snapshot import safe_official_url

MAPPING_VERSION = "literature_input_mapping_v1"
PANEL_VERSION = "literature_panel_v1"
MAPPING_STATUS = "draft_mapping_needs_method_owner_review"

# Statement totals proving the statement was parsed for a filing/period.
ANCHORS = {
    "TIFRS": {"current_assets": "CurrentAssets", "assets": "Assets", "current_liabilities": "CurrentLiabilities",
              "liabilities": "Liabilities", "cash_flow_operating": ("CashFlowsFromUsedInOperatingActivities",
                                                                     "NetCashFlowsFromUsedInOperatingActivities")},
    "TW_GAAP": {"current_assets": "code:11XX", "assets": ("code:1XXX", "label:資產總計"), "current_liabilities": "code:21XX",
                "liabilities": "code:2XXX", "cash_flow_operating": ("label:營業活動之淨現金流入",
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


def _sum(lines: list[str], anchor: str, required: list[str] | None = None) -> dict[str, Any]:
    return {"rule": "sum", "lines": lines, "anchor": anchor, "required": required or []}


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
                  _sum(["code:3120"], "assets"),
                  "TIFRS: share capital minus ordinary share capital. TW-GAAP: preferred line (3120) or line absence."),
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
                  "A positive gross or net increase is evidence of issuance; a decrease or absent line is not evidence of none."),
    MetricMapping("stock_issued", "Proceeds from issuing shares", "108 (SSTK)", "duration",
                  _sum(["ProceedsFromIssuingShares", "ProceedsFromExerciseOfEmployeeShareOptions"], "cash_flow_operating"),
                  _sum(["label:現金增資", "label:員工認股權執行"], "cash_flow_operating"),
                  "Treasury-share sales are not counted as issuance."),
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
    """Line values of one filing artifact, indexed by (line_key, period_key); ambiguity is explicit."""

    def __init__(self, observations: list[dict[str, Any]]) -> None:
        self.values: dict[tuple[str, str], dict[str, Any]] = {}
        self.conflicts: dict[tuple[str, str], list[str]] = {}
        for obs in sorted(observations, key=lambda o: o["observation_id"]):
            key = (obs["line_key"], observation_period_key(obs))
            current = self.values.get(key)
            if current is not None and current["value"] != obs["value"]:
                self.conflicts.setdefault(key, sorted({current["value"], obs["value"]}))
            elif current is None:
                self.values[key] = obs

    def get(self, line: str, period: str) -> tuple[dict[str, Any] | None, str | None]:
        if (line, period) in self.conflicts:
            return None, "conflicting_duplicate_line_values"
        return self.values.get((line, period)), None

    def present(self, line: str, period: str) -> bool:
        return (line, period) in self.values or (line, period) in self.conflicts


@dataclass
class MetricValue:
    metric: str
    value: Decimal | None
    status: str  # computed | missing_input | ambiguous_version | anchor_missing
    observations: list[dict[str, Any]] = field(default_factory=list)
    lines_not_presented: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _anchor_present(lines: FilingLines, framework: str, anchor: str, period: str) -> bool:
    target = ANCHORS[framework][anchor]
    return any(lines.present(candidate, period) for candidate in (target if isinstance(target, tuple) else (target,)))


def assemble(lines: FilingLines, framework: str, metric: str, period: str) -> MetricValue:
    mapping = MAPPING_INDEX[metric]
    rule = mapping.tifrs if framework == "TIFRS" else mapping.twgaap
    result = MetricValue(metric, None, "missing_input")
    if rule["rule"] == "one_of":
        found = []
        for line in rule["lines"]:
            obs, problem = lines.get(line, period)
            if problem:
                result.status, result.reasons = "ambiguous_version", [f"{line}:{problem}"]
                return result
            if obs is not None:
                found.append(obs)
        if not found:
            result.reasons = [f"no_line_for_{metric}"]
            return result
        chosen = found[0]
        result.value, result.status, result.observations = dm.parse_decimal(chosen["value"]), "computed", [chosen]
        for alternate in found[1:]:
            if alternate["value"] != chosen["value"]:
                result.warnings.append(f"alternate_line_disagrees:{alternate['line_key']}={alternate['value']}")
        return result
    if rule["rule"] == "difference":
        parts = []
        for group in (rule["minuend"], rule["subtrahend"]):
            obs = next((o for o in (lines.get(line, period)[0] for line in group) if o is not None), None)
            if obs is None:
                result.reasons = [f"no_line_for_{metric}_component"]
                return result
            parts.append(obs)
        result.value = dm.sub(dm.parse_decimal(parts[0]["value"]), dm.parse_decimal(parts[1]["value"]))
        result.status, result.observations = "computed", parts
        return result
    # sum
    if not _anchor_present(lines, framework, rule["anchor"], period):
        result.status, result.reasons = "anchor_missing", [f"statement_anchor_{rule['anchor']}_not_present"]
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
        used.append(obs)
        total = dm.add(total, dm.parse_decimal(obs["value"]))
    result.value, result.status, result.observations = total, "computed", used
    if not used:
        result.warnings.append("no_listed_line_presented_in_complete_statement")
    return result


# ------------------------------------------------------------------------------------------------- panels
REL_OFFSETS = {"t": 0, "t-1": 1, "t-2": 2}


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

    def provenance(self) -> dict[str, Any]:
        return {"metric": self.metric, "relative_period": self.relative, "fiscal_year": self.fiscal_year,
                "status": self.status, "value_twd": dm.text(self.value), "filing_version_id": self.filing_version_id,
                "period": self.period, "lines_not_presented": self.lines_not_presented, "reasons": self.reasons,
                "warnings": self.warnings,
                "source_observations": [{key: obs.get(key) for key in (
                    "observation_id", "line_key", "source_concept", "value", "published_value", "published_unit",
                    "raw_sha256", "locator", "extraction_method", "filing_version_type")}
                    | {"source_url": safe_official_url(obs.get("source_url"))} for obs in self.observations]}


class Panel:
    """Model-year view: ``value(metric, 't-1')`` with full provenance and explicit missing reasons."""

    def __init__(self, year: int, framework: str, filings: dict[int, dict[str, Any] | None],
                 lines: dict[str, FilingLines], filing_problems: dict[int, str]) -> None:
        self.year, self.framework = year, framework
        self.filings, self.lines, self.filing_problems = filings, lines, filing_problems
        self.used: list[PanelValue] = []

    def value(self, metric: str, relative: str) -> PanelValue:
        mapping = MAPPING_INDEX[metric]
        target_year = self.year - REL_OFFSETS[relative]
        sources: list[tuple[int, str, list[str]]] = []
        if relative in ("t", "t-1"):
            sources.append((self.year, period_key(mapping.context, target_year), []))
        elif mapping.context == "instant":
            sources.append((self.year - 1, period_key("instant", target_year), []))
            sources.append((self.year, period_key("instant", target_year + 1, opening=True),
                            ["ifrs_transition_opening_balance_used_as_prior_year_end"]))
        reasons: list[str] = []
        for filing_year, period, flags in sources:
            filing = self.filings.get(filing_year)
            if filing is None:
                reasons.append(f"FY{filing_year}_filing:{self.filing_problems.get(filing_year, 'no_filing')}")
                continue
            if filing["accounting_framework"] != self.framework:
                reasons.append(f"FY{filing_year}_filing:accounting_regime_break")
                continue
            assembled = assemble(self.lines[filing["filing_version_id"]], self.framework, metric, period)
            if assembled.status == "computed":
                result = PanelValue(metric, relative, target_year, assembled.value, "computed",
                                    filing["filing_version_id"], period, assembled.observations,
                                    assembled.lines_not_presented, [], assembled.warnings + flags)
                self.used.append(result)
                return result
            reasons.extend(f"FY{filing_year}_filing:{r}" for r in assembled.reasons)
            if assembled.status == "ambiguous_version":
                break
        status = "missing_t_minus_2" if relative == "t-2" else (
            "ambiguous_version" if any("conflicting" in r for r in reasons) else "missing_input")
        result = PanelValue(metric, relative, target_year, None, status, None, "", [], [], reasons, [])
        self.used.append(result)
        return result


def lease_flags(lines: FilingLines, period: str) -> list[str]:
    return [f"ifrs16_lease_liability_excluded_from_debt:{line}" for line in LEASE_LINES
            if (obs := lines.get(line, period)[0]) is not None and dm.parse_decimal(obs["value"]) not in (None, Decimal(0))]


def mapping_payload() -> dict[str, Any]:
    return {"mapping_version": MAPPING_VERSION, "panel_version": PANEL_VERSION, "mapping_status": MAPPING_STATUS,
            "anchors": ANCHORS,
            "metrics": [{"metric": m.metric, "description": m.description, "compustat_item": m.compustat,
                         "context": m.context, "tifrs": m.tifrs, "tw_gaap": m.twgaap, "note": m.note} for m in MAPPINGS],
            "rules": __doc__}


def fiscal_year_end(year: int) -> date:
    return date(year, 12, 31)
