from __future__ import annotations

import os
from functools import lru_cache

from app.services.analysis_repository import AnalysisRepository, build_analysis_repository
from app.services.fact_repository import FinancialFactRepository, build_fact_repository


@lru_cache(maxsize=1)
def get_fact_repository() -> FinancialFactRepository:
    return build_fact_repository()


@lru_cache(maxsize=1)
def get_analysis_repository() -> AnalysisRepository:
    return build_analysis_repository()
