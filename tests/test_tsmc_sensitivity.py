import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sensitivity_tsmc_shift import clean_text, compare_versions


def make(p,t):
    return {"period":p,"text":t}

class RobustnessTests(unittest.TestCase):
    def test_vendor_only_preserves_other_content(self):
        self.assertEqual(clean_text("Refinitiv management revenue",remove_vendor=True),"  management revenue")
    def test_repeated_lines_only(self):
        text = ("A recurring header more than twenty five characters\n" * 4
                + "Quarterly revenue demand grows as customers expand.")
        cleaned=clean_text(text,remove_repeated=True)
        self.assertNotIn("recurring header",cleaned)
        self.assertIn("Quarterly revenue",cleaned)
    def test_each_variant_recalibrates_its_own_history(self):
        words=["revenue","semiconductor","packaging","growth","capacity","demand"]
        rows=[]
        for year in range(2017,2026):
            for q in range(1,5):
                idx=(year*4+q)%len(words)
                text=("refinitiv " * 80
                      + "long repeating page banner vendor label transcript\n" * 4
                      + ("customers manufacturing expansion outlook " * 200)
                      + ((words[idx]+" ") * (70+(q*10))))
                rows.append(make(f"{year}Q{q}",text))
        result=compare_versions(rows)
        self.assertEqual(set(result["results"]),{"original","vendor_only","repeated_lines_only","vendor_plus_repeated_lines"})
        self.assertEqual(result["results"]["original"]["history_pairs"],33)
        self.assertGreater(result["results"]["vendor_only"]["removed_chars"][0],0)
        self.assertEqual(result["results"]["original"]["removed_chars"],[0,0])

if __name__=="__main__":
    unittest.main()
