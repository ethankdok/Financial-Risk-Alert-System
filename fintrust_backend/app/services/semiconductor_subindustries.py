from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ClassificationConfidence = Literal["reviewed", "high", "medium", "low", "unclassified"]


@dataclass(frozen=True)
class SubindustryClassification:
    subindustry: str
    source: str
    confidence: ClassificationConfidence


# Versioned, reviewable taxonomy for the TWSE semiconductor universe captured on
# 2026-09-19. It is deliberately separate from the official TWSE industry code:
# TWSE supplies industry 24, while these finer peer groups are project metadata.
SUBINDUSTRY_GROUPS: dict[str, set[str]] = {
    "晶圓代工": {"2303", "2330", "2342", "6770", "6789"},
    "記憶體製造": {"2337", "2344", "2408"},
    "封裝測試": {
        "2329", "2369", "2441", "2449", "3711", "6239", "6257",
        "6271", "6451", "6525", "6552", "8110", "8131", "8150",
    },
    "IC 設計": {
        "2363", "2379", "2388", "2401", "2436", "2454", "2458", "3006",
        "3014", "3034", "3035", "3041", "3094", "3150", "3257", "3443",
        "3530", "3545", "3588", "3592", "3661", "4919", "4952", "4961",
        "4968", "5222", "5236", "5269", "5471", "6202", "6243", "6415",
        "6526", "6531", "6533", "6695", "6719", "6756", "6799", "6962",
        "7749", "8016", "8081", "8162",
    },
    "分離元件與功率半導體": {
        "2302", "2340", "2351", "2434", "2481", "6573", "8261",
    },
    "半導體材料與零組件": {
        "2338", "3016", "3189", "3532", "3686", "5285", "6515", "8028",
    },
    "半導體設備": {"3413", "3583", "6909", "6937", "7730", "7769", "7822"},
    "記憶體模組與儲存": {"2451", "3135", "4967", "8271"},
    "光電與新型顯示半導體": {"3450", "6854", "6921", "7768"},
}


_TICKER_TO_SUBINDUSTRY = {
    ticker: subindustry
    for subindustry, tickers in SUBINDUSTRY_GROUPS.items()
    for ticker in tickers
}

REVIEWED_TICKERS = {"2303", "2330", "2454", "3711"}


def classify_semiconductor_company(ticker: str) -> SubindustryClassification:
    normalized = ticker.strip()
    subindustry = _TICKER_TO_SUBINDUSTRY.get(normalized)
    if subindustry is None:
        return SubindustryClassification(
            subindustry="待分類",
            source="unclassified",
            confidence="unclassified",
        )
    return SubindustryClassification(
        subindustry=subindustry,
        source="curated_twse_semiconductor_mapping_v1",
        confidence="reviewed" if normalized in REVIEWED_TICKERS else "medium",
    )


def classified_tickers() -> set[str]:
    return set(_TICKER_TO_SUBINDUSTRY)
