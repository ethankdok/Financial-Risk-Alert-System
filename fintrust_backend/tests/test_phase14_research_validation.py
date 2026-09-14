from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.acquire_phase14_official_corpus import (
    MIN_SENTENCES_FOR_INCLUSION,
    _freeze_gate_result,
    _material_event_official_text,
)


class Phase14ResearchValidationScriptTests(unittest.TestCase):
    def test_runner_creates_research_artifacts_without_human_metric_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            phase12_report = Path(tmpdir) / "phase12.json"
            output_dir = Path(tmpdir) / "phase14"
            phase12_report.write_text(json.dumps(_phase12_fixture(), ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(BACKEND_ROOT / "scripts" / "run_phase14_research_validation.py"),
                    "--phase12-report",
                    str(phase12_report),
                    "--output-dir",
                    str(output_dir),
                    "--target-annotation-size",
                    "10",
                    "--seed",
                    "7",
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("PHASE14_ENGINEERING_COMPLETE_HUMAN_GT_PENDING", result.stdout)
            summary = json.loads((output_dir / "experiment_summary.json").read_text(encoding="utf-8"))
            split = json.loads((output_dir / "split_manifest.json").read_text(encoding="utf-8"))
            annotation_csv = (output_dir / "annotation_candidates.csv").read_text(encoding="utf-8")

            self.assertEqual(summary["formal_human_ground_truth_status"], "PENDING_HUMAN_GROUND_TRUTH")
            self.assertEqual(summary["strux_status"], "STRUX_EXTERNAL_BENCHMARK_PENDING")
            self.assertTrue(split["document_leakage_prevented"])
            self.assertIn("SUGGESTION ONLY - human confirmation required", annotation_csv)
            self.assertTrue((output_dir / "model_comparison.csv").exists())
            self.assertTrue((output_dir / "drift_metrics.csv").exists())
            self.assertTrue((output_dir / "research_report.md").exists())

    def test_freeze_gate_rejects_2454_dominated_expansion(self) -> None:
        rows = [
            {"sample_id": f"2454-{index}", "ticker": "2454", "document_id": "doc-2454-a"}
            for index in range(190)
        ]
        rows.extend(
            {"sample_id": f"3711-{index}", "ticker": "3711", "document_id": "doc-3711-a"}
            for index in range(2)
        )

        result = _freeze_gate_result(rows)

        self.assertEqual(result["status"], "CORPUS_EXPANSION_PARTIAL")
        self.assertFalse(result["passed"])
        self.assertNotIn("3711", result["companies_with_substantive_text"])
        self.assertGreater(result["max_company_concentration"], 0.8)

    def test_freeze_gate_accepts_substantive_multi_company_corpus(self) -> None:
        rows = []
        rows.extend(
            {"sample_id": f"2454-{index}", "ticker": "2454", "document_id": "doc-2454-a"}
            for index in range(40)
        )
        rows.extend(
            {"sample_id": f"3711-{index}", "ticker": "3711", "document_id": "doc-3711-a"}
            for index in range(max(MIN_SENTENCES_FOR_INCLUSION, 15))
        )

        result = _freeze_gate_result(rows)

        self.assertEqual(result["status"], "ANNOTATION_DATASET_FROZEN")
        self.assertTrue(result["passed"])
        self.assertIn("2454", result["companies_with_substantive_text"])
        self.assertIn("3711", result["companies_with_substantive_text"])

    def test_material_event_title_only_is_official_but_not_full_text(self) -> None:
        class Record:
            title = "公告本公司董事會決議資本支出計畫"
            raw_text = None
            status = "available"

        text = _material_event_official_text(Record())

        self.assertEqual(text, "主旨：公告本公司董事會決議資本支出計畫")


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
                                ],
                            },
                            {
                                "document_id": "doc-b",
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
