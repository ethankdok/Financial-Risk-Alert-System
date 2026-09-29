from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from app.services.conference_document_digest import (
    ConferenceDigestNarrator,
    ConferenceDocumentDigestService,
    build_document_digest,
    explain_archive_selection,
    select_archive_document,
)
from app.services.conference_document_identity import IDENTITY_VERSION
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "conference_digest_2454"
FIXTURE_DIR = FIXTURE_ROOT / "2454" / "2025"
Q3_FILE = "245420251031M001.pdf"
Q2_FILE = "245420250730M001.pdf"
Q3_SHA = "23bb35fa060a626dc89b51892a49f250a73806b36aa018f23ae6ce73505258b6"
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def load(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def manifest_document(filename: str) -> dict:
    manifest = load("manifest.json")
    return next(item for item in manifest["documents"] if item["filename"] == filename)


def q3_digest(**overrides) -> dict:
    stem = Q3_FILE[:-4]
    arguments = {
        "pages": load(f"{stem}.pages.json"),
        "semantic": load(f"{stem}.semantic.json"),
        "analysis": None,
    }
    arguments.update(overrides)
    return build_document_digest("2454", manifest_document(Q3_FILE), arguments["pages"], arguments["semantic"],
                                 arguments["analysis"], listing_url="https://mopsov.twse.com.tw/listing")


def all_bullets(digest: dict) -> list[dict]:
    return [bullet for section in digest["sections"] for bullet in section["bullets"]]


def section(digest: dict, name: str) -> list[dict]:
    return next((item["bullets"] for item in digest["sections"] if item["section_type"] == name), [])


def write_archive(root: Path, ticker: str, year: int, documents: list[dict], pages: dict[str, list] | None = None,
                  semantic: dict[str, list] | None = None) -> None:
    folder = root / ticker / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    for document in documents:
        stem = document["filename"][:-4]
        document.setdefault("pages_path", f"{stem}.pages.json")
        (folder / f"{stem}.pages.json").write_text(json.dumps((pages or {}).get(document["filename"], [])), encoding="utf-8")
        if semantic is not None:
            document.setdefault("semantic_path", f"{stem}.semantic.json")
            (folder / f"{stem}.semantic.json").write_text(json.dumps(semantic.get(document["filename"], [])), encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps({"listing_url": "https://mopsov.twse.com.tw/listing", "documents": documents}), encoding="utf-8")


def archive_document(filename: str, period: str, *, language: str = "zh-Hant", verified: bool = True,
                     document_type: str = "earnings_presentation", dates: list[str] | None = None,
                     sha256: str | None = None, identity_version: str | None = IDENTITY_VERSION) -> dict:
    """A manifest entry whose stored identity is current (trusted as stored) unless
    identity_version says it was written by an older identity version."""
    return {
        "filename": filename, "sha256": sha256 or (filename.encode().hex() * 8)[:64], "company_name": "測試公司",
        "page_count": 1, "period": period,
        "period_validation_status": "verified" if verified else "unverified", "document_type": document_type,
        "document_language": language, "quarantined": False, "duplicate_of": None,
        "conference_dates": dates or ["114/01/01"], "identity_version": identity_version,
    }


def current_identity_fixture(root: Path) -> Path:
    """Copy of the 2454 fixture whose manifest identity is already current."""
    target = root / "2454" / "2025"
    target.mkdir(parents=True)
    for item in FIXTURE_DIR.iterdir():
        target.joinpath(item.name).write_bytes(item.read_bytes())
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    for document in manifest["documents"]:
        document["identity_version"] = IDENTITY_VERSION
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root


class CountingRepository(FileConferencePdfArchiveRepository):
    def __init__(self, root) -> None:
        super().__init__(root)
        self.calls: list[tuple[str, str]] = []

    def pages(self, ticker, year, filename):
        self.calls.append(("pages", filename))
        return super().pages(ticker, year, filename)

    def semantic(self, ticker, year, filename):
        self.calls.append(("semantic", filename))
        return super().semantic(ticker, year, filename)

    def analysis(self, ticker, year, filename):
        self.calls.append(("analysis", filename))
        return super().analysis(ticker, year, filename)


class FakeProvider:
    configured = True

    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = 0

    async def generate_structured(self, contents, *, system_instruction, schema, max_output_tokens):
        self.calls += 1
        payload = self.payload(json.loads(contents)) if callable(self.payload) else self.payload
        return payload, "fake-model"


class DigestContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.digest = q3_digest()

    def test_identity_comes_from_the_selected_mops_document(self) -> None:
        digest = self.digest
        self.assertEqual(digest["source"]["filename"], Q3_FILE)
        self.assertEqual(digest["source"]["sha256"], Q3_SHA)
        self.assertEqual(digest["period"], "2025Q3")
        self.assertEqual(digest["conference_date"], "2025-10-31")
        self.assertIn("2025年第三季法人說明會", digest["document_title"].replace(" ", ""))

    def test_overview_has_four_to_six_sentences_with_refs(self) -> None:
        self.assertTrue(4 <= len(self.digest["overview"]) <= 6)
        for sentence in self.digest["overview"]:
            self.assertTrue(sentence["evidence_refs"], sentence["text"])

    def test_same_metric_across_pages_is_merged_but_basis_is_kept_apart(self) -> None:
        operating = [bullet for bullet in all_bullets(self.digest) if bullet.get("metric_id") == "operating_income"]
        tifrs = [bullet for bullet in operating if bullet["basis"] == "TIFRS"]
        non_tifrs = [bullet for bullet in operating if bullet["basis"] == "Non-TIFRS"]
        self.assertEqual(len(tifrs), 1)
        self.assertEqual(len(non_tifrs), 1)
        self.assertTrue({13, 18} <= set(tifrs[0]["pages"]))
        self.assertIn("22,188", tifrs[0]["text"])
        self.assertIn("22,843", non_tifrs[0]["text"])
        self.assertNotIn("22,843", tifrs[0]["text"])

    def test_chart_and_table_for_the_same_metric_merge_with_both_refs(self) -> None:
        margin = [bullet for bullet in all_bullets(self.digest) if bullet.get("metric_id") == "gross_margin"]
        self.assertEqual(len(margin), 1)
        self.assertEqual({ref["evidence_type"] for ref in margin[0]["evidence_refs"] if ref["role"] == "primary"}, {"table", "chart"})
        self.assertEqual({cell["value_text"] for cell in margin[0]["cells"]}, {"46.5%", "49.1%", "48.8%"})

    def test_axis_ticks_from_row_only_tables_never_become_facts(self) -> None:
        margin_texts = " ".join(bullet["text"] for bullet in all_bullets(self.digest) if bullet.get("metric_id") == "gross_margin")
        self.assertNotIn("50%", margin_texts)
        self.assertNotIn("55%", margin_texts)

    def test_guidance_bullets_are_complete_and_in_outlook(self) -> None:
        outlook = [bullet["text"] for bullet in section(self.digest, "outlook_and_guidance")]
        self.assertEqual(len(outlook), 3)
        self.assertTrue(any("1,421億 ~ 1,506億元" in text and "1:30.6" in text for text in outlook))
        self.assertTrue(any("31% ± 2%" in text for text in outlook))

    def test_product_mix_section(self) -> None:
        texts = " ".join(bullet["text"] for bullet in section(self.digest, "product_and_business_mix"))
        self.assertIn("Mobile Phone", texts)
        self.assertIn("53%", texts)
        self.assertIn("Smart Edge Platforms", texts)

    def test_safe_harbor_is_a_notice_not_a_business_risk(self) -> None:
        risk_text = " ".join(bullet["text"] for bullet in section(self.digest, "risks_and_uncertainties"))
        self.assertNotIn("預測性陳述", risk_text)
        self.assertNotIn("投資安全聲明", risk_text)
        notices = self.digest["document_notices"]
        forward = [item for item in notices if item["notice_type"] == "forward_looking_statement_notice"]
        self.assertTrue(forward)
        self.assertEqual(forward[0]["evidence_refs"][0]["page"], 2)
        for bullet in all_bullets(self.digest):
            self.assertNotIn("預測性陳述", bullet["text"])
            self.assertNotIn(2, bullet["pages"])

    def test_wrapped_footnotes_stay_whole_and_out_of_sections(self) -> None:
        footnote = next(item["text"] for item in self.digest["document_notices"] if item["text"].startswith("註2"))
        self.assertTrue(footnote.endswith("為準。"), footnote)
        for bullet in all_bullets(self.digest):
            self.assertNotIn("補充而非替", bullet["text"])
        self.assertTrue(all(bullet["kind"] == "quantitative" for bullet in section(self.digest, "financial_performance")))

    def test_every_number_in_bullets_and_overview_is_in_its_evidence(self) -> None:
        items = [*all_bullets(self.digest), *self.digest["overview"], *self.digest["key_quantitative_disclosures"]]
        for item in items:
            text = item.get("text") or f"{item['label']} {item['column']} {item['value_text']}"
            excerpts = " ".join(ref["excerpt"] for ref in item["evidence_refs"])
            for token in NUMBER_RE.findall(text):
                self.assertIn(token, excerpts, f"{token!r} of {text!r} has no evidence")

    def test_refs_resolve_to_the_same_document(self) -> None:
        region_ids = {record["region_id"] for record in load(f"{Q3_FILE[:-4]}.semantic.json")}
        refs = [ref for bullet in all_bullets(self.digest) for ref in bullet["evidence_refs"]]
        refs += [ref for notice in self.digest["document_notices"] for ref in notice["evidence_refs"]]
        for ref in refs:
            self.assertEqual(ref["filename"], Q3_FILE)
            self.assertTrue(1 <= ref["page"] <= 20)
            if ref["region_id"]:
                self.assertIn(ref["region_id"], region_ids)
            self.assertIn(ref["verification_status"], {"verified", "partially_verified", "needs_review"})

    def test_coverage_contract_keeps_every_bullet(self) -> None:
        coverage = self.digest["coverage"]
        for key in ("content_page_count", "covered_content_pages", "included_evidence_count", "excluded_evidence_count",
                    "section_bullet_counts", "coverage_status", "coverage_warnings", "coverage_ratio"):
            self.assertIn(key, coverage)
        self.assertEqual(sum(coverage["section_bullet_counts"].values()), coverage["included_evidence_count"])
        self.assertEqual(len(all_bullets(self.digest)), coverage["included_evidence_count"])
        # All 15+ P&L / balance sheet / cash-flow / reconciliation rows survive: no silent top-k.
        self.assertGreaterEqual(len(section(self.digest, "financial_performance")), 40)
        self.assertLessEqual(len(self.digest["key_quantitative_disclosures"]), 30)
        self.assertEqual(coverage["key_quantitative_truncated_count"], coverage["key_quantitative_total"] - 30)
        self.assertIn(5, coverage["uncovered_content_pages"])

    def test_one_uncovered_content_page_is_partial_not_complete(self) -> None:
        coverage = self.digest["coverage"]
        self.assertEqual(len(coverage["covered_content_pages"]), 14)
        self.assertEqual(coverage["content_page_count"], 15)
        self.assertEqual(coverage["uncovered_content_pages"], [5])
        self.assertEqual(coverage["coverage_status"], "partial")
        self.assertTrue(any("第 5 頁" in warning for warning in coverage["coverage_warnings"]))
        self.assertTrue(self.digest["overview"][0]["text"].startswith("摘要涵蓋部分"))
        self.assertLessEqual(len(self.digest["overview"]), 6)

    def test_download_form_is_provenance_not_a_url(self) -> None:
        source = self.digest["source"]
        self.assertEqual(source["download_form"]["method"], "POST")
        self.assertNotIn("FileDownLoad", json.dumps({key: value for key, value in source.items() if key != "download_form"}))
        for value in (source.get("listing_url"), *[ref.get("excerpt") for bullet in all_bullets(self.digest) for ref in bullet["evidence_refs"]]):
            self.assertNotIn("/home/html/nas", str(value))

    def test_no_jsd_or_cosine_in_the_digest(self) -> None:
        payload = json.dumps(self.digest, ensure_ascii=False)
        self.assertNotRegex(payload, r"(?i)\bjsd\b|cosine|\bP90\b|\bP10\b")


class DigestIsolationTests(unittest.TestCase):
    def test_foreign_document_records_are_rejected(self) -> None:
        semantic = load(f"{Q3_FILE[:-4]}.semantic.json")
        intruder = copy.deepcopy(next(record for record in semantic if record["page"] == 13 and record["evidence_type"] == "table"))
        intruder["filename"] = Q2_FILE
        intruder["region_id"] = f"{Q2_FILE}#p13r2"
        intruder["values"][0]["cells"][0]["value_text"] = "99,999"
        digest = q3_digest(semantic=[*semantic, intruder])
        self.assertEqual(digest["coverage"]["rejected_foreign_records"], 1)
        self.assertNotIn("99,999", json.dumps(digest, ensure_ascii=False))
        self.assertNotIn(Q2_FILE, json.dumps(digest, ensure_ascii=False))

    def test_other_period_document_content_does_not_leak(self) -> None:
        q2_pages = json.loads((FIXTURE_DIR / f"{Q2_FILE[:-4]}.pages.json").read_text(encoding="utf-8"))
        q2_guidance = next(line for page in q2_pages for line in page["text"].splitlines() if "合併營收" in line and "億" in line)
        digest = q3_digest()
        self.assertNotIn(q2_guidance.strip(), json.dumps(digest, ensure_ascii=False))

    def test_long_english_forward_looking_title_is_a_notice_not_a_risk(self) -> None:
        pages = [
            {"page": 1, "text": "Q3 2025 Results\nInvestor Conference", "text_extraction_method": "selectable_text"},
            {"page": 2, "text": "NOTE CONCERNING FORWARD-LOOKING STATEMENTS\n"
                                "This presentation contains forward-looking statements within the meaning of Section 27A.\n"
                                "These forward-looking statements involve known and unknown risks, uncertainties and other factors "
                                "that may cause the actual performance to differ materially.",
             "text_extraction_method": "selectable_text"},
            {"page": 3, "text": "Business Outlook\n• Demand uncertainty remains due to tariff risks in end markets",
             "text_extraction_method": "selectable_text"},
        ]
        digest = build_document_digest("9999", {"filename": "x.pdf", "page_count": 3, "period": "2025Q3"}, pages, [])
        risk_and_other = [bullet["text"] for bullet in all_bullets(digest)]
        self.assertFalse(any("forward-looking" in text.lower() for text in risk_and_other), risk_and_other)
        self.assertTrue(all(ref["page"] == 2 for notice in digest["document_notices"] for ref in notice["evidence_refs"]))
        self.assertIn("forward_looking_statement_notice", {notice["notice_type"] for notice in digest["document_notices"]})

    def test_same_label_and_value_with_different_unit_is_not_merged(self) -> None:
        def page(number, unit):
            return {"page": number, "text": f"營收表\n(單位：{unit})\n營業收入 100 90", "text_extraction_method": "selectable_text"}

        def table(number):
            return {
                "filename": "x.pdf", "page": number, "evidence_type": "table", "region_id": f"x.pdf#p{number}r1",
                "verification_status": "partially_verified", "mapping_status": "aligned",
                "columns": ["2025年 第三季", "2025年 第二季"], "source_text": "營業收入 100 90",
                "values": [{"row_label": "營業收入", "values": ["100", "90"], "cells": [
                    {"column": "2025年 第三季", "value_text": "100"}, {"column": "2025年 第二季", "value_text": "90"}]}],
            }

        document = {"filename": "x.pdf", "page_count": 2, "period": "2025Q3", "company_name": "測試"}
        digest = build_document_digest("9999", document, [page(1, "新台幣佰萬元"), page(2, "百萬美元")], [table(1), table(2)])
        revenue = [bullet for bullet in all_bullets(digest) if bullet.get("metric_id") == "revenue"]
        self.assertEqual(len(revenue), 2)
        self.assertEqual({bullet["unit_text"] for bullet in revenue}, {"新台幣佰萬元", "百萬美元"})

    def test_complete_only_when_every_content_page_is_covered(self) -> None:
        pages = [{"page": number, "text": f"營運展望\n• 預期第{number}項指標：{number}0% ± 1%", "text_extraction_method": "selectable_text"}
                 for number in range(1, 6)]
        digest = build_document_digest("9999", {"filename": "x.pdf", "page_count": 5, "period": "2025Q3"}, pages, [])
        self.assertEqual(digest["coverage"]["uncovered_content_pages"], [])
        self.assertEqual(digest["coverage"]["coverage_status"], "complete")
        self.assertFalse(digest["coverage"]["coverage_warnings"])

    def test_low_coverage_is_flagged(self) -> None:
        pages = [{"page": 1, "text": "展望\n• 預期營收將持平", "text_extraction_method": "selectable_text"}]
        semantic = []
        for number in range(2, 8):
            pages.append({"page": number, "text": f"圖表{number}\n12,345\n0\n10\n20", "text_extraction_method": "selectable_text"})
            semantic.append({"filename": "x.pdf", "page": number, "evidence_type": "chart", "region_id": f"x.pdf#p{number}r1",
                             "verification_status": "needs_review", "mapping_status": "candidates_only", "values": []})
        digest = build_document_digest("9999", {"filename": "x.pdf", "page_count": 7, "period": "2025Q3"}, pages, semantic)
        self.assertEqual(digest["coverage"]["coverage_status"], "limited")
        self.assertTrue(digest["coverage"]["coverage_warnings"])
        self.assertTrue(digest["overview"][0]["text"].startswith("摘要涵蓋有限"))


class DigestFallbackTests(unittest.TestCase):
    def test_semantic_absent_falls_back_to_page_text_and_analysis(self) -> None:
        digest = q3_digest(semantic=[], analysis=load(f"{Q3_FILE[:-4]}.analysis.json"))
        self.assertEqual(digest["summary_mode"], "deterministic_page_text")
        quantitative = [bullet for bullet in all_bullets(digest) if bullet["kind"] == "quantitative"]
        self.assertTrue(quantitative)
        for bullet in quantitative:
            self.assertTrue(bullet["low_confidence"])
            self.assertTrue(bullet["text"].startswith("（待人工複核）"))
        self.assertTrue(section(digest, "outlook_and_guidance"))

    def test_old_archive_without_semantic_or_summary_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            document = archive_document("1234x.pdf", "2024Q4")
            document["page_count"] = 2
            write_archive(Path(folder), "1234", 2025, [document], pages={"1234x.pdf": [
                {"page": 1, "text": "2025年第一季營運展望\n• 合併營收：約新台幣 100億 ~ 110億元", "text_extraction_method": "selectable_text"},
                {"page": 2, "text": "合併損益表\n營業收入 1,000 900", "text_extraction_method": "selectable_text"},
            ]})
            service = ConferenceDocumentDigestService(FileConferencePdfArchiveRepository(folder))
            digest, status = service.digest_for("1234", period="2024Q4")
        self.assertEqual(status, "available")
        self.assertEqual(digest["summary_mode"], "deterministic_page_text")
        self.assertIn("100億 ~ 110億元", json.dumps(digest, ensure_ascii=False))


class DocumentSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        write_archive(self.root, "1234", 2026, [archive_document("new.pdf", "2026Q1", dates=["115/04/30"])])
        write_archive(self.root, "1234", 2025, [archive_document("mid.pdf", "2025Q1", dates=["114/04/30"])])
        write_archive(self.root, "1234", 2022, [
            archive_document("old-zh.pdf", "2022Q1", dates=["111/04/28"], verified=False),
            archive_document("old-en.pdf", "2022Q1", language="en", dates=["111/04/28"]),
        ])
        self.repo = FileConferencePdfArchiveRepository(self.root)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_exact_old_period_is_not_limited_by_latest_two_years(self) -> None:
        selected = select_archive_document(self.repo, "1234", period="2022Q1")
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], 2022)

    def test_identity_outranks_language_preference(self) -> None:
        _year, _manifest, document = select_archive_document(self.repo, "1234", period="2022Q1")
        self.assertEqual(document["filename"], "old-en.pdf")

    def test_conference_date_matches_listing_dates(self) -> None:
        _year, _manifest, document = select_archive_document(self.repo, "1234", conference_date="2025-04-30")
        self.assertEqual(document["filename"], "mid.pdf")
        self.assertIsNone(select_archive_document(self.repo, "1234", conference_date="2025-05-01"))

    def test_latest_fallback_uses_recent_years_only(self) -> None:
        _year, _manifest, document = select_archive_document(self.repo, "1234")
        self.assertEqual(document["filename"], "new.pdf")

    def test_unmatched_period_returns_no_document(self) -> None:
        self.assertIsNone(select_archive_document(self.repo, "1234", period="2026Q2"))
        digest, status = ConferenceDocumentDigestService(self.repo).digest_for("1234", period="2026Q2")
        self.assertIsNone(digest)
        self.assertEqual(status, "no_matching_archive")


class DigestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()

    def test_only_the_selected_document_is_hydrated_when_identity_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repo = CountingRepository(current_identity_fixture(Path(folder)))
            digest, status = ConferenceDocumentDigestService(repo).digest_for("2454", period="2025Q3")
        self.assertEqual(status, "available")
        self.assertEqual(digest["source"]["filename"], Q3_FILE)
        self.assertFalse(digest["source"]["identity"]["recomputed_from_archive"])
        self.assertEqual(repo.calls, [("pages", Q3_FILE), ("semantic", Q3_FILE)])

    def test_stale_identity_is_recomputed_once_then_cached(self) -> None:
        # The committed fixture keeps the real stale manifest (conference-identity-v1).
        repo = CountingRepository(FIXTURE_ROOT)
        digest, status = ConferenceDocumentDigestService(repo).digest_for("2454", period="2025Q3")
        self.assertEqual(status, "available")
        self.assertTrue(digest["source"]["identity"]["recomputed_from_archive"])
        self.assertEqual(digest["source"]["identity"]["stored_identity_version"], "conference-identity-v1")
        self.assertEqual(digest["period"], "2025Q3")
        self.assertEqual(digest["document_type"], "earnings_presentation")
        self.assertEqual(sorted(repo.calls), sorted([("pages", Q3_FILE), ("pages", Q2_FILE), ("pages", Q3_FILE), ("semantic", Q3_FILE)]))
        self.assertNotIn(("semantic", Q2_FILE), repo.calls)
        ConferenceDocumentDigestService._cache.clear()  # digest cache only; identity cache stays warm
        repo.calls.clear()
        ConferenceDocumentDigestService(repo).digest_for("2454", period="2025Q3")
        self.assertEqual(repo.calls, [("pages", Q3_FILE), ("semantic", Q3_FILE)])

    def test_failures_and_timeouts_are_statuses(self) -> None:
        class Broken(FileConferencePdfArchiveRepository):
            def pages(self, *args):
                raise OSError("storage down")

        class Unreachable:
            def available_years(self, ticker):
                raise RuntimeError("gcs unavailable")

        with tempfile.TemporaryDirectory() as folder:
            current = current_identity_fixture(Path(folder))
            self.assertEqual(ConferenceDocumentDigestService(Broken(current)).digest_for("2454", period="2025Q3"), (None, "digest_failed"))
        # A stale manifest whose page text cannot be read is rejected, never guessed.
        self.assertEqual(ConferenceDocumentDigestService(Broken(FIXTURE_ROOT)).digest_for("2454", period="2025Q3"), (None, "no_matching_archive"))
        reasons = {item["document"]["filename"]: item["reason"]
                   for item in explain_archive_selection(Broken(FIXTURE_ROOT), "2454")["candidates"]}
        self.assertEqual(set(reasons.values()), {"rejected:period_identity_unavailable"})
        self.assertEqual(ConferenceDocumentDigestService(Unreachable()).digest_for("2454"), (None, "archive_unavailable"))
        self.assertEqual(ConferenceDocumentDigestService(FIXTURE_ROOT and FileConferencePdfArchiveRepository(FIXTURE_ROOT), timeout_seconds=-1)
                         .digest_for("2454", period="2025Q3"), (None, "digest_timeout"))
        self.assertEqual(ConferenceDocumentDigestService(None).digest_for("2454"), (None, "archive_unavailable"))


