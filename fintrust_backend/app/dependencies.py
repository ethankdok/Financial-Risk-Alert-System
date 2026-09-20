from __future__ import annotations

import os
from functools import lru_cache

from app.services.analysis_repository import AnalysisRepository, build_analysis_repository
from app.services.company_master_repository import (
    CompanyMasterRepository,
    build_company_master_repository,
)
from app.services.fact_repository import FinancialFactRepository, build_fact_repository
from app.services.ingestion_run_repository import (
    IngestionRunRepository,
    build_ingestion_run_repository,
)


@lru_cache(maxsize=1)
def get_fact_repository() -> FinancialFactRepository:
    return build_fact_repository()


@lru_cache(maxsize=1)
def get_analysis_repository() -> AnalysisRepository:
    return build_analysis_repository()


@lru_cache(maxsize=1)
def get_company_master_repository() -> CompanyMasterRepository:
    return build_company_master_repository()


@lru_cache(maxsize=1)
def get_ingestion_run_repository() -> IngestionRunRepository:
    return build_ingestion_run_repository()
