"""Round9 exact 120 issuer source-universe review packet contracts (synthetic only)."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml import round9_every_company_official_review as study
from research.financial_ml.round3_research_models import ANNUAL_COLUMNS


class Round9Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.index=self.root/"cohort.csv"
        self.leads=Path(study.__file__).with_name("round9_official_case_source_leads.json")

    def index_data(self,n=120,include1785=False):
        rows=[]
        tickers=[str(i) for i in range(3000,3000+n)]
        if include1785:tickers[-1]="1785"
        for ticker in tickers:
            for y in range(2013,2026):
                row={col:"" for col in ANNUAL_COLUMNS}
                row.update(ticker=ticker,fiscal_year=str(y),
                           complete_candidate_vector="true" if y%2 else "false",
                           original_publication_verified="false",
                           original_filing_vintage_verified="false",
                           label_status="UNKNOWN",training_admitted="false")
                rows.append(row)
        with self.index.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=ANNUAL_COLUMNS)
            w.writeheader();w.writerows(rows)
        return rows

    def test_all_120_company_rows_and_1560_company_years_prepared(self):
        self.index_data()
        out=study.make_audit(self.index,self.leads,self.root/"output")
        self.assertEqual(out["full_company_count"],120)
        self.assertEqual(out["full_company_year_count"],1560)
        self.assertEqual(out["approved_positive_years"],0)
        self.assertEqual(out["approved_negative_years"],0)
        self.assertEqual(out["UNKNOWN_training_labels"],1560)
        with (self.root/"output"/"round9_each_company_research_queue.csv").open(
                encoding="utf-8-sig") as f:
            firm=list(csv.DictReader(f))
        self.assertEqual(len(firm),120)
        self.assertTrue(all(x["all_years_label_state"]=="UNKNOWN" for x in firm))
        with (self.root/"output"/"round9_each_issuer_year_research_queue.csv").open(
                encoding="utf-8-sig") as f:
            years=list(csv.DictReader(f))
        self.assertTrue(all(y["approved_training_label"]=="UNKNOWN" for y in years))

    def test_wrong_cohort_size_never_silently_substituted(self):
        self.index_data(119)
        with self.assertRaisesRegex(ValueError,"expected_exact_120"):
            study.make_audit(self.index,self.leads,self.root/"out")

    def test_reserved_1785_never_enters_supervision(self):
        self.index_data(include1785=True)
        with self.assertRaisesRegex(ValueError,"bad_cohort_or_reserved_1785"):
            study.make_audit(self.index,self.leads,self.root/"out")

    def test_repeat_issuer_year_blocked(self):
        rows=self.index_data()
        rows.append(dict(rows[0]))
        with self.index.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=ANNUAL_COLUMNS)
            w.writeheader();w.writerows(rows)
        with self.assertRaisesRegex(ValueError,"duplicate_issuer_year"):
            study.make_audit(self.index,self.leads,self.root/"out")

    def test_unverified_positive_labels_not_forged(self):
        rows=self.index_data()
        rows[0]["label_status"]="1"
        with self.index.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=ANNUAL_COLUMNS)
            w.writeheader();w.writerows(rows)
        with self.assertRaisesRegex(ValueError,"already_claims_approved_label"):
            study.make_audit(self.index,self.leads,self.root/"out")

    def test_cases_have_real_sources_and_no_approval(self):
        sources=study.official_case_leads(self.leads)
        self.assertEqual(set(sources),{"3027","8299","6452","1785"})
        self.assertFalse(any(v["approved_supervised_training"] for v in sources.values()))

    def test_known_company_3027_2015_candidate_only_not_training(self):
        self.index_data()
        m=study.make_audit(self.index,self.leads,self.root/"out")
        with (self.root/"out"/"round9_each_issuer_year_research_queue.csv").open(
                encoding="utf-8-sig") as f:
            r=list(csv.DictReader(f))
        item=next(x for x in r if x["ticker"]=="3027" and x["fiscal_year"]=="2015")
        self.assertEqual(item["proposed_label"],"CANDIDATE_1")
        self.assertEqual(item["approved_training_label"],"UNKNOWN")
        self.assertTrue(item["source_evidence_url"].startswith("https://judgment.judicial.gov.tw"))
        other=next(x for x in r if x["ticker"]=="3027" and x["fiscal_year"]=="2024")
        self.assertEqual(other["proposed_label"],"UNKNOWN")
        self.assertEqual(other["approved_training_label"],"UNKNOWN")


if __name__=="__main__":
    unittest.main()
