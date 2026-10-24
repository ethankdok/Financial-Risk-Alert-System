"""Synthetic-only tests for the independent positive-only reviewer-attested gate."""
import csv
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.round2_finlab_review_gate import (
    _check_one, _shift_months, build,
)
from datetime import date

OFFICIAL_NOTICE = "https://mops.twse.com.tw/mops/web/t05sr01_1"
OFFICIAL_FILING = "https://mops.twse.com.tw/mops/web/t164sb01"


def row(ticker="1203", fy="2017", kind="RESTATEMENT"):
    return {
        "case_id": f"{ticker}-FY{fy}", "ticker": ticker,
        "fiscal_year": fy, "holdout": str(ticker == "1785").lower(),
        "adjudication": "APPROVE_SOURCE_REVIEW",
        "reviewer_evidence_checked": "yes",
        "verified_event_kind": kind,
        "mops_notice_url": OFFICIAL_NOTICE,
        "original_financial_filing_url": OFFICIAL_FILING,
        "first_report_public_date": "2018-03-31",
        "verified_correction_date": "2018-05-11",
        "scope_verified": "consolidated",
        "line_items_old_new_verified": "true",
        "core_line_item": "total_assets",
        "verified_old_value": "100",
        "verified_new_value": "101",
    }


class FinLabReviewerGateTests(unittest.TestCase):
    def test_calendar_window_leap_day(self):
        self.assertEqual(_shift_months(date(2020, 2, 29), 24), date(2022, 2, 28))
        self.assertEqual(_shift_months(date(2019, 1, 31), 1), date(2019, 2, 28))

    def test_rejections_and_no_negative(self):
        x = row(ticker="1785")
        self.assertEqual(_check_one(x), "RESERVED_HOLDOUT")
        x = row()
        x["mops_notice_url"] = "https://evil.test/mops.twse.com.tw"
        self.assertEqual(_check_one(x), "MISSING_OFFICIAL_MOPS_EVENT_URL")
        x = row()
        x["verified_correction_date"] = "2020-04-01"
        self.assertEqual(_check_one(x), "EVENT_OUTSIDE_24_MONTH_WINDOW")
        x = row()
        x["scope_verified"] = "standalone"
        self.assertEqual(_check_one(x), "SCOPE_NOT_CONFIRMED_CONSOLIDATED")
        x = row(kind="CORE_AMOUNT_CORRECTION")
        x["verified_new_value"] = "100"
        self.assertEqual(_check_one(x), "CORE_OLD_NEW_NOT_DIFFERENT")

    def test_review_ledger_positive_only_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = Path(tmp) / "review.csv", Path(tmp) / "output"
            rows = [row(), row("1785", "2017"), row("2317", "2017", "CORE_AMOUNT_CORRECTION")]
            with inp.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            report = build(inp, out)
            self.assertEqual(report["reviewer_attested_positive_event_count"], 2)
            self.assertEqual(report["reviewer_attested_positive_core_count"], 1)
            self.assertEqual(report["negative_0_issued"], 0)
            self.assertEqual(report["reject_reasons"], {"RESERVED_HOLDOUT": 1})
            self.assertEqual(report, build(inp, out))
            with (out / "reviewer_attested_positives_private.csv").open(encoding="utf-8-sig") as f:
                accepted = list(csv.DictReader(f))
            self.assertEqual(len(accepted), 2)
            self.assertTrue(all(c["review_provenance"] == "REVIEWER_ATTESTED_NOT_AUTO_VERIFIED" for c in accepted))
            self.assertTrue(all(c["y_event_restatement_or_core_24m"] == "1" for c in accepted))
            self.assertEqual(sorted(c["y_core_change_24m"] for c in accepted), ["", "1"])
            (out / "reviewer_attested_positives_private.csv").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "immutable_output_collision"):
                build(inp, out)


if __name__ == "__main__":
    unittest.main()
