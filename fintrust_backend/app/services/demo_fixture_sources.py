from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.historical_analysis_models import HistoricalPeriodRecord
from app.models import CompanyProfile


DEMO_SOURCE_URL = (
    "https://github.com/UnaLu027/fintrust-alert/"
    "tree/feature/financial-statement-ai-mvp/backend/app/services"
)


# Synthetic, deterministic values for demonstrating the data pipeline when an
# external official endpoint is temporarily unavailable. They must never be
# presented as current company financial results.
_SUBINDUSTRY_SERIES: dict[str, list[dict[str, float]]] = {
    "晶圓代工": [
        {
            "revenue": 820_000_000,
            "gross_profit": 451_000_000,
            "operating_income": 287_000_000,
            "net_income": 238_000_000,
            "eps": 9.2,
            "cash_and_cash_equivalents": 410_000_000,
            "inventory": 92_000_000,
            "current_assets": 770_000_000,
            "total_assets": 1_850_000_000,
            "current_liabilities": 310_000_000,
            "total_liabilities": 460_000_000,
            "equity": 1_390_000_000,
            "operating_cash_flow": 310_000_000,
            "investing_cash_flow": -225_000_000,
            "capital_expenditure": -180_000_000,
            "research_and_development_expense": 66_000_000,
        },
        {
            "revenue": 900_000_000,
            "gross_profit": 504_000_000,
            "operating_income": 324_000_000,
            "net_income": 265_000_000,
            "eps": 10.3,
            "cash_and_cash_equivalents": 455_000_000,
            "inventory": 98_000_000,
            "current_assets": 835_000_000,
            "total_assets": 2_020_000_000,
            "current_liabilities": 330_000_000,
            "total_liabilities": 500_000_000,
            "equity": 1_520_000_000,
            "operating_cash_flow": 345_000_000,
            "investing_cash_flow": -260_000_000,
            "capital_expenditure": -210_000_000,
            "research_and_development_expense": 74_000_000,
        },
        {
            "revenue": 1_000_000_000,
            "gross_profit": 550_000_000,
            "operating_income": 350_000_000,
            "net_income": 290_000_000,
            "eps": 11.2,
            "cash_and_cash_equivalents": 500_000_000,
            "inventory": 105_000_000,
            "current_assets": 900_000_000,
            "total_assets": 2_200_000_000,
            "current_liabilities": 350_000_000,
            "total_liabilities": 540_000_000,
            "equity": 1_660_000_000,
            "operating_cash_flow": 380_000_000,
            "investing_cash_flow": -285_000_000,
            "capital_expenditure": -220_000_000,
            "research_and_development_expense": 82_000_000,
        },
        {
            "revenue": 1_100_000_000,
            "gross_profit": 570_000_000,
            "operating_income": 350_000_000,
            "net_income": 282_000_000,
            "eps": 10.9,
            "cash_and_cash_equivalents": 485_000_000,
            "inventory": 115_000_000,
            "current_assets": 920_000_000,
            "total_assets": 2_380_000_000,
            "current_liabilities": 390_000_000,
            "total_liabilities": 620_000_000,
            "equity": 1_760_000_000,
            "operating_cash_flow": 300_000_000,
            "investing_cash_flow": -340_000_000,
            "capital_expenditure": -260_000_000,
            "research_and_development_expense": 95_000_000,
        },
        {
            "revenue": 1_050_000_000,
            "gross_profit": 483_000_000,
            "operating_income": 265_000_000,
            "net_income": 210_000_000,
            "eps": 8.1,
            "cash_and_cash_equivalents": 390_000_000,
            "inventory": 148_000_000,
            "current_assets": 870_000_000,
            "total_assets": 2_520_000_000,
            "current_liabilities": 470_000_000,
            "total_liabilities": 760_000_000,
            "equity": 1_760_000_000,
            "operating_cash_flow": 180_000_000,
            "investing_cash_flow": -500_000_000,
            "capital_expenditure": -450_000_000,
            "research_and_development_expense": 110_000_000,
        },
    ],
    "IC 設計": [
        {
            "revenue": 410_000_000,
            "gross_profit": 188_600_000,
            "operating_income": 65_000_000,
            "net_income": 56_000_000,
            "eps": 14.0,
            "cash_and_cash_equivalents": 160_000_000,
            "inventory": 45_000_000,
            "current_assets": 310_000_000,
            "total_assets": 520_000_000,
            "current_liabilities": 105_000_000,
            "total_liabilities": 145_000_000,
            "equity": 375_000_000,
            "operating_cash_flow": 72_000_000,
            "investing_cash_flow": -18_000_000,
            "capital_expenditure": -9_000_000,
            "research_and_development_expense": 82_000_000,
        },
        {
            "revenue": 455_000_000,
            "gross_profit": 213_850_000,
            "operating_income": 79_000_000,
            "net_income": 68_000_000,
            "eps": 17.0,
            "cash_and_cash_equivalents": 178_000_000,
            "inventory": 49_000_000,
            "current_assets": 338_000_000,
            "total_assets": 558_000_000,
            "current_liabilities": 112_000_000,
            "total_liabilities": 154_000_000,
            "equity": 404_000_000,
            "operating_cash_flow": 84_000_000,
            "investing_cash_flow": -20_000_000,
            "capital_expenditure": -10_000_000,
            "research_and_development_expense": 95_000_000,
        },
        {
            "revenue": 500_000_000,
            "gross_profit": 240_000_000,
            "operating_income": 92_000_000,
            "net_income": 78_000_000,
            "eps": 19.5,
            "cash_and_cash_equivalents": 195_000_000,
            "inventory": 55_000_000,
            "current_assets": 365_000_000,
            "total_assets": 600_000_000,
            "current_liabilities": 120_000_000,
            "total_liabilities": 165_000_000,
            "equity": 435_000_000,
            "operating_cash_flow": 96_000_000,
            "investing_cash_flow": -22_000_000,
            "capital_expenditure": -11_000_000,
            "research_and_development_expense": 108_000_000,
        },
        {
            "revenue": 470_000_000,
            "gross_profit": 218_550_000,
            "operating_income": 77_000_000,
            "net_income": 65_000_000,
            "eps": 16.2,
            "cash_and_cash_equivalents": 184_000_000,
            "inventory": 72_000_000,
            "current_assets": 360_000_000,
            "total_assets": 610_000_000,
            "current_liabilities": 132_000_000,
            "total_liabilities": 180_000_000,
            "equity": 430_000_000,
            "operating_cash_flow": 58_000_000,
            "investing_cash_flow": -24_000_000,
            "capital_expenditure": -12_000_000,
            "research_and_development_expense": 116_000_000,
        },
        {
            "revenue": 420_000_000,
            "gross_profit": 189_000_000,
            "operating_income": 54_000_000,
            "net_income": 46_000_000,
            "eps": 11.5,
            "cash_and_cash_equivalents": 148_000_000,
            "inventory": 105_000_000,
            "current_assets": 345_000_000,
            "total_assets": 620_000_000,
            "current_liabilities": 155_000_000,
            "total_liabilities": 215_000_000,
            "equity": 405_000_000,
            "operating_cash_flow": 28_000_000,
            "investing_cash_flow": -27_000_000,
            "capital_expenditure": -14_000_000,
            "research_and_development_expense": 119_000_000,
        },
    ],
    "封裝測試": [
        {
            "revenue": 460_000_000,
            "gross_profit": 92_000_000,
            "operating_income": 36_000_000,
            "net_income": 27_000_000,
            "eps": 6.2,
            "cash_and_cash_equivalents": 98_000_000,
            "inventory": 48_000_000,
            "current_assets": 250_000_000,
            "total_assets": 650_000_000,
            "current_liabilities": 150_000_000,
            "total_liabilities": 285_000_000,
            "equity": 365_000_000,
            "operating_cash_flow": 72_000_000,
            "investing_cash_flow": -44_000_000,
            "capital_expenditure": -36_000_000,
            "research_and_development_expense": 18_000_000,
        },
        {
            "revenue": 500_000_000,
            "gross_profit": 102_500_000,
            "operating_income": 41_000_000,
            "net_income": 31_000_000,
            "eps": 7.1,
            "cash_and_cash_equivalents": 105_000_000,
            "inventory": 52_000_000,
            "current_assets": 270_000_000,
            "total_assets": 690_000_000,
            "current_liabilities": 160_000_000,
            "total_liabilities": 305_000_000,
            "equity": 385_000_000,
            "operating_cash_flow": 78_000_000,
            "investing_cash_flow": -48_000_000,
            "capital_expenditure": -40_000_000,
            "research_and_development_expense": 20_000_000,
        },
        {
            "revenue": 540_000_000,
            "gross_profit": 113_400_000,
            "operating_income": 46_000_000,
            "net_income": 35_000_000,
            "eps": 8.0,
            "cash_and_cash_equivalents": 112_000_000,
            "inventory": 58_000_000,
            "current_assets": 292_000_000,
            "total_assets": 730_000_000,
            "current_liabilities": 170_000_000,
            "total_liabilities": 325_000_000,
            "equity": 405_000_000,
            "operating_cash_flow": 84_000_000,
            "investing_cash_flow": -53_000_000,
            "capital_expenditure": -44_000_000,
            "research_and_development_expense": 22_000_000,
        },
        {
            "revenue": 525_000_000,
            "gross_profit": 105_000_000,
            "operating_income": 39_000_000,
            "net_income": 29_000_000,
            "eps": 6.6,
            "cash_and_cash_equivalents": 100_000_000,
            "inventory": 72_000_000,
            "current_assets": 286_000_000,
            "total_assets": 750_000_000,
            "current_liabilities": 185_000_000,
            "total_liabilities": 350_000_000,
            "equity": 400_000_000,
            "operating_cash_flow": 62_000_000,
            "investing_cash_flow": -60_000_000,
            "capital_expenditure": -49_000_000,
            "research_and_development_expense": 23_000_000,
        },
        {
            "revenue": 490_000_000,
            "gross_profit": 91_140_000,
            "operating_income": 28_000_000,
            "net_income": 19_000_000,
            "eps": 4.3,
            "cash_and_cash_equivalents": 76_000_000,
            "inventory": 105_000_000,
            "current_assets": 270_000_000,
            "total_assets": 770_000_000,
            "current_liabilities": 220_000_000,
            "total_liabilities": 430_000_000,
            "equity": 340_000_000,
            "operating_cash_flow": 28_000_000,
            "investing_cash_flow": -68_000_000,
            "capital_expenditure": -55_000_000,
            "research_and_development_expense": 24_000_000,
        },
    ],
}


