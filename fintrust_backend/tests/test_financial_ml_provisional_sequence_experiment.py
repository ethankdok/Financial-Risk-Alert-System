"""Seven strictly offline checks for experimental temporal architecture learning."""
from __future__ import annotations
import csv
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.provisional_sequence_experiment import (
    FEATURES, read_panel, samples_for_next_year, time_partition, run,
)


class TemporalArchitectureSmokeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.file = self.root / "company_year_candidate_panel.csv"
        self.rows = []
        for company in range(20):
            for year in range(2013, 2026):
                self.rows.append({
                    "ticker": str(3000+company),
                    "fiscal_year": str(year),
                    "training_admitted": "false",
                    "original_asof_verified": "false",
                    **{metric: str(int(1000 + 13*company + 23*(year-2013)
                                         + j*37 + (company*j+year)%29))
                       for j, metric in enumerate(FEATURES)}
                })
        self.save()

    def save(self):
        with self.file.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def test_yearly_partition_and_no_future_target_in_fit(self):
        panel, _ = read_panel(self.file)
        groups = time_partition(samples_for_next_year(panel, history=3))
        self.assertEqual(tuple(len(groups[k]) for k in ("fit","validation","holdout")),
                         (100,40,60))
        self.assertTrue(all(x[1] <= 2020 for x in groups["fit"]))
        self.assertTrue(all(2021 <= x[1] <= 2022 for x in groups["validation"]))
        self.assertTrue(all(x[1] >= 2023 for x in groups["holdout"]))

    def test_unverified_data_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError,"explicit_experimental"):
            run(self.file,self.root/"result",epochs=5,models=("ridge",))

    def test_reserved_1785_fails_before_learning(self):
        self.rows[0]["ticker"]="1785"
        self.save()
        with self.assertRaisesRegex(ValueError,"reserved"):
            read_panel(self.file)

    def test_missing_cells_discard_incomplete_sequence_not_zero_imputed(self):
        self.rows[0]["revenue"]=""
        self.save()
        panel,_=read_panel(self.file)
        self.assertEqual(len(samples_for_next_year(panel,history=3)),199)

    def test_duplicate_company_year_not_permitted(self):
        self.rows.append(dict(self.rows[0]))
        self.save()
        with self.assertRaisesRegex(ValueError,"duplicate_company_year"):
            read_panel(self.file)

    def test_uses_only_twelve_provisional_amounts_not_paper_variables(self):
        self.assertEqual(len(FEATURES),12)
        self.assertNotIn("DSRI",FEATURES)
        self.assertNotIn("d_rsst_acc",FEATURES)

    def test_actual_fit_all_seven_model_families_on_synthetic_panel(self):
        try:
            import torch
        except ImportError:
            self.skipTest("Optional PyTorch unavailable")
        output=self.root/"experiment"
        report=run(self.file,output,epochs=5,
                   models=("ridge","random_forest","mlp","gru","lstm","tcn","transformer"),
                   experimental_allow_unverified_data=True)
        self.assertEqual(len(report["models_trained"]),7)
        self.assertEqual(report["validation_windows"],40)
        self.assertFalse(report["fraud_detection_accuracy_measurable"])
        self.assertFalse(report["uses_Beneish_Dechow_15_variables"])
        self.assertTrue(report["reserved_1785_excluded"])
        self.assertTrue((output/"architecture_comparison_experimental.csv").is_file())
        self.assertTrue((output/"experiment_report.json").is_file())
        self.assertTrue((output/"transformer_experimental.pt").is_file())


if __name__ == "__main__":
    unittest.main()
