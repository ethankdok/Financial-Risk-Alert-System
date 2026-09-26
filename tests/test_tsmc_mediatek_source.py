"""Offline checks for official link provenance and fiscal-quarter extraction."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent / "scripts"))
from build_mediatek_corpus import period_from_official_url
from discover_mediatek_transcripts import find_candidates

URL=("https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/"
     "Quarterly%20Earnings%20Release/2024/"
     "Quarterly%20Earnings%20Release-2024Q3/Transcript.pdf")

class MediaTekSourceTests(unittest.TestCase):
    def test_exact_official_period(self):
        self.assertEqual(period_from_official_url(URL),"2024Q3")
    def test_reject_official_query_without_period(self):
        self.assertIsNone(period_from_official_url("https://www.mediatek.com/Transcript.pdf"))
    def test_no_offsite_sources(self):
        self.assertIsNone(period_from_official_url("https://unofficial.test/2024Q3/Transcript.pdf"))
    def test_discovery_requires_explicit_anchor(self):
        html=f'<section><h4>Q3</h4><a href="{URL}">Transcript</a></section>'
        links=find_candidates(html,"https://www.mediatek.com/investor-relations/financial-information")
        self.assertEqual(len(links),1)
        self.assertEqual(period_from_official_url(links[0]["href"]),"2024Q3")

if __name__=="__main__":unittest.main()
