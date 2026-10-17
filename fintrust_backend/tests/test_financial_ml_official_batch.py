"""Hermetic tests: no official web calls, cloud access or production DB writes."""
from __future__ import annotations

import asyncio
import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.financial_ml.official_batch import acquire, load_candidates, request_plan


class FakeResponse:
    content = b'<xbrl>mocked</xbrl>'
    retrieved_at = datetime(2026, 10, 18, tzinfo=timezone.utc)

    def __init__(self, status='ok'):
        self.status = status
        if status != 'ok':
            self.content = None

    def metadata(self):
        return {'http_status': 200, 'retrieved_at': self.retrieved_at.isoformat()}


class FakeFetcher:
    def __init__(self, status='ok'):
        self.status = status
        self.calls = []

    async def fetch(self, url, *, expect):
        self.calls.append(url)
        return FakeResponse(self.status)


class TestOfficialBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv_path = self.root / 'plan.csv'
        with self.csv_path.open('w', newline='', encoding='utf-8') as fp:
            fields = ('ticker', 'fiscal_year', 'historical_listing_status',
                      'historical_industry_status', 'normal_label_status')
            writer = csv.DictWriter(fp, fieldnames=fields)
            writer.writeheader()
            for ticker in ('2330', '2303', '1785'):
                for year in (2013, 2014):
                    writer.writerow(dict(ticker=ticker, fiscal_year=year,
                                         historical_listing_status='UNVERIFIED',
                                         historical_industry_status='UNVERIFIED',
                                         normal_label_status='UNREVIEWED'))

    def plan(self):
        return request_plan(load_candidates(self.csv_path), ['2330'], [2013])

    def test_dry_run_does_not_call_network(self):
        f = FakeFetcher()
        report = asyncio.run(acquire(self.plan(), self.root / 'dry', fetcher=f))
        self.assertEqual(report['network_requests'], 0)
        self.assertEqual(f.calls, [])
        self.assertFalse((self.root / 'dry' / 'candidate_facts.csv').exists())

    def test_refuses_held_out_case_and_older_years(self):
        candidates = load_candidates(self.csv_path)
        with self.assertRaises(ValueError):
            request_plan(candidates, ['1785'], [2013])
        with self.assertRaises(ValueError):
            request_plan(candidates, ['2330'], [2012])
        with self.assertRaises(ValueError):
            request_plan(candidates, ['9999'], [2013])

    def test_fetch_resume_and_no_pit_claims(self):
        f = FakeFetcher()
        def process(content, ticker, year):
            return {
                'status': 'validated', 'statement_scope': 'consolidated',
                'filing_version_type': 'unknown_revision', 'validation_status': 'validated',
                'accounting_framework': 'TIFRS',
                'facts': [{'metric_code': 'revenue', 'value': '100',
                           'unit': 'TWD', 'quality_status': 'accepted',
                           'quality_notes': ['review_alias'],
                           'taxonomy_concept': 'tifrs:Revenue'}],
            }
        one = asyncio.run(acquire(self.plan(), self.root / 'run', execute=True, fetcher=f, processor=process))
        two = asyncio.run(acquire(self.plan(), self.root / 'run', execute=True, fetcher=f, processor=process))
        self.assertEqual(one['network_requests'], 1)
        self.assertEqual(two['network_requests'], 0)
        self.assertEqual(len(f.calls), 1)
        with (self.root / 'run' / 'candidate_facts.csv').open() as fp:
            rows = list(csv.DictReader(fp))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['point_in_time_eligible'], 'false')
        self.assertEqual(rows[0]['filing_version_type'], 'unknown_revision')
        self.assertEqual(rows[0]['quality_notes'], '["review_alias"]')
        self.assertEqual(one['normal_labels_created'], 0)

    def test_failed_download_does_not_fabricate_facts(self):
        f = FakeFetcher('source_unavailable')
        report = asyncio.run(acquire(self.plan(), self.root / 'fail', execute=True, fetcher=f))
        self.assertEqual(report['outcome_counts']['source_unavailable'], 1)
        with (self.root / 'fail' / 'candidate_facts.csv').open() as fp:
            self.assertEqual(len(list(csv.DictReader(fp))), 0)


if __name__ == '__main__':
    unittest.main()
