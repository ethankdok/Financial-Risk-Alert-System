"""Tests entirely offline, without labels or production DB writes."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.dataset_readiness_gate import FEATURES,audit

class TestGate(unittest.TestCase):
    def setUp(self):
        self.ctx=tempfile.TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.root=Path(self.ctx.name)
        self.csv=self.root/'pilot.csv'
        self.manifest=self.root/'manifest.json'
        self.header=['ticker','fiscal_year','filing_version_id','filing_version_type',
                     'accounting_framework','analysis_mode','label',*FEATURES]
        self.rows=[dict(ticker='2330',fiscal_year='2013',filing_version_id='v1',
                        filing_version_type='unknown_revision',accounting_framework='TIFRS',
                        analysis_mode='retrospective',label='',**{x:'1' for x in FEATURES})]
        self.outcomes={'2330:2013':dict(ticker='2330',fiscal_year=2013,status='validated',
           filing_version_id='v1',filing_version_type='unknown_revision',
           accounting_framework='TIFRS',statement_scope='consolidated',
           normal_label_status='UNREVIEWED',training_admitted=False,facts=[])}
        self.write()
    def write(self):
        with self.csv.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=self.header);w.writeheader();w.writerows(self.rows)
        self.manifest.write_text(json.dumps({'outcomes':self.outcomes}),encoding='utf-8')
    def test_unknown_normal_blocks_fit(self):
        report=audit(self.csv,self.manifest)
        self.assertFalse(report['fit_performed'])
        self.assertIn('no_independently_reviewed_normal_reference_cohort',report['blocking_reasons'])
        self.assertEqual(report['labeled_company_years'],0)
    def test_provenance_mismatch_blocks(self):
        self.rows[0]['filing_version_id']='v2';self.write()
        report=audit(self.csv,self.manifest)
        self.assertIn('acquisition_feature_provenance_mismatch',report['blocking_reasons'])
    def test_reserved_case_detected(self):
        row=self.rows[0].copy();row['ticker']='1785';self.rows.append(row)
        self.outcomes['1785:2013']={**self.outcomes['2330:2013'],'ticker':'1785'}
        self.write();report=audit(self.csv,self.manifest)
        self.assertIn('reserved_case_in_candidate_dataset',report['blocking_reasons'])
    def test_2013_missing_lag_features_not_zero(self):
        self.rows[0]['inventory_yoy']='';self.write()
        report=audit(self.csv,self.manifest)
        self.assertEqual(report['feature_missing_counts']['inventory_yoy'],1)
    def test_duplicate_company_year_detected(self):
        self.rows.append(self.rows[0].copy());self.write()
        report=audit(self.csv,self.manifest)
        self.assertIn('duplicate_company_year',report['blocking_reasons'])

if __name__=='__main__':unittest.main()