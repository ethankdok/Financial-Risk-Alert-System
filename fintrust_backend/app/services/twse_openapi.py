from __future__ import annotations

import asyncio
from typing import Any

import httpx


class TwseOpenApiError(RuntimeError):
    pass


class TwseOpenApiClient:
    BASE_URL = "https://openapi.twse.com.tw/v1"
    ENDPOINTS = {
        "income_statement": "/opendata/t187ap06_L_ci",
        "balance_sheet": "/opendata/t187ap07_L_ci",
        "monthly_revenue": "/opendata/t187ap05_L",
    }

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @staticmethod
    def _company_code(row: dict[str, Any]) -> str:
        for key in ("公司代號", "公司代碼", "Code"):
            value = row.get(key)
            if value is not None:
                return str(value).strip()
        return ""

    async def _fetch_rows(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
    ) -> list[dict[str, Any]]:
        response = await client.get(endpoint)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise TwseOpenApiError(f"TWSE endpoint {endpoint} did not return a JSON array")
        return [row for row in payload if isinstance(row, dict)]

    async def fetch_company_bundle(self, ticker: str) -> dict[str, dict[str, Any] | None]:
        ticker = ticker.strip()
        timeout = httpx.Timeout(self.timeout_seconds)
        headers = {
            "Accept": "application/json",
            "User-Agent": "FinTrust-Alert-MVP/0.2 (+financial-rule-engine)",
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                names = list(self.ENDPOINTS)
                tasks = [
                    self._fetch_rows(client, self.ENDPOINTS[name])
                    for name in names
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
        except httpx.HTTPError as exc:
            raise TwseOpenApiError(f"Unable to reach TWSE OpenAPI: {exc}") from exc

        bundle: dict[str, dict[str, Any] | None] = {}
        errors: list[str] = []
        for name, result in zip(names, results, strict=True):
            if isinstance(result, Exception):
                errors.append(f"{name}: {result}")
                bundle[name] = None
                continue
            bundle[name] = next(
                (row for row in result if self._company_code(row) == ticker),
                None,
            )

        if all(value is None for value in bundle.values()):
            detail = "; ".join(errors) if errors else f"ticker {ticker} not found"
            raise TwseOpenApiError(f"No TWSE financial data available: {detail}")

        bundle["_errors"] = {"messages": errors} if errors else None
        return bundle

    @classmethod
    def source_url(cls, dataset_name: str) -> str:
        endpoint = cls.ENDPOINTS[dataset_name]
        return f"{cls.BASE_URL}{endpoint}"
