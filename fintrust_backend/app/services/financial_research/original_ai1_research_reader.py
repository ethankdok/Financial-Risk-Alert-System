"""Read-only adapter for isolated 1785 original scanned-PDF reviewed facts.

This is NOT a replacement for the historical-audit DB and it never exposes
unreviewed transcription, company private files or future data as early-warning.
Only data manually double-reviewed in the Round7 isolated SQLite is readable.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path


def get_1785_original_ai1(db_path):
    path=Path(db_path)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("1785_original_review_db_unavailable")
    uri=path.resolve().as_uri()+"?mode=ro"
    db=sqlite3.connect(uri,uri=True)
    db.row_factory=sqlite3.Row
    try:
        count=db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='original_1785_financial_facts'").fetchone()[0]
        if count!=1:raise ValueError("1785_review_table_not_present")
        records=[dict(r) for r in db.execute("""
            SELECT ticker,fiscal_year,metric,value_twd,unit,
                   source_pdf_sha256,pdf_page,filing_version_type,
                   statement_scope,accounting_framework,
                   review_status,original_first_publication_verified,
                   model_training_admitted
            FROM original_1785_financial_facts
            ORDER BY fiscal_year,metric
            LIMIT 37""")]
    finally:db.close()
    if len(records)>36:
        raise ValueError("1785_review_data_exceeds_expected_feature_cells")
    for r in records:
        if (r["ticker"]!="1785" or r["fiscal_year"] not in (2013,2014,2015)
            or r["filing_version_type"]!="original"
            or r["review_status"]!="DOUBLE_REVIEWED_ORIGINAL_PDF"
            or r["unit"]!="TWD" or r["statement_scope"]!="consolidated"
            or r["accounting_framework"]!="TIFRS"
            or r["original_first_publication_verified"]!=0
            or r["model_training_admitted"]!=0):
            raise ValueError("1785_review_case_data_quality_regressed")
    return {
        "ticker":"1785","mode":"RETROSPECTIVE_FORENSIC",
        "status":"ORIGINAL_AI1_DOUBLE_REVIEWED_RESEARCH_ONLY",
        "observed_original_pdf_amount_cells":len(records),
        "expected_amount_cells":36,
        "historical_original_publication_time_certified":False,
        "sample_admitted_to_fraud_training":False,
        "records":records
    }
