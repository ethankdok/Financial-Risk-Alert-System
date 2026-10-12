"""Deterministic financial-consistency screens (F1, F2) and the conditional Brazel-inspired NFM check (F4).

These are *screening* computations over issuer-reported figures. A divergence is a reason to ask for documents,
never a finding of misstatement. Thresholds are uncalibrated, versioned work-queue heuristics, reported together
with their sensitivity. F1 and F2 are financial-only checks: they are not a replication of Brazel et al. (2009).
F1's gap (AR growth − revenue growth) is *related to but numerically different from* Beneish's DSRI − 1
((AR_t/Sales_t)/(AR_t-1/Sales_t-1) − 1): AR 200→250 with sales 1,000→1,100 gives a gap of 0.15 but DSRI − 1 of
0.136364 (review CR-06). Both rest on the same receivables and sales figures, so they are one evidence family.

Freshness (review CR-02): the top-level result always describes the latest fiscal year present in the company's
facts. When that year cannot be evaluated, the top level reports it as not computable with the
``insufficient_evidence`` queue, and the last computable year is kept only as ``last_computable`` history; a stale
year can neither trigger nor clear the present-day queue.
"""

from __future__ import annotations

import os
from decimal import Decimal, localcontext
from typing import Any

from app.services.integrity import alignment as al
from app.services.integrity.contracts import FindingFamily, FindingStatus, ImplementationTier, ReviewQueue

F1_ID, F2_ID, F4_ID = "F1_REVENUE_RECEIVABLES_ALIGNMENT", "F2_NET_INCOME_CFO_ALIGNMENT", "F4_REVENUE_NFM_GROWTH"
F1_VERSION = "integrity_f1_revenue_receivables_v2"
F2_VERSION = "integrity_f2_net_income_cfo_v2"
F4_VERSION = "integrity_f4_revenue_nfm_readiness_v1"
F1_HEURISTIC_VERSION = "integrity_f1_uncalibrated_gap_heuristic_v1"
F1_DEFAULT_GAP = Decimal("0.20")
F1_SENSITIVITY = (Decimal("0.10"), Decimal("0.20"), Decimal("0.30"))
F1_ENV = "INTEGRITY_F1_GAP_HEURISTIC"

F1_EXPLANATIONS = [
    "客戶結構或授信／付款條件改變（例如給予大客戶較長票期）",
    "期末前集中出貨、季節性或新產品量產時點",
    "應收帳款保理、出售或催收政策改變",
    "併購／分割使期末餘額與全年營收口徑不同",
]
F1_LIMITS = [
    "本檢查僅使用發行人申報之財務數字（同一發行人自報），不是獨立第三方查證。",
    "應收帳款採 XBRL AccountsReceivableNet（不含關係人應收與應收票據）；營收為全年合計、應收為期末時點餘額。",
    "門檻為未經台灣樣本校準的篩檢啟發式規則（附敏感度），超過門檻只代表需要補件查核，不代表財報不實。",
    "F1 差距（AR 成長率 − 營收成長率）與 Beneish DSRI 相關但數值不同（例：AR 200→250、營收 1,000→1,100："
    "F1 = 0.15，DSRI−1 ≈ 0.136364）；附帶欄位 receivables_to_revenue_relative_change 在數學上等於 DSRI−1，"
    "但未經文獻模型輸入閘門。兩者共用應收與營收數字，不可視為互相獨立的佐證。",
    "合併口徑由 MOPS report_id=C 推定、會計年度假設 12/31 結束：兩者僅在已審查樣本（2330／2454）確認。",
]
F2_EXPLANATIONS = [
    "營運資金變動（應收、存貨增加，應付減少）",
    "產業週期與資本支出時點",
    "一次性非現金損益（處分利益、評價損益、減損迴轉）",
    "權益法投資收益未以現金股利收回",
]
F2_LIMITS = [
    "淨利採 XBRL ProfitLoss（含非控制權益）；營業現金流採 CashFlowsFromUsedInOperatingActivities。",
    "營業現金流低於淨利本身不是異常判定；僅作為優先查核排序（監測）。",
    "同一發行人自報數字，不是獨立第三方查證。",
    "正負號約定：本檢查儲存 NI − CFO；研究簡報常用 CFO − NI，兩者互為相反數（cfo_minus_net_income_twd 同時提供）。",
    "合併口徑由 MOPS report_id=C 推定、會計年度假設 12/31 結束：兩者僅在已審查樣本確認。",
]


