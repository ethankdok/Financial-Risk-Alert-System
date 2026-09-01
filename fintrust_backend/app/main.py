from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.financial import router as financial_router


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="FinTrust Alert Financial Rule Engine API",
    version="0.3.0",
    description=(
        "半導體產業官方財報自動抓取、持久化、財務指標計算、"
        "子產業版本化規則分析與前端快照 API。本服務不提供投資建議。"
    ),
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(financial_router)


@app.get("/")
def root():
    return {
        "service": "FinTrust Alert Financial Rule Engine API",
        "version": "0.3.0",
        "docs": "/docs",
        "scheduled_refresh_endpoint": "/api/v1/financial/admin/companies/2330/refresh",
        "frontend_snapshot_endpoint": "/api/v1/financial/companies/2330/analysis/latest",
        "persistence_backend": os.getenv("DATASTORE_BACKEND", "sqlite"),
        "disclaimer": "僅供財報分析與可信度風險提醒，非投資建議。",
    }
