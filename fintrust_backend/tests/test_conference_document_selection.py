"""Latest / targeted archive document selection with current conference identity.

The 2303 and 2408 cases mirror the production archive manifests (identity
versions v2 / v1): stored document types that the current identity rules no
longer produce. Only safe metadata and the cover lines that decide identity
are reproduced here; no PDF body text.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.conference_document_digest import (
    ConferenceDocumentDigestService,
    explain_archive_selection,
    select_archive_document,
)
from app.services.conference_document_identity import IDENTITY_VERSION
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from tests.test_conference_document_digest import FIXTURE_ROOT, Q3_FILE, archive_document, write_archive


def stale(filename: str, period: str, stored_type: str, version: str, language: str, dates: list[str],
          summaries: list[str]) -> dict:
    document = archive_document(filename, period, language=language, document_type=stored_type, dates=dates,
                                identity_version=version)
    document["language"] = "zh" if language == "zh-Hant" else "en"
    document["listing_summaries"] = summaries
    return document


def cover(*lines: str) -> list[dict]:
    return [{"page": 1, "text": "\n".join(lines), "text_extraction_method": "selectable_text"}]


UMC_Q2 = ["本公司2025年第二季財務暨營運報告。", "本公司受邀參加瑞銀證券舉辦之法人說明會「Taiwan Summit 2025」。"]
UMC_Q3 = ["本公司2025年第三季財務暨營運報告。", "本公司受邀參加花旗證券舉辦之法人說明會「2025 Taiwan Corporate Day」。"]


def write_2303(root: Path) -> None:
    documents = [
        stale("230320250730E001.pdf", "2025Q2", "analyst_conference_presentation", "conference-identity-v2", "en", ["114/07/30"], UMC_Q2),
        stale("230320250730M001.pdf", "2025Q2", "analyst_conference_presentation", "conference-identity-v2", "zh-Hant", ["114/07/30"], UMC_Q2),
        stale("230320251029E001.pdf", "2025Q3", "other_official_conference_document", "conference-identity-v2", "en", ["114/10/29"], UMC_Q3),
        stale("230320251029M001.pdf", "2025Q3", "other_official_conference_document", "conference-identity-v2", "zh-Hant", ["114/10/29"], UMC_Q3),
    ]
    write_archive(root, "2303", 2025, documents, pages={
        "230320250730E001.pdf": cover("UMC", "2Q25 Financial Review", "July 30, 2025"),
        "230320250730M001.pdf": cover("聯華電子", "114年第二季財務報告", "114年7月30日"),
        "230320251029E001.pdf": cover("UMC", "3Q25 Financial Review", "October 29, 2025"),
        "230320251029M001.pdf": cover("聯華電子", "114年第三季財務報告", "114年10月29日"),
    })


def write_2408(root: Path) -> None:
    documents = [
        stale("240820250710E001.pdf", "2025Q2", "investor_presentation", "conference-identity-v1", "en", ["114/07/10"], ["2025年第2季營運狀況說明"]),
        stale("240820250710M001.pdf", "2025Q2", "other_official_conference_document", "conference-identity-v1", "zh-Hant", ["114/07/10"], ["2025年第2季營運狀況說明"]),
        stale("240820251013E001.pdf", "2025Q3", "investor_presentation", "conference-identity-v1", "en", ["114/10/13"], ["2025年第3季營運狀況說明"]),
        stale("240820251013M001.pdf", "2025Q3", "other_official_conference_document", "conference-identity-v1", "zh-Hant", ["114/10/13"], ["2025年第3季營運狀況說明"]),
    ]
    write_archive(root, "2408", 2025, documents, pages={
        "240820250710E001.pdf": cover("Q2 2025 Investor Conference", "Nanya Technology", "Jul 10, 2025"),
        "240820250710M001.pdf": cover("2025年第2季財務報告摘要", "Nanya Technology", "Jul 10, 2025"),
        "240820251013E001.pdf": cover("Q3 2025 Investor Conference", "Nanya Technology", "Oct 13, 2025"),
        "240820251013M001.pdf": cover("2025年第3季財務報告摘要", "Nanya Technology", "Oct 13, 2025"),
    })


class ProductionIdentityCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        write_2303(self.root)
        write_2408(self.root)
        self.repo = FileConferencePdfArchiveRepository(self.root)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_2303_quarterly_financial_report_is_an_earnings_presentation(self) -> None:
        explained = explain_archive_selection(self.repo, "2303")
        for candidate in explained["candidates"]:
            self.assertEqual(candidate["identity"]["document_type"], "earnings_presentation", candidate["document"]["filename"])
            self.assertTrue(candidate["identity"]["identity_recomputed"])

    def test_2303_latest_is_2025q3_not_the_older_quarter(self) -> None:
        _year, _manifest, document = select_archive_document(self.repo, "2303")
        self.assertEqual(document["filename"], "230320251029M001.pdf")
        self.assertEqual((document["period"], document["document_type"], document["document_language"]),
                         ("2025Q3", "earnings_presentation", "zh-Hant"))
        self.assertEqual(document["stored_document_type"], "other_official_conference_document")
        self.assertEqual(document["stored_identity_version"], "conference-identity-v2")
        self.assertEqual(document["identity_version"], IDENTITY_VERSION)

    def test_2408_same_period_prefers_chinese_deck_once_both_are_results_decks(self) -> None:
        for target in (None, "2025Q3"):
            _year, _manifest, document = select_archive_document(self.repo, "2408", period=target)
            self.assertEqual(document["filename"], "240820251013M001.pdf", target)
            self.assertEqual((document["period"], document["document_type"]), ("2025Q3", "earnings_presentation"))
        reasons = {item["document"]["filename"]: item["reason"] for item in explain_archive_selection(self.repo, "2408")["candidates"]}
        self.assertEqual(reasons["240820251013M001.pdf"], "selected")
        self.assertEqual(reasons["240820251013E001.pdf"], "eligible")

    def test_explicit_period_still_selects_that_period(self) -> None:
        _year, _manifest, document = select_archive_document(self.repo, "2303", period="2025Q2")
        self.assertEqual(document["filename"], "230320250730M001.pdf")

    def test_digest_uses_current_identity_and_keeps_stored_identity_as_provenance(self) -> None:
        digest, status = ConferenceDocumentDigestService(self.repo).digest_for("2303")
        self.assertEqual(status, "available")
        self.assertEqual((digest["period"], digest["document_type"]), ("2025Q3", "earnings_presentation"))
        self.assertEqual(digest["source"]["identity"]["stored_document_type"], "other_official_conference_document")
        self.assertTrue(digest["source"]["identity"]["recomputed_from_archive"])
        self.assertTrue(all(ref["filename"] == "230320251029M001.pdf"
                            for section in digest["sections"] for bullet in section["bullets"] for ref in bullet["evidence_refs"]))

    def test_2454_normal_case_does_not_regress(self) -> None:
        for target in (None, "2025Q3"):
            _year, _manifest, document = select_archive_document(FileConferencePdfArchiveRepository(FIXTURE_ROOT), "2454", period=target)
            self.assertEqual((document["filename"], document["period"], document["document_type"]),
                             (Q3_FILE, "2025Q3", "earnings_presentation"))


class LatestSelectionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.repo = FileConferencePdfArchiveRepository(self.root)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def latest(self, ticker: str = "1111", **kwargs) -> str | None:
        selected = select_archive_document(self.repo, ticker, **kwargs)
        return selected[2]["filename"] if selected else None

    def test_type_preference_never_pulls_latest_back_a_quarter(self) -> None:
        write_archive(self.root, "1111", 2025, [
            archive_document("q2-presentation.pdf", "2025Q2", dates=["114/07/30"]),
            archive_document("q3-release.pdf", "2025Q3", document_type="financial_results_release", dates=["114/10/30"]),
        ])
        self.assertEqual(self.latest(), "q3-release.pdf")

    def test_newer_marketing_deck_does_not_replace_latest_results_deck(self) -> None:
        write_archive(self.root, "1111", 2025, [
            archive_document("q2-results.pdf", "2025Q2", dates=["114/07/30"]),
            archive_document("q3-roadshow.pdf", "2025Q3", document_type="analyst_conference_presentation", dates=["114/11/20"]),
            archive_document("q3-overview.pdf", "2025Q3", document_type="investor_presentation", dates=["114/11/21"]),
        ])
        self.assertEqual(self.latest(), "q2-results.pdf")

    def test_without_results_documents_the_newest_other_document_is_used(self) -> None:
        write_archive(self.root, "1111", 2025, [
            archive_document("q2-overview.pdf", "2025Q2", document_type="investor_presentation", dates=["114/07/30"]),
            archive_document("q3-other.pdf", "2025Q3", document_type="other_official_conference_document", dates=["114/10/30"]),
        ])
        self.assertEqual(self.latest(), "q3-other.pdf")

    def test_same_latest_period_orders_by_type_then_language(self) -> None:
        write_archive(self.root, "1111", 2025, [
            archive_document("q3-deck-en.pdf", "2025Q3", language="en", dates=["114/10/30"]),
            archive_document("q3-deck-zh.pdf", "2025Q3", language="zh-Hant", dates=["114/10/30"]),
            archive_document("q2-transcript.pdf", "2025Q2", document_type="full_earnings_transcript", dates=["114/07/30"]),
        ])
        self.assertEqual(self.latest(), "q3-deck-zh.pdf")
        write_archive(self.root, "1111", 2026, [
            archive_document("q4-deck-zh.pdf", "2025Q4", language="zh-Hant", dates=["115/02/05"]),
            archive_document("q4-transcript-en.pdf", "2025Q4", document_type="full_earnings_transcript", language="en", dates=["115/02/05"]),
        ])
        self.assertEqual(self.latest(), "q4-transcript-en.pdf")

    def test_explicit_period_is_exact_even_when_newer_documents_exist(self) -> None:
        write_archive(self.root, "1111", 2025, [archive_document("q3.pdf", "2025Q3", dates=["114/10/30"])])
        write_archive(self.root, "1111", 2026, [archive_document("q4.pdf", "2025Q4", dates=["115/02/05"])])
        self.assertEqual(self.latest(period="2025Q3"), "q3.pdf")
        self.assertEqual(self.latest(), "q4.pdf")

    def test_never_crosses_tickers(self) -> None:
        write_archive(self.root, "1111", 2025, [archive_document("1111-q2.pdf", "2025Q2", dates=["114/07/30"])])
        write_archive(self.root, "2222", 2025, [archive_document("2222-q3.pdf", "2025Q3", dates=["114/10/30"])])
        self.assertEqual(self.latest("1111"), "1111-q2.pdf")
        self.assertEqual(self.latest("1111", period="2025Q3"), None)
        explained = explain_archive_selection(self.repo, "1111")
        self.assertEqual({item["document"]["filename"] for item in explained["candidates"]}, {"1111-q2.pdf"})

    def test_quarantined_duplicate_and_unverified_documents_are_never_selected(self) -> None:
        quarantined = archive_document("q4-quarantined.pdf", "2025Q4", dates=["115/02/05"])
        quarantined["quarantined"] = True
        duplicate_source = archive_document("q3-original.pdf", "2025Q3", dates=["114/10/30"], sha256="b" * 64)
        duplicate = archive_document("q3-copy.pdf", "2025Q3", language="en", dates=["114/10/30"], sha256="b" * 64)
        unverified = archive_document("q4-unverified.pdf", "2025Q4", verified=False, dates=["115/02/05"])
        write_archive(self.root, "1111", 2025, [duplicate_source, duplicate, quarantined, unverified])
        explained = explain_archive_selection(self.repo, "1111")
        reasons = {item["document"]["filename"]: item["reason"] for item in explained["candidates"]}
        self.assertEqual(reasons["q4-quarantined.pdf"], "rejected:quarantined")
        self.assertEqual(reasons["q3-copy.pdf"], "rejected:duplicate_document")
        self.assertEqual(reasons["q4-unverified.pdf"], "rejected:period_unverified")
        self.assertEqual(reasons["q3-original.pdf"], "selected")

    def test_conflicting_documents_for_one_slot_are_quarantined(self) -> None:
        write_archive(self.root, "1111", 2025, [
            archive_document("q3-a.pdf", "2025Q3", dates=["114/10/30"]),
            archive_document("q3-b.pdf", "2025Q3", dates=["114/10/30"]),
            archive_document("q2.pdf", "2025Q2", dates=["114/07/30"]),
        ])
        self.assertEqual(self.latest(), "q2.pdf")


if __name__ == "__main__":
    unittest.main()
