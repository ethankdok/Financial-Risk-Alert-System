from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.models import CompanyMasterRecord, CompanyUniverseSyncResult
from app.services.company_master_repository import CompanyMasterRepository
from app.services.semiconductor_subindustries import classify_semiconductor_company


class TwseCompanyUniverseError(RuntimeError):
    pass


class TwseCompanyUniverseService:
    SOURCE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    SEMICONDUCTOR_INDUSTRY_CODE = "24"

    def __init__(
        self,
        *,
        repository: CompanyMasterRepository,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.repository = repository
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @staticmethod
    def _parse_twse_date(value: object) -> date | None:
        raw = str(value or "").strip()
        if len(raw) != 8 or not raw.isdigit():
            return None
        try:
            return date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
        except ValueError:
            return None

    @staticmethod
    def _parse_roc_date(value: object) -> date | None:
        raw = str(value or "").strip()
        if len(raw) != 7 or not raw.isdigit():
            return None
        try:
            return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:]))
        except ValueError:
            return None

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    def _to_company(self, row: dict[str, Any], synced_at: datetime) -> CompanyMasterRecord:
        ticker = self._clean(row.get("公司代號"))
        short_name = self._clean(row.get("公司簡稱"))
        legal_name = self._clean(row.get("公司名稱"))
        english_name = self._clean(row.get("英文簡稱")) or None
        classification = classify_semiconductor_company(ticker)
        aliases = [value for value in (short_name, legal_name, english_name, ticker) if value]
        return CompanyMasterRecord(
            ticker=ticker,
            name=short_name or legal_name,
            legal_name=legal_name or short_name,
            english_name=english_name,
            subindustry=classification.subindustry,
            subindustry_source=classification.source,
            subindustry_confidence=classification.confidence,
            aliases=list(dict.fromkeys(aliases)),
            listed_at=self._parse_twse_date(row.get("上市日期")),
            source_url=self.SOURCE_URL,
            source_report_date=self._parse_roc_date(row.get("出表日期")),
            synced_at=synced_at,
        )

    async def fetch(self) -> tuple[list[dict[str, Any]], list[CompanyMasterRecord]]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=True,
                transport=self.transport,
                headers={"Accept": "application/json", "User-Agent": "FinTrust-Alert/0.3"},
            ) as client:
                response = await client.get(self.SOURCE_URL)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TwseCompanyUniverseError(f"Unable to load TWSE company universe: {exc}") from exc
        if not isinstance(payload, list):
            raise TwseCompanyUniverseError("TWSE company universe did not return a JSON array")
        rows = [row for row in payload if isinstance(row, dict)]
        synced_at = datetime.now(timezone.utc)
        companies = [
            self._to_company(row, synced_at)
            for row in rows
            if self._clean(row.get("產業別")) == self.SEMICONDUCTOR_INDUSTRY_CODE
            and self._clean(row.get("公司代號"))
        ]
        return rows, companies

    async def sync(self) -> CompanyUniverseSyncResult:
        rows, companies = await self.fetch()
        persisted = self.repository.upsert_many(companies)
        source_report_date = max(
            (company.source_report_date for company in companies if company.source_report_date),
            default=None,
        )
        synced_at = max(
            (company.synced_at for company in companies),
            default=datetime.now(timezone.utc),
        )
        return CompanyUniverseSyncResult(
            source_url=self.SOURCE_URL,
            source_report_date=source_report_date,
            fetched_rows=len(rows),
            semiconductor_rows=len(companies),
            persisted_rows=persisted,
            synced_at=synced_at,
        )
