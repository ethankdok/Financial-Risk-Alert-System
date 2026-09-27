from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_conference_feasibility import (
    INVITED_ONLY,
    NEEDS_PDF_IDENTITY,
    QUARTERLY_CANDIDATE,
    build_matrix,
    classify_listing_document,
)
from scripts.backfill_conference_scope import (
    eligible_scope,
    main as backfill_main,
    require_validated_sample,
    selected_documents,
)


def results_row(period: str) -> str:
    return f"公布本公司{period[:4]}年第{period[-1]}季財務報告及業績展望。"


def doc(filename: str, language: str, period: str | None, rows: list[str] | None = None) -> dict:
    rows = rows if rows is not None else [results_row(period)]
    return {
        "filename": filename,
        "language": language,
        "conference_dates": ["114/01/01"] * len(rows),
        "period_claimed_by_listing": period,
        "period_claims_all": [period] if period else [],
        "listing_summaries": rows,
        "listing_rows": len(rows),
    }


def quarters(count: int, start_year: int = 2017) -> list[str]:
    return [f"{start_year + offset // 4}Q{offset % 4 + 1}" for offset in range(count)]


def company(ticker: str, periods: list[str], *, duplicate: bool = False, language: str = "en") -> dict:
    suffix = "E" if language == "en" else "M"
    documents = []
    for index, period in enumerate(periods):
        documents.append(doc(f"{ticker}{index:02d}{suffix}001.pdf", language, period))
        if duplicate and index == 1:
            documents.append(doc(f"{ticker}{index:02d}{suffix}002.pdf", language, period))
    return {
        "ticker": ticker,
        "company": ticker,
        "industry": "semiconductor_foundry",
        "source": "MOPS",
        "years": {"2024": {"status": "ok", "error": None}},
        "documents": documents,
    }


class ListingDocumentClassificationTests(unittest.TestCase):
    def test_reused_quarterly_deck_with_later_investor_forum_row_stays_quarterly(self) -> None:
        # MOPS lists the same file again when the quarterly deck is reused at a later forum.
        document = doc("303420170207E001.pdf", "en", "2016Q4", rows=[
            "本公司一○五年第四季合倂財務報告及一○六年第一季業績展望。",
            "受邀參加由富邦證券所舉辦之Investor Forum，就105年第4季營運績效等相關資訊作說明。",
            "本公司將參加美林證券所舉辦之『2017 Taiwan, Technology & Beyond Conference』，"
            "會中就本公司1/12法說會已公開發佈之財務數字、經營績效等相關資訊做說明。",
        ])

        identity = classify_listing_document(document)

        self.assertEqual(identity["metadata_class"], QUARTERLY_CANDIDATE)
        self.assertEqual(identity["period"], "2016Q4")
        self.assertEqual(identity["period_basis"], "periodic_row")

    def test_invited_only_investor_forum_is_event_usage_and_never_eligible(self) -> None:
        periods = quarters(34)
        forum_only = {
            **company("3034", periods),
            "documents": [
                doc(f"3034{index:02d}E002.pdf", "en", period,
                    rows=[f"Company presentation at the {period} Investor Forum hosted by a broker"])
                for index, period in enumerate(periods)
            ],
        }

        identity = classify_listing_document(forum_only["documents"][0])
        scope = build_matrix({"companies": [forum_only]}, target_tickers=("3034",))["scopes"][0]

        self.assertEqual(identity["metadata_class"], INVITED_ONLY)
        self.assertIsNone(identity["period"])
        self.assertEqual(scope["metadata_class"], INVITED_ONLY)
        self.assertFalse(scope["staged_identity_validation_eligible"])
        self.assertIn(f"metadata_class_{INVITED_ONLY}", scope["staged_identity_validation_blockers"])
        with self.assertRaisesRegex(ValueError, "not present|not eligible"):
            eligible_scope(build_matrix({"companies": [forum_only]}, target_tickers=("3034",)),
                           ticker="3034", metadata_class=INVITED_ONLY, language="en")

    def test_normal_quarterly_results_rows_stay_quarterly(self) -> None:
        for row, period in (
            ("公布本公司2025年第2季財務報告及2025年第3季業績展望。", "2025Q2"),
            ("2016年第4季營運狀況說明", "2016Q4"),
            ("本公司2017年第三季財務暨營運報告。", "2017Q3"),
            ("聯發科技股份有限公司擬於2017年04月28日舉行2017年第一季線上法人說明會，報告本公司的營運成果並回答投資人提問。"
             " 有意參加者可透過網路連結至本公司網站之投資人專區參加線上法人說明會。", "2017Q1"),
        ):
            with self.subTest(row=row):
                identity = classify_listing_document(doc("x.pdf", "en", period, rows=[row]))
                self.assertEqual((identity["metadata_class"], identity["period"]), (QUARTERLY_CANDIDATE, period))

    def test_company_attendance_rows_are_event_usage(self) -> None:
        for row in ("本公司將參加瑞銀證券所舉辦之『UBS Taiwan Conference 2017』，會中就本公司4/13法說會已公開發佈之財務數字做說明。",
                    "公告本公司111年08月23日參加瑞銀(UBS)證券舉辦之Digital Asset Conference 2022英文線上論壇"):
            with self.subTest(row=row):
                identity = classify_listing_document(doc("x.pdf", "en", None, rows=[row]))
                self.assertEqual(identity["metadata_class"], INVITED_ONLY)

    def test_invited_row_period_does_not_define_period_when_periodic_row_names_one(self) -> None:
        document = doc("x.pdf", "en", None, rows=[
            "本公司一○六年第三季合倂財務報告及第四季業績展望。",
            "受邀參加由JPMORGAN所舉辦GLOBAL TMT CONFERENCE 2017，就106年第2季營運績效等相關資訊作說明。",
        ])

        self.assertEqual(classify_listing_document(document)["period"], "2017Q3")

    def test_annual_results_row_uses_the_files_single_listing_period(self) -> None:
        document = doc("x.pdf", "en", "2016Q4", rows=[
            "本公司一○五年度自結數合倂財務報告及一○六年第一季業績展望。",
            "受邀參加由富邦證券所舉辦之非籌資巡迴說明會，就105年第4季營運績效等相關資訊作說明。",
        ])

        identity = classify_listing_document(document)

        self.assertEqual((identity["metadata_class"], identity["period"]), (QUARTERLY_CANDIDATE, "2016Q4"))
        self.assertEqual(identity["period_basis"], "other_listing_rows")

    def test_unclassifiable_listing_text_needs_pdf_identity(self) -> None:
        for rows in (["無。"], ["詳112年4月27日公開資訊觀測站之重大訊息與公告-法說會專區。"], ["財務業務相關資訊說明"]):
            with self.subTest(rows=rows):
                identity = classify_listing_document(doc("x.pdf", "en", None, rows=rows))
                self.assertEqual(identity["metadata_class"], NEEDS_PDF_IDENTITY)


