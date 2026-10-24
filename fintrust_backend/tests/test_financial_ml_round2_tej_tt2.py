"""TEJ TT2: hermetic data-contract tests ONLY; never claim fixture as real TEJ."""
from __future__ import annotations
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.round2_tej_tt2 import (
    TT2_EVENT_TARGET, CORE_TARGET, column_map, load_csv, materialize, preflight,
    parse_date, period_year_month, company_id, plus24,
)


def save_csv(path, cols, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class TT2AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.tt2 = self.base / "tej_export.csv"
        self.universe = self.base / "annual_universe.csv"
        self.coverage = self.base / "coverage.json"
        self.output = self.base / "out"
        tc = ["公司", "年/月", "重編事件日", "財報類別", "重編原因",
              "營業收入_調整金額", "稅後淨利_調整金額"]
        self.events = [
            {"公司":"2330 台積電","年/月":"202012","重編事件日":"2022/02/01",
             "財報類別":"3","重編原因":"測試重編","營業收入_調整金額":"10",
             "稅後淨利_調整金額":"0"},
            {"公司":"2330 台積電","年/月":"202012","重編事件日":"2022/02/01",
             "財報類別":"3","重編原因":"重複列","營業收入_調整金額":"10",
             "稅後淨利_調整金額":"0"},
            {"公司":"2317 鴻海","年/月":"201912","重編事件日":"2023/01/10",
             "財報類別":"3","重編原因":"超出窗口","營業收入_調整金額":"50"},
            {"公司":"1785 光洋科","年/月":"201512","重編事件日":"2016/06/01",
             "財報類別":"3","重編原因":"保留案例","稅後淨利_調整金額":"20"},
        ]
        save_csv(self.tt2, tc, self.events)
        uc = ["公司","年/月","財報類別","首次公告日"]
        self.univ = [
            {"公司":"2330 台積電","年/月":"202012","財報類別":"3",
             "首次公告日":"2021-03-15"},
            {"公司":"2454 聯發科","年/月":"202012","財報類別":"3",
             "首次公告日":"2021-03-31"},
            {"公司":"2317 鴻海","年/月":"201912","財報類別":"3",
             "首次公告日":"2020-03-31"},
            {"公司":"3711 日月光","年/月":"202312","財報類別":"3",
             "首次公告日":"2024-03-31"},
        ]
        save_csv(self.universe, uc, self.univ)
        self.coverage_data = {
            "schema_version": "fintrust_tej_tt2_coverage_v1",
            "tt2_export_sha256": hashlib.sha256(self.tt2.read_bytes()).hexdigest(),
            "universe_export_sha256": hashlib.sha256(self.universe.read_bytes()).hexdigest(),
            "closed_event_census_for_exported_universe": True,
            "includes_historical_delisted_firms": True,
            "issuer_and_year_filters_match": True,
            "covered_fiscal_years": [2019,2020,2023],
            "tt2_event_coverage_through": "2024-09-30",
        }
        self.write_coverage()

    def write_coverage(self):
        self.coverage.write_text(json.dumps(self.coverage_data),encoding="utf-8")

    def test_preflight_without_license_no_fake_data(self):
        report = preflight(self.output)
        self.assertEqual(report["real_tej_binary_labels_generated"],0)
        self.assertEqual(preflight(self.output),report)

    def test_core_and_tej_targets_are_not_conflated(self):
        r = materialize(self.tt2,self.universe,self.coverage,self.output)
        self.assertEqual(r["input_tt2_rows"],4)
        self.assertEqual(r["deduplicated_events"],2) # 1785 excluded; duplicate merged
        self.assertEqual(r["company_years_with_publication"],4)
        self.assertEqual((r["tej_restatement_y_1"],r["tej_restatement_y_0"],
                          r["tej_restatement_unlabeled"]),(1,2,1))
        self.assertEqual((r["core_amount_y_1"],r["core_amount_y_0"],
                          r["core_amount_unlabeled"]),(1,2,1))
        with (self.output/"round2_tej_issuer_year_labels.csv").open(encoding="utf-8") as f:
            d={(x["ticker"],x["fiscal_year"]):x for x in csv.DictReader(f)}
        self.assertEqual(d["2330","2020"]["y_tej_restatement_24m"],"1")
        self.assertEqual(d["2454","2020"]["y_tej_restatement_24m"],"0")
        self.assertEqual(d["2317","2019"]["y_tej_restatement_24m"],"0")
        self.assertEqual(d["3711","2023"]["y_tej_restatement_24m"],"")
        self.assertEqual(d["2330","2020"]["y_core_adjustment_24m"],"1")
        self.assertTrue(r["source_reported_not_independently_verified"])
        self.assertFalse(r["fraud_label_claim_allowed"])

    def test_same_source_reproducibility_and_no_overwrite(self):
        report = materialize(self.tt2,self.universe,self.coverage,self.output)
        self.assertEqual(materialize(self.tt2,self.universe,self.coverage,self.output),report)
        file=self.output/"round2_tej_issuer_year_labels.csv"
        file.write_text("tampered",encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError,"immutable"):
            materialize(self.tt2,self.universe,self.coverage,self.output)

    def test_full_period_coverage_and_hash_required_for_zero(self):
        self.coverage_data["closed_event_census_for_exported_universe"]=False
        self.write_coverage()
        with self.assertRaisesRegex(ValueError,"coverage_unproven"):
            materialize(self.tt2,self.universe,self.coverage,self.base/"bad")
        self.coverage_data["closed_event_census_for_exported_universe"]=True
        self.coverage_data["universe_export_sha256"]="b"*64
        self.write_coverage()
        with self.assertRaisesRegex(ValueError,"coverage_unproven"):
            materialize(self.tt2,self.universe,self.coverage,self.base/"bad")

    def test_core_absent_does_not_turn_into_negative(self):
        # no amount change data in event; broad TT2 is still positive
        for row in self.events:
            row["營業收入_調整金額"]=""
            row["稅後淨利_調整金額"]=""
        save_csv(self.tt2, ["公司","年/月","重編事件日","財報類別","重編原因",
                            "營業收入_調整金額","稅後淨利_調整金額"],self.events)
        self.coverage_data["tt2_export_sha256"]=hashlib.sha256(self.tt2.read_bytes()).hexdigest()
        self.write_coverage()
        r=materialize(self.tt2,self.universe,self.coverage,self.base/"sparse")
        self.assertEqual(r["tej_restatement_y_1"],1)
        self.assertEqual(r["core_amount_y_1"],0)
        self.assertEqual(r["core_amount_unlabeled"],2) # sparse positive + censored

    def test_invalid_tt2_date_blocks_zero_even_when_other_event_row_valid(self):
        # One bad event date must never be misread as "no restatement".
        self.events[0]["重編事件日"] = "INVALID"
        save_csv(self.tt2, ["公司","年/月","重編事件日","財報類別","重編原因",
                            "營業收入_調整金額","稅後淨利_調整金額"], self.events)
        self.coverage_data["tt2_export_sha256"] = hashlib.sha256(self.tt2.read_bytes()).hexdigest()
        self.write_coverage()
        r = materialize(self.tt2, self.universe, self.coverage, self.base / "blocked")
        self.assertEqual(r["blocked_issuer_years_due_to_unparseable_events"], 1)
        with (self.base / "blocked" / "round2_tej_issuer_year_labels.csv").open(encoding="utf-8") as f:
            rows = {(x["ticker"], x["fiscal_year"]): x for x in csv.DictReader(f)}
        self.assertEqual(rows["2330", "2020"]["y_tej_restatement_24m"], "")
        self.assertEqual(rows["2330", "2020"]["label_grade"], "BLOCKED_UNPARSEABLE_TT2_EVENT")

    def test_partial_core_zero_not_all_five_zero(self):
        for row in self.events:
            row["營業收入_調整金額"] = "0"
            row["稅後淨利_調整金額"] = ""
        save_csv(self.tt2, ["公司","年/月","重編事件日","財報類別","重編原因",
                            "營業收入_調整金額","稅後淨利_調整金額"], self.events)
        self.coverage_data["tt2_export_sha256"] = hashlib.sha256(self.tt2.read_bytes()).hexdigest()
        self.write_coverage()
        r = materialize(self.tt2, self.universe, self.coverage, self.base / "partial")
        self.assertEqual(r["tej_restatement_y_1"], 1)
        self.assertEqual(r["core_amount_y_1"], 0)
        self.assertEqual(r["core_amount_unlabeled"], 2)

    def test_coverage_template_is_unapproved_by_default(self):
        from research.financial_ml.round2_tej_tt2 import prepare_coverage_template
        r = prepare_coverage_template(self.tt2, self.universe, self.base / "template")
        self.assertTrue(r["not_training_ready"])
        d = json.loads((self.base / "template" /
                        "round2_tej_coverage_REVIEW_REQUIRED.json").read_text(encoding="utf-8"))
        self.assertFalse(d["closed_event_census_for_exported_universe"])
        self.assertFalse(d["includes_historical_delisted_firms"])
        self.assertEqual(d["covered_fiscal_years"], [])
        self.assertEqual(d["tt2_export_sha256"], hashlib.sha256(self.tt2.read_bytes()).hexdigest())

    def test_invalid_company_scope_period_roc_and_date(self):
        self.assertEqual(company_id("1101 台泥"),"1101")
        self.assertEqual(period_year_month("11212"),(2023,12))
        self.assertEqual(parse_date("1121231").isoformat(),"2023-12-31")
        self.assertEqual(plus24(parse_date("2020-02-29")).isoformat(),"2022-02-28")
        for invalid in ("1101A", "ABC", "11010"):
            with self.assertRaises(ValueError):
                company_id(invalid)
        self.events[0]["財報類別"]="個體"
        save_csv(self.tt2, ["公司","年/月","重編事件日","財報類別","重編原因",
                            "營業收入_調整金額","稅後淨利_調整金額"],self.events)
        self.coverage_data["tt2_export_sha256"]=hashlib.sha256(self.tt2.read_bytes()).hexdigest()
        self.write_coverage()
        r=materialize(self.tt2,self.universe,self.coverage,self.base/"notconsolidated")
        self.assertGreaterEqual(r["excluded_rows"],2) # contains reserved 1785 as well


if __name__=="__main__":
    unittest.main()
