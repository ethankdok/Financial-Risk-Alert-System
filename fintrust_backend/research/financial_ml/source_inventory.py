"""Read-only bounded inventory of existing local SQLite sources.

Does not read financial values or secrets, modify any database, connect to
cloud services, or treat historical-case coverage as the entire product DB.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

TABLES = ("financial_filing_versions", "versioned_financial_facts", "financial_filings", "normalized_financial_facts")
DEFAULT_PATHS = ("data/historical_audit/historical_audit.sqlite3", "data/financial_pipeline.sqlite3", "data/financial_facts.sqlite3")


def inspect_one(path):
    path = Path(path).resolve()
    if not path.is_file():
        return {"source":str(path), "status":"absent"}
    uri=path.as_uri()+"?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            results=[]
            for name in TABLES:
                if name not in tables:
                    continue
                cols={c[1] for c in db.execute(f'PRAGMA table_info("{name}")')}
                entry={"table":name,"rows":db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0],"columns":sorted(cols)}
                firm=next((c for c in ("ticker","company_code","stock_code","company_id") if c in cols),None)
                year=next((c for c in ("fiscal_year","year","report_year") if c in cols),None)
                if firm:
                    entry["distinct_companies"]=db.execute(f'SELECT COUNT(DISTINCT "{firm}") FROM "{name}"').fetchone()[0]
                if year:
                    minmax=db.execute(f'SELECT MIN("{year}"),MAX("{year}") FROM "{name}"').fetchone()
                    entry["year_range"]=[str(x) if x is not None else None for x in minmax]
                results.append(entry)
        return {"source":str(path),"status":"read_only_examined","tables":results}
    except sqlite3.Error as exc:
        return {"source":str(path),"status":"unable_to_read","reason":type(exc).__name__}


def inventory(paths, output):
    report={"status":"read_only_local_source_inventory","sources":[inspect_one(p) for p in paths],
            "warning":"This is not a cloud inventory; absence on this machine does not prove remote data are missing. No source rows are exported."}
    out=Path(output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding='utf-8')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only local SQLite source inventory")
    p.add_argument("--db",action="append",help="Existing SQLite path; repeat for multiple sources")
    p.add_argument("--output",default="data/financial_ml/local_source_inventory.json")
    args=p.parse_args(argv)
    report=inventory(args.db or DEFAULT_PATHS,args.output)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()