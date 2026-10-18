"""Offline coverage for scalable FinMind stratification, resume, quota and no-label policies."""
from __future__ import annotations
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml import finmind_scaled_cohort as mod
from research.financial_ml import finmind_bulk_stage as original


class ScaledCohortTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.source=self.root/'universe.csv'
        self.rows=[]
        for i in range(72):
            ticker='2330' if i==0 else str(3000+i)
            self.rows.append({
                'ticker':ticker,'company_name':f'issuer {i}',
                'industry_category':'半導體業' if i<18 else f'非金融產業{i%18:02d}',
                'market':'twse' if i%2 else 'tpex',
                'source_snapshot_date':'2026-10-18',
                'historical_eligibility':'UNVERIFIED',
                'normal_label_status':'UNREVIEWED',
            })
        self.save()

    def save(self):
        with self.source.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=mod.FIELDS)
            w.writeheader();w.writerows(self.rows)

    def make_cohort(self):
        mod.plan(self.source,self.root/'plan',size=36,semiconductors=6)
        return self.root/'plan'/'finmind_scaled_cohort.csv'

    def test_plan_is_reproducible_and_diverse(self):
        a=mod.plan(self.source,self.root/'plan1',size=36,semiconductors=6)
        b=mod.plan(self.source,self.root/'plan2',size=36,semiconductors=6)
        self.assertEqual(a['issuer_count'],36)
        self.assertEqual(a['semiconductor_issuer_count'],6)
        self.assertGreaterEqual(a['industry_count'],12)
        self.assertEqual(a['raw_financial_dataset_jobs'],108)
        self.assertEqual(a['network_requests'],0)
        self.assertEqual(a['cohort_sha256'],b['cohort_sha256'])
        with (self.root/'plan1'/'finmind_scaled_cohort.csv').open(encoding='utf-8') as fp:
            names=[r['ticker'] for r in csv.DictReader(fp)]
        self.assertEqual(len(names),len(set(names)))
        self.assertIn('2330',names)
        self.assertNotIn('1785',names)

    def test_plan_never_treats_companies_as_reviewed_normal(self):
        self.rows[0]['normal_label_status']='reviewed_normal'
        self.save()
        with self.assertRaisesRegex(ValueError,'label'):
            mod.plan(self.source,self.root/'bad',size=30,semiconductors=5)

    def test_strict_batch_limits_and_dry_run(self):
        cohort=self.make_cohort()
        result=mod.batch(cohort,self.root/'raw',self.root/'reports',batch_size=6,max_batches=1)
        self.assertFalse(result['execute'])
        self.assertEqual(result['expected_network_requests_at_most'],18)
        self.assertFalse((self.root/'raw').exists())
        with self.assertRaisesRegex(ValueError,'unsafe_batch_limits'):
            mod.batch(cohort,self.root/'raw',self.root/'reports',batch_size=41)

    def test_resume_skips_completed_first_chunk(self):
        cohort=self.make_cohort()
        calls=[]
        def fake(dataset,ticker,start,end,*,token=None):
            calls.append((dataset,ticker))
            return [{'stock_id':ticker,'date':'2020-12-31','type':'TotalAssets','value':100}]
        first=mod.batch(cohort,self.root/'raw',self.root/'reports',
                        batch_size=6,max_batches=1,execute=True,getter=fake)
        self.assertEqual(first['network_requests'],18)
        self.assertEqual(first['stop_reason'],'none')
        second=mod.batch(cohort,self.root/'raw',self.root/'reports',
                         batch_size=6,max_batches=1,execute=True,getter=fake)
        self.assertEqual(second['network_requests'],18)
        self.assertEqual(second['chunks_selected'],[1])
        self.assertEqual(len(calls),36)
        self.assertTrue((self.root/'reports'/'finmind_scaled_batch_000.json').is_file())
        self.assertTrue((self.root/'reports'/'finmind_scaled_batch_001.json').is_file())

    def test_quota_halts_and_next_batch_not_executed(self):
        cohort=self.make_cohort()
        def quota(dataset,ticker,start,end,*,token=None):
            raise original.QuotaOrAccessError('quota')
        report=mod.batch(cohort,self.root/'raw',self.root/'reports',
                         batch_size=6,max_batches=2,execute=True,getter=quota)
        self.assertEqual(report['network_requests'],1)
        self.assertEqual(report['stop_reason'],'incomplete_or_failed_batch')
        self.assertEqual(report['chunks_selected'],[0,1])
        self.assertFalse((self.root/'reports'/'finmind_scaled_batch_001.json').exists())

    def test_cache_corruption_does_not_overwrite(self):
        cohort=self.make_cohort()
        sample=sorted(r['ticker'] for r in mod.read_universe(cohort))[0]
        folder=self.root/'raw'/sample
        folder.mkdir(parents=True)
        path=folder/(original.DATASETS[0]+'.json')
        path.write_text('{invalid-json',encoding='utf-8')
        def forbidden(*a,**kw):
            raise RuntimeError('should stop before fetch')
        result=mod.batch(cohort,self.root/'raw',self.root/'reports',
                         batch_size=6,max_batches=1,execute=True,getter=forbidden)
        self.assertEqual(result['network_requests'],0)
        self.assertEqual(result['stop_reason'],'incomplete_or_failed_batch')
        self.assertEqual(path.read_text(),'{invalid-json')


if __name__=='__main__':
    unittest.main()