class ConferenceFeasibilityTests(unittest.TestCase):
    def test_history_pairs_exclude_target_and_future_periods(self) -> None:
        periods = ["2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3"]

        matrix = build_matrix({"companies": [company("2330", periods)]}, target_tickers=("2330",))
        scope = matrix["scopes"][0]

        self.assertEqual(scope["target_pair"], {"period_1": "2025Q2", "period_2": "2025Q3", "potentially_present": True})
        self.assertEqual(scope["potential_historical_adjacent_pairs_before_target"], 4)
        self.assertEqual(scope["staged_identity_validation_blockers"], ["scope_not_feasible"])
        self.assertEqual(scope["document_type"], "pending_pdf_identity")

    def test_classification_thresholds_are_not_lowered(self) -> None:
        periods = quarters(31) + ["2025Q2", "2025Q3"]

        feasible = build_matrix({"companies": [company("2330", periods)]}, target_tickers=("2330",))["scopes"][0]
        borderline = build_matrix({"companies": [company("2454", periods[:30])]}, target_tickers=("2454",))["scopes"][0]
        insufficient = build_matrix({"companies": [company("2303", periods[:24])]}, target_tickers=("2303",))["scopes"][0]

        self.assertEqual(feasible["classification"], "FEASIBLE")
        self.assertEqual(feasible["potential_historical_adjacent_pairs_before_target"], 30)
        self.assertTrue(feasible["staged_identity_validation_eligible"])
        self.assertEqual(borderline["classification"], "BORDERLINE")
        self.assertEqual(borderline["potential_historical_adjacent_pairs_before_target"], 29)
        self.assertEqual(insufficient["classification"], "INSUFFICIENT")
        self.assertEqual(insufficient["potential_historical_adjacent_pairs_before_target"], 23)

    def test_duplicate_metadata_candidates_are_reported(self) -> None:
        matrix = build_matrix(
            {"companies": [company("2330", ["2024Q1", "2024Q2", "2024Q3"], duplicate=True)]},
            target_tickers=("2330",),
        )

        scope = matrix["scopes"][0]

        self.assertEqual(scope["duplicate_candidate_periods"][0]["period"], "2024Q2")
        self.assertIn("duplicate_metadata_candidates_require_pdf_identity_resolution", scope["warnings"])
        self.assertIn("potential metadata-derived pairs", " ".join(matrix["important_limitations"]))

    def test_non_english_scope_is_not_eligible(self) -> None:
        periods = quarters(34)
        scope = build_matrix({"companies": [company("3034", periods, language="zh")]},
                             target_tickers=("3034",))["scopes"][0]

        self.assertEqual(scope["classification"], "FEASIBLE")
        self.assertIn("non_english_scope_not_active_for_current_method", scope["staged_identity_validation_blockers"])

    def test_failed_and_no_listing_years_are_reported_separately(self) -> None:
        data = company("6770", quarters(3))
        data["years"] = {"2019": {"status": "no_listing", "error": "no downloadable pdfs"},
                         "2021": {"status": "failed", "error": "Unexpected attachment filename"},
                         "2024": {"status": "ok", "error": None}}

        scope = build_matrix({"companies": [data]}, target_tickers=("6770",))["scopes"][0]

        self.assertEqual(scope["no_listing_years"], ["2019"])
        self.assertEqual(scope["failed_listing_years"], {"2021": "Unexpected attachment filename"})


    def test_non_pdf_quarters_are_source_gaps_not_potential_periods(self) -> None:
        data = company("2330", ["2019Q1", "2019Q2", "2019Q4"])
        data["non_pdf_attachments"] = [{**doc("233020191017E001.pptx", "en", "2019Q3"), "format": "pptx"}]

        scope = build_matrix({"companies": [data]}, target_tickers=("2330",))["scopes"][0]

        self.assertEqual(scope["periods_represented"], ["2019Q1", "2019Q2", "2019Q4"])
        self.assertEqual(scope["non_pdf_source_gap_periods"], ["2019Q3"])
        self.assertEqual(scope["potential_historical_adjacent_pairs_before_target"], 1)
        self.assertIn("some_quarters_exist_only_as_non_pdf_official_files", scope["warnings"])


