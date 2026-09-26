from __future__ import annotations

import json
import unittest
from pathlib import Path

from flask import Flask

from financial_routes import create_financial_blueprint
from fintrust_client import FinTrustClient
from tests.test_claim_verification_proxy import FakeHttpResponse

RESULT = {"ticker": "2330", "analysis_status": "complete", "calibration": {"status": "unavailable"},
          "metrics": {"jsd": 0.2, "cosine_similarity": 0.7}}


class OfficialDataShiftProxyTests(unittest.TestCase):
    def client(self, opener):
        app = Flask(__name__)
        app.register_blueprint(create_financial_blueprint(
            client=FinTrustClient(base_url="https://api.example.test", ingestion_token="secret-token", opener=opener)))
        return app.test_client()

    def test_forwards_to_official_bridge_without_token(self) -> None:
        seen = []

        def opener(request, timeout):
            seen.append((request.full_url, request.get_method(), json.loads(request.data),
                         {key.lower() for key, _ in request.header_items()}))
            return FakeHttpResponse(RESULT)

        client = self.client(opener)
        auto = client.post("/api/financial/data-shift/analyze", json={"company_code": "2330"})
        explicit = client.post("/api/financial/data-shift/analyze",
                               json={"company_code": "2330", "period_1": "2025Q2", "period_2": "2025Q3"})
        self.assertEqual((auto.status_code, auto.get_json()), (200, {"success": True, "data": RESULT}))
        self.assertEqual(explicit.status_code, 200)
        self.assertEqual(seen[0][:3], ("https://api.example.test/api/v1/financial/data-shift/analyze", "POST",
                                       {"company_code": "2330"}))
        self.assertEqual(seen[1][2], {"company_code": "2330", "period_1": "2025Q2", "period_2": "2025Q3"})
        self.assertTrue(all("x-ingestion-token" not in headers for *_, headers in seen))

    def test_invalid_input_rejected_before_backend(self) -> None:
        calls = []
        client = self.client(lambda request, timeout: calls.append(request))
        for body in ({"company_code": "AMT"}, {}, {"company_code": "2330", "period_1": "2025Q2"},
                     {"company_code": "2330", "period_1": "25Q2", "period_2": "25Q3"}):
            with self.subTest(body=body):
                self.assertEqual(client.post("/api/financial/data-shift/analyze", json=body).status_code, 400)
        self.assertEqual(calls, [])



class OfficialDataShiftFrontendContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_result_page_uses_official_section_without_legacy_wording(self) -> None:
        html = (self.ROOT / "result.html").read_text(encoding="utf-8")
        section = html[html.index('id="dataShiftSection"'):html.index("data-financial-evidence")]
        for word in ("STRUX", "AMT", "American Tower"):
            self.assertNotIn(word, section)
        for element in ("officialShiftTicker", "officialShiftRun", "officialShiftResult", "officialShiftStatus"):
            self.assertIn(f'id="{element}"', section)
        for legacy in ("runDataShiftButton", "driftTickerInput", "dataShiftContent"):
            self.assertNotIn(f'id="{legacy}"', html)
        self.assertIn('<script src="official-data-shift.js"></script>', html)
        self.assertIn("不等同資訊真假、詐騙認定或財務風險", section)

    def test_script_contract(self) -> None:
        js = (self.ROOT / "official-data-shift.js").read_text(encoding="utf-8")
        self.assertIn("'/api/financial/data-shift/analyze'", js)
        self.assertNotIn("/api/data-shift", js.replace("/api/financial/data-shift", ""))
        self.assertNotRegex(js, r"innerHTML|insertAdjacentHTML|outerHTML|run\.app|/api/v1/")
        self.assertIn("尚無相符歷史校準", js)
        self.assertIn("已完成文字分布量測，但目前沒有相同公司／文件類型／方法版本的足夠歷史資料，因此不判定漂移等級。", js)
        self.assertIn("if (!terms ||", js)


if __name__ == "__main__":
    unittest.main()
