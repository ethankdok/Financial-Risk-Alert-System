"""Source-safe hermetic official Y1 verification: all source rows are synthetic."""
import csv
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.round2_phase1_official_source_audit import build


def _write(path, names, records):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        writer.writerows(records)


class PhaseOneOfficialAuditTests(unittest.TestCase):
    def test_no_fabricated_y_and_strict_case_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cases = base / "sprint.csv"
            finlab = base / "finlab.csv"
            out = base / "review"
            title = "董事會通過更正106年度個體財務報告及重編106年度合併財務報告"
            sample = [
                {"case_id": "1203-FY2017", "ticker": "1203",
                 "issuer_name": "SYNTHETIC", "fiscal_year": "2017",
                 "candidate_type": "POSITIVE_EVENT_REVIEW", "rank": "P0",
                 "notice_title": title, "training_y": ""},
                {"case_id": "1204-FY2017", "ticker": "1204",
                 "issuer_name": "SYNTHETIC", "fiscal_year": "2017",
                 "candidate_type": "UNLABELED_CONTROL_REVIEW", "rank": "CONTROL",
                 "notice_title": "", "training_y": ""},
                {"case_id": "2443-FY2019", "ticker": "2443",
                 "issuer_name": "SYNTHETIC", "fiscal_year": "2019",
                 "candidate_type": "POSITIVE_EVENT_REVIEW", "rank": "P0",
                 "notice_title": "本公司108年度合併財報重編", "training_y": ""},
            ]
            _write(cases, sample[0].keys(), sample)
            rec = [
                {"stock_id": "1203", "title": title, "date": "2018-05-11 15:00:00",
                 "info": ("重編106年度合併財務報告:重編前資產9,079,372重編後9,192,281"
                          "重編前本期淨利633,605重編後746,401"
                          "原營業成本4,287,711更正4,174,915"),
                 "source_market": "TSE", "source_clause": "10",
                 "source_sequence": "9"},
                {"stock_id": "2443", "title": "本公司108年度合併財報重編",
                 "date": "2023-09-10 13:15:00", "info": "重編已完成",
                 "source_market": "OTC", "source_clause": "3",
                 "source_sequence": "2"},
            ]
            _write(finlab, rec[0].keys(), rec)
            report = build(cases, finlab, out)
            self.assertEqual(report["case_count"], 3)
            self.assertEqual(report["matched_exact_company_and_title_positive_notice_count"], 2)
            self.assertEqual(report["approved_y_1"], 0)
            self.assertEqual(report["approved_y_0"], 0)
            self.assertEqual(report["y_unknown"], 3)
            self.assertEqual(report["issuer_core_amounts_independently_arithmetically_crosschecked"], 1)
            self.assertEqual(report["notice_timing_flags"]
                ["NOTICE_AFTER_ORDINARY_FY_FILING_LIMIT_PLUS_24M_CHECK_EXCEPTION"], 1)
            self.assertEqual(build(cases, finlab, out), report)
            with (out / "phase1_145_case_evidence_ledger_private.csv").open(
                    encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertTrue(all(not x["label"] for x in rows))
            self.assertTrue(all(x["audit_status"] == "UNKNOWN_PENDING_MOPS_VERSIONED_EVIDENCE" for x in rows))
            self.assertTrue(all(x["verified_original_MOPS_first_public_at"] == "" for x in rows))
            (out / "phase1_145_case_evidence_ledger_private.csv").write_text("tampered")
            with self.assertRaisesRegex(FileExistsError, "phase1_refuse_overwrite"):
                build(cases, finlab, out)

    def test_refuses_preapproved_label_and_wrong_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            cases=base/"sprint.csv"
            finlab=base/"source.csv"
            vals={"case_id":"1203-FY2017","ticker":"1203","issuer_name":"SYNTH",
                "fiscal_year":"2017","candidate_type":"POSITIVE_EVENT_REVIEW",
                "rank":"P0","notice_title":"TEST","training_y":"1"}
            _write(cases,vals.keys(),[vals])
            _write(finlab,["stock_id","title","date","info",
                "source_market","source_clause","source_sequence"],[{
                "stock_id":"1203","title":"TEST","date":"2018-05-01",
                "info":"sample","source_market":"TSE","source_clause":"1",
                "source_sequence":"1",
            }])
            with self.assertRaisesRegex(ValueError,"cannot_overwrite_existing_official_outcome"):
                build(cases, finlab, base/"out")


if __name__ == "__main__":
    unittest.main()
