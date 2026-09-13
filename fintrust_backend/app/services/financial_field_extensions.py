from __future__ import annotations

from app.services.mops_inline_xbrl import FIELD_ALIASES, INSTANT_FIELDS


EXTENDED_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "cost_of_goods_sold": (
        "營業成本",
        "營業成本合計",
        "OperatingCosts",
        "CostOfGoodsSold",
        "CostOfRevenue",
    ),
    "accounts_receivable": (
        "應收帳款淨額",
        "應收帳款",
        "應收票據及應收帳款淨額",
        "AccountsReceivableNet",
        "AccountsReceivable",
        "TradeReceivables",
        "NotesAndAccountsReceivableNet",
    ),
}


def register_analysis_field_aliases() -> None:
    """Extend the shared MOPS taxonomy map without changing the stable parser core."""
    for field, aliases in EXTENDED_FIELD_ALIASES.items():
        if field not in FIELD_ALIASES:
            FIELD_ALIASES[field] = aliases
    INSTANT_FIELDS.add("accounts_receivable")


def register_persistence_fields() -> None:
    """Keep normalized fact persistence aligned with the extended MOPS fields."""
    from app.services import analysis_repository

    for field in ("cost_of_goods_sold", "accounts_receivable"):
        if field not in analysis_repository.HISTORICAL_FACT_FIELDS:
            analysis_repository.HISTORICAL_FACT_FIELDS.append(field)
    analysis_repository.INCOME_FIELDS.add("cost_of_goods_sold")
    analysis_repository.BALANCE_FIELDS.add("accounts_receivable")
