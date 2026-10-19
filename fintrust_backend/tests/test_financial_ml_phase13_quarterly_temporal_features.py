"""Phase13 hermetic tests: genuine quarter numeric parsing + leakage embargo.

Fixtures are deliberately synthetic XBRL, not claims about real Kangyou reports.
"""
from __future__ import annotations
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.financial_ml import phase13_quarterly_temporal_features as m


def synthetic_xbrl(period, *, namespace="http://example.com/ifrs-full",
                   duplicate=None, other_context=False):
    y,q,start,end=m.quarter_parts(period)
    same_start=f"{y}-01-01"
    context_extra=('<xbrli:context id="comparative"><xbrli:entity><xbrli:identifier'
        ' scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>'
        f'<xbrli:period><xbrli:instant>{y-1}-12-31</xbrli:instant></xbrli:period>'
        '</xbrli:context>')
    duplicated=(f'<ifrs:Assets contextRef="currentI" unitRef="TWD">{duplicate}</ifrs:Assets>'
                if duplicate is not None else "")
    # Q1 starts at Jan 1, so 3-month and YTD represent same context, no
    # duplication into two model features.
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:ifrs="{namespace}">
 <link:schemaRef xlink:type="simple"
   xlink:href="https://mopsov.twse.com.tw/tifrs-ci-cr-2019-03-31.xsd"/>
 <xbrli:context id="currentI"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="currentQ"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="currentY"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>{same_start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
 {context_extra}
 <xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
 <ifrs:Assets contextRef="currentI" unitRef="TWD" decimals="0">100</ifrs:Assets>
 {duplicated}
 <ifrs:Revenue contextRef="currentQ" unitRef="TWD" decimals="0">40</ifrs:Revenue>
 <ifrs:Revenue contextRef="currentY" unitRef="TWD" decimals="0">{q*40}</ifrs:Revenue>
 <ifrs:Assets contextRef="comparative" unitRef="TWD" decimals="0">9999</ifrs:Assets>
</xbrli:xbrl>'''.encode("utf-8")


class Phase13SameGrainQuarterTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)

    def test_full_twd_company_quarter_and_ytd_without_comparative(self):
        rows,meta,n,issues=m.extract_source(synthetic_xbrl("2017Q2"),"2017Q2","a"*64)
        self.assertEqual(n,3)
        self.assertEqual(len(rows),3)
        self.assertFalse(issues)
        self.assertEqual({r["period_grain"] for r in rows},
                         {"instant","quarter_duration","ytd_duration"})
        self.assertEqual({r["outcome_label"] for r in rows},{"UNKNOWN"})
        self.assertEqual({r["model_training_admitted"] for r in rows},{"false"})
        self.assertNotIn("9999",{r["value_decimal"] for r in rows})

    def test_q1_ytd_overlap_is_single_record_not_two_revenue_values(self):
        rows,_,n,issues=m.extract_source(synthetic_xbrl("2018Q1"),"2018Q1","b"*64)
        self.assertEqual(n,4)  # two identical source contexts, later deduped
        revenue=[r for r in rows if r["source_local_name"]=="Revenue"]
        self.assertEqual(len(revenue),1)
        self.assertEqual(revenue[0]["period_grain"],"quarter_duration")
        self.assertEqual(revenue[0]["observation_count"],2)
        self.assertFalse(issues)

    def test_duplicate_conflicting_financial_amount_is_quarantined(self):
        rows,_,_,issues=m.extract_source(
            synthetic_xbrl("2017Q2",duplicate="101"),"2017Q2","c"*64)
        self.assertEqual(len(issues),1)
        conflicted=next(r for r in rows if r["source_local_name"]=="Assets")
        self.assertEqual(conflicted["reconciliation_status"],"DUPLICATE_CONFLICT_QUARANTINED")
        self.assertEqual(conflicted["value_decimal"],"")
        self.assertFalse(any(s["source_local_name"]=="Assets" for s in m.derive_signals(rows)))

    def test_two_rolling_windows_are_same_concept_grain_no_ytd_qoq(self):
        rows=[]
        for period in m.FROZEN_PERIODS:
            extracted,_,_,_=m.extract_source(
                synthetic_xbrl(period),period,(period*12)[:64])
            rows.extend(extracted)
        signals=m.derive_signals(rows)
        qoq={s["period_grain"] for s in signals if s["comparison"]=="QOQ_SAME_GRAIN"}
        self.assertEqual(qoq,{"instant","quarter_duration"})
        yoy={s["period_grain"] for s in signals if s["comparison"]=="YOY_SAME_QUARTER_SAME_GRAIN"}
        self.assertEqual(yoy,{"instant","quarter_duration","ytd_duration"})
        self.assertTrue(all(s["model_training_admitted"]=="false" for s in signals))
        self.assertTrue(all(s["historical_vintage_approved"]=="false" for s in signals))
        self.assertTrue(all(s["strict_same_concept_and_grain"]=="true" for s in signals))

    def test_taxonomy_namespace_changed_not_silently_joined(self):
        rows=[]
        for period,uri in (("2017Q2","http://example.com/ifrs-full"),
                           ("2018Q2","http://example.com/v2/ifrs-full")):
            records,_,_,_=m.extract_source(
                synthetic_xbrl(period,namespace=uri),period,"a"*64)
            rows.extend(records)
        signal=m.derive_signals(rows)
        self.assertFalse(signal)

    def test_signed_delta_relative_change_and_zero_denominator(self):
        base={
            "ticker":"6452","concept_key":"uri|CashFlow","source_local_name":"CashFlow",
            "period_grain":"quarter_duration","source_unit":"TWD",
            "reconciliation_status":"CANDIDATE_CONSISTENT_REPETITIONS",
            "source_sha256":"a"*64
        }
        rows=[
            {**base,"reporting_period":"2017Q2","value_decimal":"-10"},
            {**base,"reporting_period":"2017Q3","value_decimal":"5"},
            {**base,"reporting_period":"2017Q4","value_decimal":"0"}
        ]
        signal=m.derive_signals(rows)
        a=next(s for s in signal if s["reporting_period"]=="2017Q3")
        self.assertEqual(a["delta_decimal"],"15")
        self.assertEqual(a["relative_change_abs_prior"],"1.5")
        rows.append({**base,"reporting_period":"2018Q1","value_decimal":"8"})
        signal=m.derive_signals(rows)
        b=next(s for s in signal if s["reporting_period"]=="2018Q1")
        self.assertEqual(b["relative_change_abs_prior"],"")

    def test_period_outside_frozen_12_rejected(self):
        with self.assertRaisesRegex(ValueError,"quarter_not_in_frozen"):
            m.period_grain(None,"2017Q1")

    def test_cached_input_rejects_forged_holdout_and_labels(self):
        data=self.root/"phase12_kangyou_quarterly_panel"
        data.mkdir()
        (data/"phase12_integrated_report.json").write_text(json.dumps({
            "issuer":"6452","candidate_quarters":12,
            "official_quarters_context_scope_validated":12,
            "historical_original_filing_vintages_verified":0,
            "confirmed_period_outcome_labels":1,
            "financial_misstatement_supervised_training_rows":0,
            "final_holdout_1785_excluded":True
        }),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"phase12_real_source_or_historical_label_gate"):
            list(m.cached_documents(self.root))

    def test_run_on_local_12_quarter_fixture_outputs_only_candidates(self):
        test_rows=[]
        for period in m.FROZEN_PERIODS:
            rows,_,_,_=m.extract_source(synthetic_xbrl(period),period,(period*12)[:64])
            test_rows.append((period,{"status":m.SOURCE_STATUS_OK,
                "raw_sha256":(period*12)[:64]},synthetic_xbrl(period)))
        phase12=self.root/"phase12_kangyou_quarterly_panel"
        phase12.mkdir()
        (phase12/"phase12_integrated_report.json").write_text(
            json.dumps({"status":"SYNTHETIC_TEST_ONLY"}),encoding="utf-8")
        with patch.object(m,"cached_documents",return_value=iter(test_rows)):
            result=m.run(self.root,self.root/"out")
        self.assertEqual(result["official_source_quarters_read"],12)
        self.assertEqual(result["independent_issuer_count"],1)
        self.assertEqual(result["model_training_rows_admitted"],0)
        self.assertEqual(result["genuine_historical_original_filing_versions_verified"],0)
        self.assertFalse(result["is_this_a_valid_multi_company_ml_dataset"])
        self.assertEqual(result["network_requests"],0)
        self.assertGreater(result["same_grain_change_candidates"],0)
        with (self.root/"out"/"quarterly_same_grain_change_candidates.csv").open(
                encoding="utf-8",newline="") as fh:
            signals=list(csv.DictReader(fh))
        self.assertEqual({s["outcome_label"] for s in signals},{"UNKNOWN"})


if __name__=="__main__":
    unittest.main()
