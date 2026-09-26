from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError

from flask import Flask

from financial_routes import create_financial_blueprint
from fintrust_client import FinTrustClient


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


VERIFY_RESULT = {
    "request": {"company_code": "2330", "claim": "台積電 2025 年第三季毛利率為 59.5%"},
    "verdict": "supported",
    "reason_code": "value_match",
    "evidence": [{"evidence_id": "x", "document": "233020251016E001.pdf", "page": 4}],
}


class ClaimVerificationProxyTests(unittest.TestCase):
    def make_client(self, opener):
        client = FinTrustClient(base_url="https://api.example.test", ingestion_token="secret-token", opener=opener)
        app = Flask(__name__)
        app.register_blueprint(create_financial_blueprint(client=client))
        return app.test_client()

    def test_proxy_forwards_same_origin_request_to_fastapi(self) -> None:
        seen = {}

        def opener(request, timeout):
            seen.update(url=request.full_url, method=request.get_method(), body=json.loads(request.data),
                        headers={key.lower(): value for key, value in request.header_items()})
            return FakeHttpResponse(VERIFY_RESULT)

        response = self.make_client(opener).post(
            "/api/financial/claims/verify",
            json={"company_code": "2330", "claim": "台積電 2025 年第三季毛利率為 59.5%"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "data": VERIFY_RESULT})
        self.assertEqual(seen["url"], "https://api.example.test/api/v1/financial/claims/verify")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["body"], {"company_code": "2330", "claim": "台積電 2025 年第三季毛利率為 59.5%"})
        self.assertNotIn("x-ingestion-token", seen["headers"])

    def test_empty_input_is_rejected_without_backend_call(self) -> None:
        calls = []
        client = self.make_client(lambda request, timeout: calls.append(request))
        for body in ({"company_code": "2330", "claim": " "}, {"claim": "毛利率 59.5%"}, {}):
            with self.subTest(body=body):
                response = client.post("/api/financial/claims/verify", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["success"])
        self.assertEqual(calls, [])

    def test_backend_errors_are_mapped_safely(self) -> None:
        def opener(request, timeout):
            raise HTTPError(request.full_url, 500, "boom", {}, io.BytesIO(b'{"detail":"internal"}'))

        response = self.make_client(opener).post(
            "/api/financial/claims/verify", json={"company_code": "2330", "claim": "台積電毛利率 59.5%"},
        )
        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertNotIn("secret-token", json.dumps(payload))

        def unreachable(request, timeout):
            raise TimeoutError("timed out")

        timeout = self.make_client(unreachable).post(
            "/api/financial/claims/verify", json={"company_code": "2330", "claim": "台積電毛利率 59.5%"},
        )
        self.assertEqual(timeout.status_code, 502)


if __name__ == "__main__":
    unittest.main()
