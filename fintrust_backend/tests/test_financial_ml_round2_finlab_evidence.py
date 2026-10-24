"""Synthetic-only tests: no licensed announcement data in GitHub."""
import csv
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.round2_finlab_evidence import analyze_notice, build


class Round2FinLabEvidenceTests(unittest.TestCase):
    def test_annual_consolidated_completed_with_numeric_change_cue(self):
        title = "本公司105年度合併財務報告已完成重編相關事宜"
        info = "1.事實發生日:106/05/242.發生緣由:重編前資產總計1000000，重編後資產總計900000。"
        a = analyze_notice(title, info)
        self.assertEqual(a["candidate_fys"], [2016])
        self.assertEqual(a["restatement_fys_title_explicit"], [2016])
        self.assertEqual(a["status"], "RESTATEMENT_COMPLETED_STATED")
        self.assertTrue(a["core_line_item_cue"])
        self.assertTrue(a["comparison_table_cue"])

    def test_pending_is_not_completed(self):
        a = analyze_notice("本公司擬進行105年度財報重編", "3.發生緣由:擬重編。")
        self.assertEqual(a["status"], "PENDING_OR_SCOPE_UNCLEAR")
        self.assertFalse(a["comparison_table_cue"])

    def test_mixed_years_separate_restatement_fy(self):
        a = analyze_notice(
            "公告本公司董事會通過重編112年第3季合併財務報告及更正110年度合併財務報告",
            "3.發生緣由:更正資料影響資產總計。更正前1000更正後900",
        )
        self.assertEqual(a["candidate_fys"], [2021])
        self.assertEqual(a["restatement_fys_title_explicit"], [])

    def test_completion_and_correction_different_annual_years(self):
        a = analyze_notice("董事會通過重編108年度合併財報，並更補正106年度合併財報", "資訊")
        self.assertEqual(a["candidate_fys"], [2017, 2019])
        self.assertEqual(a["restatement_fys_title_explicit"], [2019])

    def test_only_monthly_and_quarter_do_not_become_annual(self):
        a = analyze_notice("更正109年12月份自結合併財務報表之營業收入", "更正前100更正後101")
        self.assertEqual(a["candidate_fys"], [])
        a = analyze_notice("公告本公司重編110年第2季財務報告", "")
        self.assertEqual(a["candidate_fys"], [])

    def test_no_automatic_label_reserved_holdout_sha_and_immutable_output(self):
        with tempfile.TemporaryDirectory() as t:
            inp = Path(t) / "source.csv"
            out = Path(t) / "out"
            with inp.open("w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=["stock_id", "date", "title", "info", "name"])
                w.writeheader()
                w.writerow(dict(
                    stock_id="1203", date="2018-05-11 17:00:00",
                    title="本公司經董事會通過重編106年度合併財務報告",
                    info="更正前資產總計100，更正後資產總計90", name="SYNTHETIC",
                ))
                w.writerow(dict(
                    stock_id="1203", date="2018-05-18 17:00:00",
                    title="公告106年度重編後合併財報已重新上傳",
                    info="資產總計100，重編前100重編後90", name="SYNTHETIC",
                ))
                w.writerow(dict(
                    stock_id="1785", date="2016-11-11 10:00:00",
                    title="本公司103年度合併財務報告已完成重編",
                    info="重編前資產總計100重編後90", name="SYNTHETIC",
                ))
                w.writerow(dict(
                    stock_id="2317", date="2026-10-26 10:00:00",
                    title="董事會通過重編112年度合併財報",
                    info="重編前資產總計100重編後90", name="SYNTHETIC",
                ))
            report = build(inp, out)
            self.assertEqual(report["input_notice_count"], 3)
            self.assertEqual(report["source_skips"]["future_notice_skipped"], 1)
            self.assertEqual(report["fy2013_2023_case_count"], 2)
            self.assertEqual(report["case_holdout_1785_count"], 1)
            self.assertEqual(report["reserved_holdout_notices"], 1)
            self.assertEqual(report["confirmed_24m_supervised_positive_count"], 0)
            self.assertEqual(report["confirmed_24m_supervised_negative_count"], 0)
            self.assertEqual(report, build(inp, out))
            with (out / "finlab_issuer_fy_review_private.csv").open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(
                r["training_y"] == "" and
                r["adjudication"] == "PENDING_OFFICIAL_AND_FILING_CHECK"
                for r in rows
            ))
            self.assertEqual({r["ticker"] for r in rows}, {"1203", "1785"})
            (out / "finlab_notice_evidence_private.csv").write_text("modified", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "immutable_output_collision"):
                build(inp, out)

    def test_missing_columns_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            inp = Path(t) / "bad.csv"
            inp.write_text("title,info\na,b", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing_required_finlab_columns"):
                build(inp, Path(t) / "out")


if __name__ == "__main__":
    unittest.main()
