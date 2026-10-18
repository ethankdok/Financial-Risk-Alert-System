"""Offline-only tests for exploratory model; never calls MOPS or production systems."""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / 'research/financial_ml/exploratory_temporal.py'
spec = importlib.util.spec_from_file_location('exploratory_temporal', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestExploratory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'data.csv'
        self.dst = Path(self.tmp.name) / 'out'
        self.rows = []
        for y in (2013, 2014, 2015):
            for i in range(6):
                row = {'ticker': f'23{i:02}', 'fiscal_year':str(y),
                       'analysis_mode':'retrospective', 'filing_version_type':'unknown_revision',
                       'label':'','label_source':'','outcome_known_at':''}
                for j, f in enumerate(mod.FEATURES):
                    row[f] = str(1.0+(i+j+0.7)*(0.02*j+0.01)+(y-2013)*0.001*i)
                self.rows.append(row)
        self.save()

    def save(self):
        with self.src.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(self.rows[0].keys()))
            w.writeheader();w.writerows(self.rows)

    def test_pipeline_outputs_no_labels_or_cutoff(self):
        r=mod.run(self.src,self.dst,seeds=3,n_estimators=50)
        self.assertEqual(r['status'],'EXPLORATORY_FIT_ONLY_NOT_EVALUATION')
        self.assertIsNone(r['f1']);self.assertIsNone(r['threshold'])
        self.assertFalse(r['company_disjoint_validation'])
        self.assertEqual(r['year_counts']['2015'],6)
        with (self.dst/'exploratory_2015_holdout_scores.csv').open(encoding='utf-8') as fh:
            self.assertEqual(len(list(csv.DictReader(fh))),6)

    def test_reserved_case_rejected(self):
        self.rows[0]['ticker']='1785';self.save()
        with self.assertRaisesRegex(ValueError,'Reserved case'):mod.run(self.src,self.dst,seeds=2,n_estimators=50)

    def test_duplicates_rejected(self):
        self.rows.append(dict(self.rows[0]));self.save()
        with self.assertRaisesRegex(ValueError,'Duplicate'):mod.run(self.src,self.dst,seeds=2,n_estimators=50)

    def test_nonfinite_rejected(self):
        self.rows[0]['gross_margin']='inf';self.save()
        with self.assertRaisesRegex(ValueError,'Nonfinite'):mod.run(self.src,self.dst,seeds=2,n_estimators=50)

    def test_missing_required_feature_rejected(self):
        self.rows[0]['net_margin']='';self.save()
        with self.assertRaisesRegex(ValueError,'Missing/non-numeric'):mod.run(self.src,self.dst,seeds=2,n_estimators=50)

    def test_labels_rejected(self):
        self.rows[0]['label']='0';self.save()
        with self.assertRaisesRegex(ValueError,'UNREVIEWED'):mod.run(self.src,self.dst,seeds=2,n_estimators=50)


if __name__=='__main__':unittest.main()