class BackfillSelectorTests(unittest.TestCase):
    def test_selector_requires_feasibility_gate_and_honours_periods(self) -> None:
        periods = quarters(31) + ["2025Q2", "2025Q3"]
        discovery = {"companies": [company("2330", periods)]}
        matrix = build_matrix(discovery, target_tickers=("2330",))

        scope = eligible_scope(matrix, ticker="2330", metadata_class=QUARTERLY_CANDIDATE, language="en")
        everything = selected_documents(discovery, ticker="2330", metadata_class=QUARTERLY_CANDIDATE, language="en")
        sample = selected_documents(discovery, ticker="2330", metadata_class=QUARTERLY_CANDIDATE, language="en",
                                    periods={"2017Q1"})

        self.assertTrue(scope["staged_identity_validation_eligible"])
        self.assertEqual(sum(len(items) for items in everything.values()), len(periods))
        self.assertEqual(sample, {2025: {"233000E001.pdf": "2017Q1"}})
        with self.assertRaisesRegex(ValueError, "not present|not eligible"):
            eligible_scope(matrix, ticker="2330", metadata_class=QUARTERLY_CANDIDATE, language="zh-Hant")

    def test_full_scope_run_requires_passed_validated_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "sample.json"
            with self.assertRaisesRegex(ValueError, "requires --validated-sample"):
                require_validated_sample(None, ticker="2330", metadata_class=QUARTERLY_CANDIDATE, language="en")
            report.write_text(json.dumps({"ticker": "2330", "metadata_class": QUARTERLY_CANDIDATE,
                                          "language": "en", "status": "failed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not pass"):
                require_validated_sample(report, ticker="2330", metadata_class=QUARTERLY_CANDIDATE, language="en")
            report.write_text(json.dumps({"ticker": "2330", "metadata_class": QUARTERLY_CANDIDATE,
                                          "language": "en", "status": "passed"}), encoding="utf-8")
            require_validated_sample(report, ticker="2330", metadata_class=QUARTERLY_CANDIDATE, language="en")

    def test_backfill_main_uses_pipeline_defaults_for_optional_providers(self) -> None:
        periods = quarters(31) + ["2025Q2", "2025Q3"]
        discovery = {"companies": [company("2330", periods)]}
        matrix = build_matrix(discovery, target_tickers=("2330",))
        calls = []

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            discovery_path = base / "discovery.json"
            feasibility_path = base / "feasibility.json"
            discovery_path.write_text(json.dumps(discovery), encoding="utf-8")
            feasibility_path.write_text(json.dumps(matrix), encoding="utf-8")

            def fake_pipeline(**kwargs):
                # Passing False/True here once broke extract_pages ('bool' object has no attribute 'process_page').
                self.assertNotIn("interpreter", kwargs)
                self.assertNotIn("region_ocr", kwargs)
                self.assertIs(kwargs["semantic_analysis"], False)
                calls.append(kwargs)
                return {"status": "complete", "expected_pdfs": 1, "documents": [], "errors": []}

            argv = [
                "backfill_conference_scope",
                "--discovery", str(discovery_path),
                "--feasibility", str(feasibility_path),
                "--ticker", "2330",
                "--metadata-class", QUARTERLY_CANDIDATE,
                "--language", "en",
                "--periods", "2017Q1",
                "--output", str(base / "archive"),
                "--delay", "1.0",
            ]
            with patch.object(sys, "argv", argv), patch.dict("os.environ", {"CONFERENCE_PDF_OCR_PROVIDER": "rapidocr"}), \
                    patch("scripts.backfill_conference_scope.run_mops_pdf_pipeline", side_effect=fake_pipeline):
                self.assertEqual(backfill_main(), 0)
                import os
                self.assertNotIn("CONFERENCE_PDF_OCR_PROVIDER", os.environ)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["select_documents"]([type("A", (), {"filename": "233000E001.pdf"})(),
                                                       type("A", (), {"filename": "233001E001.pdf"})()])[0].filename,
                         "233000E001.pdf")


if __name__ == "__main__":
    unittest.main()