class NarratorTests(unittest.TestCase):
    def narrate(self, payload) -> tuple[dict, dict]:
        deterministic = q3_digest()
        provider = FakeProvider(payload)
        result = ConferenceDigestNarrator(provider).apply(copy.deepcopy(deterministic))
        return deterministic, result

    def assert_rejected(self, deterministic: dict, result: dict) -> None:
        self.assertEqual(result["overview"], deterministic["overview"])
        self.assertEqual(result["summary_mode"], "deterministic")
        self.assertEqual(result["llm_validation"]["status"], "rejected")
        self.assertEqual(result["sections"], deterministic["sections"])

    def test_fabricated_number_is_rejected(self) -> None:
        deterministic, result = self.narrate({"overview": [{"text": "本期營業收入 150,000。", "cited_ids": ["overview-2"]}]})
        self.assert_rejected(deterministic, result)

    def test_fabricated_qualitative_claim_without_numbers_is_rejected(self) -> None:
        for text in ("需求強勁回升。", "毛利率改善。", "營收優於前一季。", "Demand remains strong."):
            deterministic, result = self.narrate({"overview": [{"text": text, "cited_ids": ["financial_performance-1"]}]})
            self.assert_rejected(deterministic, result)

    def test_new_entity_or_period_is_rejected(self) -> None:
        for text in ("Apple 營業收入 142,097。", "2026Q1 營業收入 142,097。"):
            deterministic, result = self.narrate({"overview": [{"text": text, "cited_ids": ["financial_performance-1"]}]})
            self.assert_rejected(deterministic, result)

    def test_uncited_or_unknown_citation_is_rejected(self) -> None:
        deterministic, result = self.narrate({"overview": [{"text": "營業收入 142,097。", "cited_ids": ["nope-1"]}]})
        self.assert_rejected(deterministic, result)

    def test_grounded_rephrase_is_accepted_and_sections_stay_deterministic(self) -> None:
        def rephrase(prompt):
            return {"overview": [{"text": "此外，" + item["text"], "cited_ids": [item["id"]]} for item in prompt["overview"]]}

        deterministic, result = self.narrate(rephrase)
        self.assertEqual(result["summary_mode"], "llm_overview_deterministic_sections")
        self.assertEqual(result["sections"], deterministic["sections"])
        self.assertEqual(result["deterministic_overview"], deterministic["overview"])
        self.assertTrue(all(sentence["evidence_refs"] for sentence in result["overview"]))

    def test_unconfigured_provider_keeps_deterministic_overview(self) -> None:
        class Off:
            configured = False

        deterministic = q3_digest()
        result = ConferenceDigestNarrator(Off()).apply(copy.deepcopy(deterministic))
        self.assertEqual(result["overview"], deterministic["overview"])
        self.assertEqual(result["summary_mode"], "deterministic")

    def test_llm_is_disabled_by_default(self) -> None:
        from app.services.conference_document_digest import build_narrator_from_env

        previous = os.environ.pop("CONFERENCE_DIGEST_LLM_PROVIDER", None)
        try:
            self.assertIsNone(build_narrator_from_env())
        finally:
            if previous is not None:
                os.environ["CONFERENCE_DIGEST_LLM_PROVIDER"] = previous


if __name__ == "__main__":
    unittest.main()
