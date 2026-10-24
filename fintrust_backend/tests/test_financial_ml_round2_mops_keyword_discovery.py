"""MOPS parsing smoke tests are synthetic; live source is tested separately."""
import unittest
from research.financial_ml.round2_mops_keyword_discovery import (
    parse_html, post_once, YEARS, KEYWORDS
)


class MopsDiscoveryTests(unittest.TestCase):
    def test_extraction_is_candidate_not_annual_positive(self):
        html = ('<html><table><tr><td>6485</td><td>點序</td>'
                '<td>公告重編本公司財務報告</td></tr></table></html>').encode()
        state, rows = parse_html(html, 114, "重編")
        self.assertEqual(state, "HTML_TABLE_QUERY_RESULT_UNVERIFIED")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "6485")
        self.assertEqual(rows[0]["issuer_year_y"], "")
        self.assertEqual(rows[0]["report_fiscal_year_verified"], "false")

    def test_lost_rows_does_not_certify_negative_windows(self):
        state, rows = parse_html(b"<html><table><tr><td>No hits</td></tr></table></html>",
                                 114, "重編")
        self.assertEqual(state, "HTML_TABLE_QUERY_RESULT_UNVERIFIED")
        self.assertEqual(rows, [])

    def test_invalid_pages_are_detected(self):
        for body in [b"<html>403</html>", "請填驗證碼".encode("utf-8")]:
            state, rows = parse_html(body, 114, "重編")
            self.assertEqual(rows, [])
            self.assertNotEqual(state, "HTML_TABLE_QUERY_RESULT_UNVERIFIED")

    def test_scope_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "out_of_scope"):
            post_once(106, "重編")
        with self.assertRaisesRegex(ValueError, "out_of_scope"):
            post_once(114, "out_of_scope_term")


if __name__ == "__main__":
    unittest.main()
