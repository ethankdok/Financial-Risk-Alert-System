"""Literature-model view: FastAPI → Flask proxy → page renderer (in-process, no network, browser never persists).

FIXTURE tier renders synthetic engine output with the real ``historical-research.js`` functions under Node; the REAL
tier proxies the approved local archive through Flask (literature store rebuilt into a temporary file).
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from app.services.financial_research.literature_comparison import compare, compute_models
from app.services.financial_research.literature_method_registry import BENEISH_MODEL_ID, DECHOW_MODEL_ID
from app.services.financial_research.service import ResearchConfig, ResearchService
from tests.test_literature_models import DATABASE, HAS_REAL, RAW, ROOT, fixture_observations, literature_snapshot
from tests.test_research_ui_chain import ChainMixin, render


def synthetic_compare(observations=None):
    computed = compute_models(literature_snapshot(observations), [BENEISH_MODEL_ID, DECHOW_MODEL_ID])
    return {**compare(computed), "models": computed}


def check_safe(test: unittest.TestCase, html: str) -> None:
    test.assertNotIn("低風險", html)
    test.assertNotIn("風險低", html)
    test.assertNotIn("<script", html.lower())
    for anchor in re.findall(r"<a [^>]+>", html):
        test.assertIn('rel="noopener noreferrer"', anchor)


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page renderer")
class LiteratureRenderFixtureTests(unittest.TestCase):
    def test_side_by_side_heatmap_detail_and_registry_render(self) -> None:
        from app.services.financial_research.literature_inputs import mapping_payload
        from app.services.financial_research.literature_method_registry import registry_payload

        data = synthetic_compare()
        html = render({"literature": data, "literatureYear": {"data": data, "year": 2015},
                       "literatureModels": {**registry_payload(), "input_mapping": mapping_payload()}})
        for view in html.values():
            check_safe(self, view)
        self.assertIn("hindsight=true", html["literature"])
        self.assertIn("-2.243743", html["literature"])
        self.assertIn("不是台灣校準的舞弊機率", html["literature"])
        self.assertIn("方法待負責人核准", html["literature"])
        self.assertIn("ProceedsFromLongTermDebt", html["literatureYear"])
        self.assertIn("t-2", html["literatureYear"])
        self.assertIn("0.0037", html["literatureModels"])
        self.assertIn("Table 7 Panel A", html["literatureModels"])

    def test_incomplete_states_and_escaping(self) -> None:
        data = synthetic_compare(fixture_observations(drop={"DepreciationExpense"},
                                                      overrides={"ProceedsFromLongTermDebt": 0}))
        data["models"]["results"][BENEISH_MODEL_ID][0]["paper_variant"] = '<img src=x onerror="alert(1)">'
        html = render({"literature": data, "literatureYear": {"data": data, "year": 2015}})
        check_safe(self, html["literature"] + html["literatureYear"])
        self.assertNotIn("<img", html["literatureYear"])
        self.assertIn("&lt;img", html["literatureYear"])
        self.assertIn("發行事件無證據", html["literature"])
        self.assertIn("無（不以 0 代替）", html["literatureYear"])
        self.assertIn("可比較年度少於 2 年", html["literature"])


@unittest.skipUnless(HAS_REAL and shutil.which("node"), "approved local archive and node are required")
class LiteratureRealChainTests(ChainMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from scripts.ingest_literature_inputs import run

        cls.tmp = tempfile.TemporaryDirectory()
        store = str(Path(cls.tmp.name) / "literature_inputs.sqlite3")
        run("1785", database=str(DATABASE), raw_root=str(RAW), store_path=store, dry_run=False)
        cls.service = ResearchService(ResearchConfig(database=str(DATABASE), raw_root=str(RAW),
                                                     conference_root=str(ROOT / "data" / "historical-conference-pdfs"),
                                                     literature_database=store))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def setUp(self) -> None:
        self.start_chain()

    def tearDown(self) -> None:
        self.stop_chain()

    def test_proxy_parity_never_persists_and_renders(self) -> None:
        models = self.web.get("/api/research/literature/models")
        self.assertEqual(models.get_json(), {"success": True, "data": self.api.get("/api/v1/research/literature/models").json()})
        params = {"analysis_mode": "RETROSPECTIVE_FORENSIC", "version_policy": "original_only", "start_year": "2011",
                  "end_year": "2015", "persist": "true", "path": "/etc"}
        coverage = self.web.get("/api/research/cases/1785/literature/coverage", query_string=params)
        self.assertEqual(coverage.status_code, 200)
        self.assertNotIn("persist", self.seen[-1][1])
        direct = self.api.get("/api/v1/research/cases/1785/literature/coverage",
                              params={k: v for k, v in params.items() if k not in ("persist", "path")})
        self.assertEqual(coverage.get_json()["data"], direct.json())
        body = {"ticker": "1785", "analysis_mode": "RETROSPECTIVE_FORENSIC", "version_policy": "latest_available",
                "start_year": 2011, "end_year": 2025, "persist": True}
        proxied = self.web.post("/api/research/literature/compare", json=body)
        self.assertEqual(proxied.status_code, 200)
        self.assertFalse(proxied.get_json()["data"]["persisted"])
        self.assertFalse(json.loads(self.seen[-1][2])["persist"])
        direct = self.api.post("/api/v1/research/literature/compare", json={**body, "persist": False}).json()
        self.assertEqual(proxied.get_json()["data"]["run_id"], direct["run_id"])
        self.assertEqual(proxied.get_json()["data"]["output_digest"], direct["output_digest"])
        text = json.dumps(direct, ensure_ascii=False)
        self.assertNotIn("raw_storage_path", text)
        self.assertNotRegex(text, r"[A-Za-z]:\\\\|data/historical_audit/raw")
        html = render({"literature": direct["result"], "literatureYear": {"data": direct["result"], "year": 2015},
                       "literatureModels": models.get_json()["data"]})
        for view in html.values():
            check_safe(self, view)
        self.assertIn("-2.240182", html["literature"])
        self.assertIn("source_unavailable", json.dumps(direct["result"]["models"]["counts"]))

    def test_errors_pass_through_the_proxy(self) -> None:
        base = {"ticker": "1785", "analysis_mode": "RETROSPECTIVE_FORENSIC", "version_policy": "latest_available"}
        cases = [
            (self.web.post("/api/research/literature/compare",
                           json={**base, "analysis_mode": "CURRENT_EVIDENCE_RECONCILIATION"}), 409),
            (self.web.post("/api/research/literature/compute", json={**base, "version_policy": "earliest_available",
                                                                     "model_ids": [BENEISH_MODEL_ID]}), 422),
            (self.web.post("/api/research/literature/compute", json=base), 422),
            (self.web.post("/api/research/literature/compare", json={**base, "analysis_mode": "STRICT_AS_OF"}), 422),
            (self.web.post("/api/research/literature/compare", json={**base, "ticker": "2330"}), 404),
            (self.web.post("/api/research/literature/delete", json=base), 400),
            (self.web.post("/api/research/literature/compare", json={**base, "ticker": "../x"}), 400),
            (self.web.get("/api/research/cases/x1/literature/coverage"), 400),
        ]
        for response, status in cases:
            self.assertEqual(response.status_code, status, response.get_data(as_text=True)[:300])
        strict = self.web.post("/api/research/literature/compare",
                               json={**base, "analysis_mode": "STRICT_AS_OF", "cutoff_at": "2016-05-13T00:00:00+08:00",
                                     "start_year": 2011, "end_year": 2015})
        self.assertEqual(strict.status_code, 200)
        self.assertEqual(strict.get_json()["data"]["result"]["models"]["status"], "insufficient_point_in_time_evidence")


if __name__ == "__main__":
    unittest.main()
