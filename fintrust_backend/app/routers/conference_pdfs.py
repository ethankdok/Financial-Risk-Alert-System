from __future__ import annotations

from datetime import datetime
from pathlib import Path as FilePath

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.routers.financial import require_ingestion_token
from app.services.mops_conference_pdf_pipeline import run_mops_pdf_pipeline
from app.services.mops_conference_pdf_repository import (
    ConferencePdfArchiveRepository,
    build_conference_pdf_archive_repository,
)


router = APIRouter(prefix="/api/v1/financial", tags=["conference-pdf-archive"])


def get_conference_pdf_repository() -> ConferencePdfArchiveRepository:
    return build_conference_pdf_archive_repository()


@router.post(
    "/admin/companies/{ticker}/conference-pdfs/sync",
    dependencies=[Depends(require_ingestion_token)],
)
def sync_conference_pdfs(
    ticker: str,
    year: int = Query(..., ge=2019, le=datetime.now().year),
    market: str = Query(default="sii", pattern="^(sii|otc|rotc|pub)$"),
    output: FilePath = Query(default=FilePath("data/official-ir-pdfs")),
    ocr: bool = Query(default=False),
):
    result = run_mops_pdf_pipeline(
        ticker=ticker,
        year=year,
        market=market,
        output_dir=output,
        ocr=ocr,
    )
    if result["status"] != "complete":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/companies/{ticker}/conference-pdfs/{year}/status")
def conference_pdf_status(
    ticker: str,
    year: int = Path(..., ge=2019, le=datetime.now().year),
    repository: ConferencePdfArchiveRepository = Depends(get_conference_pdf_repository),
):
    manifest = repository.latest_manifest(ticker, year)
    if manifest is None:
        raise HTTPException(status_code=404, detail="No conference PDF manifest is available.")
    return {
        "ticker": manifest.get("ticker"),
        "year": manifest.get("year"),
        "market": manifest.get("market"),
        "status": manifest.get("status"),
        "retrieved_at": manifest.get("retrieved_at"),
        "rows": manifest.get("rows", 0),
        "listing_pages": manifest.get("listing_pages", []),
        "expected_pdfs": manifest.get("expected_pdfs", 0),
        "downloaded_pdfs": manifest.get("downloaded_pdfs", 0),
        "integrity": manifest.get("integrity", {}),
        "errors": manifest.get("errors", []),
        "storage_contract": manifest.get("storage_contract", {}),
    }


@router.get("/companies/{ticker}/conference-pdfs/{year}/documents")
def conference_pdf_documents(
    ticker: str,
    year: int = Path(..., ge=2019, le=datetime.now().year),
    repository: ConferencePdfArchiveRepository = Depends(get_conference_pdf_repository),
):
    manifest = repository.latest_manifest(ticker, year)
    if manifest is None:
        raise HTTPException(status_code=404, detail="No conference PDF manifest is available.")
    return {
        "ticker": ticker,
        "year": year,
        "count": len(manifest.get("documents", [])),
        "documents": manifest.get("documents", []),
    }


@router.get("/companies/{ticker}/conference-pdfs/{year}/documents/{filename}/pages")
def conference_pdf_pages(
    ticker: str,
    filename: str,
    year: int = Path(..., ge=2019, le=datetime.now().year),
    repository: ConferencePdfArchiveRepository = Depends(get_conference_pdf_repository),
):
    pages = repository.pages(ticker, year, filename)
    if not pages:
        raise HTTPException(status_code=404, detail="No page evidence is available for this document.")
    return {"ticker": ticker, "year": year, "filename": filename, "count": len(pages), "pages": pages}


@router.get("/companies/{ticker}/conference-pdfs/{year}/documents/{filename}/analysis")
def conference_pdf_analysis(
    ticker: str,
    filename: str,
    year: int = Path(..., ge=2019, le=datetime.now().year),
    repository: ConferencePdfArchiveRepository = Depends(get_conference_pdf_repository),
):
    analysis = repository.analysis(ticker, year, filename)
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis evidence is available for this document.")
    return {"ticker": ticker, "year": year, "filename": filename, "count": len(analysis), "analysis": analysis}
