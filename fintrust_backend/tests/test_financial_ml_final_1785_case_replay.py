"""1785 source/version/time/holdout final case tests (synthetic only).
No fake real historical fraud labels, no network, no model fit on 1785.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from research.financial_ml import final_1785_case_replay as study


def fake_facts(*,period="2016-11-13T21:26:22+08:00",revision="restated",
               n_per_year=9):
    rows=[]
    for year in (2013,2014,2015):
        for i,field in enumerate(study.METRICS[:n_per_year]):
            rows.append({
                "ticker":"1785","fiscal_year":str(year),
                "metric_code":field,"value":str(1000+i+year),
                "unit":"TWD","statement_scope":"consolidated",
                "accounting_framework":"TIFRS",
                "filing_version_type":revision,
                "point_in_time_eligible":"true",
                "effective_available_at":period,
            })
    return rows


def create_fake_zip(path, rows, *, as_of='2016-11-14'):
    root="fintrust_historical_research_dataset/"
    buff=io.StringIO()
    writer=csv.DictWriter(buff,fieldnames=list(rows[0]))
    writer.writeheader();writer.writerows(rows)
    with zipfile.ZipFile(path,"w") as z:
        z.writestr(root+"data/financial_facts.csv",buff.getvalue())
        z.writestr(root+"manifest.json",json.dumps({
            "mode":"strict_point_in_time",
            "case":{"ticker":"1785"},
            "parameters":{"as_of":as_of}}))


class Final1785Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.zip=Path(self.tmp.name)/"case.zip"
        create_fake_zip(self.zip,fake_facts())

    def test_actual_document_score_parsing_includes_original_and_restated(self):
        rows=study.literature_scores(study.LITERATURE_DOC.read_text(encoding="utf-8"))
        self.assertEqual(len(rows),5)
        self.assertAlmostEqual(rows[0]["beneish_m_score"],-1.730106)
        self.assertAlmostEqual(rows[1]["beneish_m_score"],-2.286269)
        self.assertAlmostEqual(rows[1]["dechow_f_score"],.892005)
        self.assertAlmostEqual(rows[2]["beneish_m_score"],-2.942811)
        self.assertAlmostEqual(rows[3]["dechow_f_score"],.984084)
        self.assertIsNone(rows[-1]["dechow_f_score"])
        self.assertTrue(all(not r["forecast_2016_may13_eligible"] for r in rows))

    def test_source_table_with_forged_complete_2015_dechow_is_rejected(self):
        text=study.LITERATURE_DOC.read_text(encoding="utf-8")
        # Inject exactly one forbidden positive 2015 F score.
        line=next(l for l in text.splitlines() if l.startswith("| 2015 | restated XBRL"))
        cells=line.split("|")
        cells[5]=" 1.123456 "
        fake="|".join(cells)
        self.assertNotEqual(line,fake)
        with self.assertRaisesRegex(ValueError,"invalid_incomplete_dechow_score"):
            study.literature_scores(text.replace(line,fake))

    def test_strict_package_sha_is_mandatory(self):
        with self.assertRaisesRegex(ValueError,"archive_sha256_not_accepted"):
            study.package_data(self.zip)

    def test_mops_2016_november_is_never_may_pre_event(self):
        fields=fake_facts()
        history,blockers=study.gate_features_for_event(fields)
        self.assertIsNone(history)
        self.assertEqual(len(blockers),36)
        self.assertEqual(sum(b["observation_status"]=="MISSING" for b in blockers),9)
        self.assertFalse(any(b["eligible_historical_input"] for b in blockers))

    def test_original_may_eligible_full_36_supports_frozen_inference(self):
        facts=fake_facts(period="2016-03-25T15:00:00+08:00",
                         revision="original",n_per_year=12)
        array,gaps=study.gate_features_for_event(facts)
        self.assertEqual(len(gaps),0)
        self.assertEqual(len(array),3)
        self.assertEqual(len(array[0]),12)

    def test_future_disclosure_claim_in_original_is_rejected(self):
        facts=fake_facts(period="2017-01-01T00:00:00+08:00",
                         revision="original",n_per_year=12)
        array,gaps=study.gate_features_for_event(facts)
        self.assertIsNone(array)
        self.assertEqual(len(gaps),36)

    def test_one_source_year_isnt_treated_as_36_features(self):
        facts=fake_facts(period="2016-03-25T15:00:00+08:00",
                         revision="original",n_per_year=12)
        facts=[r for r in facts if r["fiscal_year"]!="2015"]
        array,gaps=study.gate_features_for_event(facts)
        self.assertIsNone(array)
        self.assertEqual(len(gaps),12)

    def test_early_strict_original_package_can_unlock_only_originals(self):
        source=fake_facts(period="2016-03-25T16:00:00+08:00",
                          revision="original",n_per_year=12)
        create_fake_zip(self.zip,source,as_of="2016-05-12")
        # ONLY mock the separate verifier in this hermetic unit test. The
        # production call always runs the full original semantic validator.
        with patch.object(study,"verify_package",return_value={
                "status":"verified","mode":"strict_point_in_time"}):
            meta,rows=study.pre_event_original_zip(self.zip)
        self.assertEqual(meta["verified_original_fact_count"],36)
        x,gaps=study.gate_features_for_event(rows)
        self.assertEqual(len(gaps),0)
        self.assertEqual(len(x),3)

    def test_preevent_archive_rejects_wrong_cutoff_even_if_verified(self):
        with patch.object(study,"verify_package",return_value={
                "status":"verified","mode":"strict_point_in_time"}):
            with self.assertRaisesRegex(ValueError,"wrong_case_or_asof"):
                study.pre_event_original_zip(self.zip)

    def test_preevent_archive_refuses_duplicate_filing_inputs(self):
        source=fake_facts(period="2016-03-25T16:00:00+08:00",
                          revision="original",n_per_year=12)
        source.append(dict(source[0]))
        create_fake_zip(self.zip,source,as_of="2016-05-12")
        with patch.object(study,"verify_package",return_value={
                "status":"verified","mode":"strict_point_in_time"}):
            with self.assertRaisesRegex(ValueError,"duplicate_same_grain"):
                study.pre_event_original_zip(self.zip)

    def test_preevent_package_rejects_postevent_backfilled_fact(self):
        source=fake_facts(period="2016-12-25T16:00:00+08:00",
                          revision="original",n_per_year=12)
        create_fake_zip(self.zip,source,as_of="2016-05-12")
        with patch.object(study,"verify_package",return_value={
                "status":"verified","mode":"strict_point_in_time"}):
            with self.assertRaisesRegex(ValueError,"contaminated_after_cutoff"):
                study.pre_event_original_zip(self.zip)

    def test_source_published_november_package_evidence_stays_separate(self):
        with patch.object(study,"STRICT_SHA",study.digest(self.zip)),patch.object(
                study,"verify_package",return_value={
                    "status":"verified","mode":"strict_point_in_time"}):
            gate,manifest,rows=study.package_data(self.zip)
        self.assertEqual(gate["status"],"verified")
        self.assertEqual(len(rows),27)
        self.assertEqual(set(r["filing_version_type"] for r in rows),{"restated"})
        self.assertIsNone(study.gate_features_for_event(rows)[0])

    def test_case_identity_not_replaced_by_other_company(self):
        fake=fake_facts()
        fake[0]["ticker"]="2330"
        create_fake_zip(self.zip,fake)
        with patch.object(study,"STRICT_SHA",study.digest(self.zip)),patch.object(
                study,"verify_package",return_value={
                    "status":"verified","mode":"strict_point_in_time"}):
            with self.assertRaisesRegex(ValueError,"unexpected_identity"):
                study.package_data(self.zip)

    def test_champion_persistence_predictions_are_amounts_not_labels(self):
        import numpy as np
        import joblib
        from sklearn.preprocessing import RobustScaler
        ckpt=Path(self.tmp.name)/"annual_checkpoints"
        ckpt.mkdir()
        x=np.asarray([[float(i+j+3) for j in range(12)] for i in range(3)])
        data=np.sign(x)*np.log1p(np.abs(x))
        scaler=RobustScaler().fit(data)
        joblib.dump({"scaler":scaler,"study_only":True,
                     "features":tuple(study.METRICS),"seed":20261020},
                    ckpt/"fit_only_preprocessor.joblib")
        report={"experiment_seed":20261020,
                "annual_numeric_study":{
                    "selected_model_by_validation_only":"persistence"}}
        out=study.predict_2016_frozen_numeric(x,Path(self.tmp.name),report)
        self.assertEqual(out["target_year"],2016)
        self.assertIsNone(out["fraud_probability"])
        self.assertEqual(len(out["predicted_twd"]),12)
        for j,f in enumerate(study.METRICS):
            self.assertAlmostEqual(out["predicted_twd"][f],x[2,j])

    def test_entire_documented_case_report_is_generated_fail_closed(self):
        staging=Path(self.tmp.name)
        round3=staging/"round3";round3.mkdir()
        r3=round3/"round3_real_data_model_report.json"
        r3.write_text('{"source":"synthetic_only"}',encoding="utf-8")
        r4=staging/"round4.json";r4.write_text('{"source":"synthetic_only"}',encoding="utf-8")
        output=staging/"case_final_output"
        with patch.object(study,"ROUND3_SHA",study.digest(r3)),patch.object(
                study,"ROUND4_SHA",study.digest(r4)),patch.object(
                study,"read_round3",return_value={
                    "annual_numeric_study":{
                        "selected_model_by_validation_only":"persistence"}
                }),patch.object(study,"package_data",return_value=(
                    {"status":"verified","mode":"strict_point_in_time"},
                    {"parameters":{"as_of":"2016-11-14"}},fake_facts())):
            report=study.audit_and_report(
                data_root=staging,
                bridge_root=staging,
                round3_root=round3,
                round4_report=r4,
                strict_zip=self.zip,
                output=output)
        self.assertTrue(report["frozen_round3_training_test_1785_excluded"])
        self.assertEqual(report["strict_package_financial_fact_count"],27)
        self.assertEqual(len(report["historical_score_rows"]),5)
        self.assertEqual(
            report["frozen_round3_case_numeric_inference"]["status"],
            "PRE_EVENT_FROZEN_INFERENCE_NOT_INPUT_ELIGIBLE")
        self.assertEqual(
            report["frozen_round3_case_numeric_inference"]["blocked_feature_slots"],36)
        self.assertIsNone(report["classifier_accuracy_precision_recall_f1_auc"])
        self.assertTrue((output/"1785_case_final_report.json").exists())
        self.assertEqual(len(list(csv.DictReader(
            (output/"1785_historical_model_scores.csv").open(encoding="utf-8-sig")))),5)
        self.assertEqual(len(list(csv.DictReader(
            (output/"1785_pre_event_input_gaps.csv").open(encoding="utf-8-sig")))),36)
        with self.assertRaisesRegex(FileExistsError,"output_is_immutable"):
            with patch.object(study,"ROUND3_SHA",study.digest(r3)),patch.object(
                    study,"ROUND4_SHA",study.digest(r4)),patch.object(
                    study,"read_round3",return_value={
                        "annual_numeric_study":{
                            "selected_model_by_validation_only":"persistence"}}),patch.object(
                    study,"package_data",return_value=(
                        {"status":"verified","mode":"strict_point_in_time"},
                        {},fake_facts())):
                study.audit_and_report(
                    data_root=staging,bridge_root=staging,round3_root=round3,
                    round4_report=r4,strict_zip=self.zip,output=output)

    def test_no_forged_literature_scores_by_missing_table(self):
        text=study.LITERATURE_DOC.read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"literature_source_sections_missing"):
            study.literature_scores(text.replace("## 3. Original-filing series","## removed"))

if __name__=="__main__":
    unittest.main()
