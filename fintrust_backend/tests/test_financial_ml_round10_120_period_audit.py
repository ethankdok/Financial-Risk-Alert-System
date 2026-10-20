"""Round10: synthetic stage contract, zero fabricated fraud labels/clean controls."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from research.financial_ml import round10_disclosure_event_label_gate as x
from research.financial_ml.round3_research_models import ANNUAL_COLUMNS

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.panel=self.root/"source.csv"
        self.roster=x.cohort()
        self.prepare()

    def prepare(self):
        with self.panel.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=ANNUAL_COLUMNS)
            w.writeheader()
            for t in self.roster:
                for y in range(2013,2026):
                    r={k:"" for k in ANNUAL_COLUMNS}
                    r.update(ticker=t,fiscal_year=y,label_status="UNKNOWN",
                             training_admitted="false",complete_candidate_vector="true",
                             original_publication_verified="false",
                             original_filing_vintage_verified="false")
                    w.writerow(r)

    def test_real_cohort_contract_120_unique(self):
        self.assertEqual(len(self.roster),120)
        self.assertNotIn("1785",self.roster)
        self.assertIn("6485",self.roster)
        self.assertIn("7723",self.roster)
        self.assertIn("8487",self.roster)

    def test_source_document_leads_12_never_approve_fraud(self):
        leads=x.evidence()
        self.assertEqual(len(leads),12)
        self.assertEqual(len({e["ticker"] for e in leads}),11)
        self.assertTrue(all(e["fraud_label"]=="UNKNOWN" for e in leads))
        self.assertTrue(all(not e["approved_for_training"] for e in leads))

    def test_real_issuer_annual_and_quarter_fully_expand_without_labels(self):
        report=x.materialize(self.panel,self.root/"output")
        self.assertEqual(report["companies"],120)
        self.assertEqual(report["annual_periods"],1560)
        self.assertEqual(report["quarterly_periods"],6240)
        self.assertFalse(report["supervised_classifier_fit_allowed"])
        self.assertIsNone(report["true_fraud_f1"])
        with (self.root/"output"/"round10_1560_annual_manual_review.csv").open(
                encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),1560)
        self.assertTrue(all(y["supervised_fraud_label"]=="UNKNOWN" for y in rows))
        yp=next(r for r in rows if r["ticker"]=="6485" and r["fiscal_year"]=="2023")
        self.assertEqual(yp["event_screening_state"],
                         "COMPANY_DISCLOSURE_CORRECTION_LEAD_REQUIRES_HUMAN_ADJUDICATION")
        self.assertEqual(yp["supervised_fraud_label"],"UNKNOWN")
        clean=next(r for r in rows if r["ticker"]=="2330" and r["fiscal_year"]=="2021")
        self.assertEqual(clean["event_screening_state"],
                         "NOT_COMPLETED_HISTORICAL_OFFICIAL_SCREENING")
        self.assertEqual(clean["supervised_fraud_label"],"UNKNOWN")

    def test_note_correction_not_positive_fraud_training(self):
        x.materialize(self.panel,self.root/"output")
        with (self.root/"output"/"round10_1560_annual_manual_review.csv").open(
                encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f))
        y=next(r for r in rows if r["ticker"]=="1301" and r["fiscal_year"]=="2025")
        self.assertIn("S05",y["event_lead_ids"])
        self.assertEqual(y["approved_supervised_training"],"false")

    def test_no_1785_in_approved_train(self):
        self.assertTrue(all(e["ticker"]!="1785" for e in x.evidence()))
        self.assertTrue(all(r!="1785" for r in self.roster))

    def test_dirty_ticker_cohort_or_existing_1_rejected(self):
        self.panel.write_text(
            self.panel.read_text(encoding="utf-8-sig").replace("UNKNOWN","1",1),
            encoding="utf-8-sig")
        with self.assertRaisesRegex(ValueError,"existing_training_or_duplicate_annual"):
            x.materialize(self.panel,self.root/"blocked")

    def test_immutability_protects_existing_audits(self):
        out=self.root/"immutable";out.mkdir()
        (out/"critical.csv").write_text("DO NOT CHANGE")
        with self.assertRaisesRegex(FileExistsError,"no_overwrite"):
            x.materialize(self.panel,out)
        self.assertEqual((out/"critical.csv").read_text(),"DO NOT CHANGE")

    def test_2023_quarter_restatement_not_same_as_fraud(self):
        x.materialize(self.panel,self.root/"qout")
        with (self.root/"qout"/"round10_6240_quarter_manual_review.csv").open(
                encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f))
        e=next(r for r in rows if r["ticker"]=="6485" and r["period"]=="2023Q3")
        self.assertEqual(e["event_lead_ids"],"S01")
        self.assertEqual(e["supervised_fraud_label"],"UNKNOWN")

if __name__=="__main__":
    unittest.main()
