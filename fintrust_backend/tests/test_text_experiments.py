from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.text_experiments import (
    FORMAL_METRICS_PENDING,
    balanced_group_aware_split,
    binary_classification_report,
    build_phase12_official_corpus,
    calculate_drift_metric_rows,
    cohens_kappa,
    corpus_rows_to_train_ready,
    deduplicate_corpus_rows,
    evaluate_relevance_model_family,
    evaluate_topic_keyword_baseline,
    experiment_manifest,
    keyword_baseline_predict,
    multilabel_report,
    spearman_correlation,
    stratified_annotation_sample,
    summarize_annotation_quality,
    to_annotation_package_rows,
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

    def test_phase12_corpus_builder_preserves_provenance_and_deduplicates(self) -> None:
        report = _phase12_fixture()
        build = build_phase12_official_corpus(report)

        self.assertEqual(build.manifest["sentence_count"], 4)
        self.assertEqual(build.manifest["duplicate_sentence_count"], 1)
        self.assertEqual(build.manifest["companies"], ["2454"])
        self.assertIn("dataset_hash", build.manifest)
        self.assertEqual(build.rows[0]["document_id"], "doc-a")
        self.assertEqual(build.rows[0]["parser_version"], "sentence-segmentation-v1.0.0")

    def test_deduplicate_corpus_rows_only_removes_same_document_duplicate(self) -> None:
        rows = [
            {"sample_id": "a", "document_id": "doc-1", "text_hash": "same", "cleaned_text": "one"},
            {"sample_id": "b", "document_id": "doc-1", "text_hash": "same", "cleaned_text": "one"},
            {"sample_id": "c", "document_id": "doc-2", "text_hash": "same", "cleaned_text": "one"},
        ]

        result = deduplicate_corpus_rows(rows)

        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual([row["sample_id"] for row in result["rows"]], ["a", "c"])

    def test_stratified_annotation_package_keeps_labels_blank_and_suggestions_marked(self) -> None:
        build = build_phase12_official_corpus(_phase12_fixture())
        sample = stratified_annotation_sample(build.rows, target_size=2, seed=7)
        package_rows = to_annotation_package_rows(sample)

        self.assertEqual(len(package_rows), 2)
        self.assertEqual(package_rows[0]["relevant_label"], "")
        self.assertIn("SUGGESTION ONLY", package_rows[0]["suggestion_warning"])
        self.assertIn("model_suggestion_only_relevant", package_rows[0])

    def test_relevance_models_use_group_aware_split_without_document_leakage(self) -> None:
        build = build_phase12_official_corpus(_phase12_fixture())
        ready = corpus_rows_to_train_ready(build.rows)
        split = {
            "train": [row for row in ready if row["document_id"] == "doc-a"],
            "test": [row for row in ready if row["document_id"] == "doc-b"],
        }

        results = evaluate_relevance_model_family(split["train"], split["test"], label_status="WEAK_LABEL")

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["model"], "keyword_rule_baseline")
        self.assertEqual(results[0]["label_status"], "WEAK_LABEL")

    def test_balanced_group_split_avoids_tiny_group_when_larger_group_matches_ratio(self) -> None:
        rows = []
        for group, count in (("large-a", 50), ("large-b", 40), ("target-sized", 20), ("tiny", 1)):
            rows.extend({"sample_id": f"{group}-{index}", "group_key": group} for index in range(count))

        split = balanced_group_aware_split(rows, test_ratio=0.2, seed=42)

        self.assertIn("target-sized", split["test_groups"])
        self.assertTrue(split["document_leakage_prevented"])
        self.assertGreater(len(split["test"]), 1)

    def test_keyword_baseline_and_topic_metrics_are_available(self) -> None:
        prediction = keyword_baseline_predict("Revenue orders and inventory demand improved.")
        self.assertEqual(prediction["predicted_relevant"], 1)
        self.assertIn("demand_inventory", prediction["topics"])
        result = evaluate_topic_keyword_baseline(
            [{"text": "Revenue orders improved.", "topics": ["revenue_orders"]}],
            label_status="WEAK_LABEL",
        )

        self.assertEqual(result["status"], "PRELIMINARY_WEAK_SUPERVISION")
        self.assertIn("per_topic", result)

    def test_drift_metric_rows_preserve_uncombined_metrics(self) -> None:
        build = build_phase12_official_corpus(_phase12_fixture())
        drift_rows = calculate_drift_metric_rows(build.rows)

        self.assertEqual(len(drift_rows), 1)
        self.assertIn("raw_text_word_jsd", drift_rows[0])
        self.assertIn("cleaned_text_word_jsd", drift_rows[0])
        self.assertIn("relevant_text_word_jsd", drift_rows[0])
        self.assertIn("topic_distribution_jsd", drift_rows[0])
        self.assertIn("semantic_tfidf_cosine_similarity", drift_rows[0])

    def test_experiment_manifest_records_formal_metric_gate(self) -> None:
        build = build_phase12_official_corpus(_phase12_fixture())
        manifest = experiment_manifest(
            experiment_id="phase14-test",
            git_commit="abc123",
            dataset_manifest=build.manifest,
            split_manifest={"document_leakage_prevented": True},
            random_seed=42,
        )

        self.assertEqual(manifest["formal_metrics_status"], FORMAL_METRICS_PENDING)
        self.assertEqual(manifest["dataset_hash"], build.manifest["dataset_hash"])

    # ------------------------------------------------------------------
    # Targeted balanced_group_aware_split tests added in Phase 14 WIP
    # ------------------------------------------------------------------

    def test_balanced_group_split_seed_determinism(self) -> None:
        """Same seed always produces the same split — no randomness leaks between calls."""
        rows = []
        for group, count in (("alpha", 30), ("beta", 20), ("gamma", 15), ("delta", 5)):
            rows.extend({"sample_id": f"{group}-{i}", "group_key": group} for i in range(count))

        split_a = balanced_group_aware_split(rows, test_ratio=0.2, seed=99)
        split_b = balanced_group_aware_split(rows, test_ratio=0.2, seed=99)

        self.assertEqual(split_a["test_groups"], split_b["test_groups"])
        self.assertEqual(split_a["train_groups"], split_b["train_groups"])
        self.assertEqual(
            [row["sample_id"] for row in split_a["test"]],
            [row["sample_id"] for row in split_b["test"]],
        )

    def test_balanced_group_split_no_document_leakage(self) -> None:
        """Train groups and test groups are strictly disjoint; every group is assigned."""
        rows = []
        for group, count in (("doc-001", 40), ("doc-002", 30), ("doc-003", 20), ("doc-004", 10)):
            rows.extend({"sample_id": f"{group}-{i}", "group_key": group} for i in range(count))

        split = balanced_group_aware_split(rows, test_ratio=0.2, seed=42)

        train_set = set(split["train_groups"])
        test_set = set(split["test_groups"])
        self.assertTrue(split["document_leakage_prevented"])
        self.assertEqual(len(train_set & test_set), 0, "Groups must not overlap between train and test")
        self.assertEqual(len(train_set | test_set), 4, "All groups must be assigned to exactly one partition")

    def test_balanced_group_split_four_doc_actual_corpus(self) -> None:
        """Exact regression for the real Phase 14 corpus (4 documents, 190 sentences).

        The stale split_manifest.json (pre-fix) had test_count=1 because the
        old code selected the 1-sentence document as the test group.  After the fix,
        balanced_group_aware_split must select faccd7d779837a6f (41 sentences,
        closest to target≈38) as the sole test group.
        """
        doc_counts = [
            ("178168eba1ddc658", 50),
            ("e16debc33eec5ea6", 98),
            ("e27408ed27de47a9", 1),   # stale split incorrectly picked this
            ("faccd7d779837a6f", 41),  # correct test group (|41-38|=3)
        ]
        rows = []
        for doc_id, count in doc_counts:
            rows.extend({"sample_id": f"{doc_id}-{i}", "group_key": doc_id} for i in range(count))

        split = balanced_group_aware_split(rows, test_ratio=0.2, seed=42)

        # target = round(190 * 0.2) = 38; faccd7d779837a6f (41) is closest
        self.assertEqual(split["test_groups"], ["faccd7d779837a6f"])
        self.assertEqual(len(split["test"]), 41)
        self.assertEqual(len(split["train"]), 149)
        self.assertTrue(split["document_leakage_prevented"])

    def test_balanced_group_split_rejects_singleton_when_closer_group_exists(self) -> None:
        """Regression guard: must not select the 1-sentence group when a better match exists.

        This specifically guards against the pre-fix behaviour that produced
        test_count=1 from a stale run.
        """
        rows = []
        for doc_id, count in (("big-a", 50), ("big-b", 40), ("big-c", 30), ("tiny", 1)):
            rows.extend({"sample_id": f"{doc_id}-{i}", "group_key": doc_id} for i in range(count))

        split = balanced_group_aware_split(rows, test_ratio=0.2, seed=42)

        # total=121, target=24; tiny (|1-24|=23) is farther than big-c (|30-24|=6)
        self.assertNotEqual(split["test_groups"], ["tiny"])
        self.assertGreater(len(split["test"]), 1)
        self.assertTrue(split["document_leakage_prevented"])

    def test_balanced_group_split_row_balance_within_tolerance(self) -> None:
        """test_count must be reasonably close to test_ratio * total_count."""
        rows = []
        for group, count in (("g1", 100), ("g2", 80), ("g3", 60), ("g4", 40), ("g5", 20)):
            rows.extend({"sample_id": f"{group}-{i}", "group_key": group} for i in range(count))

        split = balanced_group_aware_split(rows, test_ratio=0.2, seed=42)

        total = len(rows)  # 300
        target = round(total * 0.2)  # 60
        # g3 has exactly 60 sentences → distance=0 → selected first → test_count=60
        self.assertGreater(len(split["test"]), 1)
        self.assertLessEqual(
            len(split["test"]),
            target + max(count for _, count in (("g1", 100), ("g2", 80), ("g3", 60), ("g4", 40), ("g5", 20))),
            "test_count must not exceed target by more than one group size",
        )
        self.assertEqual(len(split["train"]) + len(split["test"]), total)
        self.assertTrue(split["document_leakage_prevented"])


