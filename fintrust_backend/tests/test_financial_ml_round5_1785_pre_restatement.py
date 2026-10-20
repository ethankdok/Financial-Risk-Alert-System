"""Synthetic tests for 1785 official PRE-only numerical model application."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.preprocessing import RobustScaler

from research.financial_ml import round5_1785_pre_restatement_replay as study
COMPARISON_FIELDS, PRE_VALUE_SEMANTICS = study.COMPARISON_FIELDS, study.PRE_VALUE_SEMANTICS


def synthetic_rows(metric_count=5,*,conflicting=False,missing_2014=False):
    records=[]
    metrics=list(study.METRICS[:metric_count])
    for scope in ("consolidated","individual"):
        for year in (2013,2014,2015):
            for j,key in enumerate(metrics):
                if missing_2014 and scope=="consolidated" and year==2014 and key==metrics[-1]:
                    continue
                val=Decimal(10000+1000*(year-2013)+j*300)
                corrected=val+Decimal(2500) if year==2015 else val+Decimal(25)
                row={
                    "ticker":"1785","evidence_type":"official_restatement_comparison",
                    "period":f"{year}FY","fiscal_year":str(year),
                    "statement_scope":scope,"accounting_framework":"TIFRS",
                    "statement_type":"income_statement",
                    "pre_label":key,"post_label":key,
                    "canonical_metric":key,"sign_factor":"1",
                    "pre_restatement_value":str(val),
                    "post_restatement_value":str(corrected),
                    "difference":str(corrected-val),
                    "published_unit":"TWD_thousand",
                    "disclosed_at":"2016-11-13T21:26:22+08:00",
                    "availability_status":"verified_official_notice",
                    "point_in_time_eligible":"true",
                    "pre_value_semantics":PRE_VALUE_SEMANTICS,
                    "source_url":"https://mops.twse.com.tw/mock",
                    "announcement_key":f"notice_{scope}",
                    "content_hash":"a"*64,
                }
                records.append(row)
        # Fill counts to fixed 79 per scope with irrelevant financial labels
        scoped=sum(r["statement_scope"]==scope for r in records)
        for i in range(79-scoped):
            records.append({
                **records[0],
                "fiscal_year":"2011","period":"2011FY",
                "statement_scope":scope,
                "accounting_framework":"TW_GAAP",
                "canonical_metric":f"unmapped_metric_{i}_{scope}",
                "pre_label":f"irrelevant{i}",
                "post_label":f"irrelevant{i}",
            })
    if conflicting:
        records[0]["difference"]="10000"
    assert len(records)==158
    return records


def fake_zip(path,rows):
    with zipfile.ZipFile(path,"w") as z:
        root="fintrust_historical_research_dataset/"
        m={"mode":"strict_point_in_time",
           "case":{"ticker":"1785"},
           "parameters":{"as_of":"2016-11-14"}}
        z.writestr(root+"manifest.json",json.dumps(m))
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=COMPARISON_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        z.writestr(root+"data/restatement_comparisons.csv",output.getvalue())


class TestPreRestatementReplay(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.zip=self.root/"synthetic_notice.zip"
        fake_zip(self.zip,synthetic_rows())

    def audited(self):
        return (
            patch.object(study,"STRICT_SHA",study.digest(self.zip)),
            patch.object(study,"verify_package",
                         return_value={"status":"verified",
                                       "mode":"strict_point_in_time"}),
        )

    def bundle(self):
        x=np.asarray([[float(i+j+1) for j in range(12)] for i in range(3)])
        z=np.sign(x)*np.log1p(np.abs(x))
        scaler=RobustScaler().fit(z)
        return {"scaler":scaler,"seed":20261020,
                "study_only":True,"features":tuple(study.METRICS)}

    def test_only_pre_restated_is_feature_not_post(self):
        a,b=self.audited()
        with a,b:
            pairs,sources,meta=study.official_pre_pairs(self.zip)
        self.assertEqual(len(pairs),15)
        self.assertEqual(meta["source_scope_counts"],{"consolidated":79,"individual":79})
        self.assertEqual(pairs[(2015,"revenue")][0],Decimal(12000000))
        self.assertEqual(pairs[(2015,"revenue")][1],Decimal(14500000))
        out=study.replay(pairs,sources,self.bundle())
        target=next(r for r in out if r["forecast_year"]==2016 and r["metric"]=="revenue")
        self.assertEqual(target["forecast_twd"],"12000000")
        self.assertEqual(target["observed_pre_twd"],None)
        self.assertEqual(target["model_fitted_with_1785"],"false")
        self.assertEqual(len([r for r in out if r["forecast_year"]==2016]),5)
        y2015=next(r for r in out if r["forecast_year"]==2015 and r["metric"]=="revenue")
        self.assertEqual(y2015["forecast_twd"],"11000000")
        self.assertEqual(y2015["observed_pre_twd"],"12000000")
        self.assertEqual(y2015["observed_post_twd"],"14500000")
        self.assertEqual(y2015["error_vs_pre_twd"],"1000000")
        self.assertEqual(y2015["restatement_adjustment_twd"],"2500000")

    def test_notice_disclosed_after_revelation_never_claims_asof(self):
        a,b=self.audited()
        with a,b:
            _,sources,meta=study.official_pre_pairs(self.zip)
        self.assertTrue(all(s["disclosed_at"].startswith("2016-11-13") for s in sources.values()))
        self.assertEqual(study.STUDY_MODE,"RETROSPECTIVE_PRE_RESTATEMENT_NOTICE_REPLAY")

    def test_negative_twd_amount_applies_notice_sign(self):
        rows=synthetic_rows()
        record=next(r for r in rows if r["fiscal_year"]=="2015" and r["statement_scope"]=="consolidated" and r["canonical_metric"]=="net_income")
        record["sign_factor"]="-1"
        fake_zip(self.zip,rows)
        a,b=self.audited()
        with a,b:
            values,_,_=study.official_pre_pairs(self.zip)
        self.assertLess(values[(2015,"net_income")][0],0)

    def test_forged_official_pre_post_difference_is_rejected(self):
        fake_zip(self.zip,synthetic_rows(conflicting=True))
        a,b=self.audited()
        with a,b:
            with self.assertRaisesRegex(ValueError,"difference_inconsistent"):
                study.official_pre_pairs(self.zip)

    def test_missing_metric_does_not_impute_zero_or_post(self):
        fake_zip(self.zip,synthetic_rows(missing_2014=True))
        a,b=self.audited()
        with a,b:
            values,sources,_=study.official_pre_pairs(self.zip)
        r=study.replay(values,sources,self.bundle())
        last=study.METRICS[4]
        self.assertFalse(any(x["metric"]==last and x["forecast_year"]==2016 for x in r))
        self.assertTrue(all(x["model_fitted_with_1785"]=="false" for x in r))

    def test_derived_operating_income_uses_pre_expenses_not_post(self):
        data=synthetic_rows(metric_count=4)
        for row in data:
            if (row["statement_scope"]=="consolidated"
                and row["canonical_metric"]=="operating_income"):
                row["canonical_metric"]=""
                row["pre_label"]="營業費用合計"
                row["post_label"]="營業費用合計"
                row["sign_factor"]="1"
                row["pre_restatement_value"]="-900"
                row["post_restatement_value"]="-1100"
                row["difference"]="-200"
        fake_zip(self.zip,data)
        a,b=self.audited()
        with a,b:
            pairs,sources,_=study.official_pre_pairs(self.zip)
        self.assertEqual(len([k for k in pairs if k[1]=="operating_income"]),3)
        gp_pre=Decimal(data[2]["pre_restatement_value"])*1000
        self.assertEqual(pairs[(2013,"operating_income")][0],gp_pre-900000)
        self.assertEqual(pairs[(2013,"operating_income")][1],
                         Decimal(data[2]["post_restatement_value"])*1000-1100000)
        self.assertIn("_derived_pre_formula",sources[(2013,"operating_income")])
        results=study.replay(pairs,sources,self.bundle())
        predict=next(x for x in results if x["forecast_year"]==2016 and x["metric"]=="operating_income")
        self.assertEqual(predict["forecast_twd"],
                         study.exact_text(pairs[(2015,"operating_income")][0]))
        self.assertNotEqual(predict["forecast_twd"],
                            study.exact_text(pairs[(2015,"operating_income")][1]))

    def test_changing_post_only_cannot_change_2016_pre_prediction(self):
        original=synthetic_rows(metric_count=5)
        fake_zip(self.zip,original)
        a,b=self.audited()
        with a,b:
            pr,source,_=study.official_pre_pairs(self.zip)
        orig=[x for x in study.replay(pr,source,self.bundle())
              if x["forecast_year"]==2016]
        for row in original:
            if (row["fiscal_year"]=="2015"
                and row["statement_scope"]=="consolidated"
                and row["canonical_metric"]=="revenue"):
                row["post_restatement_value"]=str(
                    Decimal(row["post_restatement_value"])+2000000)
                row["difference"]=str(
                    Decimal(row["post_restatement_value"])-
                    Decimal(row["pre_restatement_value"]))
        fake_zip(self.zip,original)
        a,b=self.audited()
        with a,b:
            newp,news,_=study.official_pre_pairs(self.zip)
        altered=[x for x in study.replay(newp,news,self.bundle())
                 if x["forecast_year"]==2016]
        self.assertEqual({x["metric"]:x["forecast_twd"] for x in orig},
                         {x["metric"]:x["forecast_twd"] for x in altered})

    def test_round3_report_frozen_sha_required(self):
        artifact=self.root/"round3";artifact.mkdir()
        (artifact/"round3_real_data_model_report.json").write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"sha256_mismatch"):
            study.load_locked_persistence(artifact,{})

    def test_full_12_field_2016_numeric_baseline_supported(self):
        fake_zip(self.zip,synthetic_rows(metric_count=12))
        a,b=self.audited()
        with a,b:
            values,sources,_=study.official_pre_pairs(self.zip)
        r=study.replay(values,sources,self.bundle())
        self.assertEqual(len([x for x in r if x["forecast_year"]==2016]),12)
        self.assertEqual({x["metric"] for x in r if x["forecast_year"]==2016},set(study.METRICS))

    def test_no_overwrite_previous_replay(self):
        self.root.joinpath("result").mkdir()
        self.root.joinpath("result","report.json").write_text("evidence")
        with self.assertRaisesRegex(FileExistsError,"output_already_exists"):
            study.run(strict_zip=self.zip,data_root=self.root,
                round2_bridge_root=self.root,round3_root=self.root,
                output=self.root/"result")

    def test_end_to_end_persisted_csv_and_json(self):
        source=self.root/"round3";source.mkdir()
        (source/"round3_real_data_model_report.json").write_text(
            '{"fake":"synthetic"}',encoding="utf-8")
        real_model={"annual_numeric_study":{
            "selected_model_by_validation_only":"persistence"},
            "experiment_seed":20261020}
        result=self.root/"result"
        a,b=self.audited()
        with a,b,patch.object(study,"read_round3",return_value=real_model),patch.object(
            study,"load_locked_persistence",return_value=self.bundle()):
            r=study.run(strict_zip=self.zip,data_root=self.root,
                round2_bridge_root=self.root,round3_root=source,output=result)
        self.assertEqual(r["2016_three_year_same_feature_numeric_forecast_count"],5)
        self.assertFalse(r["2016_full_twelve_metric_vector_available"])
        self.assertIsNone(r["actual_fraud_f1_score"])
        self.assertTrue(r["post_restatement_not_used_as_feature"])
        self.assertTrue((result/"1785_pre_restatement_replay_report.json").is_file())
        with (result/"1785_frozen_persistence_pre_only_predictions.csv").open(
                encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(sum(int(x["forecast_year"])==2016 for x in rows),5)


if __name__=="__main__":
    unittest.main()
