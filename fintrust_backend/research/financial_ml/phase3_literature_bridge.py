"""Phase 3: official Beneish/Dechow features plus FINMIND source coverage bridge.

Official MOPS features are produced only by the existing trusted literature engine.
FinMind source-alias amounts and feature FEASIBILITY are *unapproved candidate
evidence*, never a training dataset, true fraud labels or published-model values.
No HTTP / DB writes; quarantines and unresolved official mismatches preserved.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.services.financial_research import beneish_1999, dechow_2011
from app.services.financial_research.literature_inputs import MAPPINGS, MAPPING_VERSION
from .finmind_bulk_stage import DATASETS, URL
from .finmind_cross_industry_pilot import read_universe
from .phase12_integrated_gate import inspect_archive
from .literature_dataset import produce as produce_official, FEATURES

# Only lexical/provider SOURCE CANDIDATES. None automatically authorizes a
# TIFRS / COMPUSTAT equivalence, annual semantics, 2016-asof use or ML labels.
# Nontrivial sum/difference mappings are not numerically fabricated.
PROVIDER_EXTRA_ALIASES = {
    "sales": ("Revenue",),
    "cogs": ("CostOfGoodsSold",),
    "total_assets": ("TotalAssets",),
    "receivables": ("BillsReceivableNet", "AccountsReceivableDuefromRelatedPartiesNet", "OtherReceivable"),
    "depreciation": ("Depreciation",),
    "earnings": ("IncomeFromContinuingOperations",),
    "amortization": ("AmortizationExpense",),
    "long_term_debt_issued": ("ProceedsFromLongTermDebt",),
    "short_term_investments": ("FinancialAssetsAtAmortizedCost",),
    "investments_and_advances": ("FinancialAssetsAtAmortizedCostNonCurrent",),
}
FAMILY = {name: ("cashflow" if name in (
    "depreciation", "amortization", "long_term_debt_issued", "stock_issued")
    else "income" if name in ("sales", "cogs", "selling_expense",
                               "administrative_expense", "earnings")
    else "balance") for name in (m.metric for m in MAPPINGS)}
DATASET = dict(zip(("income","balance","cashflow"), DATASETS))
QUARTERS = ("03-31","06-30","09-30","12-31")
ACCOUNT_COLUMNS = (
    "ticker","fiscal_year","metric","compustat","context","family","mapping_rule",
    "source_candidate_types","source_hash","status","candidate_annual_value",
    "observed_quarters","source_present_types","method_status","training_admitted",
    "asof_publication_verified"
)
FEATURE_COLUMNS = (
    "ticker","fiscal_year","feature","source_requirement_count",
    "candidate_requirements_met","candidate_requirements_missing",
    "readiness","computed_value","original_filing_asof_verified",
    "training_admitted","model_label"
)
PAIR_FLAGS = ("ticker","year","statement","finmind_type","mops_metric",
              "mops_annual_value","candidate_preference","evidence_status",
              "q4_relative_difference","sum_relative_difference")


def write_table(path, fields, entries):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        wr = csv.DictWriter(handle, fieldnames=fields)
        wr.writeheader()
        wr.writerows(entries)


def checked_decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("provider_non_numeric_or_boolean")
    try:
        v = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise ValueError("provider_non_decimal") from None
    if not v.is_finite():
        raise ValueError("provider_nonfinite_decimal")
    return v


def family_archive(raw_root, ticker, family):
    ds = DATASET[family]
    file = Path(raw_root)/ticker/(ds+".json")
    status = inspect_archive(file,ticker,ds)
    if status["status"] == "quarantined":
        raise ValueError("quarantined_source:"+ticker+":"+ds+":"+status["reason"])
    if status["status"] in ("archive_missing","provider_empty_response","no_monetary_rows"):
        return {}, status["status"], status["source_sha256"]
    archive = json.loads(file.read_text(encoding="utf-8"))
    rows = defaultdict(set)
    for line in archive["records"]:
        typ = str(line["type"])
        if typ.endswith("_per"):
            continue
        rows[(typ,str(line["date"]))].add(checked_decimal(line["value"]))
    if any(len(values) != 1 for values in rows.values()):
        raise ValueError("source_period_collision")
    return {key:next(iter(value)) for key,value in rows.items()}, "raw_present", status["source_sha256"]


def aliases(mapping):
    rule = mapping.tifrs
    types = []
    for key in ("lines","minuend","subtrahend"):
        types.extend(x for x in rule.get(key, []) if not x.startswith(("code:","label:")))
    types.extend(PROVIDER_EXTRA_ALIASES.get(mapping.metric, ()))
    return tuple(sorted(set(types)))


def observed(index, typ, year, family):
    if family == "income":
        values = [index.get((typ,f"{year}-{q}")) for q in QUARTERS]
        return (sum(values,Decimal(0)) if all(v is not None for v in values) else None,
                sum(v is not None for v in values))
    amount=index.get((typ,f"{year}-12-31"))
    return amount, int(amount is not None)


def item_candidate(ticker,year,mapping,source):
    family=FAMILY[mapping.metric]
    index,state,sha=source[family]
    options=aliases(mapping)
    value=None
    present=[]
    quarter_count=0
    if state != "raw_present":
        status=state
    else:
        observed_options=[]
        for typ in options:
            candidate,nq=observed(index,typ,year,family)
            if nq:
                present.append(typ)
                quarter_count=max(quarter_count,nq)
            if candidate is not None:
                observed_options.append((typ,candidate))
        rule=mapping.tifrs["rule"]
        if rule != "one_of":
            status=("multiline_evidence_only_needs_method_review"
                    if present else "multiline_source_not_found")
        elif not observed_options:
            status=("incomplete_income_quarters" if family=="income" and present
                    else "source_candidate_not_found")
        elif len({v for _,v in observed_options}) > 1:
            status="candidate_alias_values_conflict"
        else:
            value=observed_options[0][1]
            status="candidate_amount_only_unapproved"
    return {
        "ticker":ticker,"fiscal_year":year,"metric":mapping.metric,
        "compustat":mapping.compustat,"context":mapping.context,
        "family":family,"mapping_rule":mapping.tifrs["rule"],
        "source_candidate_types":"|".join(options),"source_hash":sha,
        "status":status,"candidate_annual_value":"" if value is None else format(value,"f"),
        "observed_quarters":quarter_count,
        "source_present_types":"|".join(sorted(set(present))),
        "method_status":"DRAFT_NOT_APPROVED_FOR_TAIWAN_ML",
        "training_admitted":"false","asof_publication_verified":"false"
    }


def needed_features(year, account_index):
    """Count *potential* dependencies from the real paper feature engines.

    This never evaluates feature formulas using unapproved provider values.
    """
    result=[]
    components=[
        ("b_"+name, needs) for name,(needs,_) in beneish_1999.COMPONENTS.items()
    ]+[
        ("d_"+name, needs) for name,(needs,_) in dechow_2011.COMPONENTS.items()
    ]
    components.append(("d_issue",[("long_term_debt_issued","t"),
                                   ("stock_issued","t")]))
    for name,requires in components:
        missing=[]
        possible=0
        for metric,period in requires:
            fy=year-{"t":0,"t-1":1,"t-2":2}[period]
            item=account_index.get((fy,metric))
            if item is not None and item["status"]=="candidate_amount_only_unapproved":
                possible+=1
            else:
                missing.append(f"{metric}:{period}:"+(item["status"] if item else "outside_source_range"))
        # Issue is a disjunction of positive issuance EVIDENCE, not arbitrary
        # OR over observed candidate numeric values, and never unknown => zero.
        if name=="d_issue":
            ready="ISSUANCE_POSITIVE_EVIDENCE_REQUIRES_MANUAL_SOURCE_REVIEW"
            missing.append("missing_verified_positive_issuance_or_verified_no_issuance")
        else:
            ready=("ALL_INPUTS_CANDIDATE_ONLY_NOT_OFFICIAL" if not missing else
                   "BLOCKED_BY_UNREVIEWED_OR_MISSING_SOURCE_INPUTS")
        result.append({
            "fiscal_year":year,"feature":name,"source_requirement_count":len(requires),
            "candidate_requirements_met":possible,
            "candidate_requirements_missing":"|".join(missing),
            "readiness":ready,"computed_value":"",
            "original_filing_asof_verified":"false",
            "training_admitted":"false","model_label":"UNKNOWN"
        })
    return result


def reconcile_conflicts(cross_csv,output):
    """Keep official mismatches as review tickets (not self-approval)."""
    if not Path(cross_csv).is_file():
        return {"status":"MOPS_CROSSCHECK_FILE_NOT_FOUND","review_rows":0}
    with Path(cross_csv).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        required=set(PAIR_FLAGS)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("unexpected_mops_crosscheck_columns")
        failures=[]
        for row in reader:
            if row["ticker"]=="1785":
                raise ValueError("holdout_leak_in_official_crosscheck")
            if row["candidate_preference"] in ("NO_MATCH","BOTH_AGREE_AMBIGUOUS"):
                failures.append({k:row.get(k,"") for k in PAIR_FLAGS})
    write_table(Path(output)/"mops_reconciliation_review_queue.csv",
                PAIR_FLAGS,failures)
    return {"status":"OFFICIAL_VALUE_COMPARISON_REVIEW_REQUIRED",
            "review_rows":len(failures),
            "notes":"NO_MATCH or ambiguous candidates are not official mappings."}


def run(data_root,output,*,start_year=2013,end_year=2025):
    if not 2013 <= start_year <= end_year <= 2025:
        raise ValueError("unsupported_fiscal_year_range")
    root=Path(data_root);out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    cohort=root/"finmind_scaled_120"/"finmind_scaled_cohort.csv"
    companies=read_universe(cohort)
    stage1=root/"phase12_integrated_verification"/"phase12_gate_report.json"
    if not stage1.is_file():
        raise FileNotFoundError("phase12_gate_report_missing")
    stage1_data=json.loads(stage1.read_text(encoding="utf-8"))
    stage2=stage1_data["phase2_raw"]
    if stage2["missing_archives"] or stage2["quarantined_issuers"]:
        raise ValueError("phase2_raw_archive_incomplete_or_quarantined")
    if stage2["cohort_companies"]!=len(companies):
        raise ValueError("phase2_company_count_conflicts_with_cohort")
    raw=root/"finmind_cross_industry_raw"
    accounts=[];feasibility=[];count_status=Counter();fstatus=Counter()
    for position,company in enumerate(companies,1):
        ticker=company["ticker"]
        source={family:family_archive(raw,ticker,family) for family in DATASET}
        per_company={}
        for year in range(start_year,end_year+1):
            for metric in MAPPINGS:
                record=item_candidate(ticker,year,metric,source)
                accounts.append(record)
                count_status[record["status"]]+=1
                per_company[(year,metric.metric)]=record
        for year in range(start_year,end_year+1):
            for record in needed_features(year,per_company):
                record["ticker"]=ticker
                feasibility.append(record)
                fstatus[record["readiness"]]+=1
        if position%20==0:
            print(f"[Phase3 coverage] {position}/{len(companies)} issuers",flush=True)
    write_table(out/"finmind_24_account_candidate_coverage.csv",
                ACCOUNT_COLUMNS,accounts)
    write_table(out/"finmind_15_feature_feasibility.csv",
                FEATURE_COLUMNS,feasibility)

    xbrl_manifest=root/"official_batch"/"acquisition_results.json"
    if xbrl_manifest.exists():
        official=produce_official(xbrl_manifest,out/"mops_official_15_features",
                                  min_year=start_year,max_year=end_year)
    else:
        official={"status":"MOPS_ARCHIVE_MISSING_OFFICIAL_FEATURE_EXTRACTION_SKIPPED",
                  "company_year_rows":0,"fully_computed_15_rows":0}
    mismatch=reconcile_conflicts(
        root/"phase12_integrated_verification"/"phase2"/"official"/
        "finmind_mops_annual_crosscheck.csv",out)
    report={
        "status":"PHASE3_LITERATURE_COVERAGE_AND_OFFICIAL_XBRL_FEATURES_RESEARCH_ONLY",
        "cohort_company_count":len(companies),
        "company_years":len(companies)*(end_year-start_year+1),
        "literature_base_metrics":len(MAPPINGS),
        "paper_features":len(FEATURES),
        "account_evidence_rows":len(accounts),
        "component_feasibility_rows":len(feasibility),
        "account_statuses":dict(sorted(count_status.items())),
        "feature_readiness_statuses":dict(sorted(fstatus.items())),
        "official_xbrl_feature_report":official,
        "official_crosscheck_review":mismatch,
        "finmind_accounting_mapping_approved":False,
        "finmind_original_filing_asof_verified":False,
        "finmind_training_15_feature_rows_admitted":0,
        "supervised_training_labels_created":0,
        "dechow_issue_unknown_never_zero":True,
        "reserve_1785_untouched":True,
        "network_requests":0,"production_db_writes":0,
        "prior_phase2_report_sha256":hashlib.sha256(stage1.read_bytes()).hexdigest(),
        "warning":"Official XBRL 15-variable components are retrospective; FINMIND "
                  "output is evidence / candidate feasibility ONLY, not computed "
                  "or training-approved 15 features. No issuer labels are inferred."
    }
    (out/"phase3_integrated_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Phase 3 official 15 feature and candidate 24-input coverage")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--start-year",type=int,default=2013)
    p.add_argument("--end-year",type=int,default=2025)
    a=p.parse_args(argv)
    print(json.dumps(run(a.data_root,a.output,
                         start_year=a.start_year,end_year=a.end_year),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
