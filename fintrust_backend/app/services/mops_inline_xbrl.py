from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.historical_analysis_models import HistoricalPeriodRecord
from app.models import CompanyProfile

try:
    from twmops.clients.xbrl_client import MOPSXBRLClient, MOPSXBRLClientError
    from twmops.parsers.arelle import check_arelle_available
    from twmops.parsers.xbrl_parser import XBRLParser, XBRLParserError
    from twmops.utils.numerics import parse_financial_value
except ImportError:  # pragma: no cover - deployment dependency guard
    MOPSXBRLClient = None  # type: ignore[assignment]
    XBRLParser = None  # type: ignore[assignment]

    class MOPSXBRLClientError(Exception):
        pass

    class XBRLParserError(Exception):
        pass

    def check_arelle_available() -> bool:
        return False

    def parse_financial_value(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class MopsInlineXbrlError(RuntimeError):
    pass


MOPS_DOWNLOAD_TEMPLATE = (
    "https://mopsov.twse.com.tw/server-java/FileDownLoad"
    "?functionName=t164sb01&step=9&co_id={ticker}&year={fiscal_year}"
    "&season=4&report_id=C"
)

# Each entry contains preferred Chinese labels followed by stable IFRS/TWSE
# concept suffixes. Both are used because labels and taxonomy prefixes can vary
# by filing year while the economic meaning remains the same. Taiwan cash-flow
# statement facts may use local statement item codes (for example AAAA and
# B02700) rather than the long IFRS concept names, so those stable codes are
# included explicitly.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "營業收入",
        "營業收入合計",
        "Revenue",
        "OperatingRevenue",
        "RevenueFromContractsWithCustomers",
    ),
    "gross_profit": (
        "營業毛利（毛損）",
        "營業毛利(毛損)",
        "營業毛利",
        "GrossProfitLoss",
    ),
    "operating_income": (
        "營業利益（損失）",
        "營業利益(損失)",
        "營業利益",
        "OperatingIncomeLoss",
    ),
    "net_income": (
        "本期淨利（淨損）",
        "本期淨利(淨損)",
        "本期淨利",
        "本期稅後淨利（淨損）",
        "稅後淨利",
        "ProfitLoss",
    ),
    "eps": (
        "基本每股盈餘（元）",
        "基本每股盈餘(元)",
        "基本每股盈餘",
        "BasicEarningsLossPerShare",
    ),
    "cash_and_cash_equivalents": (
        "現金及約當現金",
        "CashAndCashEquivalents",
    ),
    "inventory": ("存貨", "Inventories"),
    "current_assets": ("流動資產", "CurrentAssets"),
    "total_assets": ("資產總額", "資產合計", "Assets"),
    "current_liabilities": ("流動負債", "CurrentLiabilities"),
    "total_liabilities": ("負債總額", "負債合計", "Liabilities"),
    "equity": ("權益總額", "權益總計", "Equity"),
    "operating_cash_flow": (
        "AAAA",
        "營業活動之淨現金流入（流出）",
        "營業活動之淨現金流入(流出)",
        "營業活動之淨現金流量",
        "NetCashFlowsFromUsedInOperatingActivities",
        "NetCashFlowsFromOperatingActivities",
    ),
    "investing_cash_flow": (
        "BBBB",
        "投資活動之淨現金流入（流出）",
        "投資活動之淨現金流入(流出)",
        "投資活動之淨現金流量",
        "NetCashFlowsFromUsedInInvestingActivities",
        "NetCashFlowsFromInvestingActivities",
    ),
    "capital_expenditure": (
        "B02700",
        "取得不動產、廠房及設備",
        "購置不動產、廠房及設備",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "AcquisitionOfPropertyPlantAndEquipment",
    ),
    "research_and_development_expense": (
        "研究發展費用",
        "研究及發展費用",
        "研發費用",
        "ResearchAndDevelopmentExpense",
    ),
}

INSTANT_FIELDS = {
    "cash_and_cash_equivalents",
    "inventory",
    "current_assets",
    "total_assets",
    "current_liabilities",
    "total_liabilities",
    "equity",
}


def _normalized_token(value: Any) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[\s\-_:：()（）,.，、/\\]", "", text)


