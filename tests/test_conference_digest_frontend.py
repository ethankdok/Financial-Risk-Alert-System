from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from flask import Flask

from financial_routes import create_financial_blueprint
from fintrust_client import FinTrustClient
from tests.test_claim_verification_proxy import FakeHttpResponse

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "fintrust_backend"
FIXTURE_DIR = BACKEND / "tests" / "fixtures" / "conference_digest_2454" / "2454" / "2025"


def fixture_digest() -> dict:
    """Digest of the archived 2454 2025Q3 MOPS deck, built by the backend service.

    Runs in a subprocess: importing the backend ``app`` package here would shadow
    the Flask ``app`` module for every later test in this process.
    """
    script = "\n".join([
        "import json, pathlib, sys",
        "from app.services.conference_document_digest import build_document_digest",
        f"folder = pathlib.Path({str(FIXTURE_DIR)!r})",
        "manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))",
        "document = next(item for item in manifest['documents'] if item['filename'] == '245420251031M001.pdf')",
        "pages = json.loads((folder / '245420251031M001.pages.json').read_text(encoding='utf-8'))",
        "semantic = json.loads((folder / '245420251031M001.semantic.json').read_text(encoding='utf-8'))",
        "digest = build_document_digest('2454', document, pages, semantic, listing_url=manifest['listing_url'])",
        "sys.stdout.buffer.write(json.dumps(digest, ensure_ascii=False).encode('utf-8'))",
    ])
    completed = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, capture_output=True, check=True, timeout=120)
    return json.loads(completed.stdout.decode("utf-8"))


LEGACY_ITEM = {
    "title": "2026Q2 法說會",
    "status": "available",
    "conference_date": "2026-07-30",
    "summary": "公司官方 IR 法說會資料。",
    "source_url": "https://www.mediatek.com/zh-tw/investor-relations",
    "extracted_topics": ["營收", "毛利率"],
    "related_metrics": ["revenue"],
    "document_extract_status": "metadata_only",
    "limitations": ["僅有 metadata"],
}


def script_segment(js: str, start: str, end: str) -> str:
    return js[js.index(start):js.index(end, js.index(start))]


class ConferenceDigestScriptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (ROOT / "script.js").read_text(encoding="utf-8")
        self.digest_code = script_segment(self.js, "  const DIGEST_STATUS_LABELS = ", "  const renderFinancialEvidence = ")

    def test_digest_rendering_is_wired(self) -> None:
        for name in ("appendConferenceDigest", "appendDigestProvenance", "appendDigestSection", "appendTechnicalDetails"):
            self.assertIn(f"const {name} = ", self.js)
        self.assertIn("item.document_digest", self.digest_code)
        self.assertIn("card.conference_document_digest", self.digest_code)
        self.assertIn("查看原始證據 / Provenance", self.digest_code)
        self.assertIn("官方文件摘要 Official Document Summary", self.digest_code)

    def test_digest_code_is_dom_safe_and_separate_from_jsd(self) -> None:
        self.assertNotRegex(self.digest_code, r"innerHTML|insertAdjacentHTML|outerHTML")
        self.assertNotRegex(self.digest_code, r"(?i)\bjsd\b|cosine")

    def test_mops_post_form_is_never_turned_into_a_link(self) -> None:
        self.assertNotIn("FileDownLoad", self.digest_code)
        self.assertNotIn("download_form", self.digest_code)
        self.assertIn("safeHttpsLink(source.listing_url", self.digest_code)

    def test_legacy_fields_still_rendered_without_digest(self) -> None:
        for field in ("item.extracted_topics", "item.related_metrics", "item.document_extract_status", "item.limitations",
                      "item.summary || item.raw_text || item.document_text_preview"):
            self.assertIn(field, self.digest_code)

    def test_styles_exist(self) -> None:
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        for selector in (".financial-digest{", ".financial-digest-warning{", ".financial-official-group-wide{"):
            self.assertIn(selector, css)


