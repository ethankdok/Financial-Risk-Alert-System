"""Synthetic guards only. Actual 141k-label learning happens in CI separate job."""
from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from research.financial_ml.external_benchmark import enhanced_real_aaer_training as m

class AdvancedRealTrainingProtocol(unittest.TestCase):
    def rows(self):
        rs=[]
        for i in range(400):
            ticker=f"{i+5000}"
            for y in (2000,2006,2010):
                r={"gvkey":ticker,"fyear":y,
                   "misstate":int(i%4==0)}
                r.update({c:float(i+y+20) for c in m.FEATURES})
                rs.append(r)
        return pd.DataFrame(rs)

    def test_exante_lag_requires_exact_previous_year(self):
        r=self.rows()
        early=m.engineer(r)
        for col in (x+"_lag1" for x in m.LAGS):
            self.assertTrue(early[col].isna().all())
        previous=r.iloc[[0]].copy()
        previous["fyear"]=1999
        previous["sale"]=1000
        nextyear=r.iloc[[0]].copy()
        nextyear["sale"]=1300
        x=m.engineer(pd.concat([nextyear,previous]))
        self.assertEqual(float(x.iloc[-1]["sale_lag1"]),1000)
        self.assertNotIn("misstate",m.ALL_FEATURES)
        self.assertNotIn("gvkey",m.ALL_FEATURES)
        self.assertNotIn("fyear",m.ALL_FEATURES)

    def test_company_and_year_split_has_no_issuer_leak(self):
        df=m.engineer(self.rows())
        parts=m.select_split(df,"forward_year_and_issuer")
        self.assertTrue(all(
            a not in b for a,b in (
                (x,y["gvkey"].unique()) for part,p in parts.items()
                for x in p["gvkey"].unique()
                for other,y in parts.items() if other!=part)))
        self.assertLessEqual(int(parts["train"]["fyear"].max()),2004)
        self.assertTrue(parts["validation"]["fyear"].between(2005,2007).all())
        self.assertTrue(parts["test"]["fyear"].between(2008,2012).all())
        self.assertTrue(all(v["misstate"].isin([0,1]).all() for v in parts.values()))

    def test_no_oversampling_of_holdout_or_fabricated_metrics(self):
        y=np.array([0,0,0,1,1])
        p=np.array([.1,.2,.6,.7,.95])
        z=m.metric(y,p,.65)
        self.assertEqual(z["confusion"],{"TN":3,"FP":0,"FN":0,"TP":2})
        self.assertEqual(z["precision"],1)
        self.assertEqual(z["recall"],1)
        tri=m.triage(y,p,(2,3))
        self.assertEqual(tri["top_2"]["precision_at_k"],1)
        self.assertEqual(tri["top_3"]["precision_at_k"],2/3)

    def test_original_42_and_tw_9_feature_counts(self):
        self.assertEqual(len(m.FEATURES),42)
        self.assertEqual(len(m.COMMON),9)
        self.assertEqual(len(m.ALL_FEATURES),71)
        self.assertEqual(len(m.COMMON_FEATURES),18)
        self.assertEqual(len(set(m.ALL_FEATURES)),71)
        self.assertEqual(len(m.EXPERIMENTS),7)

if __name__=="__main__":
    unittest.main()
