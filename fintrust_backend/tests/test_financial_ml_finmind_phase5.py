"""No-network FinMind universe and multi-year raw archive smoke tests."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import finmind_universe as u
from research.financial_ml import finmind_bulk_stage as b


class FinMindStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _universe(self):
        entries = [
            {"stock_id": "2330", "stock_name": "台積電", "industry_category": "半導體業", "type": "twse", "date": "2026-10-18"},
            {"stock_id": "2303", "stock_name": "聯電", "industry_category": "半導體業", "type": "twse", "date": "2026-10-18"},
            {"stock_id": "2882", "stock_name": "金融甲", "industry_category": "金融保險業", "type": "twse", "date": "2026-10-18"},
            {"stock_id": "0050", "stock_name": "元大台灣50", "industry_category": "ETF", "type": "twse", "date": "2026-10-18"},
            {"stock_id": "1785", "stock_name": "光洋科", "industry_category": "半導體業", "type": "tpex", "date": "2026-10-18"},
            {"stock_id": "9999", "stock_name": "興櫃候選", "industry_category": "電子業", "type": "emerging", "date": "2026-10-18"}
        ]
        raw = self.root / "stock_info.json"
        raw.write_text(json.dumps({"status": 200, "data": entries}, ensure_ascii=False), encoding="utf-8")
        return raw

    def test_universe_excludes_finance_etf_reserved_case(self):
        result = u.build(self._universe(), self.root / "universe")
        self.assertEqual(result["nonfinancial_candidate_tickers"], 2)
        self.assertEqual(result["normal_labels_created"], 0)
        ids = b.tickers_from_csv(self.root / "universe" / "taiwan_nonfinancial_current_candidates.csv")
        self.assertEqual(ids, ["2303", "2330"])
        self.assertFalse(result["historical_listing_and_industry_verified"])

    def test_prior_emerging_record_latest_tpex_selected_order_independent(self):
        old = {"stock_id":"6165", "stock_name":"測試甲", "industry_category":"半導體業",
               "type":"emerging", "date":"2020-01-05"}
        latest = {"stock_id":"6165", "stock_name":"測試乙", "industry_category":"電子業",
                  "type":"tpex", "date":"2026-10-18"}
        for entries in ([old,latest], [latest,old]):
            selected, reasons, quarantined = u.current_nonfinancial_candidates(
                entries, include_conflicts=True)
            self.assertEqual(len(selected),1)
            self.assertEqual(selected[0]["market"],"tpex")
            self.assertEqual(selected[0]["company_name"],"測試乙")
            self.assertEqual(selected[0]["source_snapshot_date"],"2026-10-18")
            self.assertEqual(reasons["superseded_historical_rows"],1)
            self.assertEqual(quarantined,[])

    def test_latest_financial_or_emerging_not_resurrected(self):
        old = {"stock_id":"6165","stock_name":"示意公司","industry_category":"電子業",
               "type":"twse","date":"2024-01-01"}
        latest = {**old, "industry_category":"金融保險業","date":"2026-10-18"}
        selected, reasons = u.current_nonfinancial_candidates([old,latest])
        self.assertEqual(selected,[])
        self.assertEqual(reasons["financial_excluded"],1)
        selected, reasons = u.current_nonfinancial_candidates([old,{**latest,"type":"emerging","industry_category":"電子業"}])
        self.assertEqual(selected,[])
        self.assertEqual(reasons["not_twse_or_tpex"],1)

    def test_same_day_conflict_quarantines_only_affected_ticker(self):
        entries=[
            {"stock_id":"6165","stock_name":"示意甲","industry_category":"半導體業",
             "type":"tpex","date":"2026-10-18"},
            {"stock_id":"6165","stock_name":"示意乙","industry_category":"電子業",
             "type":"twse","date":"2026-10-18"},
            {"stock_id":"2330","stock_name":"台積電","industry_category":"半導體業",
             "type":"twse","date":"2026-10-18"},
        ]
        source=self.root/"duplicate_board_snapshot.json"
        source.write_text(json.dumps({"status":200,"data":entries},ensure_ascii=False),encoding="utf-8")
        original=source.read_bytes()
        report=u.build(source,self.root/"audit")
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual(report["nonfinancial_candidate_tickers"],1)
        self.assertEqual(report["quarantined_tickers"],1)
        self.assertEqual(report["quarantined_ticker_examples"],["6165"])
        with (self.root/"audit"/"taiwan_stock_info_quarantined.csv").open(encoding="utf-8",newline="") as fp:
            quarantine=list(csv.DictReader(fp))
        self.assertEqual(len(quarantine),2)
        self.assertTrue(all(x["reason"]=="same_date_conflicting_company_identity" for x in quarantine))
        ids=b.tickers_from_csv(self.root/"audit"/"taiwan_nonfinancial_current_candidates.csv")
        self.assertEqual(ids,["2330"])

    def test_bad_date_quarantines_ticker_instead_of_choosing_older_row(self):
        entries=[
            {"stock_id":"6165","stock_name":"示意甲","industry_category":"電子業","type":"tpex","date":"2020-01-01"},
            {"stock_id":"6165","stock_name":"示意乙","industry_category":"電子業","type":"twse","date":""},
            {"stock_id":"2330","stock_name":"台積電","industry_category":"半導體業","type":"twse","date":"2026-10-18"},
        ]
        candidates,rejections,conflicts = u.current_nonfinancial_candidates(entries,include_conflicts=True)
        self.assertEqual([c["ticker"] for c in candidates],["2330"])
        self.assertEqual(rejections["tickers_quarantined_invalid_date"],1)
        self.assertEqual({r["ticker"] for r in conflicts},{"6165"})

    def test_identical_latest_duplicate_kept_once(self):
        record={"stock_id":"2330","stock_name":"台積電","industry_category":"半導體業",
                "type":"twse","date":"2026-10-18"}
        items,counts,problems=u.current_nonfinancial_candidates([record,record],include_conflicts=True)
        self.assertEqual(len(items),1)
        self.assertEqual(counts["identical_duplicate_latest_rows"],1)
        self.assertEqual(problems,[])

    def test_stage_dry_run_no_network_no_files(self):
        u.build(self._universe(), self.root / "universe")
        path = self.root / "universe" / "taiwan_nonfinancial_current_candidates.csv"
        result = b.run(path, self.root / "raw", max_tickers=2, execute=False)
        self.assertEqual(result["jobs"], 6)
        self.assertEqual(result["requests_sent"], 0)
        self.assertFalse((self.root / "raw").exists())

    def test_raw_stage_reuses_existing_without_redownload(self):
        u.build(self._universe(), self.root / "universe")
        path = self.root / "universe" / "taiwan_nonfinancial_current_candidates.csv"
        calls = []
        def fetch(dataset, ticker, start, end, *, token=None):
            calls.append((dataset, ticker))
            return [{"stock_id": ticker, "date": "2015-12-31", "type": "Assets", "value": 42}]
        first = b.run(path, self.root / "raw", max_tickers=1, execute=True, getter=fetch)
        second = b.run(path, self.root / "raw", max_tickers=1, execute=True, getter=fetch)
        self.assertEqual(first["requests_sent"], 3)
        self.assertEqual(second["requests_sent"], 0)
        self.assertEqual(second["reused_cached"], 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(second["normal_labels_created"], 0)

    def test_rate_limit_halts_without_fake_success(self):
        u.build(self._universe(), self.root / "universe")
        path = self.root / "universe" / "taiwan_nonfinancial_current_candidates.csv"
        def fail(dataset, ticker, start, end, *, token=None):
            raise b.QuotaOrAccessError("quota")
        report = b.run(path, self.root / "raw", max_tickers=1, execute=True, getter=fail)
        self.assertTrue(report["halted"])
        self.assertEqual(report["requests_sent"], 1)
        self.assertEqual(report["outcome_counts"]["halted_quota_or_access"], 1)
        self.assertEqual(list((self.root / "raw").rglob("*.json")), [self.root / "raw" / "finmind_raw_acquisition_report.json"])


if __name__ == "__main__":
    unittest.main()
