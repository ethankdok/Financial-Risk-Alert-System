from __future__ import annotations

from typing import Any


LLM_TEXT_EVIDENCE_LIMIT = 8
LLM_TEXT_CHAR_LIMIT = 420


def _sentence_score(item: dict[str, Any]) -> tuple[float, int, int]:
    relevance = float(item.get("relevance_score") or 0.0)
    semantic = item.get("semantic_relevance_score")
    semantic_score = float(semantic) if semantic is not None else 0.0
    topic_count = len(item.get("topics") or [])
    return (max(relevance, semantic_score), topic_count, len(str(item.get("cleaned_text") or item.get("original_text") or "")))


def select_llm_text_evidence(
    text_evidence: list[dict[str, Any]],
    *,
    narrative_shift: dict[str, Any] | None = None,
    limit: int = LLM_TEXT_EVIDENCE_LIMIT,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return a bounded, source-grounded evidence payload for LLM synthesis.

    The selector never invents evidence and does not transform model scores into
    labels. It only ranks already-extracted official sentences and preserves
    source IDs/URLs for auditability.
    """

    deduped: dict[str, dict[str, Any]] = {}
    for item in text_evidence:
        evidence_id = str(item.get("evidence_id") or item.get("sample_id") or "")
        if not evidence_id:
            continue
        deduped.setdefault(evidence_id, item)
    ranked = sorted(deduped.values(), key=_sentence_score, reverse=True)[:limit]
    selected: list[dict[str, Any]] = []
    for item in ranked:
        text = str(item.get("cleaned_text") or item.get("original_text") or "")
        selected.append(
            {
                "evidence_id": item.get("evidence_id"),
                "ticker": item.get("ticker"),
                "source_type": item.get("source_type"),
                "source_name": item.get("source_name"),
                "source_url": item.get("source_url"),
                "document_url": item.get("document_url"),
                "period": item.get("period"),
                "event_date": item.get("event_date"),
                "topics": item.get("topics") or [],
                "relevance_score": item.get("relevance_score"),
                "semantic_relevance_score": item.get("semantic_relevance_score"),
                "text": text[:LLM_TEXT_CHAR_LIMIT],
                "limitations": item.get("limitations") or [],
            }
        )
    evidence_ids = [str(item["evidence_id"]) for item in selected if item.get("evidence_id")]
    if narrative_shift:
        for sentence in narrative_shift.get("supporting_sentences", [])[:2]:
            evidence_id = str(sentence.get("evidence_id") or "")
            if evidence_id and evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
    return selected, evidence_ids
