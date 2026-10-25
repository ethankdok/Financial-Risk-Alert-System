"""Synthetic-only anomaly, PIT, missingness, and split safety tests."""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.phase2_pit_x_y_bridge import OUT_COLS, FEATURES
from research.financial_ml.phase2_anomaly_readiness import build, SAFE_FEATURES

URL = "https://mops.twse.com.tw/mops/web/index"

def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

class XAnomalySafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.join = self.root / "join.csv"
        self.manifest = self.root / "manifest.json"
        self.ind = self.root / "industry.csv"
        self.out = self.root / "out"
        self.entries = {}
        self.rows = []
        for ticker in range(1201, 1226):
            t = str(ticker)
            for cy in (2016, 2017, 2018, 2019):
                fy = cy - 2
                for year in (fy, fy - 1):
                    if f"{t}:{year}" not in self.entries:
                        self.entries[f"{t}:{year}"] = {
                            "ticker":t,"fiscal_year":year,"status":"validated",
                            "statement_scope":"consolidated","accounting_framework":"TIFRS",
                            "filing_version_type":"original","source_kind":"mops_xbrl_zip",
                            "filing_version_id":f"{t}-FY{year}-original",
                            "content_hash":sha(f"{t}-{year}"),"point_in_time_eligible":True,
                            "original_version_verified":True,"first_publication_verified":True,
                            "original_first_public_at":f"{year+1}-03-30",
                            "original_publication_evidence_url":URL}
                x = {f: str(1 + (ticker-1201)*.1 + (cy-2016)*.05 + i*.01)
                     for i,f in enumerate(FEATURES)}
                self.rows.append({
                    "ticker":t,"target_calendar_year":cy,"case_key":f"{t}-CY{cy}",
                    "split":"train","y_tej_calendar_proxy":str(int(ticker % 5 == 0)),
                    "y_official_annual_24m":"","asof_date":f"{cy-1}-12-31",
                    "feature_fy":fy,"prior_feature_fy":fy-1,
                    "x_gate":"MATCHED_PIT_ORIGINAL_FEATURES","feature_count":15,
                    "missing_feature_names":"","source_current_sha256":sha(f"{t}-{fy}"),
                    "source_prior_sha256":sha(f"{t}-{fy-1}"),
                    "x_original_version_and_asof_verified":"true",
                    "training_ready":"true", **x})
        write_csv(self.join, OUT_COLS, self.rows)
        self.manifest.write_text(json.dumps({"outcomes":self.entries}),encoding="utf-8")
        write_csv(self.ind, ["ticker","industry_code","valid_from","valid_to","known_at"],
             [{"ticker":str(i),"industry_code":"SEMICONDUCTOR",
               "valid_from":"2010-01-01","valid_to":"","known_at":"2010-01-01"}
              for i in range(1201,1226)])

    def read_rows(self):
        with (self.out/"phase2_x_y_anomaly_private.csv").open(encoding="utf-8-sig",newline="") as f:
            return list(csv.DictReader(f))

    def test_year_matched_peer_and_yoy_without_fit(self):
        r = build(self.join,self.manifest,self.out,self.ind)
        self.assertEqual(r["raw_join_rows"],100)
        self.assertEqual(r["candidate_rows"],100)
        self.assertEqual(r["full_15_feature_rows"],100)
        self.assertFalse(r["baseline_training_preflight_pass"])
        self.assertIn("UPSTREAM_ARCHIVE_AND_PUBLICATION_AUDIT_NOT_ATTESTED",
                      r["baseline_blockers"])
        self.assertNotIn("y_tej_calendar_proxy", SAFE_FEATURES)
        rows=self.read_rows()
        r16=next(x for x in rows if x["ticker"]=="1201" and x["target_calendar_year"]=="2016")
        r17=next(x for x in rows if x["ticker"]=="1201" and x["target_calendar_year"]=="2017")
        r18=next(x for x in rows if x["ticker"]=="1201" and x["target_calendar_year"]=="2018")
        self.assertEqual(r16["delta_roa"],"")
        self.assertEqual(r16["streak_roa_down_2y"],"")
        self.assertEqual(float(r17["delta_roa"]),.05)
        self.assertEqual(r18["streak_roa_down_2y"],"0")
        self.assertTrue(r16["roa_industry_year_percentile"])
        self.assertTrue(r16["roa_industry_year_robust_z"])
        self.assertTrue(r17["cfo_profit_divergence"])

    def test_partial_features_are_kept_separate_from_full_15(self):
        self.rows[0]["b_GMI"]=""
        self.rows[0]["feature_count"]=14
        self.rows[0]["missing_feature_names"]="b_GMI"
        self.rows[0]["x_gate"]="PIT_SOURCE_PARTIAL_FEATURES"
        self.rows[0]["training_ready"]="false"
        write_csv(self.join,OUT_COLS,self.rows)
        report=build(self.join,self.manifest,self.out,self.ind)
        self.assertEqual(report["candidate_rows"],100)
        self.assertEqual(report["full_15_feature_rows"],99)
        self.assertEqual(report["partial_8_to_14_feature_rows"],1)

    def test_source_date_or_version_mismatch_fails_closed(self):
        self.entries["1201:2014"]["original_first_public_at"]="2016-03-31"
        self.manifest.write_text(json.dumps({"outcomes":self.entries}),encoding="utf-8")
        report=build(self.join,self.manifest,self.out,self.ind)
        self.assertEqual(report["candidate_rows"],99)
        self.assertIn("CURRENT_PUBLICATION_AFTER_PREDICTION_CUTOFF",
                      report["exclusion_reasons"])

    def test_wrong_year_or_split_or_double_key_rejected(self):
        self.rows[0]["feature_fy"]=2015
        write_csv(self.join,OUT_COLS,self.rows)
        with self.assertRaisesRegex(ValueError,"x_y_fiscal_cutoff_mismatch"):
            build(self.join,self.manifest,self.out,self.ind)
        self.rows[0]["feature_fy"]=2014
        self.rows[0]["split"]="test"
        write_csv(self.join,OUT_COLS,self.rows)
        with self.assertRaisesRegex(ValueError,"incorrect_temporal_split"):
            build(self.join,self.manifest,self.out,self.ind)
        self.rows[0]["split"]="train"
        write_csv(self.join,OUT_COLS,self.rows+[self.rows[0]])
        with self.assertRaisesRegex(ValueError,"duplicate_company_target_year"):
            build(self.join,self.manifest,self.out,self.ind)

    def test_unknown_or_future_industry_remains_missing(self):
        industries=list(csv.DictReader(self.ind.open(encoding="utf-8-sig")))
        industries[0]["known_at"]="2026-01-01"
        write_csv(self.ind,list(industries[0]),industries)
        build(self.join,self.manifest,self.out,self.ind)
        first=next(x for x in self.read_rows() if x["ticker"]=="1201" and x["target_calendar_year"]=="2016")
        self.assertEqual(first["industry_code"],"")
        self.assertEqual(first["roa_industry_year_percentile"],"")

    def test_industry_can_be_omitted_with_explicit_no_peer_signal(self):
        report=build(self.join,self.manifest,self.out)
        self.assertEqual(report["candidate_rows"],100)
        self.assertIn("INDUSTRY_PEER_COVERAGE_LOW",report["enhanced_blockers"])
        self.assertEqual(report["enhanced_feature_nonmissing"]["roa_industry_year_percentile"],0)

if __name__ == "__main__":
    unittest.main()
