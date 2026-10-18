"""No-network contract tests for the 15-variable literature adapter."""
from __future__ import annotations
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import literature_dataset as m


def example_model(names, missing=None):
    components = []
    for i, name in enumerate(names):
        valid = name != missing
        components.append({
            "variable": name,
            "status": "computed" if valid else "not_computable",
            "value_exact": str(i + 1) if valid else None,
            "reasons": [] if valid else [{"code": "missing_input"}]
        })
    return {"status": "not_computable" if missing else "computed",
            "score": None if missing else "2.5",
            "components": components}


class LiteratureFeatureContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "acquisition_results.json"

    def fixture(self, ticker, year=2013, status="validated"):
        return {
            "ticker": ticker, "fiscal_year": year, "status": status,
            "statement_scope": "consolidated", "accounting_framework": "TIFRS",
            "source_kind": "mops_xbrl_instance",
            "filing_version_id": "f123", "filing_version_type": "unknown_revision",
            "content_hash": "a" * 64, "archive_path": f"{ticker}/{year}FY/placeholder.xml"
        }

    def test_published_feature_set_is_eight_plus_seven(self):
        self.assertEqual(len(m.BENEISH), 8)
        self.assertEqual(len(m.DECHOW), 7)
        self.assertEqual(len(m.FEATURES), 15)
        self.assertEqual(len(set(m.FEATURES)), 15)
        self.assertIn("b_TATA", m.FEATURES)
        self.assertIn("d_issue", m.FEATURES)

    def test_manifest_never_uses_reserved_1785(self):
        self.path.write_text(json.dumps({"outcomes": {
            "1785:2013": self.fixture("1785"),
            "2330:2013": self.fixture("2330"),
            "2454:2013": self.fixture("2454", status="source_unavailable")
        }}), encoding="utf-8")
        valid, reasons = m.checked_manifest(self.path)
        self.assertEqual([r["ticker"] for r in valid], ["2330"])
        self.assertEqual(reasons["reserved_case_excluded"], 1)
        self.assertEqual(reasons["not_validated"], 1)

    def test_identity_mismatch_never_admitted(self):
        self.path.write_text(json.dumps({"outcomes": {
            "2303:2013": self.fixture("2330")
        }}), encoding="utf-8")
        valid, reasons = m.checked_manifest(self.path)
        self.assertEqual(valid, [])
        self.assertEqual(reasons["manifest_identity_mismatch"], 1)

    def test_missing_published_input_remains_blank_not_zero(self):
        item = self.fixture("2330")
        b = example_model(m.BENEISH, missing="AQI")
        d = example_model(m.DECHOW, missing="issue")
        row, errors = m.model_features(item, b, d)
        self.assertEqual(row["components_computed"], 13)
        self.assertEqual(row["b_AQI"], "")
        self.assertEqual(row["d_issue"], "")
        self.assertEqual(row["beneish_m_score"], "")
        self.assertEqual(row["dechow_f_score"], "")
        self.assertEqual(row["training_label"], "UNREVIEWED")
        self.assertEqual({e["variable"] for e in errors}, {"b_AQI", "d_issue"})

    def test_complete_model_values_retained_without_retraining(self):
        row, errors = m.model_features(self.fixture("2330"),
            example_model(m.BENEISH), example_model(m.DECHOW))
        self.assertEqual(row["components_computed"], 15)
        self.assertEqual(row["beneish_m_score"], "2.5")
        self.assertEqual(row["dechow_f_score"], "2.5")
        self.assertEqual(errors, [])

    def test_missing_component_definition_fails_closed(self):
        b = example_model(m.BENEISH)
        b["components"] = b["components"][1:]
        with self.assertRaisesRegex(ValueError, "method_missing_component"):
            m.model_features(self.fixture("2330"), b, example_model(m.DECHOW))


if __name__ == "__main__":
    unittest.main()
