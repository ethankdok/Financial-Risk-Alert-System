import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.anomaly import audit, scaffold_ledger, read_normal_ledger, train
from research.financial_ml.pilot import FEATURES

META = ["ticker", "fiscal_year", "filing_version_id", "filing_version_type", "accounting_framework",
        "analysis_mode", "label", "label_source", "outcome_known_at"]
LEDGER = ["ticker", "fiscal_year", "review_status", "review_source", "reviewed_at", "followup_through"]


def write_csv(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def example_row(ticker, year, label="", **kwargs):
    idx = int(ticker) if ticker.isnumeric() else 1
    row = dict(ticker=ticker, fiscal_year=str(year), filing_version_id=f"test-{ticker}-{year}",
               filing_version_type="original", accounting_framework="TIFRS", analysis_mode="retrospective",
               label=label, label_source="synthetic verified test" if label else "",
               outcome_known_at="2020-01-01T00:00:00+08:00" if label else "")
    for k, f in enumerate(FEATURES):
        row[f] = str((idx % 29) / 21.0 + year * 0.001 + k * 0.12)
    row.update(kwargs)
    return row


class TestNormalOnlyAnomalyPipeline(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name)
        self.dataset = self.path / "ml.csv"
        self.ledger = self.path / "ledger.csv"

    def assemble(self, *, positive_test=True):
        records = []
        reviews = []
        for idx in range(1101, 1135):
            ticker = str(idx)
            for year in (2013, 2014, 2015):
                lbl = ("1" if idx % 7 == 0 else "0") if year == 2015 and positive_test else ""
                records.append(example_row(ticker, year, label=lbl))
                if year <= 2014:
                    reviews.append(dict(ticker=ticker, fiscal_year=str(year), review_status="reviewed_normal",
                                        review_source=f"fake-case-review-{ticker}-{year}",
                                        reviewed_at="2019-01-01T00:00:00+08:00", followup_through="2018-12-31"))
        for year in (2013, 2014, 2015):
            records.append(example_row("1785", year, label="1" if year == 2015 else ""))
            reviews.append(dict(ticker="1785", fiscal_year=str(year), review_status="unreviewed",
                                review_source="", reviewed_at="", followup_through=""))
        write_csv(self.dataset,META+list(FEATURES),records)
        write_csv(self.ledger,LEDGER,reviews)
        return records

    def test_scaffold_is_unreviewed_not_implicitly_normal(self):
        self.assemble()
        out=self.path/'candidates.csv'
        res=scaffold_ledger(self.dataset,out)
        self.assertEqual(res['reviewed_normal'],0)
        self.assertIn('unreviewed',out.read_text())
        self.assertEqual(audit(self.dataset,self.path/'audit')['companies'],35)
        with self.assertRaisesRegex(ValueError,'NORMAL_REFERENCE_INSUFFICIENT'):
            train(self.dataset,out,self.path/'blocked',train_through=2013,val_from=2014,val_through=2014,test_from=2015)

    def test_temporal_normal_fit_reserved_case_and_metrics(self):
        self.assemble()
        report=train(self.dataset,self.ledger,self.path/'out',train_through=2013,val_from=2014,val_through=2014,test_from=2015)
        self.assertEqual(report['train_rows'],34)
        self.assertEqual(report['validation_normal_rows'],34)
        self.assertEqual(report['test_rows'],34)
        self.assertEqual(report['held_out_case_rows'],3)
        self.assertEqual(report['test_metrics']['evaluation_status'],'both_classes_available')
        self.assertTrue(report['retrospective_only'])
        self.assertTrue((self.path/'out'/'anomaly_reserved_case_scores.csv').exists())
        with (self.path/'out'/'anomaly_reserved_case_scores.csv').open(encoding='utf-8') as fh:
            self.assertEqual(len(list(csv.DictReader(fh))),3)

    def test_mlp_reconstruction_runs_on_normal_only(self):
        self.assemble()
        report=train(self.dataset,self.ledger,self.path/'mlp',train_through=2013,val_from=2014,val_through=2014,
                     test_from=2015,model_kind='mlp_autoencoder')
        self.assertEqual(report['status'],'normal_reference_model_trained')
        self.assertEqual(report['model'],'mlp_autoencoder')

    def test_company_disjoint_split(self):
        self.assemble()
        report=train(self.dataset,self.ledger,self.path/'split',train_through=2013,val_from=2014,val_through=2014,
                     test_from=2015,split_policy='company_disjoint',min_train=5,min_val=2,min_companies=2)
        self.assertEqual(report['split_policy'],'company_disjoint')
        self.assertLess(report['train_rows'],34)

    def test_invalid_followup_and_duplicate_detection(self):
        self.assemble()
        with self.ledger.open('a',encoding='utf-8') as fh:
            fh.write('1101,2013,reviewed_normal,dupe,2019-01-01T00:00:00+08:00,2020-12-31\n')
        with self.assertRaisesRegex(ValueError,'DUPLICATE_NORMAL_LEDGER'):
            read_normal_ledger(self.ledger)
        write_csv(self.ledger,LEDGER,[dict(ticker='1101',fiscal_year='2013',review_status='reviewed_normal',
                review_source='a', reviewed_at='2019-01-01T00:00:00+08:00',followup_through='2013-12-31')])
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_FOLLOWUP'):
            read_normal_ledger(self.ledger)

    def test_conflicting_positive_and_normal_training_rejected(self):
        self.assemble()
        rows, _ = __import__('research.financial_ml.anomaly',fromlist=['_csv_rows'])._csv_rows(self.dataset)
        rows[0]['label']='1';rows[0]['label_source']='independent official finding';rows[0]['outcome_known_at']='2020-01-01T00:00:00+08:00'
        write_csv(self.dataset,META+list(FEATURES),rows)
        with self.assertRaisesRegex(ValueError,'CONTRADICTORY_POSITIVE_AND_NORMAL_LEDGER'):
            train(self.dataset,self.ledger,self.path/'blocked',train_through=2013,val_from=2014,val_through=2014,test_from=2015)

    def test_no_fake_f1_when_test_not_labeled(self):
        self.assemble(positive_test=False)
        res=train(self.dataset,self.ledger,self.path/'no_label',train_through=2013,val_from=2014,val_through=2014,test_from=2015)
        self.assertNotIn('f1_positive',res['test_metrics'])
        self.assertEqual(res['test_metrics']['evaluation_status'],'not_computable_without_both_independently_labeled_classes')

    def test_reviewed_after_requested_cutoff_not_in_training(self):
        self.assemble()
        with self.assertRaisesRegex(ValueError,'NORMAL_REFERENCE_INSUFFICIENT'):
            train(self.dataset,self.ledger,self.path/'cutoff',train_through=2013,val_from=2014,val_through=2014,test_from=2015,
                  reviewed_by='2018-01-01T00:00:00+08:00')


if __name__ == '__main__':
    unittest.main()