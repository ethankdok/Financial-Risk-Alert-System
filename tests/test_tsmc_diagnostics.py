"""Offline metadata-only sensitivity checks."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from diagnose_tsmc_shift import structural_stats, alternate_cosine, diagnose


def row(period, text):
    return {
        "period": period, "text": text, "source_pdf": "https://investor.tsmc.com/test.pdf",
        "sha256": period, "ticker": "2330",
    }


class DiagnosticTests(unittest.TestCase):
    def test_structural_stats_no_raw_excerpt(self):
        x = structural_stats("Operator: question\nHello growth growth\n" * 210)
        self.assertGreater(x["clean_tokens"], 0)
        self.assertGreater(x["qa_marker_mentions"], 0)
        self.assertNotIn("raw_text", x)

    def test_count_cosine_identical(self):
        self.assertAlmostEqual(
            alternate_cosine("revenue capacity margin" * 10,
                             "revenue capacity margin" * 10)["count_cosine"],
            1, places=6)

    def test_diagnose_metadata_and_prior_exclusion(self):
        x = "revenue capacity margin growth earnings guidance " * 900
        y = "revenue demand quarter outlook equipment sales " * 900
        rows = [row("2024Q3", x), row("2024Q4", y),
                row("2025Q1", x), row("2025Q2", x),
                row("2025Q3", x), row("2025Q4", y)]
        result = diagnose(rows)
        self.assertEqual(result["historical_valid_pairs"], 3)
        self.assertEqual(result["target"]["period1"], "2025Q3")
        self.assertLess(result["target"]["cosine"], 1)
        self.assertEqual(len(result["official_documents"]), 2)


if __name__ == "__main__":
    unittest.main()
