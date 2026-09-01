from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from app.historical_analysis_models import HistoricalPeriodRecord
from app.models import CompanyProfile
from app.services.mops_inline_xbrl import (
    FIELD_ALIASES,
    INSTANT_FIELDS,
    MopsInlineXbrlClient,
    MopsInlineXbrlError,
    MOPSXBRLClientError,
    XBRLParserError,
    _object_value,
    _parse_date,
    parse_financial_value,
)


EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "operating_cash_flow": (
        "CashFlowsFromUsedInOperatingActivities",
        "CashFlowsFromOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByOperatingActivities",
    ),
    "investing_cash_flow": (
        "CashFlowsFromUsedInInvestingActivities",
        "CashFlowsFromInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
    ),
    "capital_expenditure": (
        "PurchaseOfPropertyPlantAndEquipment",
        "PurchasesOfPropertyPlantAndEquipment",
        "PaymentsForPropertyPlantAndEquipment",
        "PaymentsToAcquirePropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "AdditionsToPropertyPlantAndEquipment",
    ),
}

# Used only as a lower-priority fallback after exact taxonomy aliases. Each
# tuple is a group whose tokens must all appear in the concept or label.
FIELD_KEYWORD_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "operating_cash_flow": (
        ("cashflow", "operatingactivit"),
        ("netcash", "operatingactivit"),
        ("營業活動", "現金流"),
    ),
    "investing_cash_flow": (
        ("cashflow", "investingactivit"),
        ("netcash", "investingactivit"),
        ("投資活動", "現金流"),
    ),
    "capital_expenditure": (
        ("property", "plant", "equipment", "acquir"),
        ("property", "plant", "equipment", "purchase"),
        ("property", "plant", "equipment", "payment"),
        ("不動產", "廠房", "設備", "取得"),
        ("不動產", "廠房", "設備", "購置"),
    ),
}


def _token(value: Any) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _local_name(concept: str) -> str:
    value = concept.rsplit(":", 1)[-1]
    if "}" in value:
        value = value.rsplit("}", 1)[-1]
    return value


def _annual_context_score(context: Any, fiscal_year: int, instant: bool) -> int:
    target_end = date(fiscal_year, 12, 31)
    exclusive_end = date(fiscal_year + 1, 1, 1)

    if instant:
        instant_date = _parse_date(_object_value(context, "instant"))
        return 3 if instant_date in {target_end, exclusive_end} else 0

    start = _parse_date(_object_value(context, "period_start"))
    end = _parse_date(_object_value(context, "period_end"))
    if start is None or end not in {target_end, exclusive_end}:
        return 0

    exact_starts = {date(fiscal_year, 1, 1), date(fiscal_year - 1, 12, 31)}
    if start in exact_starts:
        return 3

    duration_days = (end - start).days
    return 2 if 350 <= duration_days <= 370 else 0


def _match_score(
    concept: str,
    labels: tuple[str, ...],
    aliases: tuple[str, ...],
    keyword_groups: tuple[tuple[str, ...], ...],
) -> int:
    concept_token = _token(_local_name(concept))
    label_tokens = [_token(label) for label in labels if label]

    best = 0
    for alias in aliases:
        alias_token = _token(alias)
        if not alias_token:
            continue
        if concept_token == alias_token:
            best = max(best, 100)
        if alias_token in label_tokens:
            best = max(best, 95)
        if concept_token.endswith(alias_token):
            best = max(best, 85)
        if any(alias_token in label for label in label_tokens):
            best = max(best, 75)

    searchable = " ".join([concept_token, *label_tokens])
    for group in keyword_groups:
        if all(_token(token) in searchable for token in group):
            best = max(best, 50 + len(group))
    return best


