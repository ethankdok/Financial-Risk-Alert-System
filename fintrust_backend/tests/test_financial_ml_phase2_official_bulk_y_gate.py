"""Synthetic official archive manifests only: no real gold assertions in CI."""
import csv
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.phase2_official_bulk_y_gate import build

HASH="a"*64; REVISED="b"*64
URL="https://mops.twse.com.tw/mops/web/t164sb01"

def write(path,columns,rows):
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(rows)

def annual(ticker):
    return {
        "ticker":ticker,"fiscal_year":"2017","first_public_at":"2018-03-29",
        "original_filing_url":URL,"original_sha256":HASH,
        "statement_scope":"consolidated","original_verified":"true",
        "first_public_verified":"true",
    }
def coverage(ticker, complete="true"):
    return {
        "ticker":ticker,"fiscal_year":"2017","coverage_start":"2018-03-29",
        "coverage_end":"2020-03-29","complete":complete,
        "all_candidates_resolved":"true","source_evidence_url":URL,
        "source_sha256":HASH,"reviewer_verified":"true",
    }
def event(ticker):
    return {
        "ticker":ticker,"fiscal_year":"2017","event_date":"2018-05-11",
        "event_kind":"CORE_AMOUNT_CORRECTION","event_url":URL,
        "original_sha256":HASH,"revised_sha256":REVISED,
        "scope":"consolidated","core_delta_verified":"true",
        "reviewer_verified":"true",
    }

class OfficialBulkYTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        d=Path(self.tmp.name)
        self.annual=d/"annual.csv";self.cover=d/"cover.csv";self.events=d/"events.csv";self.out=d/"out"
        self.a=[annual("1203"),annual("2317"),annual("2330"),annual("1785")]
        self.c=[coverage("2317"),coverage("2330","false")]
        self.e=[event("1203")]
        self.save()
    def tearDown(self):self.tmp.cleanup()
    def save(self):
        write(self.annual,list(self.a[0]),self.a)
        write(self.cover,list(coverage("1203")),self.c)
        write(self.events,list(event("1203")),self.e)

    def test_signed_positive_negative_unknown_and_reserved(self):
        rpt=build(self.annual,self.cover,self.events,self.out)
        self.assertEqual(rpt["output_records"],3)
        self.assertEqual(rpt["reviewer_attested_positive"],1)
        self.assertEqual(rpt["reviewer_attested_negative"],1)
        self.assertEqual(rpt["unknown"],1)
        self.assertEqual(rpt["independently_verified_gold_positive"],0)
        self.assertEqual(build(self.annual,self.cover,self.events,self.out),rpt)
        with (self.out/"official_y1_adjudication_private.csv").open(encoding="utf-8-sig") as f:
            rows={x["ticker"]:x for x in csv.DictReader(f)}
        self.assertEqual(rows["1203"]["y_official_annual_24m"],"1")
        self.assertEqual(rows["2317"]["y_official_annual_24m"],"0")
        self.assertEqual(rows["2330"]["y_official_annual_24m"],"")
        self.assertNotIn("1785",rows)
        (self.out/"official_y1_adjudication_private.csv").write_text("tampered")
        with self.assertRaisesRegex(FileExistsError,"immutable_phase2_output"):
            build(self.annual,self.cover,self.events,self.out)

    def test_unresolved_core_event_must_block_negative(self):
        self.e[0]["core_delta_verified"]="false"
        self.c.append(coverage("1203"))
        self.save()
        rpt=build(self.annual,self.cover,self.events,self.out)
        self.assertEqual(rpt["reviewer_attested_positive"],0)
        self.assertEqual(rpt["reviewer_attested_negative"],1)
        self.assertEqual(rpt["unknown"],2)
        self.assertEqual(rpt["blocker_counts"]["UNRESOLVED_OFFICIAL_EVENT_CANDIDATE"],1)

    def test_missing_coverage_never_y0(self):
        self.c=[]
        self.e=[]
        self.save()
        rpt=build(self.annual,self.cover,self.events,self.out)
        self.assertEqual(rpt["reviewer_attested_negative"],0)
        self.assertEqual(rpt["unknown"],3)

if __name__=="__main__":
    unittest.main()
