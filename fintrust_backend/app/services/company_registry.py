from __future__ import annotations

import logging
from typing import Any

from app.models import CompanyProfile
from app.models import CompanyMasterRecord

logger = logging.getLogger(__name__)

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


# The reviewed seeds above, frozen at import. SEMICONDUCTOR_COMPANIES itself also
# caches master profiles resolved at runtime, so it must not be used as a listing.
SEED_COMPANIES: dict[str, CompanyProfile] = dict(SEMICONDUCTOR_COMPANIES)
SEMICONDUCTOR_INDUSTRY_CODE = "24"


def is_supported_master_record(record: CompanyMasterRecord) -> bool:
    """MVP scope for the persisted company master: listed TWSE semiconductor companies."""
    # Absent fields take the CompanyMasterRecord defaults (TWSE, code 24, listed).
    return (getattr(record, "market", "TWSE") == "TWSE"
            and getattr(record, "industry_code", SEMICONDUCTOR_INDUSTRY_CODE) == SEMICONDUCTOR_INDUSTRY_CODE
            and getattr(record, "listing_status", "listed") == "listed")


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
    # from that master and caching it for the remainder of the process. Only
    # supported (listed semiconductor) master records resolve, matching the
    # company list served by list_supported_companies().
    from app.services.company_master_repository import build_company_master_repository

    record = build_company_master_repository().get(normalized)
    if record is None or not is_supported_master_record(record):
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
    """The reviewed seed registry only (used by seed/demo ingestion); never runtime-cached profiles."""
    return list(SEED_COMPANIES.values())


def list_supported_companies(repository: Any | None = None) -> list[CompanyProfile]:
    """Every company that get_company() resolves: the reviewed seeds plus each supported
    record of the persisted company master, read fresh rather than from what this
    process happened to resolve earlier. Seeds keep their reviewed profiles."""
    if repository is None:
        from app.services.company_master_repository import build_company_master_repository

        repository = build_company_master_repository()
    companies = dict(SEED_COMPANIES)
    try:
        records = repository.list_all()
    except Exception as exc:  # master unavailable: still serve the reviewed seeds
        logger.warning("company master listing failed: %s", type(exc).__name__)
        records = []
    for record in records:
        if is_supported_master_record(record) and record.ticker not in companies:
            companies[record.ticker] = profile_from_master(record)
    return sorted(companies.values(), key=lambda company: company.ticker)


def profile_from_master(record: CompanyMasterRecord) -> CompanyProfile:
    """Convert the persisted company-universe contract to the legacy service profile."""
    return CompanyProfile(
        ticker=record.ticker,
        name=record.name,
        subindustry=record.subindustry,
        aliases=record.aliases or [record.ticker, record.name],
    )
