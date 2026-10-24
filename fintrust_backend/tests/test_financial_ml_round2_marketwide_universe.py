"""Synthetic schema/guardrail tests. Actual official feeds fetched in workflow separately."""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.round2_marketwide_universe import (
    YEARS, construct_panel, parse_official, fetch_official, make_csv, sha
)


def listed(t):
    return {"公司代號": t, "公司簡稱": "上市" + t,
            "產業別": "24", "上市日期": "110/01/01"}


def otc(t):
    return {"SecuritiesCompanyCode": t, "CompanyAbbreviation": "上櫃" + t,
            "SecuritiesIndustryCode": "24"}


class MarketwideTests(unittest.TestCase):
    def setUp(self):
        self.twse = {
            x["公司代號"]: x for x in [listed(str(i)) for i in range(1101, 1116)]
        }
        self.tpex = {
            x["SecuritiesCompanyCode"]: x for x in [otc(str(i)) for i in range(6101, 6116)]
        }

    def test_official_sources_normalize_market_specific_schema(self):
        a = parse_official(json.dumps(list(self.twse.values())).encode(), "TWSE")
        b = parse_official(json.dumps(list(self.tpex.values())).encode(), "TPEX")
        self.assertEqual((len(a), len(b)), (15, 15))
        self.assertEqual(a["1101"]["market"], "TWSE")
        self.assertEqual(b["6101"]["market"], "TPEX")
        self.assertTrue(all(x["historical_market_membership_verified"] == "false"
                            for x in [*a.values(), *b.values()]))
        self.assertEqual(a["1101"]["industry"], "24")

    def test_csv_fallback_works_without_api_keys(self):
        raw = make_csv(("公司代號", "公司簡稱", "產業別", "上櫃日期"),
                       [{"公司代號": str(i), "公司簡稱": "測試" + str(i),
                         "產業別": "24", "上櫃日期": "110/01/01"}
                        for i in range(6101, 6112)])
        parsed = parse_official(raw, "TPEX", csv_input=True)
        self.assertEqual(len(parsed), 11)
        self.assertTrue(parsed["6101"]["current_asof_source"].endswith(".csv"))

    def test_no_zero_from_issuer_universe_or_future_listing(self):
        roster = {"TWSE": parse_official(
            json.dumps(list(self.twse.values())).encode(), "TWSE")}
        companies, panel = construct_panel(roster, [], include_seed=False)
        self.assertEqual(len(companies), 15)
        self.assertEqual(len(panel), len(companies) * len(YEARS))
        self.assertTrue(all(row["y"] == "" and
                            row["historical_listing_verified"] == "false" and
                            row["binary_research_eligible"] == "false"
                            for row in panel))

    def test_real_label_join_keeps_only_valid_existing_rows(self):
        a = parse_official(json.dumps(list(self.twse.values())).encode(), "TWSE")
        case = {"ticker": "2330", "fiscal_year": "2022", "y": "0",
                "evidence_grade": "SILVER", "source_url": "https://example.org/",
                "target": "EXPLICIT_CSV_REFERENCE"}
        companies, panel = construct_panel({"TWSE": a}, [case])
        match = [x for x in panel if x["ticker"] == "2330" and
                 x["fiscal_year"] == "2022"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["y"], "0")
        self.assertFalse(match[0]["binary_research_eligible"] == "true")
        self.assertEqual(sum(x["y"] == "0" for x in panel), 1)
        self.assertEqual(sum(x["y"] == "1" for x in panel), 0)

    def test_wrong_data_cannot_be_silent_source_success(self):
        with self.assertRaisesRegex(ValueError, "not_an_array"):
            parse_official(b'{"status":"blocked"}', "TWSE")
        with self.assertRaisesRegex(ValueError, "too_small"):
            parse_official(b'[{"公司代號":"2330","公司簡稱":"TSMC"}]', "TWSE")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_official(json.dumps([listed("1101")] * 12).encode(), "TWSE")
        with self.assertRaisesRegex(ValueError, "unapproved"):
            fetch_official("https://evil.example.com/")
        self.assertEqual(len(sha(b"source-data")), 64)


if __name__ == "__main__":
    unittest.main()
