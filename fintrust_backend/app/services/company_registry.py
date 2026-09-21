from __future__ import annotations

from app.models import CompanyProfile
from app.models import CompanyMasterRecord

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


def register_company_profile(company: CompanyProfile) -> CompanyProfile:
    """Cache a persisted company profile for legacy services that still resolve by ticker."""
    SEMICONDUCTOR_COMPANIES[company.ticker.strip()] = company
    return company


def get_company(ticker: str) -> CompanyProfile | None:
    normalized = ticker.strip()
    company = SEMICONDUCTOR_COMPANIES.get(normalized)
    if company is not None:
        return company

    # Production now persists the full semiconductor company master in Firestore.
    # Keep legacy source/parsing services compatible by resolving a missing seed
    # from that master and caching it for the remainder of the process.
    from app.services.company_master_repository import build_company_master_repository

    record = build_company_master_repository().get(normalized)
    if record is None:
        return None
    return register_company_profile(profile_from_master(record))


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


def profile_from_master(record: CompanyMasterRecord) -> CompanyProfile:
    """Convert the persisted company-universe contract to the legacy service profile."""
    return CompanyProfile(
        ticker=record.ticker,
        name=record.name,
        subindustry=record.subindustry,
        aliases=record.aliases or [record.ticker, record.name],
    )
