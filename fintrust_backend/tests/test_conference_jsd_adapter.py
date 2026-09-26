from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.services.conference_document_identity import (
    assess_document_identity,
    claimed_period_from_listing,
    normalize_fiscal_period,
    reconcile_documents,
)
from app.services.conference_jsd_corpus_adapter import (
    CORPUS_FIELDS,
    build_records,
    company_identity,
    comparable_pairs,
    export_corpus,
    to_corpus_rows,
)
from app.services.conference_pdf_archive_storage import GcsConferencePdfArchiveRepository, _TtlCache, publish_archive
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from tests.test_conference_pdf_archive_storage import FakeClient

BODY = " ".join(["Revenue grew on strong demand for advanced technologies."] * 30)


def deck(cover: str, body: str = BODY) -> list[dict]:
    return [{"page": 1, "text": cover}, {"page": 2, "text": "Agenda\n2\n" + body},
            {"page": 3, "text": "3\n" + body}]


def write_archive(root: Path, ticker: str, year: int, documents: list[dict], *, listing_url: str | None = "default"):
    directory = root / ticker / str(year)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_docs = []
    for spec in documents:
        stem = spec["filename"].removesuffix(".pdf")
        pdf = spec.get("pdf", f"%PDF-1.7 {spec['filename']}".encode())
        (directory / spec["filename"]).write_bytes(pdf)
        (directory / f"{stem}.pages.json").write_text(json.dumps(spec["pages"], ensure_ascii=False), encoding="utf-8")
        entry = {"filename": spec["filename"], "language": spec.get("language", "en"),
                 "sha256": hashlib.sha256(pdf).hexdigest(), "company_name": spec.get("company_name", ""),
                 "listing_summaries": spec.get("summaries", []), "conference_dates": ["114/10/16"],
                 "download_fields": {"step": "9", "filePath": "/home/html/nas/STR/", "fileName": spec["filename"],
                                     "functionName": "t100sb02_1"},
                 "pages_path": f"{stem}.pages.json"}
        manifest_docs.append(entry)
    manifest = {"ticker": ticker, "year": year, "retrieved_at": "2026-09-27T00:00:00+00:00", "documents": manifest_docs}
    if listing_url == "default":
        manifest["listing_url"] = f"https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1?co_id={ticker}&year={year - 1911}"
    elif listing_url:
        manifest["listing_url"] = listing_url
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return directory


