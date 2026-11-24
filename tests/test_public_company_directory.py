"""Offline regression tests for official company-directory normalization and caching."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

import company_directory as directory


class TestPublicDirectory(unittest.TestCase):
    def setUp(self):
        directory._cache.clear()

    def test_twse_normalization_filters_invalid_records(self):
        rows = [
            {"公司代號": "2330", "公司簡稱": "台積電", "公司名稱": "台灣積體電路製造股份有限公司", "產業別": "24"},
            {"公司代號": "23A0", "公司簡稱": "錯誤代碼"},
            {"公司代號": "2303", "公司簡稱": ""},
        ]
        normalized = directory._public_rows("listed", rows)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["ticker"], "2330")
        self.assertEqual(normalized[0]["name"], "台積電")
        self.assertEqual(normalized[0]["market"], "上市")
        self.assertNotIn("董事長", normalized[0])

    def test_tpex_english_keys(self):
        rows = [
            {"SecuritiesCompanyCode": "1240", "CompanyAbbreviation": "茂生農經",
             "CompanyName": "茂生農經股份有限公司", "SecuritiesIndustryCode": "33"}
        ]
        normalized = directory._public_rows("otc", rows)
        self.assertEqual(normalized[0]["ticker"], "1240")
        self.assertEqual(normalized[0]["name"], "茂生農經")
        self.assertEqual(normalized[0]["market"], "上櫃")

    def test_api_caches_and_serves_read_only_company_fields(self):
        raw = [
            {"公司代號": str(2000 + i), "公司簡稱": f"公司{i}", "公司名稱": f"公司{i}股份有限公司"}
            for i in range(125)
        ]
        app = Flask(__name__)
        app.register_blueprint(directory.create_company_directory_blueprint())
        with patch.object(directory, "_download", return_value=raw) as download:
            response = app.test_client().get("/data/companies/listed")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.get_json()), 125)
            response2 = app.test_client().get("/data/companies/listed")
            self.assertEqual(response2.status_code, 200)
            download.assert_called_once()
            self.assertEqual(app.test_client().get("/data/companies/unknown").status_code, 404)


if __name__ == "__main__":
    unittest.main()
