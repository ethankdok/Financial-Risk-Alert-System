"""Canonical-field normalization and the data-quality gate for one filing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.services.financial_field_extensions import EXTENDED_FIELD_ALIASES
from app.services.historical_audit.models import (
    CANONICAL_FIELDS,
    CORE_FIELDS,
    INSTANT_FIELDS,
    statement_type_for,
)
from app.services.historical_audit.xbrl_document import ParsedXbrlDocument, XbrlContext, XbrlFact
from app.services.mops_inline_xbrl import FIELD_ALIASES
from app.services.robust_mops_inline_xbrl import EXTRA_ALIASES


# Reviewed Taiwan-IFRS statement concepts, highest priority first. Verified
# against official 1785 FY2013 and FY2016 MOPS instances (tifrs 2013/2015).
PRIMARY_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("OperatingRevenue", "Revenue"),
    "cost_of_goods_sold": ("OperatingCosts", "CostOfSales"),
    "gross_profit": ("GrossProfitLossFromOperations", "GrossProfit"),
    "operating_income": ("NetOperatingIncomeLoss", "ProfitLossFromOperatingActivities", "OperatingIncomeLoss"),
    "net_income": ("ProfitLoss",),
    "eps": ("BasicEarningsLossPerShare",),
    "cash_and_cash_equivalents": ("CashAndCashEquivalents",),
    "accounts_receivable": ("AccountsReceivableNet", "CurrentTradeReceivables", "TradeReceivables"),
    "inventory": ("Inventories",),
    "current_assets": ("CurrentAssets",),
    "total_assets": ("Assets",),
    "current_liabilities": ("CurrentLiabilities",),
    "total_liabilities": ("Liabilities",),
    "equity": ("Equity",),
    "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities", "NetCashFlowsFromUsedInOperatingActivities"),
    "investing_cash_flow": ("NetCashFlowsFromUsedInInvestingActivities", "CashFlowsFromUsedInInvestingActivities"),
    "capital_expenditure": ("AcquisitionOfPropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipment"),
    "research_and_development_expense": ("ResearchAndDevelopmentExpenses", "ResearchAndDevelopmentExpense"),
}

# Statement taxonomies only; notes (tifrs-notes), audit-report (tifrs-ar) and
# equity-statement (tifrs-es) facts reuse similar names with other meanings.
_STATEMENT_NAMESPACE_MARKERS = ("xbrl.iasb.org/taxonomy", "/bsci", "/scf", "/is/", "/bs/", "/cf/", "ifrs-full")
_EXCLUDED_NAMESPACE_MARKERS = ("/notes", "/ar/", "/es/", "/es-", "/dei")


def _is_statement_namespace(namespace: str) -> bool:
    lowered = namespace.lower()
    if any(marker in lowered for marker in _EXCLUDED_NAMESPACE_MARKERS):
        return False
    return any(marker in lowered for marker in _STATEMENT_NAMESPACE_MARKERS)


def _ascii_concepts(aliases: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(alias for alias in aliases if alias.isascii() and alias[:1].isupper() and len(alias) > 4)


def concept_priority(field_name: str) -> tuple[str, ...]:
    """Primary reviewed concepts, then exact concept names reused from the shared alias maps."""
    reused = (
        FIELD_ALIASES.get(field_name, ())
        + EXTENDED_FIELD_ALIASES.get(field_name, ())
        + EXTRA_ALIASES.get(field_name, ())
    )
    ordered = list(PRIMARY_CONCEPTS.get(field_name, ()))
    for concept in _ascii_concepts(reused):
        if concept not in ordered:
            ordered.append(concept)
    return tuple(ordered)


@dataclass
class NormalizedFact:
    metric_code: str
    period: str
    value: Decimal
    unit: str
    source_unit_ref: str
    statement_type: str
    taxonomy_concept: str
    context_ref: str
    decimals: str | None
    mapping_method: str
    quality_status: str = "accepted"
    quality_notes: list[str] = field(default_factory=list)


@dataclass
class NormalizationResult:
    facts: list[NormalizedFact]
    validation_status: str
    quarantine_reason: str | None
    warnings: list[str]
    fields_found: list[str]
    fields_missing: list[str]
    diagnostics: dict[str, object]


def _current_annual(context: XbrlContext, fiscal_year: int, instant: bool) -> bool:
    if context.dimensional:
        return False
    year_end = date(fiscal_year, 12, 31)
    if instant:
        return context.instant == year_end
    return context.start == date(fiscal_year, 1, 1) and context.end == year_end


def _canonical_unit(field_name: str, measure: str) -> tuple[str | None, str | None]:
    lowered = measure.lower()
    if field_name == "eps":
        if lowered == "iso4217:twd/xbrli:shares":
            return "TWD/share", None
        if lowered == "iso4217:twd":
            # Some Taiwan filings tag EPS with the plain currency unit.
            return "TWD/share", "eps_unit_declared_as_currency"
        return None, f"unexpected_eps_unit:{measure}"
    if lowered == "iso4217:twd":
        return "TWD", None
    return None, f"unexpected_monetary_unit:{measure or 'missing'}"


def normalize_annual_filing(
    document: ParsedXbrlDocument,
    *,
    ticker: str,
    fiscal_year: int,
) -> NormalizationResult:
    period = f"{fiscal_year}FY"
    warnings: list[str] = []
    diagnostics: dict[str, object] = {"document_format": document.document_format}

    entities = document.entity_identifiers
    diagnostics["entity_identifiers"] = sorted(entities)
    if entities and entities != {ticker}:
        return NormalizationResult([], "quarantined", "entity_identifier_mismatch", warnings, [], list(CANONICAL_FIELDS), diagnostics)

    statement_facts = [
        fact for fact in document.numeric_facts if _is_statement_namespace(fact.namespace)
    ]
    statement_ends = sorted({
        (context.instant or context.end)
        for fact in statement_facts
        if (context := document.contexts.get(fact.context_ref)) is not None
        and (context.instant or context.end) is not None
    })
    diagnostics["statement_period_ends"] = [value.isoformat() for value in statement_ends[-3:]]
    if not statement_ends:
        return NormalizationResult([], "quarantined", "no_statement_contexts", warnings, [], list(CANONICAL_FIELDS), diagnostics)
    if statement_ends[-1] != date(fiscal_year, 12, 31):
        return NormalizationResult([], "quarantined", f"document_period_mismatch:{statement_ends[-1].isoformat()}", warnings, [], list(CANONICAL_FIELDS), diagnostics)

    by_local: dict[str, list[XbrlFact]] = {}
    for fact in statement_facts:
        by_local.setdefault(fact.local_name, []).append(fact)

    facts: list[NormalizedFact] = []
    mapping: dict[str, object] = {}
    for field_name in CANONICAL_FIELDS:
        instant = field_name in INSTANT_FIELDS
        selected: NormalizedFact | None = None
        alternates: list[str] = []
        for concept in concept_priority(field_name):
            candidates = [
                fact for fact in by_local.get(concept, [])
                if (context := document.contexts.get(fact.context_ref)) is not None
                and _current_annual(context, fiscal_year, instant)
                and not fact.is_nil
            ]
            if not candidates:
                continue
            unparsable = [fact for fact in candidates if fact.value is None]
            values = {fact.value for fact in candidates if fact.value is not None}
            if unparsable and not values:
                alternates.append(f"{concept}:unparsable")
                continue
            if len(values) > 1:
                warnings.append(f"{field_name}: conflicting duplicate values for {concept} {sorted(str(v) for v in values)}")
                alternates.append(f"{concept}:conflicting_duplicates")
                continue
            fact = next(fact for fact in candidates if fact.value is not None)
            measure = document.units.get(fact.unit_ref or "", "")
            unit, unit_note = _canonical_unit(field_name, measure)
            if unit is None:
                alternates.append(f"{concept}:{unit_note}")
                continue
            value = next(iter(values))
            if selected is None:
                notes = [unit_note] if unit_note else []
                if len(candidates) > 1:
                    notes.append(f"deduplicated_{len(candidates)}_identical_facts")
                selected = NormalizedFact(
                    metric_code=field_name,
                    period=period,
                    value=value,
                    unit=unit,
                    source_unit_ref=fact.unit_ref or "",
                    statement_type=statement_type_for(field_name),
                    taxonomy_concept=fact.concept,
                    context_ref=fact.context_ref,
                    decimals=fact.decimals,
                    mapping_method="primary_concept" if concept in PRIMARY_CONCEPTS.get(field_name, ()) else "shared_alias_concept",
                    quality_notes=notes,
                )
            elif value != selected.value:
                alternates.append(f"{fact.concept}={value}")
                selected.quality_status = "warning"
                selected.quality_notes.append(f"alternate_concept_disagrees:{fact.concept}={value}")
        if selected is not None:
            if any(note.startswith("eps_unit") for note in selected.quality_notes):
                selected.quality_status = "warning"
            facts.append(selected)
            mapping[field_name] = {
                "concept": selected.taxonomy_concept,
                "context": selected.context_ref,
                "method": selected.mapping_method,
                "alternates": alternates,
            }
        else:
            mapping[field_name] = {"concept": None, "alternates": alternates}
    diagnostics["mapping"] = mapping

    mapped_concepts = {fact.taxonomy_concept.split(":")[-1] for fact in facts}
    current_unmapped = sorted({
        fact.concept for fact in statement_facts
        if fact.local_name not in mapped_concepts
        and (context := document.contexts.get(fact.context_ref)) is not None
        and not context.dimensional
        and (context.instant == date(fiscal_year, 12, 31) or context.end == date(fiscal_year, 12, 31))
    })
    diagnostics["unmapped_current_period_concepts"] = current_unmapped
    diagnostics["unmapped_current_period_concept_count"] = len(current_unmapped)

    values = {fact.metric_code: fact.value for fact in facts}
    _identity_check(values, "total_assets", ("total_liabilities", "equity"), warnings)
    if all(key in values for key in ("revenue", "cost_of_goods_sold", "gross_profit")):
        expected = values["revenue"] - values["cost_of_goods_sold"]
        if abs(expected - values["gross_profit"]) > max(Decimal(1000), abs(values["revenue"]) * Decimal("0.001")):
            warnings.append(
                f"identity_check: revenue - cost_of_goods_sold = {expected} differs from gross_profit {values['gross_profit']}"
            )

    found = [fact.metric_code for fact in facts]
    missing = [name for name in CANONICAL_FIELDS if name not in found]
    core_found = [name for name in CORE_FIELDS if name in found]
    if len(core_found) < 4:
        return NormalizationResult(facts, "quarantined", "insufficient_core_fields", warnings, found, missing, diagnostics)
    status = "validated_with_warnings" if warnings or any(fact.quality_status != "accepted" for fact in facts) else "validated"
    return NormalizationResult(facts, status, None, warnings, found, missing, diagnostics)


def _identity_check(values: dict[str, Decimal], total: str, parts: tuple[str, ...], warnings: list[str]) -> None:
    if total not in values or any(part not in values for part in parts):
        return
    combined = sum((values[part] for part in parts), Decimal(0))
    if abs(combined - values[total]) > max(Decimal(1000), abs(values[total]) * Decimal("0.001")):
        warnings.append(f"identity_check: {' + '.join(parts)} = {combined} differs from {total} {values[total]}")
