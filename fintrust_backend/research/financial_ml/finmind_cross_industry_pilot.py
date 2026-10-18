"""FinMind phase5B: stratified industry pilot and read-only raw schema audit.

Never infers annual values from quarters, never assigns normal labels.
Downloads are performed separately by the pre-existing finmind_bulk_stage.py.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from .finmind_bulk_stage import DATASETS, URL

FIELDS = ('ticker', 'company_name', 'industry_category', 'market',
          'source_snapshot_date', 'historical_eligibility', 'normal_label_status')


def _write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_universe(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError('wrong_candidate_csv_schema')
        rows = list(reader)
    seen = set()
    for row in rows:
        ticker = row['ticker'].strip()
        if not (len(ticker) == 4 and ticker.isascii() and ticker.isdecimal()) or ticker == '1785':
            raise ValueError('invalid_or_reserved_ticker')
        if ticker in seen:
            raise ValueError('duplicate_ticker_in_candidate_csv')
        if row['market'] not in ('twse', 'tpex') or row['normal_label_status'] != 'UNREVIEWED':
            raise ValueError('market_or_label_contract_violation')
        if row['historical_eligibility'] != 'UNVERIFIED':
            raise ValueError('historical_eligibility_not_candidate')
        seen.add(ticker)
    return rows


def _rank(seed, row):
    return hashlib.sha256(f'{seed}:{row["ticker"]}'.encode()).hexdigest()


def pilot(source, output, *, size=24, semiconductor=4, seed=42, anchor='2330'):
    """Deterministic current-issuer stratification; creates no finance API requests."""
    if not 6 <= size <= 30 or not 1 <= semiconductor <= size:
        raise ValueError('pilot_sample_size_out_of_bounds')
    rows = read_universe(source)
    industry = defaultdict(list)
    for row in rows:
        industry[row['industry_category']].append(row)
    if len(rows) < size or not industry.get('半導體業'):
        raise ValueError('insufficient_universe_or_no_semiconductors')
    semi = sorted(industry.pop('半導體業'), key=lambda row: _rank(seed, row))
    anchors = [row for row in semi if row['ticker'] == anchor]
    selected = anchors[:1]
    selected.extend(row for row in semi if row['ticker'] not in {r['ticker'] for r in selected})
    selected = selected[:semiconductor]
    groups = sorted(industry, key=lambda sector: (-len(industry[sector]), sector))
    for number in range(2):
        for sector in groups:
            if len(selected) >= size:
                break
            possibilities = sorted(industry[sector], key=lambda row: _rank(seed, row))
            used = {row['ticker'] for row in selected}
            candidates = [row for row in possibilities if row['ticker'] not in used]
            if not candidates or number >= len(industry[sector]):
                continue
            if number == 0:
                preferred = min(('twse', 'tpex'),
                                key=lambda market: sum(row['market'] == market for row in selected))
                selected.append(next((row for row in candidates if row['market'] == preferred), candidates[0]))
            else:
                selected.append(candidates[0])
        if len(selected) >= size:
            break
    if len(selected) != size:
        raise ValueError('insufficient_industry_sample_capacity')
    output = Path(output)
    _write_csv(output/'finmind_pilot_candidates.csv', selected, FIELDS)
    report = {
        'status': 'CURRENT_UNIVERSE_STRATIFIED_PILOT_PLAN_NOT_FINANCIAL_DOWNLOAD',
        'input_company_count': len(rows), 'selected_company_count': len(selected),
        'selected_industries': dict(sorted(Counter(row['industry_category'] for row in selected).items())),
        'selected_markets': dict(sorted(Counter(row['market'] for row in selected).items())),
        'semiconductor_selected': sum(row['industry_category'] == '半導體業' for row in selected),
        'anchor_included': any(row['ticker'] == anchor for row in selected),
        'finance_request_budget': len(selected)*len(DATASETS),
        'source_sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        'historical_membership_verified': False, 'normal_labels_created': 0,
        'network_requests': 0,
        'warning': 'Selection reflects current issuer master, not a historical representative sample.'
    }
    (output/'finmind_pilot_plan.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return report


def _literature_input_aliases():
    from app.services.financial_research.literature_inputs import MAPPINGS
    mapping = {}
    for metric in MAPPINGS:
        rule = metric.tifrs
        names = set()
        for key in ('lines', 'minuend', 'subtrahend'):
            names.update(rule.get(key, []))
        mapping[metric.metric] = tuple(sorted(names))
    return mapping


def audit(pilot_csv, raw_root, output, *, mapping=None):
    """Inspect cached FinMind JSON for source line availability, not financial semantics."""
    selected = read_universe(pilot_csv)
    mapping = mapping if mapping is not None else _literature_input_aliases()
    raw_root, folder = Path(raw_root), Path(output)
    diagnostics, matches = [], []
    fields = defaultdict(lambda: {'dates': set(), 'tickers': set(), 'names': set()})
    statuses = Counter()
    for company in selected:
        ticker = company['ticker']
        found_types = set()
        for dataset in DATASETS:
            path = raw_root/ticker/(dataset+'.json')
            record = {'ticker':ticker, 'industry_category':company['industry_category'],
                      'dataset':dataset, 'status':'raw_not_downloaded', 'raw_rows':0,
                      'fiscal_years_seen':'', 'quarter_end_dates_seen':0,
                      'non_quarter_end_rows':0, 'duplicate_type_period_collisions':0,
                      'source_sha256':'', 'invalid_raw_rows':0}
            if path.exists():
                raw = path.read_bytes()
                record['source_sha256'] = hashlib.sha256(raw).hexdigest()
                try:
                    body = json.loads(raw)
                    if (body.get('ticker') != ticker or body.get('dataset') != dataset
                        or body.get('source') != URL or not isinstance(body.get('records'), list)):
                        raise ValueError('wrong_raw_archive_contract')
                    seen, dates = defaultdict(set), set()
                    invalid, non_quarter = 0, 0
                    for item in body['records']:
                        try:
                            if str(item['stock_id']) != ticker:
                                raise ValueError('wrong_ticker')
                            when = date.fromisoformat(str(item['date']))
                            typ = str(item['type']).strip()
                            amount = float(item['value'])
                            if not typ or not math.isfinite(amount):
                                raise ValueError('invalid_value_or_type')
                            seen[(when.isoformat(), typ)].add(
                                (str(item['value']), str(item.get('origin_name', ''))))
                            dates.add(when)
                            if (when.month, when.day) not in ((3,31),(6,30),(9,30),(12,31)):
                                non_quarter += 1
                            found_types.add(typ)
                            field = fields[(dataset, typ)]
                            field['dates'].add(when.isoformat())
                            field['tickers'].add(ticker)
                            field['names'].add(str(item.get('origin_name', '')))
                        except (ValueError, TypeError, KeyError, OverflowError):
                            invalid += 1
                    record.update(status='raw_schema_review_only', raw_rows=len(body['records']),
                                  fiscal_years_seen=','.join(map(str, sorted({d.year for d in dates}))),
                                  quarter_end_dates_seen=sum((d.month, d.day) in
                                      ((3,31),(6,30),(9,30),(12,31)) for d in dates),
                                  non_quarter_end_rows=non_quarter,
                                  duplicate_type_period_collisions=sum(len(x)>1 for x in seen.values()),
                                  invalid_raw_rows=invalid)
                    if not body['records']:
                        record['status'] = 'raw_empty_response'
                    elif invalid:
                        record['status'] = 'raw_has_invalid_rows'
                except (ValueError, TypeError, KeyError, OSError):
                    record['status'] = 'raw_archive_invalid'
            statuses[record['status']] += 1
            diagnostics.append(record)
        for metric, aliases in mapping.items():
            common = sorted(found_types.intersection(aliases))
            matches.append({
                'ticker':ticker, 'industry_category':company['industry_category'],
                'literature_input_metric':metric,
                'mops_taxonomy_aliases':'|'.join(aliases),
                'matched_finmind_types':'|'.join(common),
                'status':'ALIAS_FOUND_UNVERIFIED_PERIOD_AND_UNIT' if common
                         else 'NO_EXACT_ALIAS_IN_RAW'
            })
    _write_csv(folder/'finmind_raw_schema_audit.csv', diagnostics,
               ('ticker','industry_category','dataset','status','raw_rows',
                'fiscal_years_seen','quarter_end_dates_seen','non_quarter_end_rows',
                'duplicate_type_period_collisions','source_sha256','invalid_raw_rows'))
    _write_csv(folder/'finmind_literature_input_alias_audit.csv', matches,
               ('ticker','industry_category','literature_input_metric',
                'mops_taxonomy_aliases','matched_finmind_types','status'))
    catalog = [
        {'dataset':dataset,'type':typ,'company_count':len(info['tickers']),
         'date_count':len(info['dates']),
         'origin_name_examples':'|'.join(sorted(info['names'])[:3])}
        for (dataset,typ),info in sorted(fields.items())
    ]
    _write_csv(folder/'finmind_field_catalog.csv', catalog,
               ('dataset','type','company_count','date_count','origin_name_examples'))
    report = {
        'status':'RAW_FINMIND_SCHEMA_AND_ALIAS_AUDIT_ONLY_NO_LITERATURE_FEATURES',
        'companies_requested':len(selected),
        'dataset_requests_expected':len(selected)*len(DATASETS),
        'statuses':dict(statuses), 'observed_type_count':len(catalog),
        'input_metric_alias_presence':dict(Counter(row['status'] for row in matches)),
        'source_root':str(raw_root), 'period_semantics_verified':False,
        'finmind_to_mops_value_reconciled':False,
        'official_published_version_verified':False,
        'fiscal_year_annual_values_built':False,
        'literature_15_features_built':False, 'models_trained':False,
        'network_requests':0,
        'warning':('Matching a source type string is not enough to establish '
                   'accounting or fiscal-year comparability. Q4 is not assumed annual.')
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'finmind_pilot_schema_report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Stratified FinMind pilot; no HTTP in this module')
    cmd = parser.add_subparsers(dest='mode', required=True)
    plan = cmd.add_parser('plan')
    plan.add_argument('--candidate-csv', required=True)
    plan.add_argument('--output', required=True)
    plan.add_argument('--size', type=int, default=24)
    plan.add_argument('--semiconductor', type=int, default=4)
    plan.add_argument('--seed', type=int, default=42)
    review = cmd.add_parser('audit')
    review.add_argument('--pilot-csv', required=True)
    review.add_argument('--raw-root', required=True)
    review.add_argument('--output', required=True)
    options = parser.parse_args(argv)
    output = (pilot(options.candidate_csv, options.output, size=options.size,
                    semiconductor=options.semiconductor, seed=options.seed)
              if options.mode == 'plan' else
              audit(options.pilot_csv, options.raw_root, options.output))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