def _phase12_fixture() -> dict[str, object]:
    sentence_base = {
        "ticker": "2454",
        "company_name": "MediaTek",
        "source_type": "investor_conference",
        "source_name": "company_official_ir",
        "source_url": "https://example.com/source",
        "document_url": "https://example.com/doc",
        "document_hash": "hash-doc",
        "retrieved_at": "2026-09-14T00:00:00+00:00",
        "parser_version": "sentence-segmentation-v1.0.0",
        "section": "management_prepared_remarks",
        "relevance_model_name": "prototype_semantic_ngram",
        "relevance_model_version": "1.0.0",
    }
    return {
        "companies": [
            {
                "ticker": "2454",
                "unified": {
                    "text_intelligence": {
                        "documents": [
                            {
                                "document_id": "doc-a",
                                "source_type": "investor_conference",
                                "period": "2025Q1",
                                "sentences": [
                                    {
                                        **sentence_base,
                                        "evidence_id": "s1",
                                        "document_id": "doc-a",
                                        "period": "2025Q1",
                                        "sentence_id": "s0001",
                                        "original_text": "Revenue orders improved because customer demand recovered.",
                                        "cleaned_text": "Revenue orders improved because customer demand recovered.",
                                        "text_hash": "h1",
                                        "relevant": True,
                                        "relevance_score": 0.9,
                                        "topics": ["revenue_orders", "demand_inventory"],
                                    },
                                    {
                                        **sentence_base,
                                        "evidence_id": "s2",
                                        "document_id": "doc-a",
                                        "period": "2025Q1",
                                        "sentence_id": "s0002",
                                        "original_text": "Thank you operator and welcome to the conference.",
                                        "cleaned_text": "Thank you operator and welcome to the conference.",
                                        "text_hash": "h2",
                                        "relevant": False,
                                        "relevance_score": 0.02,
                                        "topics": [],
                                    },
                                    {
                                        **sentence_base,
                                        "evidence_id": "s2-dup",
                                        "document_id": "doc-a",
                                        "period": "2025Q1",
                                        "sentence_id": "s0003",
                                        "original_text": "Thank you operator and welcome to the conference.",
                                        "cleaned_text": "Thank you operator and welcome to the conference.",
                                        "text_hash": "h2",
                                        "relevant": False,
                                        "relevance_score": 0.02,
                                        "topics": [],
                                    },
                                ],
                            },
                            {
                                "document_id": "doc-b",
                                "source_type": "investor_conference",
                                "period": "2025Q2",
                                "sentences": [
                                    {
                                        **sentence_base,
                                        "evidence_id": "s3",
                                        "document_id": "doc-b",
                                        "period": "2025Q2",
                                        "sentence_id": "s0001",
                                        "original_text": "Inventory digestion and capacity expansion are expected next quarter.",
                                        "cleaned_text": "Inventory digestion and capacity expansion are expected next quarter.",
                                        "text_hash": "h3",
                                        "relevant": True,
                                        "relevance_score": 0.86,
                                        "topics": ["demand_inventory", "capacity_capex", "outlook"],
                                    },
                                    {
                                        **sentence_base,
                                        "evidence_id": "s4",
                                        "document_id": "doc-b",
                                        "period": "2025Q2",
                                        "sentence_id": "s0002",
                                        "original_text": "Board governance and cash flow planning remain under review.",
                                        "cleaned_text": "Board governance and cash flow planning remain under review.",
                                        "text_hash": "h4",
                                        "relevant": True,
                                        "relevance_score": 0.7,
                                        "topics": ["governance", "cash_financing"],
                                    },
                                ],
                            },
                        ]
                    }
                },
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
