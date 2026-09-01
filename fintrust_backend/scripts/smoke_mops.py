from __future__ import annotations

import asyncio
import json

from app.services.company_registry import get_company
from app.services.robust_mops_inline_xbrl import RobustMopsInlineXbrlClient


async def main() -> None:
    profile = get_company("2330")
    if profile is None:
        raise RuntimeError("台積電不在 semiconductor registry")

    # 2024 / ROC 113 is a stable, fully published annual filing.
    record = await RobustMopsInlineXbrlClient().fetch_annual(profile, 113)
    result = {
        "ticker": record.ticker,
        "period": record.period,
        "status": record.status,
        "revenue": record.revenue,
        "total_assets": record.total_assets,
        "net_income": record.net_income,
        "operating_cash_flow": record.operating_cash_flow,
        "capital_expenditure": record.capital_expenditure,
        "fields_found": record.fields_found,
        "fields_missing": record.fields_missing,
        "concept_matches": record.concept_matches,
        "warnings": record.warnings,
        "source_url": record.source_url,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if record.status != "available":
        raise RuntimeError("MOPS iXBRL 已下載但核心欄位未通過 mapping／context 檢查")
    if record.revenue is None or record.total_assets is None or record.net_income is None:
        raise RuntimeError("MOPS smoke test 缺少營收、資產或淨利核心欄位")
    if record.operating_cash_flow is None or record.capital_expenditure is None:
        raise RuntimeError(
            "MOPS smoke test 缺少營業現金流或資本支出；請執行 diagnose_mops_mapping.py。"
        )


if __name__ == "__main__":
    asyncio.run(main())