def robust_extract_package_value(
    package: Any,
    canonical: str,
    aliases: tuple[str, ...],
    *,
    fiscal_year: int,
    instant: bool,
) -> tuple[float | None, str | None]:
    contexts = _object_value(package, "contexts") or {}
    labels_zh = _object_value(package, "labels") or {}
    labels_en = _object_value(package, "labels_en") or {}
    facts = _object_value(package, "facts") or []

    expanded_aliases = aliases + EXTRA_ALIASES.get(canonical, ())
    keyword_groups = FIELD_KEYWORD_GROUPS.get(canonical, ())
    best: tuple[int, int, int, float, str] | None = None

    for fact in facts:
        context_ref = str(_object_value(fact, "context_ref") or "")
        context = contexts.get(context_ref) if isinstance(contexts, dict) else None
        if context is None:
            continue
        context_score = _annual_context_score(context, fiscal_year, instant)
        if context_score == 0:
            continue

        concept = str(_object_value(fact, "concept") or "")
        zh = str(labels_zh.get(concept, "")) if isinstance(labels_zh, dict) else ""
        en = str(labels_en.get(concept, "")) if isinstance(labels_en, dict) else ""
        score = _match_score(concept, (zh, en), expanded_aliases, keyword_groups)
        if score == 0:
            continue

        value = parse_financial_value(_object_value(fact, "value"))
        if value is None:
            continue

        # Exact aliases first, then the cleanest annual context. Shorter
        # context ids usually represent the consolidated total rather than a
        # dimensional segment fact.
        candidate = (score, context_score, -len(context_ref), float(value), _local_name(concept))
        if best is None or candidate[:3] > best[:3]:
            best = candidate

    if best is None:
        return None, None
    return best[3], best[4]


def robust_normalize_mops_annual_package(
    profile: CompanyProfile,
    roc_year: int,
    package: Any,
) -> HistoricalPeriodRecord:
    fiscal_year = roc_year + 1911
    values: dict[str, float | None] = {}
    concept_matches: dict[str, str] = {}
    found: list[str] = []
    missing: list[str] = []

    for canonical, aliases in FIELD_ALIASES.items():
        value, concept = robust_extract_package_value(
            package,
            canonical,
            aliases,
            fiscal_year=fiscal_year,
            instant=canonical in INSTANT_FIELDS,
        )
        values[canonical] = value
        if value is None:
            missing.append(canonical)
        else:
            found.append(canonical)
            if concept:
                concept_matches[canonical] = concept

    warnings: list[str] = []
    if not (_object_value(package, "contexts") or {}):
        warnings.append("iXBRL 文件未解析出 context，系統不會使用未確認期間的數值。")

    core_found = sum(
        values.get(field) is not None
        for field in ("revenue", "net_income", "total_assets", "total_liabilities")
    )
    status = "available" if core_found >= 2 else "missing"
    if status == "missing":
        warnings.append("MOPS iXBRL 已下載，但核心欄位不足；需檢查 taxonomy 或期間 context。")

    critical_missing = [
        field
        for field in ("operating_cash_flow", "capital_expenditure")
        if values.get(field) is None
    ]
    if critical_missing:
        warnings.append(
            "歷史現金流規則缺少原始欄位：" + "、".join(critical_missing)
            + "；系統保留資料不足，不以其他欄位替代。"
        )

    source_url = (
        "https://mopsov.twse.com.tw/server-java/FileDownLoad"
        f"?functionName=t164sb01&step=9&co_id={profile.ticker}&year={roc_year}"
        "&season=4&report_id=C"
    )
    return HistoricalPeriodRecord(
        ticker=profile.ticker,
        company_name=profile.name,
        subindustry=profile.subindustry,
        fiscal_year=fiscal_year,
        roc_year=roc_year,
        period=f"{fiscal_year}FY",
        source_url=source_url,
        status=status,
        fields_found=found,
        fields_missing=missing,
        concept_matches=concept_matches,
        warnings=warnings,
        **values,
    )