def _object_value(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _match_score(concept: str, label: str, alias: str) -> int:
    normalized_alias = _normalized_token(alias)
    normalized_label = _normalized_token(label)
    normalized_concept = _normalized_token(concept.split(":")[-1])
    if normalized_label == normalized_alias:
        return 4
    if normalized_concept == normalized_alias:
        return 3
    if normalized_alias and normalized_alias in normalized_label:
        return 2
    if normalized_alias and normalized_concept.endswith(normalized_alias):
        return 1
    return 0


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group())
    except ValueError:
        return None


def _context_is_current_annual(context: Any, fiscal_year: int, instant: bool) -> bool:
    target_end = date(fiscal_year, 12, 31)
    arelle_exclusive_end = date(fiscal_year + 1, 1, 1)

    if instant:
        instant_date = _parse_date(_object_value(context, "instant"))
        return instant_date in {target_end, arelle_exclusive_end}

    start_date = _parse_date(_object_value(context, "period_start"))
    end_date = _parse_date(_object_value(context, "period_end"))
    if start_date is None or end_date not in {target_end, arelle_exclusive_end}:
        return False
    return start_date in {date(fiscal_year, 1, 1), date(fiscal_year - 1, 12, 31)}


def _extract_package_value(
    package: Any,
    aliases: tuple[str, ...],
    *,
    fiscal_year: int,
    instant: bool,
) -> tuple[float | None, str | None]:
    contexts = _object_value(package, "contexts") or {}
    labels = _object_value(package, "labels") or {}
    facts = _object_value(package, "facts") or []
    best: tuple[int, int, float, str] | None = None

    for fact in facts:
        context_ref = str(_object_value(fact, "context_ref") or "")
        context = contexts.get(context_ref) if isinstance(contexts, dict) else None
        if context is None or not _context_is_current_annual(context, fiscal_year, instant):
            continue

        concept = str(_object_value(fact, "concept") or "")
        label = str(labels.get(concept, concept)) if isinstance(labels, dict) else concept
        alias_score = max(
            (_match_score(concept, label, alias) for alias in aliases),
            default=0,
        )
        if alias_score == 0:
            continue

        value = parse_financial_value(_object_value(fact, "value"))
        if value is None:
            continue

        # Prefer exact label/concept matches and shorter context ids. In MOPS
        # consolidated filings, the shortest matching current-period context is
        # normally the non-dimensional total rather than a segment breakdown.
        candidate = (alias_score, -len(context_ref), float(value), label or concept)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is None:
        return None, None
    return best[2], best[3]


def normalize_mops_annual_package(
    profile: CompanyProfile,
    roc_year: int,
    package: Any,
    *,
    source_url: str | None = None,
) -> HistoricalPeriodRecord:
    fiscal_year = roc_year + 1911
    values: dict[str, float | None] = {}
    concept_matches: dict[str, str] = {}
    found: list[str] = []
    missing: list[str] = []

    for canonical, aliases in FIELD_ALIASES.items():
        value, matched_name = _extract_package_value(
            package,
            aliases,
            fiscal_year=fiscal_year,
            instant=canonical in INSTANT_FIELDS,
        )
        values[canonical] = value
        if value is None:
            missing.append(canonical)
        else:
            found.append(canonical)
            if matched_name:
                concept_matches[canonical] = matched_name

    warnings: list[str] = []
    if not (_object_value(package, "contexts") or {}):
        warnings.append("iXBRL 文件未解析出 context，系統不會使用未確認期間的數值。")

    core_found = sum(
        values.get(field) is not None
        for field in ("revenue", "net_income", "total_assets", "total_liabilities")
    )
    status = "available" if core_found >= 2 else "missing"
    if status == "missing":
        warnings.append(
            "MOPS iXBRL 已下載，但目前年度的核心欄位不足；可能是 taxonomy mapping 或 context 尚未涵蓋。"
        )

    return HistoricalPeriodRecord(
        ticker=profile.ticker,
        company_name=profile.name,
        subindustry=profile.subindustry,
        fiscal_year=fiscal_year,
        roc_year=roc_year,
        period=f"{fiscal_year}FY",
        source_url=source_url
        or MOPS_DOWNLOAD_TEMPLATE.format(
            ticker=profile.ticker,
            fiscal_year=fiscal_year,
        ),
        status=status,
        fields_found=found,
        fields_missing=missing,
        concept_matches=concept_matches,
        warnings=warnings,
        **values,
    )


