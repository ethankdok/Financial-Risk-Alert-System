"""Offline tests for FinMind cross-industry source/period readiness."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.finmind_cross_industry_pilot import pilot, audit, read_universe
from research.financial_ml.finmind_bulk_stage import DATASETS, URL

FIELDS=('ticker','company_name','industry_category','market',
        'source_snapshot_date','historical_eligibility','normal_label_status')


class FinMindCrossIndustryPilotTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.source=self.root/'source.csv'
        rows=[]
        for i in range(50):
            rows.append({'ticker': '2330' if i==0 else f'{3000+i}',
                         'company_name':f'company{i}',
                         'industry_category':'半導體業' if i<10 else f'產業{(i-10)//4:02d}',
                         'market':'tpex' if i%3 else 'twse',
                         'source_snapshot_date':'2026-10-18',
                         'historical_eligibility':'UNVERIFIED',
                         'normal_label_status':'UNREVIEWED'})
        with self.source.open('w',encoding='utf-8',newline='') as fp:
            writer=csv.DictWriter(fp,fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_stratified_plan_is_reproducible(self):
        first=pilot(self.source,self.root/'first',size=12,semiconductor=3)
        second=pilot(self.source,self.root/'second',size=12,semiconductor=3)
        self.assertEqual(first['network_requests'],0)
        self.assertTrue(first['anchor_included'])
        self.assertEqual(first['semiconductor_selected'],3)
        self.assertGreaterEqual(len(first['selected_industries']),8)
        self.assertEqual(first['finance_request_budget'],12*len(DATASETS))
        self.assertEqual((self.root/'first'/'finmind_pilot_candidates.csv').read_bytes(),
                         (self.root/'second'/'finmind_pilot_candidates.csv').read_bytes())

    def test_input_csv_is_not_modified(self):
        before=self.source.read_bytes()
        pilot(self.source,self.root/'pilot')
        self.assertEqual(self.source.read_bytes(),before)

    def test_normal_labels_are_not_silently_admitted(self):
        data=self.source.read_text(encoding='utf-8')
        self.source.write_text(data.replace('UNREVIEWED','REVIEWED_NORMAL',1),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'market_or_label'):
            read_universe(self.source)

    def test_finmind_q4_does_not_turn_into_annual_features(self):
        pilot(self.source,self.root/'sample',size=9,semiconductor=2)
        candidates=self.root/'sample'/'finmind_pilot_candidates.csv'
        ticker=read_universe(candidates)[0]['ticker']
        root=self.root/'stage'/ticker
        root.mkdir(parents=True)
        doc={'source':URL,'dataset':DATASETS[0],'ticker':ticker,
             'period':['2013-01-01','2025-12-31'],
             'records':[{'stock_id':ticker,'date':'2023-12-31',
                         'type':'OperatingRevenue','value':100,
                         'origin_name':'營業收入'},
                        {'stock_id':ticker,'date':'2023-06-30',
                         'type':'OperatingRevenue','value':50,
                         'origin_name':'營業收入'}]}
        (root/(DATASETS[0]+'.json')).write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
        report=audit(candidates,self.root/'stage',self.root/'audit',
                     mapping={'sales':('OperatingRevenue','Revenue'),
                              'cash':('CashAndCashEquivalents',)})
        self.assertEqual(report['statuses']['raw_schema_review_only'],1)
        self.assertEqual(report['statuses']['raw_not_downloaded'],26)
        self.assertFalse(report['fiscal_year_annual_values_built'])
        self.assertFalse(report['literature_15_features_built'])
        with (self.root/'audit'/'finmind_literature_input_alias_audit.csv').open(
            encoding='utf-8', newline='') as fp:
            rows=list(csv.DictReader(fp))
        self.assertTrue(any(r['literature_input_metric']=='sales' and
                            r['status']=='ALIAS_FOUND_UNVERIFIED_PERIOD_AND_UNIT'
                            for r in rows))
        self.assertFalse((self.root/'audit'/'annual_features.csv').exists())

    def test_invalid_cached_source_is_quarantined_not_imputed(self):
        pilot(self.source,self.root/'sample',size=9,semiconductor=2)
        csv_path=self.root/'sample'/'finmind_pilot_candidates.csv'
        ticker=read_universe(csv_path)[0]['ticker']
        path=self.root/'stage'/ticker
        path.mkdir(parents=True)
        (path/(DATASETS[0]+'.json')).write_text('{bad json',encoding='utf-8')
        result=audit(csv_path,self.root/'stage',self.root/'audit',
                     mapping={'sales':('OperatingRevenue',)})
        self.assertEqual(result['statuses']['raw_archive_invalid'],1)
        self.assertEqual(result['input_metric_alias_presence']['NO_EXACT_ALIAS_IN_RAW'],9)


if __name__=='__main__':
    unittest.main()
