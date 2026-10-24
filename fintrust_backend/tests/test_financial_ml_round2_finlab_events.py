"""FinLab Round2 hermetic research tests. Fixtures are not real announcements."""
from __future__ import annotations
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.round2_finlab_events import (
    classify, annual_years, fiscal_year, build,
)

class FinLabTriageTests(unittest.TestCase):
    def test_roc_years_and_quarter_scope(self):
        self.assertEqual(fiscal_year("112"), 2023)
        self.assertEqual(fiscal_year("一○九"), 2020)
        self.assertEqual(fiscal_year("九十五"), 2006)
        self.assertEqual(annual_years("公告重編112年度合併財報"), [2023])
        self.assertEqual(annual_years("重編112年第2季財務報告"), [])
        self.assertEqual(annual_years("重編110年第四季財報"), [2021])
        self.assertEqual(annual_years("重編一○九年度財報"), [2020])

    def test_safe_grouping_not_automatic_y(self):
        self.assertEqual(classify("公告本公司112年度合併財務報告重編完成")[0],
                         "A_RESTATEMENT_ANNUAL_REVIEW")
        self.assertEqual(classify("公告本公司重編112年第2季合併財務報告")[0],
                         "B_RESTATEMENT_CONTEXT_REVIEW")
        self.assertEqual(classify("公告展延重編111年度財報申報期限")[0],
                         "B_RESTATEMENT_CONTEXT_REVIEW")
        self.assertEqual(classify("更正110年度合併財務報告附註")[0],
                         "C_ANNUAL_CORRECTION_REVIEW")
        self.assertEqual(classify("更正111年度合併財務報告董事會召開日期")[0],
                         "D_QUARTER_OR_YEAR_UNCLEAR")
        self.assertEqual(classify("更正本公司財務主管變動公告")[0],
                         "E_ADMIN_OR_NONFINANCIAL_REVIEW")
        self.assertEqual(classify("更正本公司103年度重編後合併財報第83頁")[0],
                         "B_RESTATEMENT_CONTEXT_REVIEW")
        self.assertEqual(classify("公告重編108Q4~111Q4合併財報")[3],
                         "YEAR_RANGE_REVIEW")

    def test_real_column_contract_hash_idempotence_and_holdout(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            inp=base/"finlab.csv";out=base/"output"
            with inp.open("w",encoding="utf-8-sig",newline="") as f:
                w=csv.DictWriter(f,fieldnames=["stock_id","date","title","info","name","key_date"])
                w.writeheader()
                w.writerow({"stock_id":"2330","date":"2023-08-01 09:00:00",
                            "title":"公告本公司重編111年度合併財報",
                            "info":"example ONLY", "name":"測試","key_date":"2026-10-20"})
                w.writerow({"stock_id":"2330","date":"2023-09-01 09:00:00",
                            "title":"更正公告董事會議案","info":"sample 2","name":"測試"})
                w.writerow({"stock_id":"1785","date":"2016-11-13 12:00:00",
                            "title":"本公司重編104年度合併財務報告",
                            "info":"heldout synthetic","name":"測試"})
                w.writerow({"stock_id":"2317","date":"2026-10-25 12:00:00",
                            "title":"更正115年度合併財務報告",
                            "info":"future synthetic","name":"測試"})
            result=build(inp,out)
            self.assertEqual(result["source_total_candidate_rows"],3)
            self.assertEqual(result["future_rows_excluded"],1)
            self.assertEqual(result["y_positive_assigned"],0)
            self.assertEqual(result["y_negative_assigned"],0)
            self.assertEqual(result["fy2013_2023_review_event_links"],2)
            self.assertEqual(build(inp,out),result)
            with (out/"round2_finlab_annual_year_review_links.csv").open(encoding="utf-8") as f:
                records=list(csv.DictReader(f))
            self.assertEqual({r["ticker"] for r in records},{"2330","1785"})
            self.assertTrue(all(r["training_y"]=="" for r in records))
            (out/"round2_finlab_review_notices.csv").write_text("tamper",encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError,"refuse_overwrite"):
                build(inp,out)

    def test_missing_columns_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp=Path(tmp)/"bad.csv";inp.write_text("title\nfoo\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"required_columns_missing"):
                build(inp,Path(tmp)/"out")

if __name__=="__main__":
    unittest.main()
