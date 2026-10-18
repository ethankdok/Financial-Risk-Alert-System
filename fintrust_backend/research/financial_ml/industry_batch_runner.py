"""Bounded, resumable research-only acquisition of candidate semiconductor XBRL.

Consumes the historical candidate CSV and delegates to official_batch's official
allowlisted fetcher, immutable raw archive, and XBRL parser. No cloud or
production DB writes. All candidates remain UNREVIEWED. Dry-run by default.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from research.financial_ml.official_batch import (
    MAX_REQUESTS, acquire, load_candidates, request_plan,
)

ALLOWED_YEARS = (2013, 2014, 2015)
HARD_RUN_CAP = 36


def _previous_verified(folder: Path) -> set[tuple[str, int]]:
    """Only trust manifest successes whose archived bytes match their hash."""
    p = folder / 'acquisition_results.json'
    if not p.is_file():
        return set()
    try:
        outcomes = json.loads(p.read_text(encoding='utf-8')).get('outcomes', {})
    except (ValueError, OSError, TypeError):
        return set()
    from app.services.historical_audit.archive import RawEvidenceArchive
    archive = RawEvidenceArchive(folder / 'raw')
    seen = set()
    for key, outcome in outcomes.items():
        if not isinstance(outcome, dict) or outcome.get('status') != 'validated':
            continue
        try:
            ticker, year = key.split(':', 1)
            if str(outcome.get('ticker')) != ticker or int(outcome.get('fiscal_year')) != int(year):
                continue
            if int(year) not in ALLOWED_YEARS or ticker == '1785':
                continue
            raw = archive.read(outcome['archive_path'])
            import hashlib
            if hashlib.sha256(raw).hexdigest() == outcome.get('content_hash'):
                seen.add((ticker, int(year)))
        except (ValueError, OSError, KeyError, TypeError, RuntimeError):
            continue
    return seen


def _previous_unavailable(folder: Path) -> set[tuple[str, int]]:
    """Defer already-failed official requests until a user explicitly retries them.

    A failed archive request is not proof that the historical filing does not
    exist. We keep its unresolved status and allow explicit retry.
    """
    p = folder / 'acquisition_results.json'
    if not p.is_file():
        return set()
    try:
        outcomes = json.loads(p.read_text(encoding='utf-8')).get('outcomes', {})
        if not isinstance(outcomes, dict):
            return set()
    except (ValueError, OSError, TypeError):
        return set()
    skipped = set()
    for key, item in outcomes.items():
        if not isinstance(item, dict) or item.get('status') != 'source_unavailable':
            continue
        try:
            ticker, year = key.split(':', 1)
            year = int(year)
            if ticker == str(item.get('ticker')) and year == int(item.get('fiscal_year')) and year in ALLOWED_YEARS:
                skipped.add((ticker, year))
        except (AttributeError, TypeError, ValueError):
            continue
    return skipped


def select(candidates: dict, *, years=ALLOWED_YEARS, output_dir='data/financial_ml/official_batch',
           max_company_years=12, tickers=None, retry_unavailable=False) -> tuple[list[dict], dict]:
    if max_company_years < 1 or max_company_years > HARD_RUN_CAP:
        raise ValueError(f'max_company_years must be 1..{HARD_RUN_CAP}')
    if len(set(years)) != len(years) or any(year not in ALLOWED_YEARS for year in years):
        raise ValueError(f'Only distinct years {ALLOWED_YEARS} are supported')
    allowed = set(tickers) if tickers else None
    if allowed is not None and ('1785' in allowed or not allowed.issubset({k[0] for k in candidates})):
        raise ValueError('Requested ticker forbidden or absent from candidate CSV')
    prior = _previous_verified(Path(output_dir))
    universe = sorted({t for t, _ in candidates if t != '1785' and (allowed is None or t in allowed)})
    available = [(ticker, year) for ticker in universe for year in sorted(years) if (ticker, year) in candidates]
    missing = [key for key in available if key not in prior]
    deferred = set() if retry_unavailable else (_previous_unavailable(Path(output_dir)) & set(missing))
    eligible = [key for key in missing if key not in deferred]
    chosen = eligible[:max_company_years]
    plan=[]
    for ticker, year in chosen:
        # Existing validation checks for candidate inventory and 1785 holdout.
        plan += request_plan(candidates, [ticker], [year])
    info = {'status':'candidate_acquisition_plan_only', 'universe_company_years':len(available),
            'verified_archives_reused':len(set(available)&prior),
            'remaining_before_run':len(missing),
            'deferred_source_unavailable':len(deferred),
            'remaining_eligible_before_run':len(eligible),
            'retry_unavailable':bool(retry_unavailable),
            'selected':len(plan),
            'remaining_after_selected':max(0, len(missing)-len(plan)),
            'years':sorted(years), 'max_company_years':max_company_years,
            'network_requests':0, 'normal_labels_created':0, 'production_database_writes':0,
            'historical_eligibility':'UNVERIFIED',
            'warning':'This is acquisition only; no filing is certified original, historical-as-of or normal.'}
    return plan,info


async def run(plan, info, *, folder, execute=False):
    """Execute in chunks (max 12 official requests) with a safe, restartable manifest."""
    if not execute:
        return {**info,'mode':'dry_run','requested_company_years':[(x['ticker'],x['fiscal_year']) for x in plan]}
    total=0
    results=[]
    for index in range(0,len(plan),MAX_REQUESTS):
        batch=plan[index:index+MAX_REQUESTS]
        reply=await acquire(batch,folder,execute=True)
        total+=reply['network_requests']
        results.append({'chunk':index//MAX_REQUESTS+1,'requested':len(batch),
                        'network_requests':reply['network_requests'],
                        'outcome_counts_cumulative':reply['outcome_counts']})
    # Empty execute: do not alter existing manifests or source files.
    return {**info,'mode':'execute','network_requests':total,'chunks':results,
            'selected_company_years':[(x['ticker'],x['fiscal_year']) for x in plan],
            'production_database_writes':0,'normal_labels_created':0}


def main(argv=None):
    p=argparse.ArgumentParser(description='Resume bounded official XBRL research acquisition; dry-run by default')
    p.add_argument('--candidate-csv',default='data/financial_ml/historical_candidate_coverage/historical_candidate_gap_plan.csv')
    p.add_argument('--output-dir',default='data/financial_ml/official_batch')
    p.add_argument('--year',type=int,action='append')
    p.add_argument('--ticker',action='append')
    p.add_argument('--max-company-years',type=int,default=12)
    p.add_argument('--execute',action='store_true',help='Explicitly allow official network download to research archive')
    p.add_argument('--retry-unavailable',action='store_true',help='Explicitly retry previous source_unavailable requests')
    args=p.parse_args(argv)
    candidates=load_candidates(args.candidate_csv)
    plan,info=select(candidates, years=tuple(args.year or ALLOWED_YEARS),
                     output_dir=args.output_dir, max_company_years=args.max_company_years,tickers=args.ticker,
                     retry_unavailable=args.retry_unavailable)
    print(json.dumps(asyncio.run(run(plan,info,folder=args.output_dir,execute=args.execute)),ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()