"""Hermetic Phase4 controls: disjoint issuer/time, source tier, no false labels."""
from __future__ import annotations
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import phase4_taiwan_dataset_gate as m
from research.financial_ml.literature_dataset import FEATURES
from research.financial_ml.finmind_cross_industry_pilot import FIELDS


class Phase4TaiwanDatasetGateTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.stage=self.root/"phase3_literature_integrated"
        self.stage.mkdir()
        (self.stage/"phase3_integrated_report.json").write_text(json.dumps({
            "cohort_company_count":120,"finmind_training_15_feature_rows_admitted":0
        }),encoding="utf-8")
        cohort=self.root/"finmind_scaled_120"
        cohort.mkdir()
        self.cohort=cohort/"finmind_scaled_cohort.csv"
        with self.cohort.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS)
            w.writeheader()
            for num in range(2000,2120):
                w.writerow({
                    "ticker":str(num),"company_name":"Synthetic test issuer",
                    "industry_category":"半導體業" if num%2 else "塑膠工業",
                    "market":"twse" if num%2 else "tpex",
                    "source_snapshot_date":"2026-10-18",
                    "historical_eligibility":"UNVERIFIED",
                    "normal_label_status":"UNREVIEWED"
                })
        self.provider=self.stage/"finmind_provisional_paper_component_values.csv"
        self.official=self.stage/"mops_official_15_features"/"literature_15_features.csv"
        self.official.parent.mkdir()
        self.pentries=[]
        self.oentries=[]
        for ticker in ("2000","2001","2002"):
            for year in (2019,2021,2023):
                self.pentries.append({
                    "ticker":ticker,"fiscal_year":year,
                    "component_source":"FINMIND_UNAPPROVED_CANDIDATE_ONLY",
                    "complete_15_paper_features_training_approved":"false",
                    "label_status":"UNKNOWN","candidate_components_with_values":14,
                    **{name:"" if name=="d_issue" else "1.2" for name in FEATURES}
                })
        self.oentries.append({
            "ticker":"2000","fiscal_year":2019,"raw_sha256":"a"*64,
            "filing_version_type":"unknown_revision","analysis_mode":"retrospective",
            "training_label":"UNREVIEWED","accounting_framework":"TIFRS",
            "statement_scope":"consolidated","components_computed":15,
            **{name:"1.1" for name in FEATURES}
        })
        self.save()

    def save(self):
        with self.provider.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(self.pentries[0]))
            w.writeheader()
            w.writerows(self.pentries)
        with self.official.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(self.oentries[0]))
            w.writeheader()
            w.writerows(self.oentries)

    def test_all_real_taiwan_evidence_split_without_label_promotion(self):
        r=m.build(self.root,self.root/"phase4")
        self.assertEqual(r["cohort_issuer_count"],120)
        self.assertEqual(r["evidence_rows"],10)
        self.assertEqual(r["official_retrospective_rows"],1)
        self.assertEqual(r["finmind_candidate_rows"],9)
        self.assertEqual(r["labels_approved_positive"],0)
        self.assertEqual(r["train_val_test_supervised_admitted_rows"],0)
        self.assertFalse(r["eligible_for_supervised_financial_fraud_training"])
        self.assertEqual(r["cross_source_overlap_company_years"],1)
        self.assertEqual(r["cross_source_comparable_feature_cells"],15)
        with (self.root/"phase4"/"taiwan_research_split_register.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual({r["outcome_label"] for r in rows},{"UNKNOWN"})
        self.assertEqual({r["approved_supervised_training"] for r in rows},{"false"})
        for ticker in {x["ticker"] for x in rows}:
            self.assertEqual(len({x["issuer_split"] for x in rows if x["ticker"]==ticker}),1)

    def test_temporal_partitions_use_target_fiscal_year_only(self):
        self.assertEqual(m.temporal_partition(2013),"fit")
        self.assertEqual(m.temporal_partition(2020),"fit")
        self.assertEqual(m.temporal_partition(2021),"validation")
        self.assertEqual(m.temporal_partition(2023),"test")
        self.assertEqual(m.temporal_partition(2025),"test")
        with self.assertRaisesRegex(ValueError,"unsupported"):
            m.temporal_partition(2012)

    def test_company_partition_deterministic_disjoint_and_reserved(self):
        self.assertEqual(m.issuer_partition("2330"),m.issuer_partition("2330"))
        self.assertGreaterEqual(len({m.issuer_partition(str(x)) for x in range(2000,2200)}),3)
        with self.assertRaisesRegex(ValueError,"heldout"):
            m.issuer_partition("1785")

    def test_forged_provider_or_official_supervised_label_rejected(self):
        self.pentries[0]["label_status"]="normal"
        self.save()
        with self.assertRaisesRegex(ValueError,"unapproved_provider"):
            m.build(self.root,self.root/"out")
        self.pentries[0]["label_status"]="UNKNOWN"
        self.oentries[0]["training_label"]="1"
        self.save()
        with self.assertRaisesRegex(ValueError,"unapproved_official"):
            m.build(self.root,self.root/"out")

    def test_finmind_provisional_d_issue_must_not_be_fabricated(self):
        self.pentries[0]["d_issue"]="0"
        self.pentries[0]["candidate_components_with_values"]=15
        self.save()
        with self.assertRaisesRegex(ValueError,"dechow_issue"):
            m.build(self.root,self.root/"out")

    def test_unsafe_provider_full_paper_approval_rejected(self):
        self.pentries[0]["complete_15_paper_features_training_approved"]="true"
        self.save()
        with self.assertRaisesRegex(ValueError,"unapproved_provider"):
            m.build(self.root,self.root/"out")

    def test_duplicate_financial_issuer_year_and_nonfinite_values_rejected(self):
        self.pentries.append(dict(self.pentries[0]))
        self.save()
        with self.assertRaisesRegex(ValueError,"duplicate_issuer"):
            m.build(self.root,self.root/"out")
        self.pentries.pop()
        self.pentries[0][FEATURES[0]]="NaN"
        self.save()
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            m.build(self.root,self.root/"out")

    def test_1785_rejected_in_source_even_when_not_in_cohort(self):
        self.oentries[0]["ticker"]="1785"
        self.save()
        with self.assertRaisesRegex(ValueError,"reserved"):
            m.build(self.root,self.root/"out")

    def test_mops_two_real_disagreements_are_not_approved(self):
        p=self.root/"crosscheck.csv"
        fields=("ticker","year","statement","finmind_type","mops_metric",
                "finmind_q4_value","finmind_four_quarter_sum","mops_annual_value",
                "candidate_preference","provider_archive_sha256","mops_raw_sha256",
                "q4_relative_difference","sum_relative_difference",
                "sum_within_tolerance")
        with p.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields)
            w.writeheader()
            w.writerow(dict(ticker="2330",year=2014,statement="balance",
                finmind_type="Liabilities",mops_metric="total_liabilities",
                finmind_q4_value="448720754000",finmind_four_quarter_sum="",
                mops_annual_value="449458098000",candidate_preference="NO_MATCH",
                provider_archive_sha256="a"*64,mops_raw_sha256="b"*64,
                q4_relative_difference="0.001640517777",sum_relative_difference="",
                sum_within_tolerance="False"))
            w.writerow(dict(ticker="2458",year=2013,statement="cashflow",
                finmind_type="CashFlowsFromOperatingActivities",
                mops_metric="operating_cash_flow",
                finmind_q4_value="1661734000",finmind_four_quarter_sum="4040000000",
                mops_annual_value="1670146000",candidate_preference="NO_MATCH",
                provider_archive_sha256="c"*64,mops_raw_sha256="d"*64,
                q4_relative_difference="0.0050366854",sum_relative_difference="1.42259",
                sum_within_tolerance="False"))
        r,lines=m.disputes(p,self.root)
        self.assertEqual(r["disputes"],2)
        self.assertEqual(lines[0]["signed_q4_minus_official"],"-737344000")
        self.assertEqual(lines[0]["resolution_status"],"UNRESOLVED_DO_NOT_AUTO_APPROVE")
        self.assertEqual(lines[1]["absolute_q4_discrepancy"],"8412000")
        self.assertFalse(r["threshold_changed"])

    def test_temporal_sequence_windows_do_not_impute_or_look_ahead(self):
        report=m.build(self.root,self.root/"phase4")
        self.assertEqual(report["sequence_window_training_admitted"],0)
        p=self.root/"phase4"/"taiwan_sequence_window_admission.csv"
        with p.open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertTrue(rows)
        for row in rows:
            self.assertLessEqual(int(row["start_year"]),int(row["target_year"]))
            self.assertEqual(row["approved_for_training"],"false")
            self.assertEqual(row["asof_publication_verified"],"false")
            self.assertEqual(row["complete_15_window"],"false")
        self.assertTrue(any(row["missing_years"] for row in rows))

    def test_provider_and_official_same_issuer_year_not_coalesced(self):
        r=m.build(self.root,self.root/"phase4")
        self.assertTrue(r["source_tiers_not_fused"])
        with (self.root/"phase4"/"taiwan_research_split_register.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        keys=[(x["evidence_tier"],x["ticker"],x["fiscal_year"]) for x in rows]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertEqual(sum(x[1:] == ("2000","2019") for x in keys),2)


if __name__=="__main__":
    unittest.main()
