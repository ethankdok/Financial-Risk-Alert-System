import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from calibrate_tsmc_vendor_candidate import calibrate_clean, METHOD_VERSION

def row(period,text):
    return {"period":period,"text":text,"ticker":"2330","company":"TSMC",
            "industry":"semiconductor_foundry","language":"en",
            "document_type":"full_earnings_transcript",
            "source_page":"https://investor.tsmc.com",
            "source_pdf":"https://investor.tsmc.com/x.pdf",
            "sha256":"original-pdf-"+period}

class VersionedCandidateTest(unittest.TestCase):
    def test_normalized_variant_does_not_mutate_original(self):
        body = "revenue demand customers manufacturing outlook capacity " * 170
        rows = [
            row("2024Q1",body + " refinitiv " * 15),
            row("2024Q2",body + " lseg " * 15),
            row("2024Q3",body + " refinitiv " * 15),
            row("2024Q4",body + " lseg " * 15),
        ]
        originals = [r["text"] for r in rows]
        result=calibrate_clean(rows,"2024Q3","2024Q4",min_history=1)
        self.assertEqual([r["text"] for r in rows],originals)
        self.assertEqual(result["method"]["version"],METHOD_VERSION)
        self.assertEqual(result["source_documents"][0]["sha256"],"original-pdf-2024Q3")
        self.assertEqual(result["calibration"]["history_pair_count"],1)

if __name__=="__main__":
    unittest.main()
