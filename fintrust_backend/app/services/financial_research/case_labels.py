"""Known-outcome case labels — RETROSPECTIVE evaluation only.

Outcome labels are results, not features. They are reachable only through ``labels_for_retrospective_evaluation``,
which refuses every mode except ``RETROSPECTIVE_FORENSIC``. Feature, evidence-policy and snapshot modules must not
import this module (enforced by an AST test).
"""

from __future__ import annotations

from typing import Any

from app.services.financial_research.modes import AnalysisContext, AnalysisMode, ModeNotSupportedError

LABEL_PURPOSE = "retrospective_evaluation_only"

_CASE_LABELS: dict[str, list[dict[str, Any]]] = {
    "1785": [
        {"label_id": "1785_misstatement_admitted", "label": "financial_statement_misstatement_admitted",
         "outcome_known_at": "2016-05-14T00:00:00+08:00",
         "outcome_known_at_basis": "date-precision official quote of 2016-05-13; public from the next Taipei day",
         "legal_source": "official_disclosure:misstatement_admitted_20160513", "confidence": "official_quote",
         "purpose": LABEL_PURPOSE},
        {"label_id": "1785_restatement_disclosed", "label": "restatement_of_fy2011_fy2015_disclosed",
         "outcome_known_at": "2016-11-13T21:25:31+08:00",
         "outcome_known_at_basis": "MOPS 發言日期/發言時間 of the first restatement comparison notice",
         "legal_source": "official_disclosure:mops:20161113:212531:2", "confidence": "official_notice",
         "purpose": LABEL_PURPOSE},
        {"label_id": "1785_appellate_judgment", "label": "appellate_criminal_judgment_reported",
         "outcome_known_at": "2022-05-26", "outcome_known_at_basis": "judgment date; source not archived",
         "legal_source": "external_reference:court_tnhv_109_jinshang_5", "confidence": "unarchived_external_reference",
         "purpose": LABEL_PURPOSE},
    ],
}


def labels_for_retrospective_evaluation(ticker: str, context: AnalysisContext) -> list[dict[str, Any]]:
    if context.mode is not AnalysisMode.RETROSPECTIVE_FORENSIC:
        raise ModeNotSupportedError("labels_retrospective_only",
                                    "Case outcome labels are available only to RETROSPECTIVE_FORENSIC evaluation.")
    return [dict(label) for label in _CASE_LABELS.get(ticker, [])]
