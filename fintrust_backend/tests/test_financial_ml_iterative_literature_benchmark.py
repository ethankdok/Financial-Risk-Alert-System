"""Synthetic offline checks for the Phase 5 iterative literature baseline."""
import csv
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.iterative_literature_benchmark import (
    read_data, split_indices, usable_paper_features, run,
)
from research.financial_ml.literature_dataset import FEATURES


class IterativeLiteratureBenchmarkTests(unittest.TestCase):
    def fixture(self, folder, firms=16):
        path = folder / "input.csv"
        keys = ("ticker", "fiscal_year", "analysis_mode", "training_label",
                "accounting_framework", "statement_scope", *FEATURES)
        with path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=keys)
            writer.writeheader()
            for company in range(firms):
                for year in (2013, 2014, 2015):
                    writer.writerow({
                        "ticker": str(2300 + company), "fiscal_year": year,
                        "analysis_mode": "retrospective", "training_label": "UNREVIEWED",
                        "accounting_framework": "TIFRS", "statement_scope": "consolidated",
                        **{name: 0.1 * company + 0.002 * year + 0.08 * j
                           + (company * j % 7) * 0.13 for j, name in enumerate(FEATURES)}
                    })
        return path

    def test_year_split(self):
        with tempfile.TemporaryDirectory() as d:
            rows, _ = read_data(self.fixture(Path(d)))
            a, b, c = split_indices(rows, "temporal", 42)
            self.assertEqual([len(x) for x in (a,b,c)], [16,16,16])

    def test_company_disjoint_split(self):
        with tempfile.TemporaryDirectory() as d:
            rows, _ = read_data(self.fixture(Path(d), 26))
            cohorts = split_indices(rows, "company_disjoint", 42)
            groups = [{rows[i]["ticker"] for i in part} for part in cohorts]
            self.assertFalse(groups[0] & groups[1])
            self.assertFalse(groups[0] & groups[2])
            self.assertFalse(groups[1] & groups[2])

    def test_missing_not_zero_or_invented(self):
        import numpy as np
        data = np.ones((20,len(FEATURES)))
        data[:,3] = np.nan
        for i in (0,1,2,4):
            data[:,i] = np.arange(20) * (i+1) * 0.1
        chosen, dropped = usable_paper_features(data)
        self.assertNotIn(3,chosen)
        self.assertIn(FEATURES[3],dropped)

    def test_reserved_case_forbidden(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.fixture(Path(d))
            path.write_text(path.read_text().replace("2300,2013", "1785,2013", 1))
            with self.assertRaisesRegex(ValueError,"reserved_case"):
                read_data(path)

    def test_unreviewed_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.fixture(Path(d))
            path.write_text(path.read_text().replace("UNREVIEWED","reviewed_normal",1))
            with self.assertRaisesRegex(ValueError,"labelled_row"):
                read_data(path)

    def test_real_small_fit_and_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            result = run(self.fixture(folder), folder/"out", rounds=2)
            self.assertEqual(result["independent_fits"],8)
            self.assertIsNone(result["selected_best_fraud_detector"])
            self.assertTrue((folder/"out"/"models"/"iforest_200_seed0.joblib").exists())
            self.assertTrue((folder/"out"/"literature_feature_sensitivity.csv").exists())


if __name__ == "__main__":
    unittest.main()
