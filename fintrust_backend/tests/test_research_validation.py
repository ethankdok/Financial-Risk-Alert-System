"""Isolated tests: do not connect to any production datastore."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers.research_validation import router


class ResearchValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"RESEARCH_RESULTS_DIR": self.tmp.name})
        self.env.start()
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.periods = [f"{year}Q{q}" for year in (2024, 2025) for q in range(1, 5)]
        self.hashes = {p: f"{i + 1:064x}" for i, p in enumerate(self.periods)}
        self.baseline = [{
            "before": self.periods[i], "after": self.periods[i+1],
            "jsd": .20, "cosine": .80,
        } for i in range(7)]
        self.fixed = [{
            "before": self.periods[i], "after": self.periods[i+1],
            "raw_pairwise": .80, "clean_pairwise": .85,
            "raw_fixed": .75, "clean_fixed": .82,
        } for i in range(7)]
        for company, prefix in (("TSMC", "tsmc"), ("MediaTek", "mediatek")):
            history = {"documents": [{"period": p, "sha256": h} for p,h in self.hashes.items()],
                       "comparisons": self.baseline, "thresholds": {"status": "EXPLORATORY_ONLY"}}
            fixed = {"documents": self.hashes, "comparisons": self.fixed}
            (self.folder / f"{prefix}_history.json").write_text(json.dumps(history))
            filename = "tsmc_cleaned_tfidf.json" if company == "TSMC" else "mediatek_tfidf_validation.json"
            (self.folder / filename).write_text(json.dumps(fixed))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_health_and_two_companies(self):
        self.assertEqual(self.client.get("/api/v1/financial/research-validation/health").status_code, 200)
        for ticker in ("2330", "2454"):
            response = self.client.get(f"/api/v1/financial/research-validation/companies/{ticker}/history")
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(len(result["comparisons"]), 7)
            self.assertEqual(result["status"], "EXPLORATORY_ONLY")
            self.assertEqual(result["comparisons"][-1]["dataset"], "holdout")
        self.assertEqual(len(self.client.get("/api/v1/financial/research-validation/comparison").json()["companies"]), 2)

    def test_rejects_hash_mismatch(self):
        path = self.folder / "mediatek_tfidf_validation.json"
        data = json.loads(path.read_text())
        data["documents"]["2025Q4"] = "f" * 64
        path.write_text(json.dumps(data))
        response = self.client.get("/api/v1/financial/research-validation/companies/2454/history")
        self.assertEqual(response.status_code, 409)

    def test_missing_file_is_unavailable(self):
        (self.folder / "tsmc_cleaned_tfidf.json").unlink()
        response = self.client.get("/api/v1/financial/research-validation/companies/2330/history")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