def f1_heuristic() -> dict[str, Any]:
    raw = os.getenv(F1_ENV, "").strip()
    threshold, source = F1_DEFAULT_GAP, "default"
    if raw:
        parsed = al.to_decimal(raw)
        if parsed is not None and Decimal(0) < parsed < Decimal(5):
            threshold, source = parsed, "environment"
    return {"version": F1_HEURISTIC_VERSION, "metric": "ar_growth_minus_sales_growth", "threshold": al.text(threshold),
            "threshold_source": source, "calibrated": False, "approved_by_method_owner": False,
            "sensitivity_thresholds": [al.text(t) for t in F1_SENSITIVITY],
            "meaning": "work-queue trigger for document requests; not a fraud or misstatement threshold"}


def _finding(check_id: str, family: FindingFamily, title: str, status: FindingStatus, *, version: str,
             tier: ImplementationTier = ImplementationTier.implemented, **fields: Any) -> dict[str, Any]:
    base = {"finding_id": f"{check_id}:{fields.get('period') or 'na'}", "check_id": check_id, "family": family.value,
            "title": title, "status": status.value, "review_queue": None, "implementation_tier": tier.value,
            "method_version": version, "literature_basis": None, "period": None, "evidence_families": [],
            "evidence_ids": [], "inputs": {}, "formula": None, "computed": {}, "heuristic": None, "series": [],
            "reasons": [], "legitimate_explanations": [], "limitations": [], "not_independent_of": [],
            "latest_fact_fiscal_year": None, "latest_period_status": None, "freshness_status": "not_applicable",
            "last_computable": None}
    base.update(fields)
    base["finding_id"] = f"{check_id}:{base['period'] or 'na'}"
    return base


def _value(record: dict[str, Any]) -> Decimal:
    return al.to_decimal(record["value_twd"])


def _input(record: dict[str, Any]) -> dict[str, Any]:
    return {"evidence_id": record["evidence_id"], "fiscal_period": record["fiscal_period"], "value": record["value"],
            "unit": record["unit"], "value_twd": record["value_twd"], "scope": record["scope"],
            "filing_version": record["filing_version"]}


def _missing(index: dict[tuple[str, int], dict[str, Any]], needed: list[tuple[str, int]]) -> list[str]:
    return [f"missing:{metric}:{year}FY" for metric, year in needed if (metric, year) not in index]


