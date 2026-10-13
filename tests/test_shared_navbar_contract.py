"""Regression contract for the shared user-facing navigation.

Only the page header and contextual links are standardized; analysis DOM/JS is
not modified by this change.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "financial-integrity.html",
    "financial-integrity-case.html",
    "historical-research.html",
    "financial-evidence.html",
    "financial-nfm-evidence.html",
    "b2b-due-diligence.html",
    "b2b-watchlist.html",
)
EXPECTED_LINKS = (
    ("index.html", "首頁"),
    ("analysis.html", "資訊分析"),
    ("official.html", "公告比對"),
    ("financial-integrity.html", "財務可信度健檢"),
    ("records.html", "分析紀錄"),
    ("member.html", "會員中心"),
    ("login.html", "登入"),
    ("register.html", "註冊"),
)
HEADER = re.compile(r'<header\b[^>]*class="site-header"[^>]*>(.*?)</header>', re.S)
LINK = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
TAG = re.compile(r'<[^>]+>')


def _nav_links(html: str) -> list[tuple[str, str]]:
    match = HEADER.search(html)
    if match is None:
        raise AssertionError("Missing site-header")
    section = re.search(r'<nav\b[^>]*class="nav-links"[^>]*>(.*?)</nav>', match.group(1), re.S)
    if section is None:
        raise AssertionError("Missing nav-links")
    return [(href, TAG.sub("", label).strip()) for href, label in LINK.findall(section.group(1))]


class SharedNavbarContract(unittest.TestCase):
    def test_standalone_pages_match_homepage_navigation(self):
        homepage = _nav_links((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(homepage, list(EXPECTED_LINKS))
        for name in PAGES:
            with self.subTest(page=name):
                html = (ROOT / name).read_text(encoding="utf-8")
                self.assertEqual(_nav_links(html), homepage)
                self.assertIn('href="fintrust-shared-navbar.css"', html)
                self.assertIn('class="fintrust-related-links"', html)
                self.assertNotIn('href="member-dashboard.html"', html)
                self.assertIn('href="index.html"', html)

    def test_nav_destinations_exist(self):
        for href, _ in EXPECTED_LINKS:
            with self.subTest(href=href):
                self.assertTrue((ROOT / href).is_file(), href)

    def test_workbench_interaction_ids_unchanged(self):
        workbench = (ROOT / "financial-integrity.html").read_text(encoding="utf-8")
        for element in ("tickerSelect", "runBtn", "tab-overview", "tab-models", "tab-cross",
                        "tab-b2b", "overviewBody", "modelsBody", "crossBody", "b2bBody"):
            with self.subTest(id=element):
                self.assertIn(f'id="{element}"', workbench)
        self.assertIn('src="financial-integrity.js"', workbench)


if __name__ == "__main__":
    unittest.main()
