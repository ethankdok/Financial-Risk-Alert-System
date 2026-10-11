"""Research knowledge for reviewed historical cases: key events and accounting-mechanism hypotheses.

Event identities refer to the archived official timeline by ``event_key`` (times and hashes are resolved from the
archive at request time, never restated here). Each statement carries its source class; the legal-source
classification of the 1785 mechanisms (court finding vs party allegation) is **not yet verified paragraph by
paragraph**, so they are research hypotheses until the method owner (Yu-Jing) signs off.

Outcome labels are deliberately *not* in this module: see ``case_labels`` (retrospective evaluation only).
"""

from __future__ import annotations

from typing import Any

SOURCE_CLASSES = ("official_disclosure", "regulator_announcement", "court_finding", "litigation_allegation",
                  "research_hypothesis")

CASE_KNOWLEDGE: dict[str, dict[str, Any]] = {
    "1785": {
        "case_id": "1785-solar-applied-materials",
        "research_question_ids": ["RQ-A", "RQ-B", "RQ-C"],
        "key_events": [
            {"event_key": "mops:20160513:184919:8", "role": "main_public_revelation_press_conference",
             "source_class": "official_disclosure",
             "note": "Listed MOPS notice of the 2016-05-13 material-information press conference (listing-only bytes)."},
            {"event_key": "misstatement_admitted_20160513", "role": "misstatement_admission",
             "source_class": "official_disclosure",
             "note": "Official quote 「致有財務報表不實表達之情事」; date precision only (public from the next Taipei day)."},
            {"event_key": "tpex:證櫃監字第10502004811號", "role": "trading_suspension",
             "source_class": "regulator_announcement", "note": "TPEx suspension from 2016-05-17."},
            {"event_key": "mops:20160819:171005:1", "role": "restatement_required", "source_class": "official_disclosure",
             "note": "Notice that FY2011–FY2015 affected quarters will be corrected and restated."},
            {"event_key": "mops:20161113:212531:2", "role": "restatement_disclosure_individual",
             "source_class": "official_disclosure", "note": "Pre/post restatement comparison, individual statements."},
            {"event_key": "mops:20161113:212622:3", "role": "restatement_disclosure_consolidated",
             "source_class": "official_disclosure", "note": "Pre/post restatement comparison, consolidated statements."},
        ],
        "hypotheses": [
            {"hypothesis_id": "H1_precious_metal_inventory_valuation",
             "statement": "貴金屬存貨跌價損失提列不足與價值衡量問題",
             "related_metrics": ["cost_of_goods_sold", "gross_profit", "operating_income", "net_income", "equity"],
             "expected_restatement_direction": {"cost_of_goods_sold": "increase", "gross_profit": "decrease",
                                                "net_income": "decrease", "equity": "decrease"}},
            {"hypothesis_id": "H2_deferred_losses_temporary_payments",
             "statement": "不當成本遞延：透過「暫付款」／營業成本沖抵等記載使損失期間延後",
             "related_metrics": ["cost_of_goods_sold", "gross_profit", "current_assets", "net_income"],
             "expected_restatement_direction": {"cost_of_goods_sold": "increase", "current_assets": "decrease"}},
            {"hypothesis_id": "H3_consigned_metal_quantity_classification",
             "statement": "客戶寄存貴金屬與自有存貨的數量辨識風險",
             "related_metrics": ["current_assets", "current_liabilities", "total_liabilities"],
             "expected_restatement_direction": {}},
            {"hypothesis_id": "H4_inappropriate_price_source",
             "statement": "不適當價格來源造成存貨與成本相關損益錯置",
             "related_metrics": ["cost_of_goods_sold", "gross_profit"],
             "expected_restatement_direction": {"cost_of_goods_sold": "increase", "gross_profit": "decrease"}},
        ],
        "hypothesis_source": {
            "source_class": "research_hypothesis",
            "basis": ("Summarized in architecture v2 §2.1 from regulatory documents and the cited appellate judgment. "
                      "Paragraph-level classification (court finding vs litigation allegation vs company disclosure) "
                      "has not been verified in this repository."),
            "legal_status": "classification_unverified",
            "method_owner_approval": "DRAFT_PENDING_METHOD_OWNER_REVIEW",
        },
        "external_references": [
            {"reference_id": "court_tnhv_109_jinshang_5", "source_class": "court_finding",
             "title": "臺灣高等法院臺南分院 109 年度金上字第 5 號判決（2022-05-26）",
             "url": None, "url_status": "third_party_mirror_not_exposed",
             "archived": False, "note": "Not archived; findings vs allegations must be cited by paragraph before use."},
            {"reference_id": "tpex_10502015021", "source_class": "regulator_announcement",
             "title": "TPEx 2016-12 trading-resumption announcement",
             "url": "https://www.tpex.org.tw/storage/eb_data/10512/10502015021.htm", "url_status": "official",
             "archived": True, "note": "Archived raw bytes; see the source timeline."},
        ],
        "accounting_regimes": [
            {"framework": "TW_GAAP", "fiscal_years": [2011, 2012]},
            {"framework": "TIFRS", "fiscal_years": list(range(2013, 2026))},
        ],
        "strict_feasibility_note": (
            "Before the 2016-05-13 revelation no early canonical financial observation of 1785 has verified "
            "point-in-time availability; early-warning predictive performance cannot be demonstrated from these data."),
    },
}


def accounting_regime(ticker: str, fiscal_year: int) -> str | None:
    for regime in CASE_KNOWLEDGE.get(ticker, {}).get("accounting_regimes", []):
        if fiscal_year in regime["fiscal_years"]:
            return regime["framework"]
    return None


def knowledge(ticker: str) -> dict[str, Any] | None:
    return CASE_KNOWLEDGE.get(ticker)
