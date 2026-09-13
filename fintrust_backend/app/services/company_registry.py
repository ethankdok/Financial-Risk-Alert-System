from __future__ import annotations

from app.models import CompanyProfile

# Seed registry for the MVP. The architecture is intentionally not restricted to
# wafer foundries; subindustry is retained so future peer comparisons can be
# limited to comparable business models.
SEMICONDUCTOR_COMPANIES: dict[str, CompanyProfile] = {
    "2330": CompanyProfile(
        ticker="2330",
        name="台積電",
        subindustry="晶圓代工",
        aliases=["台積電", "台灣積體電路", "TSMC", "2330"],
    ),
    "2303": CompanyProfile(
        ticker="2303",
        name="聯電",
        subindustry="晶圓代工",
        aliases=["聯電", "聯華電子", "UMC", "2303"],
    ),
    "2454": CompanyProfile(
        ticker="2454",
        name="聯發科",
        subindustry="IC 設計",
        aliases=["聯發科", "MediaTek", "MTK", "2454"],
    ),
    "3711": CompanyProfile(
        ticker="3711",
        name="日月光投控",
        subindustry="封裝測試",
        aliases=["日月光投控", "日月光", "ASE", "ASEH", "3711"],
    ),
}


def get_company(ticker: str) -> CompanyProfile | None:
    return SEMICONDUCTOR_COMPANIES.get(ticker.strip())


def find_company(text: str, ticker_hint: str | None = None) -> CompanyProfile | None:
    if ticker_hint:
        company = get_company(ticker_hint)
        if company:
            return company

    normalized = text.casefold()
    for company in SEMICONDUCTOR_COMPANIES.values():
        if any(alias.casefold() in normalized for alias in company.aliases):
            return company
    return None


def list_companies() -> list[CompanyProfile]:
    return list(SEMICONDUCTOR_COMPANIES.values())
