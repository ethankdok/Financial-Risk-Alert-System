import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.source_inventory import inspect_one, inventory


class TestInventory(unittest.TestCase):
    def test_read_only_inventory_and_absent_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            database=root/'research.db'
            with sqlite3.connect(database) as conn:
                conn.executescript('''CREATE TABLE versioned_financial_facts(ticker TEXT, fiscal_year INTEGER, value REAL);
INSERT INTO versioned_financial_facts VALUES('1785',2013,7),('1785',2014,8),('2330',2014,9);''')
            result=inspect_one(database)
            self.assertEqual(result['tables'][0]['distinct_companies'],2)
            self.assertEqual(result['tables'][0]['year_range'],['2013','2014'])
            self.assertEqual(inspect_one(root/'does-not-exist.db')['status'],'absent')
            report=inventory([database],root/'report.json')
            self.assertEqual(report['status'],'read_only_local_source_inventory')
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM versioned_financial_facts').fetchone()[0],3)

if __name__=='__main__':
    unittest.main()