class DemoTwseOpenApiClient:
    """TWSE-shaped synthetic input for flow verification only."""

    async def fetch_company_bundle(self, ticker: str) -> dict[str, dict[str, Any] | None]:
        from app.services.company_registry import get_company

        profile = get_company(ticker)
        if profile is None:
            raise ValueError(f"Unsupported demo ticker: {ticker}")
        values = deepcopy(_SUBINDUSTRY_SERIES[profile.subindustry][-1])
        year = 113

        return {
            "income_statement": {
                "公司代號": profile.ticker,
                "年度": str(year),
                "季別": "4",
                "營業收入": values["revenue"],
                "營業毛利（毛損）": values["gross_profit"],
                "營業利益（損失）": values["operating_income"],
                "本期淨利（淨損）": values["net_income"],
                "基本每股盈餘（元）": values["eps"],
            },
            "balance_sheet": {
                "公司代號": profile.ticker,
                "年度": str(year),
                "季別": "4",
                "現金及約當現金": values["cash_and_cash_equivalents"],
                "存貨": values["inventory"],
                "流動資產": values["current_assets"],
                "資產總額": values["total_assets"],
                "流動負債": values["current_liabilities"],
                "負債總額": values["total_liabilities"],
                "權益總額": values["equity"],
            },
            "monthly_revenue": {
                "公司代號": profile.ticker,
                "資料年月": "11406",
                "營業收入-當月營收": values["revenue"] / 12,
                "營業收入-上月營收": values["revenue"] / 12 * 1.03,
                "營業收入-去年當月營收": values["revenue"] / 12 * 1.08,
                "營業收入-上月比較增減(%)": -2.9126,
                "營業收入-去年同月增減(%)": -7.4074,
            },
            "_errors": {
                "messages": [
                    "DEMO FIXTURE：此回應為合成資料，只用來驗證自動抓取後的正規化、規則與資料庫流程。"
                ]
            },
        }


