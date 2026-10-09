"""Deterministic SYNTHETIC XBRL fixtures for historical-audit tests.

These documents mimic the structure of Taiwan-IFRS MOPS instances (contexts,
dimensional equity members, units, audit-report facts) with invented numbers.
They prove pipeline behaviour only; they are not real 1785 filings and must
never be described as evidence of an actual original or restated statement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_VALUES: dict[str, int] = {
    "revenue": 1_000_000_000,
    "cost_of_goods_sold": 800_000_000,
    "gross_profit": 200_000_000,
    "operating_income": 50_000_000,
    "net_income": 40_000_000,
    "accounts_receivable": 150_000_000,
    "inventory": 300_000_000,
    "current_assets": 700_000_000,
    "total_assets": 2_000_000_000,
    "current_liabilities": 400_000_000,
    "total_liabilities": 1_200_000_000,
    "equity": 800_000_000,
    "operating_cash_flow": 90_000_000,
    "investing_cash_flow": -60_000_000,
    "capital_expenditure": -55_000_000,
    "cash_and_cash_equivalents": 120_000_000,
}

_CONCEPTS = {
    "revenue": ("tifrs-bsci-ci", "OperatingRevenue", "duration"),
    "cost_of_goods_sold": ("tifrs-bsci-ci", "OperatingCosts", "duration"),
    "gross_profit": ("tifrs-bsci-ci", "GrossProfitLossFromOperations", "duration"),
    "operating_income": ("tifrs-bsci-ci", "NetOperatingIncomeLoss", "duration"),
    "net_income": ("ifrs", "ProfitLoss", "duration"),
    "accounts_receivable": ("tifrs-bsci-ci", "AccountsReceivableNet", "instant"),
    "inventory": ("ifrs", "Inventories", "instant"),
    "current_assets": ("ifrs", "CurrentAssets", "instant"),
    "total_assets": ("ifrs", "Assets", "instant"),
    "current_liabilities": ("ifrs", "CurrentLiabilities", "instant"),
    "total_liabilities": ("ifrs", "Liabilities", "instant"),
    "equity": ("ifrs", "Equity", "instant"),
    "operating_cash_flow": ("ifrs", "CashFlowsFromUsedInOperatingActivities", "duration"),
    "investing_cash_flow": ("tifrs-SCF", "NetCashFlowsFromUsedInInvestingActivities", "duration"),
    "capital_expenditure": ("tifrs-SCF", "AcquisitionOfPropertyPlantAndEquipment", "duration"),
    "cash_and_cash_equivalents": ("ifrs", "CashAndCashEquivalents", "instant"),
}


def synthetic_instance(
    *,
    ticker: str = "1785",
    fiscal_year: int = 2014,
    overrides: dict[str, int] | None = None,
    omit: tuple[str, ...] = (),
    eps: str = "0.50",
    audit_date: str | None = None,
    emphasis_text: str = "",
    entry_point: str = "tifrs-ci-cr-2013-03-31.xsd",
    entity: str | None = None,
    extra_facts: str = "",
) -> bytes:
    values = {**BASE_VALUES, **(overrides or {})}
    year = fiscal_year
    audit = audit_date or f"{year + 1}-03-20"
    audit_id = "AsOf" + audit.replace("-", "")
    instant, duration = f"AsOf{year}1231", f"From{year}0101To{year}1231"
    prior = f"AsOf{year - 1}1231"
    identifier = entity or ticker

    def context(context_id: str, period: str, member: str | None = None) -> str:
        segment = (
            f"<xbrli:segment><xbrldi:explicitMember dimension=\"ifrs:ComponentsOfEquityAxis\">ifrs:{member}</xbrldi:explicitMember></xbrli:segment>"
            if member else ""
        )
        return (
            f"<xbrli:context id=\"{context_id}\"><xbrli:entity><xbrli:identifier scheme=\"http://www.twse.com.tw\">{identifier}</xbrli:identifier>{segment}</xbrli:entity>"
            f"<xbrli:period>{period}</xbrli:period></xbrli:context>"
        )

    facts = []
    for field, (prefix, local, kind) in _CONCEPTS.items():
        if field in omit:
            continue
        ref = instant if kind == "instant" else duration
        facts.append(f"<{prefix}:{local} contextRef=\"{ref}\" decimals=\"-3\" unitRef=\"TWD\">{values[field]}</{prefix}:{local}>")
    # Prior-year comparative and a dimensional equity component must both be ignored.
    facts.append(f"<ifrs:Inventories contextRef=\"{prior}\" decimals=\"-3\" unitRef=\"TWD\">999999000</ifrs:Inventories>")
    facts.append(f"<ifrs:Equity contextRef=\"{instant}_RetainedEarningsMember\" decimals=\"-3\" unitRef=\"TWD\">12345000</ifrs:Equity>")
    facts.append(f"<ifrs:BasicEarningsLossPerShare contextRef=\"{duration}\" decimals=\"2\" unitRef=\"EarningsPerShare\">{eps}</ifrs:BasicEarningsLossPerShare>")
    # Same-named notes fact with another meaning must not be mapped.
    facts.append(f"<tifrs-notes:OperatingRevenue contextRef=\"{duration}\" decimals=\"-3\" unitRef=\"TWD\">1</tifrs-notes:OperatingRevenue>")
    facts.append(f"<tifrs-ar:ReviewAuditDate contextRef=\"{audit_id}\">{audit}</tifrs-ar:ReviewAuditDate>")
    facts.append(f"<tifrs-ar:DescriptionEmphasizeItemBody contextRef=\"{audit_id}\" lang=\"zh\"><![CDATA[{emphasis_text}]]></tifrs-ar:DescriptionEmphasizeItemBody>")

    xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<xbrli:xbrl xmlns:xbrli=\"http://www.xbrl.org/2003/instance\" xmlns:link=\"http://www.xbrl.org/2003/linkbase\""
        " xmlns:xlink=\"http://www.w3.org/1999/xlink\" xmlns:xbrldi=\"http://xbrl.org/2006/xbrldi\""
        " xmlns:iso4217=\"http://www.xbrl.org/2003/iso4217\""
        " xmlns:ifrs=\"http://xbrl.iasb.org/taxonomy/2010-04-30/ifrs\""
        " xmlns:tifrs-bsci-ci=\"http://www.xbrl.org/tifrs/bsci/ci/2013-03-31\""
        " xmlns:tifrs-SCF=\"http://www.xbrl.org/tifrs/scf/2013-03-31\""
        " xmlns:tifrs-notes=\"http://www.xbrl.org/tifrs/notes/2013-03-31\""
        " xmlns:tifrs-ar=\"http://www.xbrl.org/tifrs/ar/2013-03-31\">"
        f"<link:schemaRef xlink:type=\"simple\" xlink:href=\"{entry_point}\"/>"
        + context(instant, f"<xbrli:instant>{year}-12-31</xbrli:instant>")
        + context(prior, f"<xbrli:instant>{year - 1}-12-31</xbrli:instant>")
        + context(duration, f"<xbrli:startDate>{year}-01-01</xbrli:startDate><xbrli:endDate>{year}-12-31</xbrli:endDate>")
        + context(f"{instant}_RetainedEarningsMember", f"<xbrli:instant>{year}-12-31</xbrli:instant>", "RetainedEarningsMember")
        + context(audit_id, f"<xbrli:instant>{audit}</xbrli:instant>")
        + "<xbrli:unit id=\"TWD\"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>"
        + "<xbrli:unit id=\"EarningsPerShare\"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unitNumerator>"
        + "<xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>"
        + "".join(facts) + extra_facts
        + "</xbrli:xbrl>\n"
    )
    return xml.encode("utf-8")


def synthetic_inline(*, ticker: str = "1785", fiscal_year: int = 2019, inventory_thousands: str = "1,234") -> bytes:
    year = fiscal_year
    html = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:ifrs-full="http://xbrl.ifrs.org/taxonomy/2018-03-16/ifrs-full"
 xmlns:tifrs-bsci-ci="http://www.twse.com.tw/tifrs/bsci/ci/2018-03-31"
 xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2015-02-26">
<head><title>synthetic</title></head><body>
<ix:header><ix:references><link:schemaRef xlink:type="simple" xlink:href="tifrs-ci-cr-2018-03-31.xsd"/></ix:references>
<ix:resources>
<xbrli:context id="AsOf{year}1231"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">{ticker}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>{year}-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="From{year}0101To{year}1231"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">{ticker}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{year}-01-01</xbrli:startDate><xbrli:endDate>{year}-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
</ix:resources></ix:header>
<table>
<tr><td><ix:nonFraction name="ifrs-full:Inventories" contextRef="AsOf{year}1231" unitRef="TWD" decimals="-3" scale="3" format="ixt:numdotdecimal">{inventory_thousands}</ix:nonFraction></td></tr>
<tr><td><ix:nonFraction name="tifrs-bsci-ci:OperatingRevenue" contextRef="From{year}0101To{year}1231" unitRef="TWD" decimals="-3" scale="3" format="ixt:numdotdecimal">10,000</ix:nonFraction></td></tr>
<tr><td><ix:nonFraction name="ifrs-full:ProfitLoss" contextRef="From{year}0101To{year}1231" unitRef="TWD" decimals="-3" scale="3" sign="-" format="ixt:numdotdecimal">250</ix:nonFraction></td></tr>
<tr><td><ix:nonFraction name="ifrs-full:Assets" contextRef="AsOf{year}1231" unitRef="TWD" decimals="-3" scale="3" format="ixt:numdotdecimal">50,000</ix:nonFraction></td></tr>
<tr><td><ix:nonFraction name="ifrs-full:Liabilities" contextRef="AsOf{year}1231" unitRef="TWD" decimals="-3" scale="3" format="ixt:numdotdecimal">20,000</ix:nonFraction></td></tr>
<tr><td><ix:nonFraction name="ifrs-full:Equity" contextRef="AsOf{year}1231" unitRef="TWD" decimals="-3" scale="3" format="ixt:numdotdecimal">30,000</ix:nonFraction></td></tr>
</table></body></html>
"""
    return html.encode("utf-8")


MOPS_NOT_FOUND_PAGE = (
    "<html>\n<body>\n<center>\n<br><h4 align='center'><font color='red'>下載檔名或路徑不正確，請檢查!!</font></h4>\n"
    "<form action='/server-java/FileDownLoad'>\n<center><input type='button' value=' 回上頁 ' "
    "onClick={window.history.back()}></center>\n</form>\n</center>\n</body>\n</html>\n"
).encode("cp950")


def write_manifest(directory: Path, documents: list[dict[str, Any]], *, ticker: str = "1785") -> Path:
    path = directory / "manifest.json"
    path.write_text(json.dumps({"manifest_version": 1, "ticker": ticker, "documents": documents}, ensure_ascii=False), encoding="utf-8")
    return path
