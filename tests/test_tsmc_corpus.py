"""Offline tests; no live PDF download and no Firestore write."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_tsmc_corpus import get_pdf_link, official_pdf
from calibrate_tsmc_shift import quarter_number, pair, analyze

PDF = "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/x/TSMC%201Q24%20Transcript.pdf"


def make_record(period, text=None):
    return {"ticker": "2330", "company": "TSMC", "industry": "semiconductor_foundry",
            "period": period, "document_type": "full_earnings_transcript",
            "language": "en", "source_page": "https://investor.tsmc.com/",
            "source_pdf": PDF, "sha256": "hash_" + period,
            "text": text or ("revenue wafer demand capacity quarterly outlook. " * 160)}


class TsmcPilotTests(unittest.TestCase):
    def test_html_official_source_discovery(self):
        html = ('<html><a href="' + PDF.replace("https://investor.tsmc.com", "") +
                '">Earnings Conference Transcript</a></html>')
        self.assertEqual(get_pdf_link(html, "https://investor.tsmc.com/english/quarterly-results/2024/q1"), PDF)
        self.assertTrue(official_pdf(PDF))
        self.assertFalse(official_pdf("https://unofficial.example/fake.pdf"))

    def test_adjacent_quarter_calculation_identical(self):
        result = pair(make_record("2024Q4"), make_record("2025Q1"))
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["metrics"]["jsd"], 0.0, places=5)
        self.assertAlmostEqual(result["metrics"]["cosine_similarity"], 1.0, places=5)

    def test_reject_non_adjacent(self):
        with self.assertRaises(ValueError):
            pair(make_record("2024Q1"), make_record("2024Q3"))

    def test_no_calibration_with_short_history(self):
        rows = [make_record(f"{y}Q{q}") for y in (2024, 2025) for q in (1, 2, 3, 4)]
        result = analyze(rows, "2025Q3", "2025Q4")
        self.assertIsNone(result["calibration"]["thresholds"])
        self.assertIsNone(result["combined_rule"])
        self.assertEqual(result["calibration"]["history_pair_count"], 5)
        self.assertIn("資料不足", result["drift_result"])

    def test_thresholds_only_use_earlier_quarters(self):
        rows = []
        vocabulary = ["wafer", "packaging", "substrate", "assembly", "lithography",
                      "foundry", "capacity", "automation", "shipping", "suppliers",
                      "electrical", "industrial", "transistors", "production"]
        index = 0
        for year in range(2017, 2026):
            for quarter in range(1, 5):
                # Vary token mix and relative proportions; repeated digits alone
                # would disappear in the English tokenizer.
                word = vocabulary[index % len(vocabulary)]
                other = vocabulary[(index + 3) % len(vocabulary)]
                text = ("revenue manufacturing demand global quarterly outlook " * 130
                        + (word + " ") * (55 + index * 2)
                        + (other + " ") * (18 + (index % 5) * 11))
                rows.append(make_record(f"{year}Q{quarter}", text))
                index += 1
        result = analyze(rows, "2025Q3", "2025Q4")
        self.assertEqual(result["calibration"]["history_pair_count"], 33)
        self.assertIsNotNone(result["calibration"]["thresholds"])
        self.assertIn("jsd_p90", result["calibration"]["thresholds"])
        self.assertTrue(all(
            quarter_number(x["period_2"]) < quarter_number("2025Q3")
            for x in result["calibration"]["history_pairs"]
        ))

    def test_text_length_rejects_insufficient(self):
        with self.assertRaises(ValueError):
            analyze([make_record("2025Q3", "short"), make_record("2025Q4")],
                    "2025Q3", "2025Q4")


if __name__ == "__main__":
    unittest.main()