class MopsInlineXbrlClient:
    """Download one consolidated annual iXBRL package per year and select facts
    using the current annual context.

    Only Q4/annual filings are used in the first integration, preventing
    year-to-date Q2/Q3 values from being presented as standalone quarters.
    """

    def __init__(
        self,
        *,
        xbrl_client: Any | None = None,
        parser: Any | None = None,
        require_arelle: bool = True,
        cache_enabled: bool = True,
        cache_dir: str | Path | None = None,
        cache_ttl_hours: float | None = None,
    ) -> None:
        if MOPSXBRLClient is None or XBRLParser is None:
            raise MopsInlineXbrlError(
                "缺少 twmops 套件；請重新安裝 backend/requirements.txt。"
            )
        if require_arelle and parser is None and not check_arelle_available():
            raise MopsInlineXbrlError(
                "缺少 Arelle；請安裝 twmops[xbrl]，避免 iXBRL scale 或 taxonomy 解析不完整。"
            )
        self.xbrl_client = xbrl_client or MOPSXBRLClient()
        self.parser = parser or XBRLParser()
        self.cache_enabled = cache_enabled
        self.cache_dir = Path(
            cache_dir
            or os.getenv("MOPS_XBRL_CACHE_DIR", "./data/mops_ixbrl_cache")
        )
        self.cache_ttl_seconds = (
            float(cache_ttl_hours)
            if cache_ttl_hours is not None
            else float(os.getenv("MOPS_XBRL_CACHE_TTL_HOURS", "24"))
        ) * 3600

    def _cache_path(self, profile: CompanyProfile, roc_year: int) -> Path:
        return self.cache_dir / f"{profile.ticker}_{roc_year}_Q4_C.ixbrl"

    def _read_cache(self, profile: CompanyProfile, roc_year: int) -> bytes | None:
        if not self.cache_enabled:
            return None
        path = self._cache_path(profile, roc_year)
        try:
            age_seconds = time.time() - path.stat().st_mtime
            if age_seconds <= self.cache_ttl_seconds:
                return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        return None

    def _write_cache(self, profile: CompanyProfile, roc_year: int, content: bytes) -> None:
        if not self.cache_enabled:
            return
        path = self._cache_path(profile, roc_year)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
        except OSError:
            # Cache failure must never turn a valid official download into an
            # analysis failure. The next request will simply download again.
            return

    async def fetch_annual(self, profile: CompanyProfile, roc_year: int) -> HistoricalPeriodRecord:
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
            package = self.parser.parse(content, profile.ticker, roc_year, 4)
        except (MOPSXBRLClientError, XBRLParserError) as exc:
            raise MopsInlineXbrlError(str(exc)) from exc
        except Exception as exc:
            raise MopsInlineXbrlError(f"MOPS iXBRL 下載或解析失敗：{exc}") from exc

        return normalize_mops_annual_package(profile, roc_year, package)

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

        # Try at most two additional years so an annual filing not yet published
        # does not prevent returning the requested number of available periods.
        while (
            sum(period.status == "available" for period in periods) < years
            and attempts < years + 2
        ):
            attempts += 1
            try:
                periods.append(await self.fetch_annual(profile, candidate))
            except MopsInlineXbrlError as exc:
                fiscal_year = candidate + 1911
                periods.append(
                    HistoricalPeriodRecord(
                        ticker=profile.ticker,
                        company_name=profile.name,
                        subindustry=profile.subindustry,
                        fiscal_year=fiscal_year,
                        roc_year=candidate,
                        period=f"{fiscal_year}FY",
                        source_url=MOPS_DOWNLOAD_TEMPLATE.format(
                            ticker=profile.ticker,
                            fiscal_year=fiscal_year,
                        ),
                        status="error",
                        warnings=[str(exc)],
                        fields_missing=list(FIELD_ALIASES),
                    )
                )
            candidate -= 1

        return sorted(periods, key=lambda period: period.fiscal_year)