@unittest.skipUnless(shutil.which("node"), "node is required to execute script.js render functions")
class ConferenceDigestRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.digest = fixture_digest()

    def render(self, items: list[dict]) -> dict:
        completed = subprocess.run(
            ["node", str(ROOT / "tests" / "frontend_render_harness.js")],
            input=json.dumps({"items": items}, ensure_ascii=False).encode("utf-8"),
            capture_output=True, check=True, timeout=60,
        )
        return json.loads(completed.stdout.decode("utf-8"))

    def test_renders_structured_summary_with_provenance(self) -> None:
        item = {**LEGACY_ITEM, "title": "2025Q3 法說會", "document_digest": self.digest, "summary_status": "available"}
        output = self.render([item])
        html, text = output["html"], output["text"]
        for expected in ("官方文件摘要 Official Document Summary", "財務表現 Financial Performance", "產品與業務組合",
                         "未來展望 Outlook & Guidance", "重要量化資訊", "查看原始證據 / Provenance", "31% ± 2%",
                         "Mobile Phone", self.digest["source"]["sha256"], "245420251031M001.pdf", "文件聲明與註記"):
            self.assertIn(expected, text)
        self.assertIn("financial-official-group-wide", html)
        self.assertIn("financial-digest-evidence", html)
        self.assertNotRegex(text, r"(?i)\bjsd\b|cosine")
        # Debug metadata lives in the collapsed technical details, not the main card.
        technical = html[html.index("技術細節 Technical details"):]
        self.assertIn("topics", technical)
        self.assertNotIn("<b>topics</b>", html[:html.index("技術細節 Technical details")])
        for link in output["links"]:
            self.assertTrue(link.startswith("https://"), link)
            self.assertNotIn("FileDownLoad", link)
            self.assertNotIn("/home/html", link)
        self.assertIn(self.digest["source"]["listing_url"], output["links"])

    def test_renders_legacy_item_without_summary(self) -> None:
        output = self.render([{**LEGACY_ITEM, "summary_status": "no_matching_archive"}])
        text = output["text"]
        self.assertIn("公司官方 IR 法說會資料。", text)
        self.assertIn("2026-07-30", text)
        self.assertIn("尚無此期間的 MOPS 歸檔法說會文件", text)
        self.assertIn("技術細節 Technical details", text)
        self.assertIn("topics", text)
        self.assertNotIn("官方文件摘要 Official Document Summary", text)
        self.assertNotIn("financial-official-group-wide", output["html"])

    def test_renders_old_payload_without_new_fields(self) -> None:
        output = self.render([LEGACY_ITEM])
        self.assertIn("公司官方 IR 法說會資料。", output["text"])
        self.assertNotIn("官方文件摘要", output["text"])
        self.assertNotIn("尚無此期間", output["text"])

    def test_partial_coverage_badge_and_banner(self) -> None:
        self.assertEqual(self.digest["coverage"]["coverage_status"], "partial")
        output = self.render([{**LEGACY_ITEM, "document_digest": self.digest}])
        self.assertIn("涵蓋部分", output["text"])
        self.assertIn("摘要涵蓋部分 / Coverage partial", output["text"])
        self.assertNotIn("涵蓋完整", output["text"])
        self.assertNotIn("Coverage partial：摘要涵蓋部分", output["text"])

    def test_limited_coverage_banner(self) -> None:
        digest = json.loads(json.dumps(self.digest))
        digest["coverage"]["coverage_status"] = "limited"
        digest["coverage"]["coverage_warnings"] = ["只涵蓋 2/10 頁"]
        output = self.render([{**LEGACY_ITEM, "document_digest": digest}])
        self.assertIn("摘要涵蓋有限 / Coverage limited", output["text"])
        self.assertIn("financial-digest-warning", output["html"])

    def test_low_confidence_bullets_are_marked(self) -> None:
        digest = json.loads(json.dumps(self.digest))
        bullet = digest["sections"][0]["bullets"][0]
        bullet.update(low_confidence=True, verification_status="needs_review")
        output = self.render([{**LEGACY_ITEM, "document_digest": digest}])
        self.assertIn("is-low-confidence", output["html"])
        self.assertIn("待人工複核", output["text"])


class OfficialEvidenceCardProxyTests(unittest.TestCase):
    def test_proxy_passes_digest_fields_through_unchanged(self) -> None:
        card = {
            "schema_version": "frontend-official-evidence-card-1.1.0",
            "investor_conferences": [{**LEGACY_ITEM, "document_digest": {"period": "2025Q3", "sections": []},
                                      "summary_status": "available", "archive_identity": {"filename": "x.pdf"}}],
            "conference_document_digest": None,
        }
        app = Flask(__name__)
        app.register_blueprint(create_financial_blueprint(
            client=FinTrustClient(base_url="https://api.example.test", opener=lambda request, timeout: FakeHttpResponse(card))))
        response = app.test_client().get("/api/financial/companies/2454/official-evidence-card")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["investor_conferences"][0]["document_digest"], {"period": "2025Q3", "sections": []})
        self.assertEqual(data["investor_conferences"][0]["summary_status"], "available")
        self.assertIn("conference_document_digest", data)


if __name__ == "__main__":
    unittest.main()
