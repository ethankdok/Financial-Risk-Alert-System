"""Synthetic API/Flask contract for separate B2B page; mocks all backend stores."""
from __future__ import annotations

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from fastapi.testclient import TestClient
from flask import Flask

from app.main import app as fastapi_app
from app.routers.integrity import get_integrity_workbench
from tests.test_integrity_phase456_dossier_evaluation import assessment

from b2b_routes import create_b2b_blueprint


class FakeWorkbench:
    def __init__(self):
        self.calls = []

    def assess(self, req):
        self.calls.append(req)
        if req.ticker == "9999":
            from app.services.integrity.service import UnsupportedTicker
            raise UnsupportedTicker("9999")
        data = assessment()
        data["ticker"] = req.ticker
        return data


class FakeClient:
    def __init__(self):
        self.calls = []

    def b2b_dossier_preview(self, body):
        self.calls.append(body)
        return {"ticker": body["ticker"], "persisted": False}


class B2BContractTests(unittest.TestCase):
    def setUp(self):
        self.workbench = FakeWorkbench()
        fastapi_app.dependency_overrides[get_integrity_workbench] = lambda: self.workbench
        self.api = TestClient(fastapi_app)

    def tearDown(self):
        self.api.close()
        fastapi_app.dependency_overrides.clear()

    def test_new_api_does_not_add_routes_under_phase1_integrity(self):
        routes = fastapi_app.openapi()["paths"]
        self.assertIn("/api/v1/b2b/dossiers/preview", routes)
        self.assertEqual(set(routes["/api/v1/b2b/dossiers/preview"]), {"post"})
        self.assertNotIn("/api/v1/integrity/b2b/dossiers/preview", routes)

    def test_preview_passes_no_persist_flag(self):
        response = self.api.post("/api/v1/b2b/dossiers/preview", json={
            "ticker": "2454", "relationship_type": "supplier", "persist": False
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["relationship"]["evidence_status"], "user_declared_unverified")
        self.assertFalse(data["persisted"])
        self.assertEqual(len(self.workbench.calls), 1)
        self.assertFalse(self.workbench.calls[0].persist)

    def test_unknown_fields_and_persist_are_rejected(self):
        for body in (
            {"ticker": "2454", "persist": True},
            {"ticker": "2454", "api_url": "https://evil.test"},
            {"ticker": "2454", "relationship_type": "detected_supplier"},
            {"ticker": "24O4"},
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.api.post("/api/v1/b2b/dossiers/preview", json=body).status_code, 422
                )

    def test_unregistered_ticker_404(self):
        r = self.api.post("/api/v1/b2b/dossiers/preview", json={"ticker": "9999"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["detail"]["error_code"], "ticker_not_supported")

    def test_flask_facade_forwards_only_whitelisted_fields(self):
        fake = FakeClient()
        flask_app = Flask(__name__)
        flask_app.register_blueprint(create_b2b_blueprint(fake))
        with flask_app.test_client() as client:
            response = client.post("/api/b2b/dossiers/preview", json={
                "ticker": "2454", "relationship_type": "potential_counterparty",
                "persist": False
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["data"]["ticker"], "2454")
            self.assertEqual(fake.calls, [{"ticker": "2454",
                                            "relationship_type": "potential_counterparty",
                                            "persist": False}])
            self.assertEqual(client.post("/api/b2b/dossiers/preview", json={
                "ticker": "2454", "persist": False, "backend_url": "https://evil.test"
            }).status_code, 400)


if __name__ == "__main__":
    unittest.main()
