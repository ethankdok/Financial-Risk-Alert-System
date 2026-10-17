"""No network or production database access in these tests."""
import asyncio
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.financial_ml.industry_batch_runner import select, run


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.root=tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.dir=Path(self.root.name)
        self.candidates={
            (ticker,year): {'ticker':ticker,'fiscal_year':str(year),'historical_listing_status':'UNVERIFIED',
                             'historical_industry_status':'UNVERIFIED','normal_label_status':'UNREVIEWED'}
            for ticker in ('2303','2330','2454','1785') for year in (2013,2014,2015)
        }

    def test_dry_run_doesnt_invoke_acquisition(self):
        plan,meta=select(self.candidates,output_dir=self.dir,max_company_years=4)
        with patch('research.financial_ml.industry_batch_runner.acquire') as fake:
            result=asyncio.run(run(plan,meta,folder=self.dir))
        fake.assert_not_called()
        self.assertEqual(result['mode'],'dry_run')
        self.assertEqual(len(plan),4)
        self.assertEqual(result['network_requests'],0)
        self.assertNotIn('1785', {p['ticker'] for p in plan})

    def test_only_historical_candidate_years_2013_to_2015(self):
        for years in ((2012,), (2013,2013), (2014,2016)):
            with self.assertRaises(ValueError):
                select(self.candidates,years=years,output_dir=self.dir)

    def test_respects_hard_cap_and_reserved_case(self):
        for limit in (0,37):
            with self.assertRaises(ValueError):
                select(self.candidates,max_company_years=limit,output_dir=self.dir)
        with self.assertRaises(ValueError):
            select(self.candidates,tickers=['1785'],output_dir=self.dir)
        with self.assertRaises(ValueError):
            select(self.candidates,tickers=['9999'],output_dir=self.dir)

    def test_execute_chunks_not_more_than_12(self):
        extended={
            (str(ticker),year): {'ticker':str(ticker),'fiscal_year':str(year),
            'historical_listing_status':'UNVERIFIED','historical_industry_status':'UNVERIFIED',
            'normal_label_status':'UNREVIEWED'}
            for ticker in range(2300,2315) for year in (2013,2014,2015)
        }
        plan,meta=select(extended,output_dir=self.dir,max_company_years=25)
        async def fake_acquire(batch, folder, execute):
            self.assertTrue(execute)
            self.assertLessEqual(len(batch),12)
            return {'network_requests':len(batch),'outcome_counts':{'validated':len(batch)}}
        with patch('research.financial_ml.industry_batch_runner.acquire',side_effect=fake_acquire) as mocked:
            result=asyncio.run(run(plan,meta,folder=self.dir,execute=True))
        self.assertEqual(result['network_requests'],25)
        self.assertEqual(len(result['chunks']),3)
        self.assertEqual(mocked.await_count,3)
        self.assertEqual(result['normal_labels_created'],0)

    def test_rerun_skips_validated_archive_only_if_hash_verifies(self):
        from app.services.historical_audit.archive import RawEvidenceArchive
        import json
        archive=RawEvidenceArchive(self.dir/'raw')
        stored=archive.store(ticker='2303',period='2013FY',content=b'abcd',detected_format='xbrl_instance',retrieval={})
        valid={'ticker':'2303','fiscal_year':2013,'status':'validated',
               'archive_path':stored.relative_path,'content_hash':stored.content_hash}
        (self.dir/'acquisition_results.json').write_text(json.dumps({'outcomes':{'2303:2013':valid}}),encoding='utf-8')
        plan,meta=select(self.candidates,output_dir=self.dir,max_company_years=9)
        self.assertEqual(meta['verified_archives_reused'],1)
        self.assertNotIn(('2303',2013),[(x['ticker'],x['fiscal_year']) for x in plan])
        valid['content_hash']='0'*64
        (self.dir/'acquisition_results.json').write_text(json.dumps({'outcomes':{'2303:2013':valid}}),encoding='utf-8')
        _,meta=select(self.candidates,output_dir=self.dir,max_company_years=9)
        self.assertEqual(meta['verified_archives_reused'],0)


if __name__=='__main__':
    unittest.main()