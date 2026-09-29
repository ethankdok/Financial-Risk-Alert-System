"""python3 -m unittest discover -s tests -p 'test_taiwan_shift.py'"""
import unittest

import pandas as pd

from taiwan_shift import analyze_taiwan_shift, compare_groups, tokenize_zh


class TaiwanShiftTests(unittest.TestCase):
    def test_traditional_chinese_tokenization(self):
        terms = tokenize_zh("保證獲利，立刻加入LINE群組")
        self.assertIn("保證", terms)
        self.assertIn("獲利", terms)
        self.assertIn("line", terms)

    def test_identical_months(self):
        texts = ["台灣科技產業營運成長" * 4 for _ in range(5)]
        metrics = compare_groups(texts, texts)
        self.assertAlmostEqual(metrics["jsd"], 0, places=6)
        self.assertAlmostEqual(metrics["cosine_similarity"], 1, places=6)

    def test_different_chinese_documents(self):
        a = ["光電面板需求與產能配置" * 5 for _ in range(5)]
        b = ["銀行授信與存款利息收入" * 5 for _ in range(5)]
        metrics = compare_groups(a, b)
        self.assertGreater(metrics["jsd"], 0)
        self.assertLess(metrics["cosine_similarity"], 1)

    def test_no_inherited_strux_threshold_and_filter(self):
        rows = []
        for month in ("2026-07", "2026-08"):
            for i in range(5):
                rows.append({"date": f"{month}-{i+1:02d}",
                             "text": "股票發行公司財報資訊揭露" * 3,
                             "sector": "半導體", "source": "mops"})
                rows.append({"date": f"{month}-{i+1:02d}",
                             "text": "此案例為網路交友提醒" * 3,
                             "sector": "半導體", "source": "165_debunk"})
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df["month"] = df["date"].dt.to_period("M")
        result = analyze_taiwan_shift(
            df=df, sector="半導體", source="mops",
            period_1="2026-07", period_2="2026-08",
        )
        self.assertEqual(result["sample_counts"], {"period_1": 5, "period_2": 5})
        self.assertEqual(result["calibration"]["status"], "insufficient_history")
        self.assertIsNone(result["combined_rule"])
        self.assertIn("未校準", result["drift_result"])

    def test_reject_nonconsecutive_months(self):
        df = pd.DataFrame(columns=["sector", "source", "text", "month"])
        with self.assertRaises(ValueError):
            analyze_taiwan_shift(df=df, sector="半導體", source="mops",
                                 period_1="2026-01", period_2="2026-03")


if __name__ == "__main__":
    unittest.main()
