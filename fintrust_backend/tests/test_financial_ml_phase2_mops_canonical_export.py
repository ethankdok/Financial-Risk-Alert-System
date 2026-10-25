"""MOPS official XBRL extractor contract, synthetic fake-source tests."""
import unittest
from research.financial_ml.phase2_mops_canonical_export import metric_observation,ALIAS

class FakeLines:
    def __init__(self,vals,blocks=None):
        self.vals=vals;self.blocks=blocks or set()
    def get(self,name,period):
        return self.vals.get((name,period)),None
    def gate(self,o):
        return ("source_identity_incomplete","synthetic_bad") if o.get("line_key") in self.blocks else None

class CanonicalMOPSTests(unittest.TestCase):
    def test_periods_and_alias_agreement(self):
        fy=2014
        vals={
            ("Assets","I:2014-12-31"):{"value":"100","line_key":"Assets"},
            ("OperatingRevenue","D:2014-01-01/2014-12-31"):
                {"value":"1000","line_key":"OperatingRevenue"},
            ("Revenue","D:2014-01-01/2014-12-31"):
                {"value":"1000.00","line_key":"Revenue"},
        }
        a=metric_observation(FakeLines(vals),fy,"total_assets")
        self.assertEqual(a[0],"OBSERVED_OFFICIAL_XBRL_LINE")
        self.assertEqual(a[1],"100")
        self.assertEqual(metric_observation(FakeLines(vals),fy,"revenue")[0],
                         "OBSERVED_OFFICIAL_XBRL_LINE")
        self.assertEqual(metric_observation(FakeLines(vals),fy,"net_income")[0],
                         "MISSING_STATEMENT_CONCEPT")

    def test_conflict_blocks_and_zero_remains_zero(self):
        p="D:2014-01-01/2014-12-31"
        vals={
            ("OperatingRevenue",p):{"value":"1000","line_key":"OperatingRevenue"},
            ("Revenue",p):{"value":"1001","line_key":"Revenue"},
        }
        self.assertEqual(metric_observation(FakeLines(vals),2014,"revenue")[0],
                         "CONFLICTING_ACCOUNT_ALIASES")
        p="I:2014-12-31"
        vals={("Assets",p):{"value":"0","line_key":"Assets"}}
        self.assertEqual(metric_observation(FakeLines(vals),2014,"total_assets")[1],"0")
        self.assertEqual(metric_observation(FakeLines(vals,{"Assets"}),2014,"total_assets")[0],
                         "AMBIGUOUS_OR_SOURCE_IDENTITY")
if __name__=="__main__":
    unittest.main()