class IdentityTests(unittest.TestCase):
    # A
    def test_company_identity_uses_listing_name_and_project_taxonomy(self) -> None:
        self.assertEqual(company_identity("2379", "瑞昱"), ("瑞昱", "semiconductor_fabless"))
        self.assertEqual(company_identity("2408", "南亞科")[1], "semiconductor_memory")
        self.assertEqual(company_identity("2330", None), ("台積電", "semiconductor_foundry"))
        self.assertEqual(company_identity("9999", None), ("9999", "semiconductor_unclassified"))

    # B
    def test_fiscal_period_normalization(self) -> None:
        for text in ("3Q25", "Q3 2025", "2025 Q3", "2025Q3", "2025 Third Quarter", "Third Quarter of 2025",
                     "2025年第三季", "2025 年第 3 季", "114年第3季", "一一四年第三季"):
            self.assertEqual(normalize_fiscal_period(text), "2025Q3", text)
        self.assertIsNone(normalize_fiscal_period("January 16, 2025"))
        self.assertIsNone(normalize_fiscal_period("112年下半年度"))
        self.assertEqual(claimed_period_from_listing(["公布本公司2024年第4季財務報告及2025年第1季業績展望"])[0], "2024Q4")
        self.assertIsNone(claimed_period_from_listing(["本公司受邀參加J.P. Morgan Conference"])[0])

    # C
    def test_source_period_disagreeing_with_document_is_quarantined(self) -> None:
        pages = deck("MediaTek 3Q24 Earnings Call")
        by_url = assess_document_identity(pages, language="en",
                                          source_pdf_url="https://example.com/ir/2023Q3/Transcript.pdf")
        self.assertEqual((by_url["period_validation_status"], by_url["quarantined"], by_url["period"]),
                         ("mismatch", True, None))
        self.assertEqual(by_url["period_detected_in_document"], "2024Q3")
        self.assertEqual(by_url["period_claimed_by_source"], {"source_url": "2023Q3"})
        by_listing = assess_document_identity(pages, language="en", summaries=["公布本公司2023年第3季財務報告"])
        self.assertTrue(by_listing["quarantined"])
        agreeing = assess_document_identity(pages, language="en", summaries=["公布本公司2024年第3季財務報告"])
        self.assertEqual((agreeing["period"], agreeing["period_validation_confidence"]), ("2024Q3", 0.95))
        undated = assess_document_identity(deck("Company Overview\nJanuary 2025"), language="en")
        self.assertEqual((undated["period_validation_status"], undated["period"]), ("unconfirmed", None))

    # D / E
    def test_duplicate_sha256_handling(self) -> None:
        conflict = [{"filename": "a.pdf", "sha256": "x", "period_detected_in_document": "2023Q3", "period": "2023Q3"},
                    {"filename": "b.pdf", "sha256": "x", "period_detected_in_document": "2024Q3", "period": "2024Q3"}]
        reconcile_documents(conflict)
        self.assertTrue(all(doc["quarantined"] for doc in conflict))
        self.assertIn("sha256_reused_across_periods", conflict[0]["quarantine_reasons"])
        same = [{"filename": "a.pdf", "sha256": "y", "period_detected_in_document": "2025Q3", "period": "2025Q3"},
                {"filename": "b.pdf", "sha256": "y", "period_detected_in_document": "2025Q3", "period": "2025Q3"}]
        reconcile_documents(same)
        self.assertEqual((same[0].get("duplicate_of"), same[1].get("duplicate_of")), (None, "a.pdf"))
        self.assertFalse(any(doc.get("quarantined") for doc in same))

    # F / G / H
    def test_document_type_classification(self) -> None:
        transcript = assess_document_identity(deck("MediaTek 3Q24 Earnings Call Transcript"), language="en")
        self.assertEqual(transcript["document_type"], "full_earnings_transcript")
        presentation = assess_document_identity(deck("2025 Third Quarter Earnings Conference\nOctober 16, 2025"),
                                                language="en")
        self.assertEqual(presentation["document_type"], "earnings_presentation")
        self.assertIn("Earnings Conference", presentation["document_type_evidence"])
        self.assertTrue(presentation["document_type_method"].startswith("deterministic_rules_v1"))
        empty = assess_document_identity([{"page": 1, "text": ""}], language="en")
        self.assertEqual(empty["document_type"], "unknown")
        analyst = assess_document_identity(deck("Company Update"), language="en",
                                           summaries=["本公司受邀參加摩根大通證券舉辦之 Taiwan CEO-CFO Conference"])
        self.assertEqual(analyst["document_type"], "analyst_conference_presentation")

    def test_real_world_results_wording_and_text_artifacts(self) -> None:
        for cover in ("UMC 4Q24 Financial Review January 21, 2025", "聯華電子 113年第四季財務報告",
                      "Q4 2024 Investor Conference Nanya Technology", "2024 年第 4 季財務報告摘要",
                      "2025年第一季法說會", "2025年第㇐季法人說明會"):
            identity = assess_document_identity(deck(cover), language="en")
            self.assertEqual(identity["document_type"], "earnings_presentation", cover)
            self.assertEqual(identity["period_validation_status"], "verified", cover)
        call = deck("MediaTek 3Q24 Earnings Call Wednesday, October 30, 2024 PREPARED REMARKS",
                    "we will open for Q&A. " + " ".join(f"Question: item {i}? Answer." for i in range(4)))
        self.assertEqual(assess_document_identity(call, language="en")["document_type"], "full_earnings_transcript")
        release = assess_document_identity(deck("NOVATEK FOR IMMEDIATE RELEASE fourth quarter 2024 results"), language="en")
        self.assertEqual(release["document_type"], "financial_results_release")
        half_year = assess_document_identity(deck("2H24 Investor Conference Feb. 19th, 2025"), language="en")
        self.assertEqual((half_year["period"], half_year["document_type"]), (None, "investor_presentation"))
        qualified = assess_document_identity(
            deck("2025年第一季法人說明會資訊 (1) 說明2025年第一季損益表 (2) 2025年第二季營運展望"), language="zh")
        self.assertEqual(qualified["period"], "2025Q1")

    # I
    def test_language_metadata(self) -> None:
        self.assertEqual(assess_document_identity(deck("2025 Third Quarter Earnings Conference"), language="en")["language"], "en")
        self.assertEqual(assess_document_identity(deck("2025年第三季法人說明會", "營運成果與業績展望說明" * 60), language="zh")["language"], "zh-Hant")
        bilingual = assess_document_identity(deck("2025 Third Quarter 法人說明會", "營運成果 revenue " * 80), language="en")
        self.assertEqual(bilingual["language"], "bilingual")


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def presentations(self, ticker: str = "2330", quarters=((2025, 1), (2025, 2), (2025, 4))) -> None:
        words = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}
        write_archive(self.root, ticker, 2025, [
            {"filename": f"{ticker}2025{q:02d}01E001.pdf",
             "pages": deck(f"{y} {words[q]} Quarter Earnings Conference"), "company_name": "台積電",
             "summaries": [f"公布本公司{y}年第{q}季財務報告"]}
            for y, q in quarters])

    def records(self):
        return build_records(FileConferencePdfArchiveRepository(self.root), "2330")

    # J / Q
    def test_record_matches_teammate_contract_and_keeps_sha(self) -> None:
        self.presentations()
        records = self.records()
        self.assertEqual(len(records), 3)
        for item in records:
            self.assertEqual(list(item.record), CORPUS_FIELDS)
            self.assertTrue(item.jsd_ready, item.readiness_issues)
            self.assertRegex(item.record["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(item.record["source_pdf"].startswith("https://mopsov.twse.com.tw/server-java/FileDownLoad?"))
            self.assertEqual(item.record["text_length"], len(item.record["text"]))
            self.assertEqual(item.provenance["period_validation_status"], "verified")
        manifest = json.loads((self.root / "2330" / "2025" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual({r.record["sha256"] for r in records}, {d["sha256"] for d in manifest["documents"]})
        self.assertEqual(list(to_corpus_rows(records)[0]), CORPUS_FIELDS)

    # K / L
    def test_missing_source_and_text_are_not_ready_but_recorded(self) -> None:
        write_archive(self.root, "2330", 2025, [
            {"filename": "233020250116E001.pdf", "pages": deck("2024 Fourth Quarter Earnings Conference")}],
            listing_url=None)
        write_archive(self.root, "2330", 2024, [
            {"filename": "233020240118E001.pdf", "pages": [{"page": 1, "text": "2023 Fourth Quarter Earnings Conference"}]},
            {"filename": "233020240418E001.pdf", "pages": [{"page": 1, "text": ""}]}])
        by_file = {r.provenance["filename"]: r for r in self.records()}
        self.assertIn("missing_official_source_page", by_file["233020250116E001.pdf"].readiness_issues)
        short = by_file["233020240118E001.pdf"]
        self.assertTrue(short.jsd_ready)
        self.assertLess(short.record["text_length"], 100)
        empty = by_file["233020240418E001.pdf"]
        self.assertFalse(empty.jsd_ready)
        self.assertIn("empty_text", empty.readiness_issues)

    # M / N
    def test_pairs_require_adjacent_same_type_same_language(self) -> None:
        self.presentations(quarters=((2025, 1), (2025, 2), (2025, 4)))
        pairs = comparable_pairs(self.records())
        self.assertEqual([(p["period_1"], p["period_2"]) for p in pairs], [("2025Q1", "2025Q2")])
        self.assertFalse(pairs[0]["transcript_calibration_compatible"])
        write_archive(self.root, "2454", 2025, [
            {"filename": "245420250201E001.pdf", "pages": deck("MediaTek 4Q24 Earnings Call Transcript")},
            {"filename": "245420250501E001.pdf", "pages": deck("MediaTek 1Q25 Earnings Call Transcript")},
            {"filename": "245420250502E001.pdf", "pages": deck("2025 Second Quarter Earnings Conference")},
            {"filename": "245420250503M001.pdf", "language": "zh", "pages": deck("2025年第一季法人說明會", "營運成果" * 400)}])
        records = build_records(FileConferencePdfArchiveRepository(self.root), "2454")
        pairs = comparable_pairs(records)
        self.assertEqual([(p["document_type"], p["period_1"], p["period_2"]) for p in pairs],
                         [("full_earnings_transcript", "2024Q4", "2025Q1")])
        self.assertTrue(pairs[0]["transcript_calibration_compatible"])

    # O
    def test_export_corpus_contract(self) -> None:
        self.presentations()
        paths = export_corpus(self.records(), self.root / "export")
        with open(paths["csv"], encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            self.assertEqual(reader.fieldnames, CORPUS_FIELDS)
            self.assertEqual(len(list(reader)), 3)
        with open(paths["index"], encoding="utf-8-sig", newline="") as file:
            header = next(csv.reader(file))
            self.assertNotIn("text", header)
        import pandas as pd

        frame = pd.read_parquet(paths["parquet"])
        self.assertEqual(list(frame.columns), CORPUS_FIELDS)

    # P
    def test_text_is_original_page_text_only(self) -> None:
        pages = deck("2025 First Quarter Earnings Conference")
        pages[1]["semantic_evidence"] = [{"summary": "GEMINI NARRATIVE: margins look risky", "evidence_type": "chart"}]
        pages[1]["analysis_results"] = [{"kind": "numeric_text", "source_excerpt": "ANALYSIS LABEL"}]
        write_archive(self.root, "2330", 2025, [{"filename": "233020250417E001.pdf", "pages": pages}])
        text = self.records()[0].record["text"]
        self.assertNotIn("GEMINI NARRATIVE", text)
        self.assertNotIn("ANALYSIS LABEL", text)
        self.assertTrue(text.startswith("2025 First Quarter Earnings Conference"))
        self.assertNotIn("\n2\n", f"\n{text}\n")  # bare page-number lines removed

    # R
    def test_local_and_gcs_archives_produce_same_records(self) -> None:
        self.presentations()
        client = FakeClient()
        publish_archive(client=client, bucket="b", prefix="conference-pdf-archive", ticker="2330", year=2025,
                        directory=self.root / "2330" / "2025", execute=True)
        gcs = GcsConferencePdfArchiveRepository("b", client=client, cache=_TtlCache(0))
        local_records, gcs_records = self.records(), build_records(gcs, "2330")
        self.assertEqual([r.record for r in local_records], [r.record for r in gcs_records])
        self.assertEqual({r.provenance["archive_backend"] for r in gcs_records}, {"gcs"})


class EncryptedPdfTests(unittest.TestCase):
    @staticmethod
    def pdf(user_password: str) -> bytes:
        import io

        from pypdf import PdfWriter

        from app.services.mops_conference_pdf_semantics import load_pymupdf

        fitz = load_pymupdf()
        source = fitz.open()
        source.new_page().insert_text((72, 72), "2025 Third Quarter Earnings Conference " * 3)
        writer = PdfWriter(clone_from=io.BytesIO(source.tobytes()))
        writer.encrypt(user_password=user_password, owner_password="owner-secret", algorithm="AES-128")
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    def test_owner_password_only_pdf_is_read_and_user_password_pdf_is_refused(self) -> None:
        from app.services.mops_conference_pdf_pipeline import AcquisitionError, extract_pages, pdf_encryption

        restricted = self.pdf("")
        self.assertEqual(pdf_encryption(restricted), "empty_user_password")
        pages, _problems = extract_pages(restricted, filename="restricted.pdf")
        self.assertIn("Third Quarter", pages[0]["text"])
        locked = self.pdf("user-secret")
        self.assertEqual(pdf_encryption(locked), "password_protected")
        with self.assertRaisesRegex(AcquisitionError, "password protected"):
            extract_pages(locked, filename="locked.pdf")


if __name__ == "__main__":
    unittest.main()
