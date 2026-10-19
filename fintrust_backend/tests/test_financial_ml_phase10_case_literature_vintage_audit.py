"""Phase10 hermetic tests: actual paper-engine adapter, 3-yr case PIT embargo."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.financial_ml import phase10_case_literature_vintage_audit as m
from research.financial_ml.literature_dataset import FEATURES
from research.financial_ml.phase1_case_registry import validate
from research.financial_ml.phase6_official_evidence_recovery import ROOT_SEED
from research.financial_ml.phase8_original_filing_intake import QUEUE_COLUMNS


class Phase10PaperResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.phase9=self.root/"phase9_case_mops_xbrl_candidates"
        self.phase7=self.root/"phase7_official_case_asof_recovery"
        self.phase9.mkdir();self.phase7.mkdir()
        seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
        self.cases=validate(seed)
        needs=set()
        demands=[]
        for c in self.cases:
            for target in c["affected_fiscal_years"]:
                for year in range(target-2,target+1):
                    needs.add((c["ticker"],year))
                    demands.append({
                        "ticker":c["ticker"],"case_id":c["case_id"],
                        "affected_fiscal_year":target,"historical_input_year":year,
                        "historical_role":"TARGET" if year==target else "PRIOR_YEAR",
                        "required_source":"ORIGINAL_MOPS_FILING_AS_FIRST_PUBLISHED",
                        "original_publication_time":"","original_filing_version_sha256":"",
                        "filing_status":"UNKNOWN_ORIGINAL_VERSION_NEEDS_RECOVERY",
                        "case_outcome_status":"POTENTIAL_CASE_PERIOD_REVIEW_PENDING",
                        "label_approved":"false","heldout_1785_excluded":"true",
                        "review_note":""
                    })
        self.save_csv(self.phase7/"phase7_original_filing_asof_gap_queue.csv",
                      QUEUE_COLUMNS,demands)
        self.source=[]
        self.manifest={}
        for ticker,year in sorted(needs):
            stage=("LEGACY_ORIGINAL_PDF_REQUIRES_SEPARATE_SOURCE" if year<=2012
                   else "filing_not_found" if (ticker,year)==("3027",2013)
                   else "validated")
            sha=(ticker+"0"*(4-len(ticker))+"ab"*(30))[:64]
            sha=f"{year:04x}"+sha[:60]
            self.source.append({
                "ticker":ticker,"fiscal_year":year,
                "official_xbrl_status":stage,
                "source_sha256":sha if stage=="validated" else "",
                "official_statement_scope":"consolidated" if stage=="validated" else "",
                "official_filing_version_type":"unknown_revision",
                "historical_original_filing_version_verified":"false",
                "source_publication_timestamp_verified":"false",
                "first_misstatement_disclosure_time_verified":"false",
                "financial_statement_misstatement_label":"UNKNOWN",
                "approved_for_historical_model_training":"false",
                **{f:"" for f in m.ARCHIVE_TABLE
                   if f not in ("ticker","fiscal_year","official_xbrl_status",
                                "source_sha256","official_statement_scope",
                                "official_filing_version_type",
                                "historical_original_filing_version_verified",
                                "source_publication_timestamp_verified",
                                "first_misstatement_disclosure_time_verified",
                                "financial_statement_misstatement_label",
                                "approved_for_historical_model_training")}
            })
            # Correct actual original Phase9 schema names, not research aliases
            row=self.source[-1]
            row["acquisition_status"]=row.pop("official_xbrl_status")
            row["source_raw_sha256"]=row.pop("source_sha256")
            row["xbrl_statement_scope"]=row.pop("official_statement_scope")
            row["xbrl_filing_version_type"]=row.pop("official_filing_version_type")
            if year>=2013:
                self.manifest[f"{ticker}:{year}"]={
                    "ticker":ticker,"fiscal_year":year,"status":stage,
                    "content_hash":row["source_raw_sha256"],
                    "source_url":"https://mopsov.twse.com.tw",
                    "statement_scope":"consolidated"
                }
        self.save_csv(self.phase9/"phase9_case_mops_version_review.csv",
                      m.ARCHIVE_TABLE,self.source)
        (self.phase9/"acquisition_results.json").write_text(
            json.dumps({"outcomes":self.manifest}),encoding="utf-8")
        self.faked=set()

    def save_csv(self,p,fields,rows):
        with p.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields)
            w.writeheader();w.writerows(rows)

    def fake_produce(self,manifest,out,**kwargs):
        self.faked.add("original_formula_engine_invoked")
        out=Path(out);out.mkdir(parents=True)
        rows=[]
        for r in self.source:
            if r["acquisition_status"]!="validated":
                continue
            values={k:("1.1" if k!="d_issue" else "") for k in FEATURES}
            rows.append({
                "ticker":r["ticker"],"fiscal_year":r["fiscal_year"],
                "raw_sha256":r["source_raw_sha256"],"analysis_mode":"retrospective",
                "training_label":"UNREVIEWED","accounting_framework":"TIFRS",
                "statement_scope":"consolidated",
                "filing_version_type":"unknown_revision",
                "beneish_m_score":"", "dechow_f_score":"",
                "components_computed":14,**values
            })
        self.save_csv(out/"literature_15_features.csv",
                      ("ticker","fiscal_year","raw_sha256","analysis_mode",
                       "training_label","accounting_framework","statement_scope",
                       "filing_version_type","beneish_m_score","dechow_f_score",
                       "components_computed",*FEATURES),rows)
        return {"status":"TEST_MOCK_ORIGINAL_PAPER_ENGINE","company_year_rows":len(rows)}

    def execute(self):
        with patch.object(m,"validate_manifest",return_value=self.manifest):
            with patch.object(m,"produce",side_effect=self.fake_produce):
                return m.run(self.root,self.root/"phase10")

    def test_runs_original_paper_engine_and_11_case_years(self):
        r=self.execute()
        self.assertIn("original_formula_engine_invoked",self.faked)
        self.assertEqual(r["source_issuer_year_rows"],13)
        self.assertEqual(r["official_archived_xbrl_years"],11)
        self.assertEqual(r["actual_paper_feature_years"],11)
        self.assertEqual(r["fully_computed_15_feature_years"],0)
        self.assertEqual(r["beneish8_complete_years"],11)
        self.assertEqual(r["dechow7_complete_years"],0)
        self.assertEqual(r["missing_literature_feature_cells"],13*15-11*14)
        self.assertEqual(r["candidate_event_three_year_windows"],7)
        self.assertEqual(r["historical_asof_training_rows_admitted"],0)
        self.assertEqual(len(r["missing_official_years"]),2)

    def test_missing_source_year_and_2012_old_gaap_report_explicit(self):
        r=self.execute()
        names={(x["ticker"],int(x["fiscal_year"]),x["status"])
               for x in r["missing_official_years"]}
        self.assertEqual(names,{("8299",2012,"LEGACY_ORIGINAL_PDF_REQUIRES_SEPARATE_SOURCE"),
                                ("3027",2013,"filing_not_found")})
        with (self.root/"phase10"/"phase10_case_missing_features.csv").open(
                encoding="utf-8",newline="") as f:
            errors=list(csv.DictReader(f))
        self.assertTrue(any(x["missing_reason"]=="PRE_TIFRS_REPORT_SEPARATE_GAAP_METHOD_NEEDED"
                            for x in errors))
        self.assertTrue(all(x["missing_not_financial_zero"]=="true" for x in errors))

    def test_case_three_year_lookbacks_do_not_fabricate_missing_2012(self):
        self.execute()
        with (self.root/"phase10"/"phase10_case_three_year_windows.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),7)
        ref=next(x for x in rows if x["ticker"]=="8299")
        self.assertEqual(ref["source_years"],"2012|2013|2014")
        self.assertIn("2012",ref["missing_source_years"])
        self.assertEqual(ref["full_3yr_literature_sequence"],"false")
        self.assertTrue(all(x["asof_model_training_approved"]=="false" for x in rows))

    def test_no_supervised_labels_and_final_holdout_in_features(self):
        r=self.execute()
        self.assertEqual(r["verified_positive_labels"],0)
        self.assertEqual(r["verified_negative_labels"],0)
        self.assertTrue(r["final_holdout_1785_excluded"])
        with (self.root/"phase10"/"phase10_case_official_paper_features.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual({x["outcome_label"] for x in rows},{"UNKNOWN"})
        self.assertNotIn("1785",{x["ticker"] for x in rows})
        self.assertTrue(all(x["admitted_for_supervised_learning"]=="false" for x in rows))

    def test_fake_approved_case_label_rejected_before_formula_produce(self):
        self.source[0]["financial_statement_misstatement_label"]="1"
        self.save_csv(self.phase9/"phase9_case_mops_version_review.csv",
                      m.ARCHIVE_TABLE,self.source)
        with self.assertRaisesRegex(ValueError,"unapproved_historical"):
            self.execute()

    def test_fake_historical_publication_promotion_rejected(self):
        self.source[1]["historical_original_filing_version_verified"]="true"
        self.save_csv(self.phase9/"phase9_case_mops_version_review.csv",
                      m.ARCHIVE_TABLE,self.source)
        with self.assertRaisesRegex(ValueError,"unapproved_historical"):
            self.execute()

    def test_source_sha_conflict_blocks_retro_feature(self):
        def corrupted(*args,**kwargs):
            self.fake_produce(*args,**kwargs)
            p=self.root/"phase10"/"official_case_literature"/"literature_15_features.csv"
            with p.open(encoding="utf-8",newline="") as f:
                rows=list(csv.DictReader(f));headers=f""
            rows[0]["raw_sha256"]="0"*64
            self.save_csv(p,rows[0].keys(),rows)
            return {"status":"TEST"}
        with patch.object(m,"validate_manifest",return_value=self.manifest):
            with patch.object(m,"produce",side_effect=corrupted):
                with self.assertRaisesRegex(ValueError,"source_sha_conflict"):
                    m.run(self.root,self.root/"phase10")

    def test_no_hidden_training_on_unknown_control(self):
        r=self.execute()
        self.assertEqual(r["network_requests"],0)
        self.assertEqual(r["production_db_writes"],0)
        self.assertEqual(r["original_pre_correction_versions_verified"],0)


if __name__=="__main__":
    unittest.main()
