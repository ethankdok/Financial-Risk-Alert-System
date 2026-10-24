"""Synthetic-only tests: TEJ private licensed source must never enter GitHub."""
from __future__ import annotations
import csv
import tempfile
import unittest
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from research.financial_ml.round2_tej_transparency import build

HEADERS = ["代號", "名稱", "年月", "轉投資佔淨值%",
           "轉投資佔資產%", "財測次數", "資訊評鑑等級", "資訊評鑑說明",
           "當年度財報重編次數", "3年內CPA異動次數"]


def synthetic_tej(path, data_rows, headers=None):
    """Tiny legitimate OOXML file containing only made-up data."""
    rows = [headers or HEADERS] + data_rows
    content = []
    for i, row in enumerate(rows, 1):
        cells = []
        for j, value in enumerate(row):
            col = chr(ord("A") + j)
            t = escape(str(value))
            cells.append(
                f'<c r="{col}{i}" t="inlineStr"><is><t>{t}</t></is></c>'
            )
        content.append(
            f'<row r="{i}">' + "".join(cells) + "</row>"
        )
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<worksheet xmlns="{ns}"><sheetData>' +
           "".join(content) + '</sheetData></worksheet>')
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", xml)


def data(ticker, month, count, cpa=0):
    return [ticker, "SYNTHETIC", month, "-", "-", "0", "", "",
            str(count), str(cpa)]


class TEJTransparencyTests(unittest.TestCase):
    def test_yearly_snapshots_preserve_zeros_as_observations_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            x = Path(tmp) / "test.xlsx"
            synthetic_tej(x, [
                data("1203", "2018/01", 0),
                data("1203", "2018/05", 1, 2),
                data("1203", "2018/11", 1, 3),
                data("000960", "2018/12", 2),
                data("A00012", "2018/12", 1),
                data("1785", "2016/11", 2),
            ])
            cases = Path(tmp) / "finlab.csv"
            with cases.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "case_id", "ticker", "fiscal_year", "first_notice_date",
                    "rank", "holdout", "training_y"
                ])
                w.writeheader()
                w.writerow({"case_id": "1203-FY2017", "ticker": "1203",
                            "fiscal_year": "2017",
                            "first_notice_date": "2018-05-11",
                            "rank": "P0", "holdout": "false", "training_y": ""})
                w.writerow({"case_id": "1785-FY2015", "ticker": "1785",
                            "fiscal_year": "2015",
                            "first_notice_date": "2016-11-11",
                            "rank": "P1", "holdout": "true", "training_y": ""})
            out = Path(tmp) / "output"
            result = build(x, out, cases)
            self.assertEqual(result["input_monthly_rows"], 6)
            self.assertEqual(result["distinct_tickers"], 4)
            self.assertEqual(result["positive_month_rows"], 5)
            self.assertEqual(result["nonzero_company_calendar_years_2013_2023"], 4)
            self.assertEqual(result["y_positive_assigned"], 0)
            self.assertEqual(result["y_negative_assigned"], 0)
            self.assertEqual(result["finlab_join"]["metrics"]["notice_calendar_year_positive_cue"], 2)
            self.assertEqual(result, build(x, out, cases))
            with (out / "finlab_tej_join_review_private.csv").open(
                    encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["training_y_tej"] == "" for row in rows))
            self.assertEqual(rows[0]["tej_notice_year_max_count"], "1")
            self.assertEqual(rows[0]["tej_fy_calendar_year_observed"], "false")
            self.assertEqual(rows[1]["holdout"], "true")
            (out / "finlab_tej_join_review_private.csv").write_text(
                "tamper", encoding="utf-8"
            )
            with self.assertRaisesRegex(FileExistsError, "immutable_existing_output"):
                build(x, out, cases)

    def test_duplicate_company_month_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            x = Path(tmp) / "duplicate.xlsx"
            synthetic_tej(x, [data("1203", "2017/11", 1),
                              data("1203", "2017/11", 0)])
            with self.assertRaisesRegex(ValueError, "duplicate_tej_company_year_month"):
                build(x, Path(tmp) / "out")

    def test_wrong_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            x = Path(tmp) / "wrong.xlsx"
            synthetic_tej(x, [data("1203", "2017/11", 1)],
                          headers=["AAA"] + HEADERS[1:])
            with self.assertRaisesRegex(ValueError, "tej_information_transparency_columns_missing"):
                build(x, Path(tmp) / "out")

    def test_finlab_prelabeled_y_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            x = Path(tmp) / "test.xlsx"
            synthetic_tej(x, [data("1203", "2018/05", 1)])
            f = Path(tmp) / "case.csv"
            with f.open("w", encoding="utf-8-sig", newline="") as h:
                w = csv.DictWriter(h, fieldnames=[
                    "ticker", "fiscal_year", "first_notice_date", "rank",
                    "holdout", "training_y"
                ])
                w.writeheader()
                w.writerow({"ticker": "1203", "fiscal_year": "2017",
                            "first_notice_date": "2018-05-11", "rank": "P0",
                            "holdout": "false", "training_y": "1"})
            with self.assertRaisesRegex(ValueError, "refuse_join_preapproved_training_y"):
                build(x, Path(tmp) / "out", f)


if __name__ == "__main__":
    unittest.main()