class DemoMopsInlineXbrlClient:
    """MOPS-shaped synthetic history for deterministic offline demonstrations."""

    async def fetch_history(
        self,
        profile: CompanyProfile,
        *,
        years: int = 5,
        end_roc_year: int | None = None,
    ) -> list[HistoricalPeriodRecord]:
        end_year = (end_roc_year + 1911) if end_roc_year is not None else 2024
        full_series = deepcopy(_SUBINDUSTRY_SERIES[profile.subindustry])
        selected = full_series[-years:]
        start_year = end_year - len(selected) + 1
        rows: list[HistoricalPeriodRecord] = []

        concept_matches = {
            "revenue": "demo:RevenueFromContractsWithCustomers",
            "gross_profit": "demo:GrossProfit",
            "operating_income": "demo:OperatingIncome",
            "net_income": "demo:ProfitLoss",
            "eps": "demo:BasicEarningsLossPerShare",
            "inventory": "demo:Inventories",
            "operating_cash_flow": "demo:NetCashFlowsFromUsedInOperatingActivities",
            "capital_expenditure": "demo:PaymentsToAcquirePropertyPlantAndEquipment",
            "research_and_development_expense": "demo:ResearchAndDevelopmentExpense",
        }

        for offset, values in enumerate(selected):
            fiscal_year = start_year + offset
            fields_found = sorted(values)
            rows.append(
                HistoricalPeriodRecord(
                    ticker=profile.ticker,
                    company_name=profile.name,
                    subindustry=profile.subindustry,
                    fiscal_year=fiscal_year,
                    roc_year=fiscal_year - 1911,
                    period=f"{fiscal_year}FY",
                    source_name="DEMO FIXTURE（合成資料，非官方即時財報）",
                    source_url=DEMO_SOURCE_URL,
                    status="available",
                    fields_found=fields_found,
                    fields_missing=[],
                    concept_matches=concept_matches,
                    warnings=[
                        "此年度資料為離線 Demo fixture，只驗證解析後資料結構、指標運算、規則判斷與持久化流程。"
                    ],
                    **values,
                )
            )
        return rows
