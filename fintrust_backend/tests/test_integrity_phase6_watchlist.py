"""Synthetic-only multi-company watchlist contract and Flask/FastAPI tests."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from b2b_routes import create_b2b_blueprint
from app.main import app
from app.routers.integrity import get_integrity_workbench
from app.services.integrity.b2b_watchlist import preview_watchlist
from tests.test_integrity_phase456_dossier_evaluation import assessment


def two():
    first = assessment()
    second = deepcopy(first)
    second["ticker"] = "2330"
    second["company"] = "合成公司乙"
    return [first, second]


class WatchlistUnitTests(unittest.TestCase):
    def test_two_distinct_companies_are_not_a_trade_graph(self):
        result = preview_watchlist(two(), ["supplier", "customer"])
        self.assertEqual(result["count"], 2)
        self.assertEqual([d["ticker"] for d in result["dossiers"]], ["2454", "2330"])
        self.assertEqual(result["relationship_graph_inferred"], False)
        self.assertEqual(result["persisted"], False)
        self.assertIsNone(result["fraud_probability"])

    def test_five_company_limit_and_duplicates(self):
        with self.assertRaises(ValueError):
            preview_watchlist(two() * 3, ["supplier"] * 6)
        with self.assertRaises(ValueError):
            preview_watchlist([assessment(), assessment()], ["supplier", "customer"])

    def test_retrospective_case_cannot_join_current_dossier(self):
        rows = two()
        rows[0]["review_mode"] = "RETROSPECTIVE_CASE"
        with self.assertRaises(ValueError):
            preview_watchlist(rows, ["supplier", "partner"])


class WorkbenchStub:
    def __init__(self):
        self.calls = []

    def assess(self, request):
        self.calls.append(request)
        if request.ticker not in {"2454", "2330"}:
            from app.services.integrity.service import UnsupportedTicker
            raise UnsupportedTicker(request.ticker)
        data = assessment()
        data["ticker"] = request.ticker
        return data


class FlaskClientStub:
    def __init__(self):
        self.calls = []

    def b2b_watchlist_preview(self, body):
        self.calls.append(body)
        return {"count": len(body["items"]), "persisted": False}


class WatchlistApiTests(unittest.TestCase):
    def setUp(self):
        self.wb = WorkbenchStub()
        app.dependency_overrides[get_integrity_workbench] = lambda: self.wb
        self.api = TestClient(app)

    def tearDown(self):
        self.api.close()
        app.dependency_overrides.clear()

    def test_batch_is_readonly_and_independent_route(self):
        req = {"items": [
            {"ticker": "2454", "relationship_type": "supplier"},
            {"ticker": "2330", "relationship_type": "customer"}],
               "persist": False}
        response = self.api.post("/api/v1/b2b/watchlists/preview", json=req)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertTrue(all(not x.persist for x in self.wb.calls))
        self.assertNotIn("/api/v1/integrity/watchlists/preview", app.openapi()["paths"])

    def test_duplicate_company_and_malformed_fields(self):
        bodies = [
            {"items": [{"ticker": "2454"}, {"ticker": "2454"}]},
            {"items": [{"ticker": "2454"}], "persist": True},
            {"items": [{"ticker": "2454", "supplier_url": "https://example.test"}]},
            {"items": []},
            {"items": [{"ticker": "2454"}] * 6},
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(
                    self.api.post("/api/v1/b2b/watchlists/preview", json=body).status_code, 422
                )

    def test_flask_whitelist_and_no_persist(self):
        fake = FlaskClientStub()
        flask = Flask(__name__)
        flask.register_blueprint(create_b2b_blueprint(fake))
        with flask.test_client() as client:
            response = client.post("/api/b2b/watchlists/preview", json={
                "items": [{"ticker": "2454", "relationship_type": "supplier"}],
                "persist": False,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(fake.calls[0]["persist"], False)
            self.assertEqual(client.post("/api/b2b/watchlists/preview", json={
                "items": [{"ticker": "2454"}], "persist": False,
                "backend_url": "https://evil.test",
            }).status_code, 400)


if __name__ == "__main__":
    unittest.main()