class RobustMopsInlineXbrlClient(MopsInlineXbrlClient):
    """MOPS client with bilingual labels, semantic fallbacks and diagnostics."""

    async def load_package(self, profile: CompanyProfile, roc_year: int) -> Any:
        try:
            content = self._read_cache(profile, roc_year)
            if content is None:
                content = await self.xbrl_client.download_xbrl_async(
                    profile.ticker,
                    roc_year,
                    4,
                    report_type="C",
                )
                self._write_cache(profile, roc_year, content)
            return self.parser.parse(content, profile.ticker, roc_year, 4)
        except (MOPSXBRLClientError, XBRLParserError) as exc:
            raise MopsInlineXbrlError(str(exc)) from exc
        except Exception as exc:
            raise MopsInlineXbrlError(f"MOPS iXBRL 下載或解析失敗：{exc}") from exc

    async def fetch_annual(self, profile: CompanyProfile, roc_year: int) -> HistoricalPeriodRecord:
        package = await self.load_package(profile, roc_year)
        return robust_normalize_mops_annual_package(profile, roc_year, package)

    async def fetch_history(
        self,
        profile: CompanyProfile,
        *,
        years: int = 5,
        end_roc_year: int | None = None,
    ) -> list[HistoricalPeriodRecord]:
        if not 3 <= years <= 5:
            raise ValueError("MVP 歷史期間僅支援 3 至 5 年。")

        now = datetime.now(timezone.utc)
        latest_candidate = end_roc_year or (now.year - 1911 - 1)
        periods: list[HistoricalPeriodRecord] = []
        attempts = 0
        candidate = latest_candidate
        while (
            sum(period.status == "available" for period in periods) < years
            and attempts < years + 2
        ):
            attempts += 1
            try:
                periods.append(await self.fetch_annual(profile, candidate))
            except MopsInlineXbrlError as exc:
                fiscal_year = candidate + 1911
                source_url = (
                    "https://mopsov.twse.com.tw/server-java/FileDownLoad"
                    f"?functionName=t164sb01&step=9&co_id={profile.ticker}&year={candidate}"
                    "&season=4&report_id=C"
                )
                periods.append(
                    HistoricalPeriodRecord(
                        ticker=profile.ticker,
                        company_name=profile.name,
                        subindustry=profile.subindustry,
                        fiscal_year=fiscal_year,
                        roc_year=candidate,
                        period=f"{fiscal_year}FY",
                        source_url=source_url,
                        status="error",
                        warnings=[str(exc)],
                        fields_missing=list(FIELD_ALIASES),
                    )
                )
            candidate -= 1
        return sorted(periods, key=lambda period: period.fiscal_year)

    async def diagnose_annual(self, profile: CompanyProfile, roc_year: int) -> dict[str, Any]:
        package = await self.load_package(profile, roc_year)
        record = robust_normalize_mops_annual_package(profile, roc_year, package)
        contexts = _object_value(package, "contexts") or {}
        labels_zh = _object_value(package, "labels") or {}
        labels_en = _object_value(package, "labels_en") or {}
        candidates: list[dict[str, Any]] = []
        keywords = (
            "cash", "operating", "investing", "property", "plant", "equipment",
            "acquir", "purchase", "payment", "現金", "營業活動", "投資活動",
            "不動產", "廠房", "設備", "取得", "購置",
        )
        for fact in _object_value(package, "facts") or []:
            concept = str(_object_value(fact, "concept") or "")
            zh = str(labels_zh.get(concept, "")) if isinstance(labels_zh, dict) else ""
            en = str(labels_en.get(concept, "")) if isinstance(labels_en, dict) else ""
            searchable = " ".join((concept, zh, en)).casefold()
            if not any(keyword.casefold() in searchable for keyword in keywords):
                continue
            context_ref = str(_object_value(fact, "context_ref") or "")
            context = contexts.get(context_ref) if isinstance(contexts, dict) else None
            candidates.append(
                {
                    "concept": concept,
                    "label_zh": zh,
                    "label_en": en,
                    "value": _object_value(fact, "value"),
                    "unit": _object_value(fact, "unit"),
                    "context_ref": context_ref,
                    "period_start": _object_value(context, "period_start") if context else None,
                    "period_end": _object_value(context, "period_end") if context else None,
                    "instant": _object_value(context, "instant") if context else None,
                }
            )
        return {
            "ticker": profile.ticker,
            "period": record.period,
            "status": record.status,
            "fields_found": record.fields_found,
            "fields_missing": record.fields_missing,
            "concept_matches": record.concept_matches,
            "warnings": record.warnings,
            "candidate_facts": candidates,
        }
