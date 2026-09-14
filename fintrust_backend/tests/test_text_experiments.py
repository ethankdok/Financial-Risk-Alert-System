from __future__ import annotations

import unittest

from app.services.text_experiments import (
    binary_classification_report,
    cohens_kappa,
    multilabel_report,
    spearman_correlation,
    summarize_annotation_quality,
)
from app.services.text_intelligence import TfidfNaiveBayesClassifier


class TextExperimentTests(unittest.TestCase):
    def test_binary_classification_report(self) -> None:
        report = binary_classification_report([1, 1, 0, 0], [1, 0, 0, 0])

        self.assertEqual(report.precision, 1.0)
        self.assertEqual(report.recall, 0.5)
        self.assertGreater(report.f1, 0.6)
        self.assertIn("1", report.confusion_matrix)

    def test_multilabel_report(self) -> None:
        report = multilabel_report(
            [{"outlook", "revenue_orders"}, {"governance"}],
            [{"outlook", "demand_inventory"}, {"governance"}],
        )

        self.assertIn("per_topic", report)
        self.assertGreater(report["micro_f1"], 0)
        self.assertIn("outlook", report["per_topic"])

    def test_cohens_kappa(self) -> None:
        value = cohens_kappa(["1", "1", "0", "0"], ["1", "1", "0", "1"])

        self.assertGreater(value, 0)
        self.assertLess(value, 1)

    def test_spearman_correlation(self) -> None:
        self.assertEqual(spearman_correlation([0.1, 0.3, 0.9], [0, 1, 2]), 1.0)

    def test_annotation_quality_requires_paired_samples(self) -> None:
        rows = [
            {"sample_id": "a", "relevant_label": "1"},
            {"sample_id": "b", "relevant_label": "0"},
        ]
        summary = summarize_annotation_quality(rows)

        self.assertIsNone(summary["cohens_kappa_relevance"])

    def test_tfidf_naive_bayes_training_infrastructure(self) -> None:
        classifier = TfidfNaiveBayesClassifier()
        classifier.fit([
            ("revenue growth and customer orders improved", "relevant"),
            ("inventory correction is ending", "relevant"),
            ("thank you operator", "irrelevant"),
            ("welcome to the conference", "irrelevant"),
        ])

        probabilities = classifier.predict_proba("customer orders improved")

        self.assertGreater(probabilities["relevant"], probabilities["irrelevant"])


if __name__ == "__main__":
    unittest.main()