# ----------------------------------------------------------------------------------------------- F1
def _f1_pair(index: dict[tuple[str, int], dict[str, Any]], year: int, threshold: Decimal) -> dict[str, Any]:
    needed = [("revenue", year), ("revenue", year - 1), ("accounts_receivable", year), ("accounts_receivable", year - 1)]
    missing = _missing(index, needed)
    pair: dict[str, Any] = {"period": f"{year}FY", "prior_period": f"{year - 1}FY", "evidence_ids": [], "reasons": []}
    if missing:
        return {**pair, "status": FindingStatus.not_computable.value, "reasons": missing}
    records = [index[key] for key in needed]
    pair["evidence_ids"] = [r["evidence_id"] for r in records]
    pair["inputs"] = {name: _input(r) for name, r in zip(("revenue_t", "revenue_t_minus_1", "receivables_t",
                                                          "receivables_t_minus_1"), records, strict=True)}
    problems = al.comparability_problems(records)
    if problems:
        return {**pair, "status": FindingStatus.not_comparable.value, "reasons": problems}
    rev_t, rev_p, ar_t, ar_p = (_value(r) for r in records)
    reasons = []
    if rev_p <= 0:
        reasons.append("prior_revenue_not_positive")
    if ar_p <= 0:
        reasons.append("prior_receivables_not_positive")
    if rev_t < 0 or ar_t < 0:
        reasons.append("negative_current_value")
    if rev_t == 0:
        reasons.append("current_revenue_zero_ratio_undefined")
    if reasons:
        return {**pair, "status": FindingStatus.not_computable.value, "reasons": reasons}
    with localcontext() as ctx:
        ctx.prec = al.PRECISION
        sales_growth = rev_t / rev_p - 1
        ar_growth = ar_t / ar_p - 1
        gap = ar_growth - sales_growth
        ar_to_sales_t, ar_to_sales_p = ar_t / rev_t, ar_p / rev_p
        ar_to_sales_change = ar_to_sales_t / ar_to_sales_p - 1
    pair["computed"] = {
        "sales_growth": al.quantize(sales_growth), "ar_growth": al.quantize(ar_growth), "gap": al.quantize(gap),
        "gap_percentage_points": al.quantize(gap * 100, 2),
        "delta_revenue_twd": al.text(rev_t - rev_p), "delta_receivables_twd": al.text(ar_t - ar_p),
        "receivables_to_revenue_t": al.quantize(ar_to_sales_t), "receivables_to_revenue_t_minus_1": al.quantize(ar_to_sales_p),
        "receivables_to_revenue_relative_change": al.quantize(ar_to_sales_change),
        "approx_days_sales_in_receivables_t": al.quantize(ar_to_sales_t * 365, 1),
        "approx_days_sales_in_receivables_t_minus_1": al.quantize(ar_to_sales_p * 365, 1),
    }
    pair["sensitivity"] = {al.text(t): bool(gap > t) for t in F1_SENSITIVITY}
    pair["exceeds_heuristic"] = bool(gap > threshold)
    pair["status"] = (FindingStatus.descriptive_divergence if gap > threshold
                      else FindingStatus.within_screening_heuristic).value
    return pair


