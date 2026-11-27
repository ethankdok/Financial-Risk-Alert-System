import unittest
from model_workbench import run_workbench
class WorkbenchTests(unittest.TestCase):
    def test_training_and_shap(self):
        for m in ("lr","dt","rf"):
            d=run_workbench({"algorithm":m,"smote":True})
            r=d["training"]; p=d["prediction"]
            self.assertEqual(d["data_mode"],"synthetic_workbench")
            self.assertEqual(sum(map(sum,r["confusion_matrix"])),r["test_count"])
            self.assertEqual(*r["training_after"])
            self.assertAlmostEqual(p["base_value"]+sum(x["shap"] for x in p["contributions"]),p["prediction"],places=9)
            self.assertTrue(0<=d["text_analysis"]["jsd"]<=1)
            self.assertEqual(len(d["text_analysis"]["topics"]),3)
            self.assertEqual(len(r["training_preview"]),12)
    def test_no_smote_and_identical_text(self):
        d=run_workbench({"smote":False,"prior_text":"財務資訊內部控制","current_text":"財務資訊內部控制"})
        self.assertEqual(d["training"]["training_before"],d["training"]["training_after"])
        self.assertAlmostEqual(d["text_analysis"]["jsd"],0)
        self.assertAlmostEqual(d["text_analysis"]["cosine"],1)
    def test_bad_request(self):
        with self.assertRaises(ValueError):run_workbench({"algorithm":"unknown"})
