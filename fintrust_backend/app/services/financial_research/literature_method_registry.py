"""Machine-readable source lock for the two published literature models (method lock v1).

Every term, coefficient, transformation, scaling constant and benchmark below was read from the paper text itself
(local, SHA-256-identified copies that are **not** redistributed: see ``PAPER_SOURCES``). Values keep the precision
printed in the source; nothing was taken from secondary websites. The human-readable lock with page/table citations
is ``docs/research/BENEISH_1999_DECHOW_2011_METHOD_LOCK.md``.

Verification levels:

- ``source_verified_published``: read in the published journal version (Dechow et al. 2011, CAR 28(1)).
- ``source_verified_author_manuscript``: read in the author's June-1999 manuscript of Beneish (1999); the published
  FAJ text is paywalled and was not accessed, so the published page numbers are not mapped
  (``published_version_crosscheck = not_performed``).
- ``secondary_only`` / ``unverified``: never enables a published score.

A published score is computed only when ``score_enabled`` is true, i.e. every coefficient and the transformation are
at an allowed verification level. Method interpretation (local applicability, input mapping to Taiwan IFRS / TW-GAAP)
remains ``DRAFT_PENDING_METHOD_OWNER_REVIEW`` (Yu-Jing); reproducing the arithmetic does not approve it.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

REGISTRY_VERSION = "literature_method_registry_v1"
APPROVAL_STATUS = "DRAFT_PENDING_METHOD_OWNER_REVIEW"
ALLOWED_VERIFICATION = ("source_verified_published", "source_verified_author_manuscript")
BENEISH_MODEL_ID = "beneish_1999_full8_v1"
DECHOW_MODEL_ID = "dechow_2011_model1_v1"
COMPARISON_ID = "literature_comparison_v1"

PAPER_SOURCES: dict[str, dict[str, Any]] = {
    "beneish_1999": {
        "citation": "Beneish, M. D. (1999). The Detection of Earnings Manipulation. Financial Analysts Journal, 55(5), 24-36.",
        "doi": "10.2469/faj.v55.n5.2296",
        "publisher_url": "https://rpc.cfainstitute.org/research/financial-analysts-journal/1999/the-detection-of-earnings-manipulation",
        "publisher_access": "members_only_not_accessed",
        "verified_text": {
            "version": "author_manuscript_june_1999",
            "title_page": "The Detection of Earnings Manipulation, Messod D. Beneish, June 1999, Comments Welcome",
            "retrieved_from": "https://www.calctopia.com/papers/beneish1999.pdf",
            "retrieved_at": "2026-10-12",
            "pages": 27,
            "bytes": 153381,
            "sha256": "78b2f0143770c9c06871ba8e8d8fb764fc95a4dd379ae37e1c301d16c42faffe",
            "redistributed": False,
            "host_note": "Third-party host of the author's working paper; not the publisher's version of record.",
        },
        "published_version_crosscheck": "not_performed_publisher_text_paywalled",
    },
    "dechow_2011": {
        "citation": ("Dechow, P. M., Ge, W., Larson, C. R., & Sloan, R. G. (2011). Predicting Material Accounting "
                     "Misstatements. Contemporary Accounting Research, 28(1), 17-82."),
        "doi": "10.1111/j.1911-3846.2010.01041.x",
        "manuscript_url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=997483",
        "verified_text": {
            "version": "published_journal_version_car_28_1",
            "retrieved_from": "https://www.thecaq.org/wp-content/uploads/2018/03/Dechow-et-al-2011-Contemporary_Accounting_Research.pdf",
            "retrieved_at": "2026-10-12",
            "pages": 67,
            "bytes": 752761,
            "sha256": "e1a6e49ce1e10ad893eefe7fd5264c95fe841bd55f1ee68e82998445a4dc15dc",
            "redistributed": False,
            "page_mapping": "journal page = PDF page + 15 (PDF page 1 is the CAAA copyright cover)",
            "copyright_note": "CAAA retains copyright; further reproduction not permitted. Only short citations are quoted.",
        },
        "secondary_reference_not_used_for_verification": "https://bpb-us-w2.wpmucdn.com/u.osu.edu/dist/3/40936/files/2016/12/F-Score-xx23jg.pdf",
    },
}

# --------------------------------------------------------------------------------------------- Beneish (1999)
_B_SRC = "beneish_1999"
_B_TABLE2 = {"source": _B_SRC, "location": "Table 2 (manuscript p. 23): definitions with COMPUSTAT item numbers",
             "verification": "source_verified_author_manuscript"}
_B_TABLE3 = {"source": _B_SRC, "location": "Table 3, Panel A, row 'Unweighted Probit' (manuscript p. 24)",
             "verification": "source_verified_author_manuscript"}

BENEISH_1999: dict[str, Any] = {
    "model_id": BENEISH_MODEL_ID,
    "paper": _B_SRC,
    "paper_variant": ("Beneish (1999) eight-variable unweighted probit, Table 3 Panel A (estimation sample of 50 "
                      "manipulators and 1,708 controls, 1982-1988). Not the five-variable variant, not the WESML row, "
                      "not Beneish, Lee & Nichols (2013)."),
    "formula_version": "beneish_1999_full8_unweighted_probit_v1",
    "transformation": {"kind": "probit_index",
                       "score": "M = constant + sum(coefficient_i * variable_i)",
                       "probability": "Phi(M), standard normal CDF (original estimation sample; unweighted probit "
                                      "over-represents manipulators; not a population or Taiwan probability)",
                       "source": {"source": _B_SRC, "location": "Table 3 Panel A; text p. 17 (score vs probability)",
                                  "verification": "source_verified_author_manuscript"}},
    "intercept": {"value": "-4.840", **_B_TABLE3},
    "terms": [
        {"variable": "DSRI", "name": "Days Sales in Receivables Index", "coefficient": "0.920", **_B_TABLE3,
         "definition": "(Receivables_t / Sales_t) / (Receivables_t-1 / Sales_t-1)",
         "compustat": {"Receivables": 2, "Sales": 12}, "periods": ["t", "t-1"]},
        {"variable": "GMI", "name": "Gross Margin Index", "coefficient": "0.528", **_B_TABLE3,
         "definition": "[(Sales_t-1 - COGS_t-1) / Sales_t-1] / [(Sales_t - COGS_t) / Sales_t]",
         "compustat": {"Sales": 12, "COGS": 41}, "periods": ["t", "t-1"]},
        {"variable": "AQI", "name": "Asset Quality Index", "coefficient": "0.404", **_B_TABLE3,
         "definition": "[1 - (CurrentAssets_t + PPE_t) / TotalAssets_t] / [1 - (CurrentAssets_t-1 + PPE_t-1) / TotalAssets_t-1]",
         "compustat": {"CurrentAssets": 4, "PPE": 8, "TotalAssets": 6}, "periods": ["t", "t-1"],
         "note": "The 1999 definition has no 'securities' term (that term belongs to later variants)."},
        {"variable": "SGI", "name": "Sales Growth Index", "coefficient": "0.892", **_B_TABLE3,
         "definition": "Sales_t / Sales_t-1", "compustat": {"Sales": 12}, "periods": ["t", "t-1"]},
        {"variable": "DEPI", "name": "Depreciation Index", "coefficient": "0.115", **_B_TABLE3,
         "definition": "[Dep_t-1 / (Dep_t-1 + PPE_t-1)] / [Dep_t / (Dep_t + PPE_t)]",
         "compustat": {"Depreciation": "14 less 65 (depreciation excluding amortization of intangibles)", "PPE": 8},
         "periods": ["t", "t-1"]},
        {"variable": "SGAI", "name": "SG&A Expense Index", "coefficient": "-0.172", **_B_TABLE3,
         "definition": "(SGA_t / Sales_t) / (SGA_t-1 / Sales_t-1)", "compustat": {"SGA": 189, "Sales": 12},
         "periods": ["t", "t-1"]},
        {"variable": "LVGI", "name": "Leverage Index", "coefficient": "-0.327", **_B_TABLE3,
         "definition": ("[(LTD_t + CurrentLiabilities_t) / TotalAssets_t] / "
                        "[(LTD_t-1 + CurrentLiabilities_t-1) / TotalAssets_t-1]"),
         "compustat": {"LTD": 9, "CurrentLiabilities": 5, "TotalAssets": 6}, "periods": ["t", "t-1"]},
        {"variable": "TATA", "name": "Total Accruals to Total Assets", "coefficient": "4.679", **_B_TABLE3,
         "definition": ("[(dCurrentAssets_t - dCash_t) - (dCurrentLiabilities_t - dCurrentMaturitiesLTD_t - "
                        "dIncomeTaxPayable_t) - DepreciationAndAmortization_t] / TotalAssets_t"),
         "compustat": {"CurrentAssets": 4, "Cash": 1, "CurrentLiabilities": 5, "CurrentMaturitiesLTD": 44,
                       "IncomeTaxPayable": 71, "DepreciationAndAmortization": 14, "TotalAssets": 6},
         "periods": ["t", "t-1"],
         "note": "Working-capital accrual definition of the 1999 paper; NOT (income - CFO) and NOT the existing proxy."},
    ],
    "definition_source": _B_TABLE2,
    "benchmark": {"kind": "original_us_sample_classification_cutoff", "score_cutoff": "-1.78",
                  "probability_cutoff": "0.0376",
                  "condition": "unweighted probit, relative error costs 20:1 or 30:1 (estimation and holdout sample)",
                  "source": {"source": _B_SRC, "location": "text p. 17 and Table 5",
                             "verification": "source_verified_author_manuscript"},
                  "applicability": "Original US-sample benchmark only; NOT a Taiwan cutoff and never applied as a label."},
    "paper_sample_treatments_not_applied": [
        "Winsorization at the 1st/99th percentiles (sample-level; undefined for a single firm-year).",
        "AQI set to 1 when its t-1 denominator is zero; DEPI and SGAI set to 1 when COMPUSTAT items are unavailable "
        "(p. 12). These are estimation-sample treatments; here such cases are reported as not computable.",
    ],
    "excluded_alternatives": {
        "WESML row (Table 3 Panel A)": "-4.954, .789, .459, .306, .701, .033, -.006, 3.937, -.264 (different estimator)",
        "five_variable_variant": "not this paper's eight-variable specification",
    },
}

# --------------------------------------------------------------------------------------------- Dechow et al. (2011)
_D_SRC = "dechow_2011"
_D_TABLE3 = {"source": _D_SRC, "location": "Table 3 'Variable definitions', CAR pp. 35-38 (PDF pp. 20-23)",
             "verification": "source_verified_published"}
_D_TABLE7 = {"source": _D_SRC,
             "location": "Table 7 Panel A, column 'Model 1 Financial statement variables', CAR pp. 55-56 (PDF pp. 40-41)",
             "verification": "source_verified_published"}

DECHOW_2011: dict[str, Any] = {
    "model_id": DECHOW_MODEL_ID,
    "paper": _D_SRC,
    "paper_variant": ("Dechow, Ge, Larson & Sloan (2011) Table 7 Model 1 (financial-statement variables only). Not "
                      "Model 2 or 3, not a recalibrated version and not Piotroski's (2000) F-score."),
    "formula_version": "dechow_2011_table7_model1_v1",
    "transformation": {"kind": "logistic",
                       "predicted_value": "PV = intercept + sum(coefficient_i * variable_i)",
                       "probability": "exp(PV) / (1 + exp(PV))",
                       "f_score": "probability / unconditional_probability",
                       "source": {"source": _D_SRC, "location": "CAR p. 60 (PDF p. 45) and the Enron example p. 61 (PDF p. 46)",
                                  "verification": "source_verified_published"}},
    "intercept": {"value": "-7.893", **_D_TABLE7},
    "terms": [
        {"variable": "rsst_acc", "name": "RSST accruals", "coefficient": "0.790", **_D_TABLE7,
         "definition": ("(dWC + dNCO + dFIN) / average total assets; WC = (CurrentAssets - CashAndShortTermInvestments) - "
                        "(CurrentLiabilities - DebtInCurrentLiabilities); NCO = (TotalAssets - CurrentAssets - "
                        "InvestmentsAndAdvances) - (TotalLiabilities - CurrentLiabilities - LongTermDebt); FIN = "
                        "(ShortTermInvestments + LongTermInvestments) - "
                        "(LongTermDebt + DebtInCurrentLiabilities + PreferredStock)"),
         "compustat": {"CurrentAssets": 4, "CashAndShortTermInvestments": 1, "CurrentLiabilities": 5,
                       "DebtInCurrentLiabilities": 34, "TotalAssets": 6, "InvestmentsAndAdvances": 32,
                       "TotalLiabilities": 181, "LongTermDebt": 9, "ShortTermInvestments": 193,
                       "LongTermInvestments": 32, "PreferredStock": 130},
         "periods": ["t", "t-1"], "definition_source": _D_TABLE3,
         "note": "Richardson et al. (2005) decomposition; NOT net income minus operating cash flow."},
        {"variable": "ch_rec", "name": "Change in receivables", "coefficient": "2.518", **_D_TABLE7,
         "definition": "dAccountsReceivable / average total assets", "compustat": {"AccountsReceivable": 2},
         "periods": ["t", "t-1"], "definition_source": _D_TABLE3},
        {"variable": "ch_inv", "name": "Change in inventory", "coefficient": "1.191", **_D_TABLE7,
         "definition": "dInventory / average total assets", "compustat": {"Inventory": 3},
         "periods": ["t", "t-1"], "definition_source": _D_TABLE3},
        {"variable": "soft_assets", "name": "% Soft assets", "coefficient": "1.979", **_D_TABLE7,
         "definition": "(TotalAssets - PPE - CashAndCashEquivalent) / TotalAssets",
         "compustat": {"TotalAssets": 6, "PPE": 8, "CashAndCashEquivalent": 1}, "periods": ["t"],
         "definition_source": _D_TABLE3},
        {"variable": "ch_cs", "name": "Change in cash sales", "coefficient": "0.171", **_D_TABLE7,
         "definition": ("percentage change in cash sales, cash sales = Sales - dAccountsReceivable; "
                        "(CS_t - CS_t-1) / CS_t-1"),
         "compustat": {"Sales": 12, "AccountsReceivable": 2}, "periods": ["t", "t-1", "t-2"],
         "definition_source": _D_TABLE3},
        {"variable": "ch_roa", "name": "Change in return on assets", "coefficient": "-0.932", **_D_TABLE7,
         "definition": "Earnings_t / average total assets_t - Earnings_t-1 / average total assets_t-1",
         "compustat": {"Earnings": 18, "TotalAssets": 6}, "periods": ["t", "t-1", "t-2"],
         "definition_source": _D_TABLE3},
        {"variable": "issue", "name": "Actual issuance", "coefficient": "1.029", **_D_TABLE7,
         "definition": "1 if the firm issued securities during year t (DATA 108 > 0 or DATA 111 > 0), else 0",
         "compustat": {"SaleOfCommonAndPreferredStock": 108, "LongTermDebtIssuance": 111}, "periods": ["t"],
         "definition_source": _D_TABLE3,
         "note": "An absent issuance record is UNKNOWN here, never 0."},
    ],
    "scaling": {"unconditional_probability": "0.0037",
                "derivation": "494 / (132,967 + 494) = 0.0037 (misstatement firm-years / all firm-years, model 1 sample)",
                "source": {"source": _D_SRC, "location": "CAR p. 61 (PDF p. 46), Enron example",
                           "verification": "source_verified_published"},
                "applicability": "Sample-specific US SEC-AAER base rate; the F-score is not a Taiwan probability."},
    "reference_example": {"firm_year": "Enron 2000 (published worked example)",
                          "inputs": {"rsst_acc": "0.01659", "ch_rec": "0.17641", "ch_inv": "0.00718",
                                     "soft_assets": "0.79975", "ch_cs": "1.33335", "ch_roa": "-0.01285", "issue": "1"},
                          "published_predicted_value": "-4.575", "published_probability": "0.01020",
                          "published_f_score": "2.76",
                          "source": {"source": _D_SRC, "location": "CAR p. 61 (PDF p. 46)",
                                     "verification": "source_verified_published"}},
    "benchmark": {"kind": "original_us_sample_reference_points", "f_score_one": "1.00 = unconditional expectation",
                  "model1_quintile5_minimum": "1.397",
                  "source": {"source": _D_SRC, "location": "CAR p. 61 and Table 7 Panel B/C",
                             "verification": "source_verified_published"},
                  "applicability": "Original US-sample reference points only; NOT a Taiwan cutoff and never applied as a label."},
    "paper_sample_treatments_not_applied": [
        "Winsorization of continuous variables at the 1st/99th percentiles (sample-level; undefined for one firm-year).",
    ],
    "excluded_alternatives": {"Model 2": "adds abnormal change in employees and operating leases",
                              "Model 3": "adds market-adjusted returns", "Piotroski_F_score": "different paper and construct"},
}

MODELS = {BENEISH_MODEL_ID: BENEISH_1999, DECHOW_MODEL_ID: DECHOW_2011}


def verification_problems(spec: dict[str, Any]) -> list[str]:
    """Reasons a published score must stay disabled for this specification (empty = enabled)."""
    problems = []
    numeric = [("intercept", spec.get("intercept", {}), "value")] + [
        (term["variable"], term, "coefficient") for term in spec.get("terms", [])]
    sourced = [(name, item) for name, item, _ in numeric]
    sourced.append(("transformation", spec.get("transformation", {}).get("source", {})))
    if "scaling" in spec:
        sourced.append(("scaling", spec["scaling"].get("source", {})))
        numeric.append(("scaling", spec["scaling"], "unconditional_probability"))
    for name, item in sourced:
        if item.get("verification") not in ALLOWED_VERIFICATION:
            problems.append(f"{name}:{item.get('verification', 'missing')}")
    for name, item, field in numeric:
        if not _exact(item.get(field)):
            problems.append(f"{name}:value_not_exact_decimal")
    return problems


def _exact(text: Any) -> bool:
    if text is None:
        return False
    try:
        return Decimal(str(text)).is_finite()
    except Exception:  # noqa: BLE001 - any parse failure means not exact
        return False


def coefficients(spec: dict[str, Any]) -> tuple[Decimal, dict[str, Decimal]]:
    return Decimal(spec["intercept"]["value"]), {t["variable"]: Decimal(t["coefficient"]) for t in spec["terms"]}


def model_spec(model_id: str) -> dict[str, Any]:
    if model_id not in MODELS:
        raise KeyError(model_id)
    return deepcopy(MODELS[model_id])


def registry_payload() -> dict[str, Any]:
    models = []
    for spec in MODELS.values():
        problems = verification_problems(spec)
        models.append({**deepcopy(spec), "score_enabled": not problems, "verification_problems": problems,
                       "approval_status": APPROVAL_STATUS})
    return {"registry_version": REGISTRY_VERSION, "approval_status": APPROVAL_STATUS,
            "paper_sources": deepcopy(PAPER_SOURCES),
            "models": models,
            "comparison": {"comparison_id": COMPARISON_ID,
                           "unit_of_observation": ["ticker", "fiscal_year", "statement_scope", "accounting_framework",
                                                   "filing_version_side", "as_of_cutoff", "model_version"],
                           "limits": ("A single known case cannot show that one model outperforms the other; no AUC, "
                                      "precision, sensitivity, specificity, confidence interval or significance is reported.")},
            "approval_note": ("The arithmetic reproduces the published formulas; local applicability, the Taiwan input "
                              "mapping and any interpretation await the method owner (Yu-Jing).")}