def check_revenue_receivables(index: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    heuristic = f1_heuristic()
    threshold = Decimal(heuristic["threshold"])
    years = sorted({year for metric, year in index if metric in ("revenue", "accounts_receivable")})
    pairs = [_f1_pair(index, year, threshold) for year in years if year - 1 in years]
    common = dict(title="營收與應收帳款成長背離（F1）", version=F1_VERSION, heuristic=heuristic,
                  evidence_families=["revenue", "receivables"],
                  formula="gap = (AR_t / AR_t-1 − 1) − (Revenue_t / Revenue_t-1 − 1)",
                  legitimate_explanations=F1_EXPLANATIONS, limitations=F1_LIMITS,
                  not_independent_of=["beneish_1999_full8_v1:DSRI", "dechow_2011_model1_v1:ch_rec"],
                  literature_basis="Financial-only consistency screen (receivables vs sales); related to, but numerically "
                                   "different from, Beneish (1999) DSRI. Not a Brazel et al. (2009) NFM replication.")
    computable = (FindingStatus.descriptive_divergence.value, FindingStatus.within_screening_heuristic.value)
    latest_year = latest_fact_year(index)
    if latest_year is None or not pairs:
        reasons = ["fewer_than_two_consecutive_annual_periods"] + _missing(
            index, [("revenue", y) for y in years] + [("accounts_receivable", y) for y in years])
        return _finding(F1_ID, FindingFamily.financial_consistency, status=FindingStatus.not_computable,
                        reasons=sorted(set(reasons)), review_queue=ReviewQueue.insufficient_evidence.value,
                        latest_fact_fiscal_year=latest_year, latest_period_status=FindingStatus.not_computable.value,
                        freshness_status="no_computable_period", series=pairs, **common)
    latest = next((p for p in pairs if p["period"] == f"{latest_year}FY"), None) or _f1_pair(index, latest_year, threshold)
    last = next((p for p in reversed(pairs) if p["status"] in computable), None)
    freshness = dict(latest_fact_fiscal_year=latest_year, latest_period_status=latest["status"])
    if latest["status"] in computable:
        queue = ReviewQueue.requires_verification.value if latest.get("exceeds_heuristic") else None
        return _finding(F1_ID, FindingFamily.financial_consistency, status=FindingStatus(latest["status"]),
                        period=latest["period"], review_queue=queue, evidence_ids=latest.get("evidence_ids", []),
                        inputs=latest.get("inputs", {}), computed={**latest.get("computed", {}),
                                                                   "sensitivity": latest.get("sensitivity", {})},
                        reasons=latest.get("reasons", []), series=pairs, freshness_status="current", **freshness,
                        **common)
    return _finding(F1_ID, FindingFamily.financial_consistency, status=FindingStatus(latest["status"]),
                    period=latest["period"], review_queue=ReviewQueue.insufficient_evidence.value,
                    evidence_ids=latest.get("evidence_ids", []), inputs=latest.get("inputs", {}),
                    reasons=["latest_period_not_computable", *latest.get("reasons", [])], series=pairs,
                    freshness_status="latest_period_not_computable", **freshness,
                    last_computable=_history(last), **common)


def latest_fact_year(index: dict[tuple[str, int], dict[str, Any]]) -> int | None:
    """Latest fiscal year with any admitted annual fact of the company (the year a current review must describe)."""
    return max((year for _metric, year in index), default=None)


def _history(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """A stale computable year, kept as history only: it never drives the present-day queue."""
    if entry is None:
        return None
    return {"period": entry["period"], "status": entry["status"], "computed": entry.get("computed", {}),
            "evidence_ids": entry.get("evidence_ids", []), "is_current": False,
            "note": "歷史觀察：最新年度不可計算，本期間結果不代表目前查核結論。"}


# ----------------------------------------------------------------------------------------------- F2
def _f2_year(index: dict[tuple[str, int], dict[str, Any]], year: int) -> dict[str, Any]:
    needed = [("net_income", year), ("operating_cash_flow", year)]
    entry: dict[str, Any] = {"period": f"{year}FY", "evidence_ids": [], "reasons": []}
    missing = _missing(index, needed)
    if missing:
        return {**entry, "status": FindingStatus.unavailable.value, "reasons": missing}
    ni_rec, cfo_rec = index[needed[0]], index[needed[1]]
    entry["evidence_ids"] = [ni_rec["evidence_id"], cfo_rec["evidence_id"]]
    entry["inputs"] = {"net_income": _input(ni_rec), "operating_cash_flow": _input(cfo_rec)}
    problems = al.comparability_problems([ni_rec, cfo_rec])
    if ni_rec.get("filing_version") != cfo_rec.get("filing_version"):
        problems.append("filing_version_mismatch")
    if problems:
        return {**entry, "status": FindingStatus.not_comparable.value, "reasons": sorted(set(problems))}
    ni, cfo = _value(ni_rec), _value(cfo_rec)
    with localcontext() as ctx:
        ctx.prec = al.PRECISION
        gap = ni - cfo
        computed = {"net_income_twd": al.text(ni), "operating_cash_flow_twd": al.text(cfo),
                    "net_income_minus_cfo_twd": al.text(gap), "cfo_minus_net_income_twd": al.text(-gap),
                    "cfo_to_net_income": al.ratio(cfo, ni) if ni > 0 else None,
                    "direction": "cfo_below_net_income" if cfo < ni else "cfo_at_or_above_net_income"}
    if ni <= 0:
        entry["reasons"].append("net_income_not_positive_ratio_undefined")
    return {**entry, "status": FindingStatus.descriptive_gap.value, "computed": computed}


def check_net_income_cfo(index: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    years = sorted({year for metric, year in index if metric in ("net_income", "operating_cash_flow")})
    series = [_f2_year(index, year) for year in years]
    common = dict(title="淨利與營業現金流背離（F2）", version=F2_VERSION,
                  evidence_families=["net_income", "operating_cash_flow"], formula="gap = NI_t − CFO_t；CFO_t / NI_t",
                  legitimate_explanations=F2_EXPLANATIONS, limitations=F2_LIMITS,
                  not_independent_of=["beneish_1999_full8_v1:TATA", "dechow_2011_model1_v1:rsst_acc"],
                  literature_basis="Financial-only accrual-quality screen (earnings vs operating cash flow). Accrual "
                                   "measures in Beneish (1999) TATA and Dechow et al. (2011) RSST use related inputs.")
    gap = FindingStatus.descriptive_gap.value
    latest_year = latest_fact_year(index)
    if latest_year is None:
        return _finding(F2_ID, FindingFamily.financial_consistency, status=FindingStatus.unavailable,
                        reasons=["no_annual_net_income_and_cfo"], series=series,
                        review_queue=ReviewQueue.insufficient_evidence.value, latest_period_status=None,
                        freshness_status="no_computable_period", **common)
    latest = next((s for s in series if s["period"] == f"{latest_year}FY"), None) or _f2_year(index, latest_year)
    last = next((s for s in reversed(series) if s["status"] == gap), None)
    freshness = dict(latest_fact_fiscal_year=latest_year, latest_period_status=latest["status"])
    if latest["status"] != gap:
        status = FindingStatus(latest["status"])
        reasons = ["latest_period_not_computable", *latest.get("reasons", [])] if last else latest.get("reasons", [])
        return _finding(F2_ID, FindingFamily.financial_consistency, status=status, period=latest["period"],
                        reasons=reasons or ["no_annual_net_income_and_cfo"], series=series,
                        evidence_ids=latest.get("evidence_ids", []), inputs=latest.get("inputs", {}),
                        review_queue=ReviewQueue.insufficient_evidence.value,
                        freshness_status="latest_period_not_computable" if last else "no_computable_period",
                        last_computable=_history(last), **freshness, **common)
    streak = 0
    for item in reversed(series):
        if item["status"] != gap or item["computed"]["direction"] != "cfo_below_net_income":
            break
        streak += 1
    queue = ReviewQueue.monitor.value if latest["computed"]["direction"] == "cfo_below_net_income" else None
    return _finding(F2_ID, FindingFamily.financial_consistency, status=FindingStatus.descriptive_gap,
                    period=latest["period"], review_queue=queue, evidence_ids=latest["evidence_ids"],
                    inputs=latest["inputs"], computed={**latest["computed"],
                                                       "consecutive_latest_years_cfo_below_net_income": streak},
                    reasons=latest["reasons"], series=series, freshness_status="current", **freshness,
                    heuristic={"version": "integrity_f2_work_queue_rule_v1", "calibrated": False,
                               "rule": "latest-year CFO below net income → monitor (document request), never a risk level",
                               "sign_convention": "net_income_minus_cfo_twd = NI − CFO; cfo_minus_net_income_twd = CFO − NI"},
                    **common)


# ----------------------------------------------------------------------------------------------- F4
F4_LIMITS = [
    "Brazel, Jones & Zimbelman (2009) 以財務成長與相關非財務指標（如員工數、產能、據點數）成長之差比較；"
    "本系統尚無經驗證、同口徑、連續兩年的非財務指標資料，因此僅提供就緒度檢查與已測試的計算路徑。",
    "非財務指標多為公司自行揭露；外包、自動化或產品組合改變會使營收與員工／產能成長合理背離。",
    "未經台灣樣本驗證之前不設定門檻，也不輸出任何舞弊分數。",
]


def check_revenue_nfm(index: dict[tuple[str, int], dict[str, Any]], nfm_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 1 synthetic compatibility helper, *not* the production F4 entry.

    This historical test-path accepts caller-attested verified_source; it has
    no archived-bytes check. IntegrityWorkbench now exclusively invokes
    nfm_evidence_bridge.check_revenue_nfm_strict. Do not reuse this helper for
    persisted, third-party or real-company assertions.
    """
    common = dict(title="營收與非財務指標成長差異（F4，Brazel 啟發，條件式）", version=F4_VERSION,
                  tier=ImplementationTier.readiness_only, evidence_families=["revenue", "nonfinancial_measure"],
                  formula="diff = (Revenue_t / Revenue_t-1 − 1) − (NFM_t / NFM_t-1 − 1)",
                  literature_basis="Brazel, Jones & Zimbelman (2009), doi:10.1111/j.1475-679X.2009.00349.x "
                                   "(design inspiration; not a replication)", limitations=F4_LIMITS)
    usable = [r for r in nfm_records if r.get("verified_source") and r.get("scale_related")
              and al.to_decimal(r.get("value")) is not None]
    if not usable:
        reasons = ["no_verified_nonfinancial_measure_series"] if not nfm_records else \
            sorted({"nfm_source_not_verified" if not r.get("verified_source") else "nfm_not_scale_related"
                    if not r.get("scale_related") else "nfm_value_missing" for r in nfm_records})
        return _finding(F4_ID, FindingFamily.financial_consistency, status=FindingStatus.unavailable, reasons=reasons,
                        review_queue=ReviewQueue.insufficient_evidence.value, **common)
    by_measure: dict[str, dict[int, dict[str, Any]]] = {}
    for record in usable:
        by_measure.setdefault(record["measure"], {})[int(record["fiscal_year"])] = record
    candidates = []
    for measure, years in sorted(by_measure.items()):
        for year in sorted(years, reverse=True):
            if year - 1 in years and ("revenue", year) in index and ("revenue", year - 1) in index:
                candidates.append((measure, year))
                break
    if not candidates:
        return _finding(F4_ID, FindingFamily.financial_consistency, status=FindingStatus.not_computable,
                        reasons=["no_two_consecutive_years_with_both_revenue_and_nfm"],
                        review_queue=ReviewQueue.insufficient_evidence.value, **common)
    measure, year = candidates[0]
    nfm_t, nfm_p = by_measure[measure][year], by_measure[measure][year - 1]
    rev_t, rev_p = index[("revenue", year)], index[("revenue", year - 1)]
    problems = al.comparability_problems([rev_t, rev_p])
    if nfm_t.get("unit") != nfm_p.get("unit"):
        problems.append("nfm_unit_mismatch")
    if nfm_t.get("scope") != nfm_p.get("scope"):
        problems.append("nfm_scope_mismatch")
    nfm_t_value, nfm_p_value = al.to_decimal(nfm_t["value"]), al.to_decimal(nfm_p["value"])
    if problems:
        return _finding(F4_ID, FindingFamily.financial_consistency, status=FindingStatus.not_comparable,
                        period=f"{year}FY", reasons=sorted(problems), **common)
    if nfm_p_value <= 0 or _value(rev_p) <= 0:
        return _finding(F4_ID, FindingFamily.financial_consistency, status=FindingStatus.not_computable,
                        period=f"{year}FY", reasons=["prior_value_not_positive"], **common)
    with localcontext() as ctx:
        ctx.prec = al.PRECISION
        revenue_growth = _value(rev_t) / _value(rev_p) - 1
        nfm_growth = nfm_t_value / nfm_p_value - 1
        diff = revenue_growth - nfm_growth
    return _finding(F4_ID, FindingFamily.financial_consistency, status=FindingStatus.descriptive_gap,
                    period=f"{year}FY", evidence_ids=[rev_t["evidence_id"], rev_p["evidence_id"]],
                    inputs={"revenue_t": _input(rev_t), "revenue_t_minus_1": _input(rev_p),
                            "nfm_measure": measure, "nfm_t": nfm_t.get("value"), "nfm_t_minus_1": nfm_p.get("value"),
                            "nfm_unit": nfm_t.get("unit")},
                    computed={"revenue_growth": al.quantize(revenue_growth), "nfm_growth": al.quantize(nfm_growth),
                              "growth_difference": al.quantize(diff)},
                    heuristic={"version": F4_VERSION, "calibrated": False, "threshold": None,
                               "note": "no validated Taiwan threshold; descriptive only"}, **common)
