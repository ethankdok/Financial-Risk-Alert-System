"""Offline fake-data tests for Y1 reviewed-positive and unlabeled-control selection."""
from __future__ import annotations
import csv
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.round2_official_review_sprint import build

FULL=";".join(f"{i:02d}" for i in range(1,13))


def write(path,headers,rows):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=headers)
        w.writeheader()
        w.writerows(rows)


class ReviewSprintTests(unittest.TestCase):
    def test_positive_and_control_unlabeled_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); c=root/"cases.csv";t=root/"tej.csv";out=root/"out"
            case_columns=["case_id","ticker","fiscal_year","rank",
                "first_notice_date","last_notice_date","tej_notice_year_max_count",
                "holdout","training_y","issuer_name","notice_count","representative_title"]
            write(c,case_columns,[
                dict(case_id="1203-FY2017",ticker="1203",fiscal_year="2017",
                     rank="P0",first_notice_date="2018-05-11",
                     last_notice_date="2018-05-11",tej_notice_year_max_count="1",
                     holdout="false",training_y="",issuer_name="SYNTHETIC",
                     notice_count="1",representative_title="Fictitious restatement"),
                dict(case_id="2201-FY2017",ticker="2201",fiscal_year="2017",
                     rank="P1",first_notice_date="2018-05-11",
                     last_notice_date="2018-05-11",tej_notice_year_max_count="0",
                     holdout="false",training_y="",issuer_name="SYNTHETIC",
                     notice_count="1",representative_title="Fictitious correction"),
            ])
            annual=[]
            for fy in range(2016,2024):
                for ticker,count in [("3210","0"),("1203","1")]:
                    annual.append(dict(ticker=ticker,calendar_year=fy,
                        issuer_name="SYNTHETIC",observed_month_count="12",
                        observed_months=FULL,max_reported_restatement_count=count))
            write(t,["ticker","calendar_year","issuer_name",
                "observed_month_count","observed_months",
                "max_reported_restatement_count"],annual)
            report=build(c,t,out,controls_per_fy=1)
            self.assertEqual(report["positive_notice_candidates"],2)
            self.assertEqual(report["cross_source_positive_cue"],1)
            self.assertEqual(report["control_candidates"],5)
            self.assertEqual(report["official_y_0_assigned"],0)
            self.assertEqual(report["official_y_1_assigned"],0)
            self.assertEqual(report,build(c,t,out,controls_per_fy=1))
            with (out/"official_y1_evidence_review_sprint_private.csv").open(
                    encoding="utf-8-sig") as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),7)
            self.assertTrue(all(r["y_official_annual_24m"]=="" for r in rows))
            self.assertEqual(rows[-1]["review_status"],"PENDING_FULL_24M_MOPS_COVERAGE")
            (out/"official_y1_evidence_review_sprint_private.csv").write_text("corrupt")
            with self.assertRaisesRegex(FileExistsError,"refuse_overwrite"):
                build(c,t,out,controls_per_fy=1)

    def test_unaudited_preapproved_y_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);c=d/"c.csv";t=d/"y.csv"
            write(c,["case_id","ticker","fiscal_year","rank",
                     "first_notice_date","tej_notice_year_max_count",
                     "holdout","training_y"],[{
                "case_id":"1203-FY2017","ticker":"1203","fiscal_year":"2017",
                "rank":"P0","first_notice_date":"2018-05-11",
                "tej_notice_year_max_count":"1","holdout":"false","training_y":"1",
            }])
            write(t,["ticker","calendar_year","observed_month_count",
                     "observed_months","max_reported_restatement_count",
                     "issuer_name"],[
                     dict(ticker="3210",calendar_year="2017",observed_month_count="12",
                          observed_months=FULL,max_reported_restatement_count="0",issuer_name="TEST")])
            with self.assertRaisesRegex(ValueError,"refuse_mixed_training_y"):
                build(c,t,d/"out",controls_per_fy=1)


if __name__=="__main__":
    unittest.main()
