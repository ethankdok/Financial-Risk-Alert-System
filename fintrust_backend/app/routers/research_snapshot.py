
import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(
    prefix="/api/v1/financial/research-snapshots",
    tags=["research-snapshots"],
)

DB = (
    Path(__file__).resolve().parents[2]
    / "data/research-results/research_snapshots.sqlite3"
)

TICKERS = {
    "2330": "TSMC",
    "2454": "MediaTek",
}


def latest_snapshot():
    if not DB.is_file():
        raise HTTPException(
            status_code=404,
            detail="Research database not found",
        )

    with sqlite3.connect(
        f"file:{DB}?mode=ro",
        uri=True,
    ) as conn:
        row = conn.execute("""
            SELECT snapshot_id, created_at,
                   method_status, payload_json
            FROM research_snapshots
            ORDER BY created_at DESC, snapshot_id DESC
            LIMIT 1
        """).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No research snapshot",
        )

    payload = json.loads(row[3])

    return {
        "snapshot_id": row[0],
        "created_at": row[1],
        "status": row[2],
        "sources": payload.get("sources", []),
        "companies": payload.get("companies", []),
    }


@router.get("/health")
def health():
    return {
        "status": "ok" if DB.is_file() else "missing",
        "database_available": DB.is_file(),
        "read_only": True,
    }


@router.get("/latest")
def get_latest():
    return latest_snapshot()


@router.get("/latest/companies/{ticker}")
def get_company(ticker: str):
    company = TICKERS.get(ticker)

    if company is None:
        raise HTTPException(
            status_code=404,
            detail="Unsupported ticker",
        )

    snapshot = latest_snapshot()

    for item in snapshot["companies"]:
        if item.get("company") == company:
            return {
                "snapshot_id": snapshot["snapshot_id"],
                "created_at": snapshot["created_at"],
                "company": item,
            }

    raise HTTPException(
        status_code=404,
        detail="Company not found in snapshot",
    )
