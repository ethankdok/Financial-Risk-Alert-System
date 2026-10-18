"""Reproducible multi-industry FinMind cohort, quota-paced resumable raw acquisition.

Never generates outcome labels, canonical 8+7 paper variables or training data.
Never calls providers unless --execute is explicitly passed. Each invocation
executes at most max_batches (default 1) of <= 40 issuers. No API keys logged.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .finmind_bulk_stage import DATASETS, URL, run as fetch_batch
from .finmind_cross_industry_pilot import FIELDS, read_universe


def _order(seed, row):
    return hashlib.sha256(f'{seed}:{row["ticker"]}'.encode('ascii')).hexdigest()


def _choose(group, n, seed, selected):
    """Select both boards when possible, otherwise stable hash ordering."""
    unused = [r for r in group if r['ticker'] not in selected]
    boards = {board: sorted((r for r in unused if r['market'] == board), key=lambda r: _order(seed,r))
              for board in ('twse','tpex')}
    result = []
    while len(result) < n and any(boards.values()):
        preferred = min(boards, key=lambda k: (sum(x['market']==k for x in result), -len(boards[k]),k))
        if not boards[preferred]:
            preferred = next(k for k in boards if boards[k])
        result.append(boards[preferred].pop(0))
    return result


def plan(candidate_csv, output, *, size=120, semiconductors=24, seed=42):
    """Reserve a large semiconductor cohort and balance the remainder across industries."""
    if not (24 <= size <= 500 and 3 <= semiconductors <= size//2):
        raise ValueError('invalid_cohort_size_or_semiconductor_quota')
    original = read_universe(candidate_csv)
    if size > len(original):
        raise ValueError('insufficient_available_issuers')
    groups = defaultdict(list)
    for row in original:
        groups[row['industry_category']].append(row)
    semi = groups.pop('半導體業', [])
    if len(semi) < semiconductors:
        raise ValueError('not_enough_semiconductor_candidates')
    selected=[]
    selected_ids=set()
    preferred_anchor=next((r for r in semi if r['ticker']=='2330'),None)
    if preferred_anchor:
        selected.append(preferred_anchor)
        selected_ids.add('2330')
    for row in _choose(semi,semiconductors-len(selected),seed,selected_ids):
        selected.append(row)
        selected_ids.add(row['ticker'])
    # One pass at a time over distinct non-semiconductor industries, avoiding
    # domination by sectors with larger listing counts.
    industries=sorted(groups, key=lambda g:hashlib.sha256(f'{seed}:{g}'.encode()).hexdigest())
    next_indices={sector:0 for sector in industries}
    for sector in industries:
        groups[sector]=sorted(groups[sector],key=lambda r:_order(seed,r))
    while len(selected)<size:
        additions=0
        for sector in industries:
            index=next_indices[sector]
            entries=groups[sector]
            while index<len(entries) and entries[index]['ticker'] in selected_ids:
                index+=1
            next_indices[sector]=index
            if index<len(entries):
                row=entries[index]
                selected.append(row)
                selected_ids.add(row['ticker'])
                next_indices[sector]=index+1
                additions+=1
            if len(selected)==size:
                break
        if not additions:
            raise ValueError('cohort_stratification_exhausted')
    if any(r['ticker']=='1785' for r in selected) or len(selected_ids)!=size:
        raise ValueError('invalid_final_cohort')
    root=Path(output)
    root.mkdir(parents=True,exist_ok=True)
    csv_path=root/'finmind_scaled_cohort.csv'
    with csv_path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    report={'status':'PLANNED_NO_FINANCIAL_API_REQUESTS',
        'issuer_count':size,'semiconductor_issuer_count':sum(r['industry_category']=='半導體業' for r in selected),
        'industry_count':len({r['industry_category'] for r in selected}),
        'markets':dict(sorted(Counter(r['market'] for r in selected).items())),
        'raw_financial_dataset_jobs':size*len(DATASETS),'batch_size_suggestion':12,
        'source_sha256':hashlib.sha256(Path(candidate_csv).read_bytes()).hexdigest(),
        'cohort_sha256':hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'current_universe_not_historical_panel':True,'normal_labels_created':0,
        'reserved_1785_excluded':True, 'network_requests':0,
        'warning':'Current TWSE/TPEx candidates do not imply historically available filings or verified normal outcomes.'}
    (root/'scaled_cohort_plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def _cached_ok(root,ticker,dataset,start,end):
    path=Path(root)/ticker/(dataset+'.json')
    if not path.is_file():
        return False
    try:
        obj=json.loads(path.read_text(encoding='utf-8'))
        return (obj.get('source')==URL and obj.get('ticker')==ticker and
                obj.get('dataset')==dataset and obj.get('period')==[start,end] and
                isinstance(obj.get('records'),list))
    except (ValueError,OSError,TypeError):
        return False


def batch(candidate_csv, raw_root, reports_root, *, batch_size=12,max_batches=1,
          execute=False,pause_seconds=15,start='2013-01-01',end='2025-12-31',
          getter=None):
    if not 1<=batch_size<=40 or not 1<=max_batches<=3:
        raise ValueError('unsafe_batch_limits')
    if pause_seconds<0:
        raise ValueError('negative_pause')
    if execute and getter is None and pause_seconds < 15:
        raise ValueError('minimum_15_second_api_pause_for_live_run')
    companies=read_universe(candidate_csv)
    all_tickers=sorted(x['ticker'] for x in companies)
    chunks=[all_tickers[i:i+batch_size] for i in range(0,len(all_tickers),batch_size)]
    remaining=[]
    for i, tickers in enumerate(chunks):
        if not all(_cached_ok(raw_root,ticker,dataset,start,end)
                   for ticker in tickers for dataset in DATASETS):
            remaining.append((i,tickers))
    selected=remaining[:max_batches]
    expected_missing=sum(not _cached_ok(raw_root,t,d,start,end)
                         for _,group in selected for t in group for d in DATASETS)
    plan_result={'status':'DRY_RUN_NO_NETWORK' if not execute else 'EXECUTED_OR_PARTIAL',
        'cohort_issuers':len(all_tickers), 'total_jobs':len(all_tickers)*len(DATASETS),
        'chunk_size':batch_size,'remaining_chunks':len(remaining),'chunks_selected':[i for i,_ in selected],
        'expected_network_requests_at_most':expected_missing,'execute':bool(execute),
        'network_requests':0,'reused_cached':0,'zero_record_responses':0,
        'outcome_counts':{},'stop_reason':'none',
        'reserved_1785_excluded':True,'normal_labels_created':0,'production_db_writes':0}
    if not execute:
        return plan_result
    folder=Path(reports_root)
    folder.mkdir(parents=True,exist_ok=True)
    outcomes=Counter()
    for index,tickers in selected:
        # Existing stable archive contract and quota handling remain canonical.
        # It sorts issuer IDs internally and accepts a slice of cohort CSV.
        first=index*batch_size
        kwargs={'source_csv':candidate_csv,'output':raw_root,'offset':first,
               'max_tickers':len(tickers),'start':start,'end':end,
               'execute':True,'pause_seconds':pause_seconds}
        if getter is not None:
            kwargs['getter']=getter
        one=fetch_batch(**kwargs)
        report_path=folder/f'finmind_scaled_batch_{index:03d}.json'
        report_path.write_text(json.dumps(one,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        outcomes.update(one.get('outcome_counts',{}))
        plan_result['network_requests']+=one['requests_sent']
        plan_result['reused_cached']+=one['reused_cached']
        plan_result['zero_record_responses']+=sum(x.get('records')==0 and x.get('status') in ('downloaded','reused')
                                                  for x in one['request_results'])
        # Stop if any request is unsuccessful, not just a quota/access error.
        bad=[x for x in one['request_results'] if x['status'] not in ('downloaded','reused')]
        if one['halted'] or bad or len(one['request_results']) != len(tickers)*len(DATASETS):
            plan_result['stop_reason']='incomplete_or_failed_batch'
            break
    plan_result['outcome_counts']=dict(sorted(outcomes.items()))
    plan_result['remaining_chunks_after_run']=sum(not all(
        _cached_ok(raw_root,t,d,start,end) for t in group for d in DATASETS)
        for group in chunks)
    (folder/'finmind_scaled_run_summary.json').write_text(
        json.dumps(plan_result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return plan_result


def main(argv=None):
    ap=argparse.ArgumentParser(description='Stratified multi-industry FinMind acquisition; dry-run default')
    sub=ap.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('plan')
    p.add_argument('--candidate-csv',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--size',type=int,default=120)
    p.add_argument('--semiconductors',type=int,default=24)
    p.add_argument('--seed',type=int,default=42)
    b=sub.add_parser('batch')
    b.add_argument('--cohort-csv',required=True)
    b.add_argument('--raw-root',required=True)
    b.add_argument('--reports-root',required=True)
    b.add_argument('--batch-size',type=int,default=12)
    b.add_argument('--max-batches',type=int,default=1)
    b.add_argument('--pause-seconds',type=float,default=15)
    b.add_argument('--execute',action='store_true')
    args=ap.parse_args(argv)
    result=plan(args.candidate_csv,args.output,size=args.size,
                semiconductors=args.semiconductors,seed=args.seed) if args.mode=='plan' else batch(
        args.cohort_csv,args.raw_root,args.reports_root,batch_size=args.batch_size,
        max_batches=args.max_batches,pause_seconds=args.pause_seconds,execute=args.execute)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
