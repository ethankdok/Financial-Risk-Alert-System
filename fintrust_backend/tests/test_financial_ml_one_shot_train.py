import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.one_shot_train import FEATURES, read_data, run

class OneShotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.data=self.root/'features.csv'

    def write(self, *, with_reserved=False, with_duplicate=False, with_positive_label=False):
        fieldnames=['ticker','fiscal_year','analysis_mode','filing_version_type','label']+list(FEATURES)
        rows=[]
        for n in range(12):
            for year in (2013,2014,2015):
                r={'ticker':str(2300+n),'fiscal_year':year,
                   'analysis_mode':'retrospective','filing_version_type':'unknown_revision',
                   'label':'1' if with_positive_label and n==0 else ''}
                for f in FEATURES:
                    r[f]=0.13 + n*0.012 + (year-2013)*0.006 +(0.02 if f=='net_margin' else 0)
                rows.append(r)
        if with_reserved:rows[0]['ticker']='1785'
        if with_duplicate:rows.append(rows[-1].copy())
        with self.data.open('w',encoding='utf-8',newline='') as fh:
            w=csv.DictWriter(fh,fieldnames=fieldnames);w.writeheader();w.writerows(rows)

    def test_reserved_company_refused(self):
        self.write(with_reserved=True)
        with self.assertRaisesRegex(ValueError,'Reserved'):
            read_data(self.data)
    def test_duplicate_company_year_refused(self):
        self.write(with_duplicate=True)
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            read_data(self.data)
    def test_outcome_label_refused(self):
        self.write(with_positive_label=True)
        with self.assertRaisesRegex(ValueError,'Labeled outcomes'):
            read_data(self.data)
    def test_models_and_disjoint_output(self):
        self.write()
        result=run(self.data,self.root/'output')
        self.assertEqual(result['experiment_count'],8)
        self.assertEqual(result['labeled_normal_count'],0)
        self.assertIsNone(result['test_accuracy'])
        self.assertTrue(result['company_disjoint_robustness']['no_overlap'])
        self.assertEqual(len(list((self.root/'output'/'models').glob('*.joblib'))),8)
        self.assertTrue((self.root/'output'/'holdout_2015_provisional_scores.csv').is_file())
        self.assertEqual(json.loads((self.root/'output'/'one_shot_report.json').read_text())['rows'],36)

if __name__=='__main__':unittest.main()