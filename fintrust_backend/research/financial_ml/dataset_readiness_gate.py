"""Read-only, evidence-based research readiness audit for financial ML.

Never infer reference-normal labels from no restatement notice, filing parser
success, missing labels, or a 2026 company taxonomy. No model is fitted here.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

FEATURES = (
    'gross_margin','cogs_sales_ratio','operating_margin','net_margin',
    'inventory_to_assets','receivables_sales_ratio','debt_asset_ratio',
    'inventory_turnover','inventory_growth_assets','receivables_growth_assets',
    'earnings_cashflow_gap_proxy','revenue_yoy','inventory_yoy',
    'receivables_yoy','cashflow_assets_ratio'
)


def audit(dataset_path: str | Path, acquisition_path: str | Path, *,
          reserve_ticker: str='1785', min_training_firms: int=20):
    with Path(dataset_path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        columns=set(reader.fieldnames or [])
        required={'ticker','fiscal_year','filing_version_id','filing_version_type',
                  'accounting_framework','analysis_mode',*FEATURES}
        if not required.issubset(columns):
            raise ValueError('Missing required dataset columns: '+str(sorted(required-columns)))
        rows=list(reader)
    outcomes=json.loads(Path(acquisition_path).read_text(encoding='utf-8')).get('outcomes')
    if not isinstance(outcomes,dict):
        raise ValueError('Acquisition manifest missing outcomes map')
    by_year=Counter(); by_ticker=Counter(); missing=Counter(); duplicate_keys=[]
    keys=set(); provenance_errors=[]; nonfinite=[]; warnings=Counter()
    all_admitted=True; any_asof=True
    for r in rows:
        ticker=r['ticker'].strip()
        try:year=int(r['fiscal_year'])
        except (TypeError, ValueError):raise ValueError('Invalid fiscal_year')
        key=(ticker,year)
        if key in keys:duplicate_keys.append(f'{ticker}:{year}')
        keys.add(key);by_year[year]+=1;by_ticker[ticker]+=1
        item=outcomes.get(f'{ticker}:{year}')
        if not isinstance(item,dict) or item.get('status')!='validated':
            provenance_errors.append(f'{ticker}:{year}:missing_validated_acquisition')
            all_admitted=False; any_asof=False
        else:
            if item.get('filing_version_id')!=r['filing_version_id']:
                provenance_errors.append(f'{ticker}:{year}:version_mismatch')
            if item.get('filing_version_type')!=r['filing_version_type']:
                provenance_errors.append(f'{ticker}:{year}:version_type_mismatch')
            if item.get('accounting_framework')!=r['accounting_framework']:
                provenance_errors.append(f'{ticker}:{year}:framework_mismatch')
            if item.get('statement_scope')!='consolidated':
                provenance_errors.append(f'{ticker}:{year}:not_consolidated')
            all_admitted &= bool(item.get('training_admitted',False))
            any_asof &= item.get('filing_version_type')=='original' and bool(item.get('point_in_time_eligible',False))
            for f in item.get('facts',[]):
                if f.get('quality_status')=='warning':
                    warnings[f.get('metric_code','?')]+=1
        for name in FEATURES:
            value=str(r.get(name) or '').strip()
            if not value:
                missing[name]+=1;continue
            try:
                if not math.isfinite(float(value)):nonfinite.append(f'{ticker}:{year}:{name}')
            except ValueError:
                nonfinite.append(f'{ticker}:{year}:{name}')
    n=len(rows)
    labeled=sum(str(r.get('label','')).strip() in {'0','1'} for r in rows)
    normal_reviewed=sum(v.get('normal_label_status')=='reviewed_normal' for v in outcomes.values() if isinstance(v,dict))
    status='blocked_not_training_ready'
    blockers=[]
    if len(by_ticker)<min_training_firms:blockers.append('insufficient_independent_training_companies')
    if not rows:blockers.append('empty_feature_dataset')
    if duplicate_keys:blockers.append('duplicate_company_year')
    if provenance_errors:blockers.append('acquisition_feature_provenance_mismatch')
    if nonfinite:blockers.append('invalid_or_nonfinite_features')
    if reserve_ticker in by_ticker:blockers.append('reserved_case_in_candidate_dataset')
    if not all_admitted or normal_reviewed==0:blockers.append('no_independently_reviewed_normal_reference_cohort')
    if not any_asof:blockers.append('original_filing_and_historical_asof_unverified')
    if labeled==0:blockers.append('no_independent_outcome_labels_for_evaluation')
    # For normal-only experiments, labeled anomalies belong only in evaluation.
    report={
        'status':status if blockers else 'passed_metadata_gates_requires_manual_review',
        'dataset_path':str(dataset_path),'acquisition_manifest':str(acquisition_path),
        'rows':n,'companies':len(by_ticker),'year_counts':dict(sorted(by_year.items())),
        'company_counts':dict(sorted(by_ticker.items())),
        'expected_features':list(FEATURES),'feature_missing_counts':dict(sorted(missing.items())),
        'field_warning_counts':dict(sorted(warnings.items())),
        'labeled_company_years':labeled,'source_reviewed_normal_observations':normal_reviewed,
        'duplicate_company_years':duplicate_keys,'provenance_errors':provenance_errors,
        'nonfinite_features':nonfinite,'excluded_reserved_case':reserve_ticker,
        'original_and_asof_verified':bool(any_asof),
        'fit_performed':False,'test_metrics_performed':False,'model_f1':None,'model_accuracy':None,
        'blocking_reasons':blockers,
        'limitations':[
            'Acquisition manifest is a research record, not an independent normal-label verification.',
            'Without historical original-filing availability, outputs are retrospective-only.',
            'Minimum company count is a pragmatic engineering gate, not a statistical guarantee.',
            'Formal validation requires time/company separation and an untouched reserved case.'
        ]}
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only financial ML readiness and leakage audit')
    p.add_argument('--dataset',required=True)
    p.add_argument('--acquisition-results',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args(argv)
    report=audit(args.dataset,args.acquisition_results)
    dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()