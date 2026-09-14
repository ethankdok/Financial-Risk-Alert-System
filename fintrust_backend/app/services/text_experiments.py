from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REQUIRED_ANNOTATION_COLUMNS = {
    "sample_id",
    "ticker",
    "document_id",
    "period",
    "original_text",
    "relevant_label",
    "primary_topic",
    "annotator_id",
    "annotation_round",
}
VALID_RELEVANCE_LABELS = {"0", "1", ""}
CANONICAL_TOPICS = [
    "outlook",
    "capacity_capex",
    "demand_inventory",
    "revenue_orders",
    "rd_product",
    "cash_financing",
    "ma_investment",
    "operation_disruption",
    "legal_regulatory",
    "governance",
    "other",
]
FORMAL_METRICS_PENDING = "PENDING_HUMAN_GROUND_TRUTH"
WEAK_SUPERVISION_LABEL_SOURCE = "WEAK_LABEL_FROM_PHASE12_PROTOTYPE"
EXPERIMENT_METRIC_VERSION = "phase14-metrics-v1.0"

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "outlook": ("展望", "guidance", "outlook", "forecast", "預期", "預估", "能見度", "動能", "recover", "improve"),
    "capacity_capex": ("資本支出", "擴產", "產能", "建廠", "設備", "capex", "capacity", "equipment", "expansion"),
    "demand_inventory": ("庫存", "存貨", "需求", "去化", "拉貨", "inventory", "demand", "digestion", "channel"),
    "revenue_orders": ("營收", "訂單", "接單", "出貨", "revenue", "orders", "shipment", "sales", "backlog"),
    "rd_product": ("研發", "新產品", "產品組合", "technology", "platform", "roadmap", "product", "r&d"),
    "cash_financing": ("現金流", "自由現金流", "負債", "借款", "融資", "liquidity", "cash flow", "debt", "financing"),
    "ma_investment": ("併購", "投資", "取得", "處分", "股權", "acquisition", "investment", "disposal"),
    "operation_disruption": ("停工", "停產", "火災", "地震", "斷電", "缺料", "outage", "disruption", "shutdown"),
    "legal_regulatory": ("訴訟", "裁罰", "罰款", "違反", "法規", "監管", "litigation", "penalty", "regulatory"),
    "governance": ("董事", "總經理", "董事會", "內控", "審計", "governance", "board", "management", "control"),
}

BOILERPLATE_HINTS = (
    "safe harbor",
    "forward-looking statements",
    "thank you operator",
    "welcome to",
    "operator instructions",
    "copyright",
    "免責聲明",
    "版權所有",
)
TOKEN_RE = re.compile(r"\d+(?:\.\d+)?%?|[A-Za-z][A-Za-z0-9&'/-]*|[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True)
class ClassificationReport:
    precision: float
    recall: float
    f1: float
    macro_f1: float
    confusion_matrix: dict[str, dict[str, int]]


@dataclass(frozen=True)
class Phase14CorpusBuild:
    rows: list[dict[str, object]]
    manifest: dict[str, object]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def normalize_experiment_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def tokenize_experiment_text(text: str, *, include_ngrams: bool = False) -> list[str]:
    tokens = [match.group(0).casefold() for match in TOKEN_RE.finditer(str(text or ""))]
    filtered = [token for token in tokens if len(token) > 1]
    if include_ngrams:
        filtered.extend(f"{left}_{right}" for left, right in zip(filtered, filtered[1:]))
    return filtered


def is_likely_boilerplate(text: str) -> bool:
    normalized = normalize_experiment_text(text).casefold()
    if not normalized or len(normalized) <= 2:
        return True
    return any(hint in normalized for hint in BOILERPLATE_HINTS)


def keyword_hits_by_topic(text: str) -> dict[str, list[str]]:
    normalized = normalize_experiment_text(text).casefold()
    hits: dict[str, list[str]] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        topic_hits = sorted({keyword for keyword in keywords if keyword.casefold() in normalized})
        if topic_hits:
            hits[topic] = topic_hits
    return hits


def keyword_baseline_predict(text: str) -> dict[str, object]:
    hits = keyword_hits_by_topic(text)
    relevant = bool(hits) and not is_likely_boilerplate(text)
    topics = sorted(hits) if relevant else []
    return {
        "model": "keyword_rule_baseline",
        "model_version": "phase14-0.1",
        "predicted_relevant": int(relevant),
        "topics": topics or (["other"] if relevant else []),
        "keyword_hits": hits,
        "score_is_calibrated_probability": False,
    }


def safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def confusion_matrix(y_true: Iterable[str], y_pred: Iterable[str]) -> dict[str, dict[str, int]]:
    true_values = list(y_true)
    pred_values = list(y_pred)
    labels = sorted(set(true_values) | set(pred_values))
    matrix = {label: {inner: 0 for inner in labels} for label in labels}
    for truth, prediction in zip(true_values, pred_values):
        matrix[truth][prediction] += 1
    return matrix


def binary_classification_report(y_true: Iterable[int], y_pred: Iterable[int], *, positive_label: int = 1) -> ClassificationReport:
    true_values = [str(value) for value in y_true]
    pred_values = [str(value) for value in y_pred]
    matrix = confusion_matrix(true_values, pred_values)
    pos = str(positive_label)
    tp = matrix.get(pos, {}).get(pos, 0)
    fp = sum(row.get(pos, 0) for label, row in matrix.items() if label != pos)
    fn = sum(value for label, value in matrix.get(pos, {}).items() if label != pos)
    precision = safe_divide(tp, tp + fp)
    recall = safe_divide(tp, tp + fn)
    f1 = safe_divide(2 * precision * recall, precision + recall)
    macro_scores = []
    for label in matrix:
        label_tp = matrix[label].get(label, 0)
        label_fp = sum(row.get(label, 0) for other, row in matrix.items() if other != label)
        label_fn = sum(value for other, value in matrix[label].items() if other != label)
        p = safe_divide(label_tp, label_tp + label_fp)
        r = safe_divide(label_tp, label_tp + label_fn)
        macro_scores.append(safe_divide(2 * p * r, p + r))
    return ClassificationReport(
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
        macro_f1=round(sum(macro_scores) / len(macro_scores), 6) if macro_scores else 0.0,
        confusion_matrix=matrix,
    )


def multilabel_report(true_labels: list[set[str]], pred_labels: list[set[str]]) -> dict[str, object]:
    labels = sorted(set().union(*true_labels, *pred_labels)) if true_labels or pred_labels else []
    per_topic: dict[str, dict[str, float]] = {}
    micro_tp = micro_fp = micro_fn = 0
    f1_values = []
    for label in labels:
        tp = sum(1 for truth, pred in zip(true_labels, pred_labels) if label in truth and label in pred)
        fp = sum(1 for truth, pred in zip(true_labels, pred_labels) if label not in truth and label in pred)
        fn = sum(1 for truth, pred in zip(true_labels, pred_labels) if label in truth and label not in pred)
        micro_tp += tp
        micro_fp += fp
        micro_fn += fn
        precision = safe_divide(tp, tp + fp)
        recall = safe_divide(tp, tp + fn)
        f1 = safe_divide(2 * precision * recall, precision + recall)
        f1_values.append(f1)
        per_topic[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": sum(1 for truth in true_labels if label in truth),
        }
    micro_precision = safe_divide(micro_tp, micro_tp + micro_fp)
    micro_recall = safe_divide(micro_tp, micro_tp + micro_fn)
    micro_f1 = safe_divide(2 * micro_precision * micro_recall, micro_precision + micro_recall)
    return {
        "macro_f1": round(sum(f1_values) / len(f1_values), 6) if f1_values else 0.0,
        "micro_f1": round(micro_f1, 6),
        "per_topic": per_topic,
    }


def cohens_kappa(labels_a: Iterable[str], labels_b: Iterable[str]) -> float:
    left = list(labels_a)
    right = list(labels_b)
    if len(left) != len(right):
        raise ValueError("Cohen's Kappa requires paired label lists of equal length.")
    if not left:
        return 0.0
    observed = sum(1 for a, b in zip(left, right) if a == b) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum((left_counts[label] / len(left)) * (right_counts[label] / len(right)) for label in set(left) | set(right))
    return round(safe_divide(observed - expected, 1 - expected), 6)


def spearman_correlation(xs: Iterable[float], ys: Iterable[float]) -> float:
    x_values = list(xs)
    y_values = list(ys)
    if len(x_values) != len(y_values):
        raise ValueError("Spearman correlation requires equal-length inputs.")
    if len(x_values) < 2:
        return 0.0
    x_ranks = rank_values(x_values)
    y_ranks = rank_values(y_values)
    x_mean = sum(x_ranks) / len(x_ranks)
    y_mean = sum(y_ranks) / len(y_ranks)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_ranks, y_ranks))
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in x_ranks) * sum((y - y_mean) ** 2 for y in y_ranks))
    return round(safe_divide(numerator, denominator), 6)


def rank_values(values: list[float]) -> list[float]:
    sorted_pairs = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(sorted_pairs):
        end = index
        while end + 1 < len(sorted_pairs) and sorted_pairs[end + 1][0] == sorted_pairs[index][0]:
            end += 1
        rank = (index + end + 2) / 2
        for _, original_index in sorted_pairs[index : end + 1]:
            ranks[original_index] = rank
        index = end + 1
    return ranks


def load_annotation_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def dataset_hash(rows: list[dict[str, str]]) -> str:
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def object_hash(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_phase12_official_corpus(report: dict[str, Any], *, dataset_version: str = "phase14-official-corpus-v1") -> Phase14CorpusBuild:
    rows: list[dict[str, object]] = []
    for company in report.get("companies", []):
        ticker = str(company.get("ticker") or "")
        document_payloads = _phase12_full_text_document_payloads(company)
        if not document_payloads:
            text_intelligence = company.get("unified", {}).get("text_intelligence", {})
            document_payloads = list(text_intelligence.get("documents", []) or [])
        rows.extend(_corpus_rows_from_text_intelligence_documents(document_payloads, ticker=ticker))
    deduped = deduplicate_corpus_rows(rows)
    final_rows = deduped["rows"]
    manifest = corpus_manifest(final_rows, dataset_version=dataset_version)
    manifest["raw_sentence_count"] = len(rows)
    manifest["duplicate_sentence_count"] = deduped["duplicate_count"]
    manifest["duplicate_sample_ids"] = deduped["duplicate_sample_ids"][:50]
    return Phase14CorpusBuild(rows=final_rows, manifest=manifest)


def _phase12_full_text_document_payloads(company: dict[str, Any]) -> list[dict[str, Any]]:
    official_events = company.get("unified", {}).get("official_events_refresh", {})
    if not official_events:
        return []
    try:
        from app.services.text_embedding_provider import DisabledTextEmbeddingProvider
        from app.services.text_intelligence import FinancialTextIntelligenceService
        from app.text_intelligence_models import OfficialTextDocumentInput
    except Exception:  # pragma: no cover - optional application import boundary
        return []

    inputs: list[OfficialTextDocumentInput] = []
    for record in official_events.get("investor_conferences", []) or []:
        parts = [
            record.get("document_full_text"),
            *[
                extraction.get("full_text")
                for extraction in record.get("document_extractions", []) or []
                if isinstance(extraction, dict) and extraction.get("full_text")
            ],
            record.get("document_text_preview"),
            record.get("summary"),
            " ".join(record.get("source_evidence", []) or []),
            record.get("title"),
        ]
        text = "\n".join(str(part) for part in parts if part)
        if not text.strip():
            continue
        fiscal_year = record.get("fiscal_year")
        quarter = record.get("quarter")
        period = f"{fiscal_year}Q{quarter}" if fiscal_year and quarter else record.get("conference_date")
        inputs.append(
            OfficialTextDocumentInput(
                ticker=str(record.get("ticker") or company.get("ticker") or ""),
                company_name=record.get("company_name"),
                source_type="investor_conference",
                source_name=record.get("source_name") or "company_official_ir",
                source_url=record.get("source_url") or "",
                document_url=record.get("document_url"),
                document_id=record.get("event_id"),
                period=period,
                event_date=record.get("conference_date"),
                section="management_prepared_remarks",
                text=text,
                document_kind="transcript" if record.get("document_text_preview") else "unknown",
                extraction_status=record.get("document_extract_status") or record.get("status") or "unknown",
                limitations=record.get("limitations", []) or [],
            )
        )
    for record in official_events.get("material_events", []) or []:
        parts = [record.get("raw_text"), record.get("summary"), record.get("title")]
        text = "\n".join(str(part) for part in parts if part)
        if not text.strip():
            continue
        inputs.append(
            OfficialTextDocumentInput(
                ticker=str(record.get("ticker") or company.get("ticker") or ""),
                company_name=record.get("company_name"),
                source_type="material_event",
                source_name=record.get("source_name") or "mops",
                source_url=record.get("source_url") or "",
                document_url=record.get("detail_url"),
                document_id=record.get("event_id"),
                period=record.get("event_date"),
                event_date=record.get("event_date"),
                section="material_event_description",
                text=text,
                document_kind="html",
                extraction_status=record.get("status") or "unknown",
                limitations=record.get("limitations", []) or [],
            )
        )
    if not inputs:
        return []
    service = FinancialTextIntelligenceService(embedding_provider=DisabledTextEmbeddingProvider())
    analysis = service.analyze_documents(inputs, include_irrelevant_sentences=True)
    return [document.model_dump(mode="json") for document in analysis.documents]


def _corpus_rows_from_text_intelligence_documents(document_payloads: list[dict[str, Any]], *, ticker: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for document in document_payloads:
        for sentence in document.get("sentences", []) or []:
            original_text = str(sentence.get("original_text") or "")
            cleaned_text = str(sentence.get("cleaned_text") or normalize_experiment_text(original_text))
            if not original_text.strip() and not cleaned_text.strip():
                continue
            sample_id = str(sentence.get("evidence_id") or stable_text_hash(f"{document.get('document_id')}|{cleaned_text}"))
            topics = [topic for topic in sentence.get("topics", []) or [] if topic in CANONICAL_TOPICS]
            rows.append(
                {
                    "sample_id": sample_id,
                    "ticker": str(sentence.get("ticker") or ticker),
                    "company_name": sentence.get("company_name") or document.get("company_name"),
                    "source_type": sentence.get("source_type") or document.get("source_type"),
                    "source_name": sentence.get("source_name") or document.get("source_name"),
                    "source_url": sentence.get("source_url") or document.get("source_url"),
                    "document_url": sentence.get("document_url") or document.get("document_url"),
                    "document_id": str(sentence.get("document_id") or document.get("document_id") or ""),
                    "document_hash": sentence.get("document_hash"),
                    "period": sentence.get("period") or document.get("period"),
                    "event_date": sentence.get("event_date") or document.get("event_date"),
                    "retrieved_at": sentence.get("retrieved_at"),
                    "parser_version": sentence.get("parser_version"),
                    "section": sentence.get("section"),
                    "sentence_id": sentence.get("sentence_id"),
                    "original_text": original_text,
                    "cleaned_text": cleaned_text,
                    "text_hash": sentence.get("text_hash") or stable_text_hash(cleaned_text),
                    "weak_relevant_label": int(bool(sentence.get("relevant"))),
                    "weak_topics": sorted(set(topics)),
                    "weak_relevance_score": float(sentence.get("relevance_score") or 0.0),
                    "weak_relevance_model_name": sentence.get("relevance_model_name"),
                    "weak_relevance_model_version": sentence.get("relevance_model_version"),
                    "semantic_relevance_score": sentence.get("semantic_relevance_score"),
                    "semantic_provider": sentence.get("semantic_provider"),
                    "label_source": WEAK_SUPERVISION_LABEL_SOURCE,
                }
            )
    return rows


def deduplicate_corpus_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    kept: list[dict[str, object]] = []
    duplicate_ids: list[str] = []
    for row in rows:
        key = str(row.get("text_hash") or stable_text_hash(str(row.get("cleaned_text") or row.get("original_text") or "")))
        doc_key = f"{row.get('document_id') or ''}|{key}"
        if doc_key in seen:
            duplicate_ids.append(str(row.get("sample_id") or key))
            continue
        seen.add(doc_key)
        kept.append(row)
    return {
        "rows": kept,
        "duplicate_count": len(duplicate_ids),
        "duplicate_sample_ids": duplicate_ids,
    }


def corpus_manifest(rows: list[dict[str, object]], *, dataset_version: str) -> dict[str, object]:
    companies = sorted({str(row.get("ticker")) for row in rows if row.get("ticker")})
    documents = sorted({str(row.get("document_id")) for row in rows if row.get("document_id")})
    periods = sorted({str(row.get("period")) for row in rows if row.get("period")})
    source_type_counts = Counter(str(row.get("source_type") or "unknown") for row in rows)
    parser_versions = sorted({str(row.get("parser_version")) for row in rows if row.get("parser_version")})
    retrieved_dates = sorted({str(row.get("retrieved_at"))[:10] for row in rows if row.get("retrieved_at")})
    by_company = Counter(str(row.get("ticker") or "unknown") for row in rows)
    by_document = Counter(str(row.get("document_id") or "unknown") for row in rows)
    by_topic = Counter(topic for row in rows for topic in row.get("weak_topics", []) or [])
    return {
        "schema_version": "phase14-dataset-manifest-v1.0",
        "dataset_version": dataset_version,
        "dataset_hash": object_hash(rows),
        "generated_at": utc_now_iso(),
        "human_ground_truth_status": FORMAL_METRICS_PENDING,
        "label_source": WEAK_SUPERVISION_LABEL_SOURCE,
        "companies": companies,
        "document_count": len(documents),
        "documents": documents,
        "periods": periods,
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "sentence_count": len(rows),
        "weak_relevant_count": sum(1 for row in rows if row.get("weak_relevant_label") == 1),
        "weak_irrelevant_count": sum(1 for row in rows if row.get("weak_relevant_label") == 0),
        "company_sentence_counts": dict(sorted(by_company.items())),
        "document_sentence_counts": dict(sorted(by_document.items())),
        "weak_topic_counts": dict(sorted(by_topic.items())),
        "retrieval_dates": retrieved_dates,
        "parser_versions": parser_versions,
        "strux_status": "STRUX_EXTERNAL_BENCHMARK_PENDING",
    }


def stratified_annotation_sample(rows: list[dict[str, object]], *, target_size: int = 500, seed: int = 42) -> list[dict[str, object]]:
    deduped = deduplicate_corpus_rows(rows)["rows"]
    strata: dict[tuple[str, str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in deduped:
        topics = row.get("weak_topics", []) or ["none"]
        key = (
            str(row.get("ticker") or "unknown"),
            str(row.get("source_type") or "unknown"),
            str(row.get("period") or "unknown"),
            str(row.get("weak_relevant_label")),
            str(topics[0]),
        )
        strata[key].append(row)
    rng = random.Random(seed)
    for bucket in strata.values():
        rng.shuffle(bucket)
    sample: list[dict[str, object]] = []
    while len(sample) < target_size:
        progressed = False
        for key in sorted(strata):
            bucket = strata[key]
            if bucket and len(sample) < target_size:
                sample.append(bucket.pop())
                progressed = True
        if not progressed:
            break
    sample.sort(key=lambda row: str(row.get("sample_id")))
    return sample


def to_annotation_package_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    package_rows: list[dict[str, object]] = []
    for row in rows:
        keyword_prediction = keyword_baseline_predict(str(row.get("cleaned_text") or row.get("original_text") or ""))
        package_rows.append(
            {
                "sample_id": row.get("sample_id"),
                "ticker": row.get("ticker"),
                "company_name": row.get("company_name"),
                "source_type": row.get("source_type"),
                "source_name": row.get("source_name"),
                "source_url": row.get("source_url"),
                "document_url": row.get("document_url"),
                "document_id": row.get("document_id"),
                "period": row.get("period"),
                "event_date": row.get("event_date"),
                "section": row.get("section"),
                "sentence_id": row.get("sentence_id"),
                "original_text": row.get("original_text"),
                "cleaned_text": row.get("cleaned_text"),
                "relevant_label": "",
                "primary_topic": "",
                "secondary_topics": "",
                "forward_looking": "",
                "risk_relevant": "",
                "annotator_id": "",
                "annotation_round": "",
                "annotation_notes": "",
                "model_suggestion_only_relevant": row.get("weak_relevant_label"),
                "model_suggestion_only_topics": ",".join(row.get("weak_topics", []) or []),
                "model_suggestion_only_score": row.get("weak_relevance_score"),
                "keyword_rule_suggestion_only_relevant": keyword_prediction["predicted_relevant"],
                "keyword_rule_suggestion_only_topics": ",".join(keyword_prediction["topics"]),
                "suggestion_warning": "SUGGESTION ONLY - human confirmation required",
            }
        )
    return package_rows


def validate_annotation_rows(rows: list[dict[str, str]]) -> dict[str, object]:
    columns = set(rows[0]) if rows else set()
    missing_columns = sorted(REQUIRED_ANNOTATION_COLUMNS - columns)
    seen: set[tuple[str, str, str]] = set()
    duplicate_keys: list[str] = []
    invalid_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        key = (
            row.get("sample_id", ""),
            row.get("annotator_id", ""),
            row.get("annotation_round", ""),
        )
        if key in seen:
            duplicate_keys.append("|".join(key))
        seen.add(key)
        label = row.get("relevant_label", "")
        if label not in VALID_RELEVANCE_LABELS:
            invalid_rows.append({"row": index, "field": "relevant_label", "value": label})
        if row.get("primary_topic") and label != "1":
            invalid_rows.append({"row": index, "field": "primary_topic", "value": row.get("primary_topic"), "reason": "topic requires relevant_label=1"})
    return {
        "row_count": len(rows),
        "missing_columns": missing_columns,
        "duplicate_annotation_keys": duplicate_keys,
        "invalid_rows": invalid_rows,
        "dataset_hash": dataset_hash(rows),
        "valid": not missing_columns and not duplicate_keys and not invalid_rows,
    }


def to_train_ready_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    ready: list[dict[str, object]] = []
    for row in rows:
        label = row.get("relevant_label", "")
        text = row.get("original_text", "").strip()
        if label not in {"0", "1"} or not text:
            continue
        topics = [
            value.strip()
            for value in ",".join([row.get("primary_topic", ""), row.get("secondary_topics", "")]).split(",")
            if value.strip()
        ]
        ready.append(
            {
                "sample_id": row.get("sample_id"),
                "text": text,
                "relevant_label": int(label),
                "topics": sorted(set(topics)),
                "group_key": row.get("document_id") or "|".join([row.get("ticker", ""), row.get("period", "")]),
            }
        )
    return ready


def group_aware_split(
    rows: list[dict[str, object]],
    *,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("group_key") or row.get("document_id") or row.get("sample_id")), []).append(row)
    group_keys = sorted(groups)
    rng = random.Random(seed)
    rng.shuffle(group_keys)
    test_group_count = max(1, round(len(group_keys) * test_ratio)) if group_keys else 0
    test_groups = set(group_keys[:test_group_count])
    train = [row for key in group_keys if key not in test_groups for row in groups[key]]
    test = [row for key in group_keys if key in test_groups for row in groups[key]]
    return {
        "seed": seed,
        "test_ratio": test_ratio,
        "train": train,
        "test": test,
        "train_groups": sorted(set(group_keys) - test_groups),
        "test_groups": sorted(test_groups),
        "document_leakage_prevented": not (set(group_keys) - test_groups) & test_groups,
    }


def balanced_group_aware_split(
    rows: list[dict[str, object]],
    *,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("group_key") or row.get("document_id") or row.get("sample_id")), []).append(row)
    if not groups:
        return group_aware_split(rows, test_ratio=test_ratio, seed=seed)
    target_rows = max(1, round(len(rows) * test_ratio))
    rng = random.Random(seed)
    group_items = list(groups.items())
    rng.shuffle(group_items)
    group_items.sort(key=lambda item: abs(len(item[1]) - target_rows))
    test_groups: set[str] = set()
    test_count = 0
    for key, items in group_items:
        if not test_groups:
            test_groups.add(key)
            test_count += len(items)
            continue
        current_distance = abs(test_count - target_rows)
        next_distance = abs(test_count + len(items) - target_rows)
        if next_distance <= current_distance or test_count < target_rows * 0.5:
            test_groups.add(key)
            test_count += len(items)
    group_keys = sorted(groups)
    train = [row for key in group_keys if key not in test_groups for row in groups[key]]
    test = [row for key in group_keys if key in test_groups for row in groups[key]]
    return {
        "seed": seed,
        "test_ratio": test_ratio,
        "train": train,
        "test": test,
        "train_groups": sorted(set(group_keys) - test_groups),
        "test_groups": sorted(test_groups),
        "document_leakage_prevented": not (set(group_keys) - test_groups) & test_groups,
    }


def corpus_rows_to_train_ready(rows: list[dict[str, object]], *, label_field: str = "weak_relevant_label") -> list[dict[str, object]]:
    ready: list[dict[str, object]] = []
    for row in rows:
        label = row.get(label_field)
        if label not in {0, 1, "0", "1"}:
            continue
        text = str(row.get("cleaned_text") or row.get("original_text") or "").strip()
        if not text:
            continue
        ready.append(
            {
                "sample_id": row.get("sample_id"),
                "text": text,
                "relevant_label": int(label),
                "topics": sorted(set(row.get("weak_topics", []) or [])),
                "group_key": row.get("document_id") or "|".join([str(row.get("ticker") or ""), str(row.get("period") or "")]),
                "ticker": row.get("ticker"),
                "period": row.get("period"),
                "source_type": row.get("source_type"),
                "document_id": row.get("document_id"),
            }
        )
    return ready


def _can_train_supervised_model(rows: list[dict[str, object]]) -> bool:
    labels = {int(row["relevant_label"]) for row in rows if row.get("relevant_label") in {0, 1}}
    return len(rows) >= 4 and labels == {0, 1}


def evaluate_relevance_model_family(
    train_rows: list[dict[str, object]],
    test_rows: list[dict[str, object]],
    *,
    label_status: str = FORMAL_METRICS_PENDING,
) -> list[dict[str, object]]:
    if not test_rows:
        return []
    y_true = [int(row["relevant_label"]) for row in test_rows]
    results: list[dict[str, object]] = []

    keyword_predictions = [
        int(keyword_baseline_predict(str(row.get("text") or ""))["predicted_relevant"])
        for row in test_rows
    ]
    keyword_report = binary_classification_report(y_true, keyword_predictions)
    results.append(_classification_result_row("keyword_rule_baseline", "phase14-0.1", keyword_report, label_status, {}))

    if not _can_train_supervised_model(train_rows):
        results.append(
            {
                "model": "tfidf_multinomial_nb",
                "model_version": "0.1.0",
                "status": "SKIPPED_INSUFFICIENT_CLASS_DIVERSITY",
                "label_status": label_status,
            }
        )
        results.append(
            {
                "model": "tfidf_logistic_regression",
                "model_version": "0.1.0",
                "status": "SKIPPED_INSUFFICIENT_CLASS_DIVERSITY",
                "label_status": label_status,
            }
        )
        results.append(
            {
                "model": "tfidf_linear_svm",
                "model_version": "0.1.0",
                "status": "SKIPPED_INSUFFICIENT_CLASS_DIVERSITY",
                "label_status": label_status,
            }
        )
        return results

    try:
        from app.services.text_intelligence import TfidfNaiveBayesClassifier

        nb = TfidfNaiveBayesClassifier()
        nb.fit((str(row["text"]), "relevant" if int(row["relevant_label"]) else "irrelevant") for row in train_rows)
        nb_predictions = [
            1 if nb.predict_proba(str(row["text"])).get("relevant", 0.0) >= 0.5 else 0
            for row in test_rows
        ]
        nb_report = binary_classification_report(y_true, nb_predictions)
        results.append(_classification_result_row("tfidf_multinomial_nb", "0.1.0", nb_report, label_status, {"alpha": 1.0}))
    except Exception as exc:
        results.append(_skipped_model_row("tfidf_multinomial_nb", "0.1.0", label_status, exc))

    for model_kind, model_name in (("logistic_regression", "tfidf_logistic_regression"), ("linear_svm", "tfidf_linear_svm")):
        try:
            classifier = SklearnTextClassifier(model_kind=model_kind)
            classifier.fit((str(row["text"]), int(row["relevant_label"])) for row in train_rows)
            predictions = classifier.predict([str(row["text"]) for row in test_rows])
            report = binary_classification_report(y_true, predictions)
            results.append(
                _classification_result_row(
                    model_name,
                    "0.1.0",
                    report,
                    label_status,
                    {"ngram_range": [1, 2], "model_kind": model_kind},
                )
            )
        except Exception as exc:
            results.append(_skipped_model_row(model_name, "0.1.0", label_status, exc))
    return results


def _classification_result_row(
    model: str,
    version: str,
    report: ClassificationReport,
    label_status: str,
    hyperparameters: dict[str, object],
) -> dict[str, object]:
    support = sum(sum(row.values()) for row in report.confusion_matrix.values())
    correct = sum(report.confusion_matrix[label].get(label, 0) for label in report.confusion_matrix)
    return {
        "model": model,
        "model_version": version,
        "status": "PRELIMINARY_WEAK_SUPERVISION" if label_status != "HUMAN_GT" else "FORMAL_HUMAN_GT",
        "label_status": label_status,
        "metric_version": EXPERIMENT_METRIC_VERSION,
        "precision": report.precision,
        "recall": report.recall,
        "f1": report.f1,
        "macro_f1": report.macro_f1,
        "accuracy": round(safe_divide(correct, support), 6),
        "support": support,
        "confusion_matrix": report.confusion_matrix,
        "hyperparameters": hyperparameters,
    }


def _skipped_model_row(model: str, version: str, label_status: str, exc: Exception) -> dict[str, object]:
    return {
        "model": model,
        "model_version": version,
        "status": "SKIPPED_RUNTIME_UNAVAILABLE",
        "label_status": label_status,
        "error": f"{type(exc).__name__}: {exc}",
    }


def evaluate_topic_keyword_baseline(rows: list[dict[str, object]], *, label_status: str = FORMAL_METRICS_PENDING) -> dict[str, object]:
    true_labels = [set(row.get("topics", []) or []) for row in rows]
    predictions = [set(keyword_baseline_predict(str(row.get("text") or ""))["topics"]) for row in rows]
    report = multilabel_report(true_labels, predictions)
    return {
        "model": "keyword_topic_rule_baseline",
        "model_version": "phase14-0.1",
        "status": "PRELIMINARY_WEAK_SUPERVISION" if label_status != "HUMAN_GT" else "FORMAL_HUMAN_GT",
        "label_status": label_status,
        "metric_version": EXPERIMENT_METRIC_VERSION,
        **report,
    }


def document_level_texts(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_document: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_document[str(row.get("document_id") or row.get("sample_id"))].append(row)
    documents: list[dict[str, object]] = []
    for document_id, sentence_rows in by_document.items():
        ordered = sorted(sentence_rows, key=lambda row: str(row.get("sentence_id") or ""))
        topics = Counter(topic for row in ordered for topic in row.get("weak_topics", []) or [])
        total_topics = sum(topics.values()) or 1
        documents.append(
            {
                "document_id": document_id,
                "ticker": ordered[0].get("ticker"),
                "period": ordered[0].get("period"),
                "source_type": ordered[0].get("source_type"),
                "raw_text": " ".join(str(row.get("original_text") or "") for row in ordered),
                "cleaned_text": " ".join(str(row.get("cleaned_text") or row.get("original_text") or "") for row in ordered),
                "relevant_text": " ".join(str(row.get("cleaned_text") or "") for row in ordered if row.get("weak_relevant_label") == 1),
                "topic_distribution": {topic: count / total_topics for topic, count in topics.items()},
                "sentence_count": len(ordered),
            }
        )
    return sorted(documents, key=lambda item: (str(item.get("ticker")), str(item.get("period")), str(item.get("document_id"))))


def calculate_drift_metric_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    try:
        from app.services.text_intelligence import calculate_jsd_from_distributions, calculate_text_cosine, calculate_word_jsd, clean_text
    except Exception:  # pragma: no cover - app import boundary
        return []

    documents = document_level_texts(rows)
    by_ticker: dict[str, list[dict[str, object]]] = defaultdict(list)
    for document in documents:
        by_ticker[str(document.get("ticker") or "unknown")].append(document)
    drift_rows: list[dict[str, object]] = []
    for ticker, ticker_docs in sorted(by_ticker.items()):
        ordered_docs = sorted(ticker_docs, key=lambda item: (str(item.get("period")), str(item.get("document_id"))))
        for first, second in zip(ordered_docs, ordered_docs[1:]):
            raw_jsd = calculate_word_jsd(str(first["raw_text"]), str(second["raw_text"]))
            cleaned_jsd = calculate_word_jsd(clean_text(str(first["raw_text"])), clean_text(str(second["raw_text"])))
            relevant_jsd = calculate_word_jsd(str(first["relevant_text"]), str(second["relevant_text"]))
            topic_jsd = calculate_jsd_from_distributions(
                dict(first.get("topic_distribution") or {}),
                dict(second.get("topic_distribution") or {}),
            )
            cosine = calculate_text_cosine(
                str(first["relevant_text"] or first["cleaned_text"]),
                str(second["relevant_text"] or second["cleaned_text"]),
            )
            drift_rows.append(
                {
                    "ticker": ticker,
                    "document_id_1": first["document_id"],
                    "document_id_2": second["document_id"],
                    "period_1": first.get("period"),
                    "period_2": second.get("period"),
                    "raw_text_word_jsd": round(raw_jsd, 6),
                    "cleaned_text_word_jsd": round(cleaned_jsd, 6),
                    "relevant_text_word_jsd": round(relevant_jsd, 6),
                    "topic_distribution_jsd": round(topic_jsd, 6),
                    "semantic_tfidf_cosine_similarity": round(cosine, 6),
                    "semantic_embedding_cosine_similarity": "PENDING_EMBEDDING_PROVIDER",
                    "human_drift_label_status": FORMAL_METRICS_PENDING,
                }
            )
    return drift_rows


def ablation_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    documents = document_level_texts(rows)
    stages = [
        ("A0_raw_text", "raw_text"),
        ("A1_boilerplate_removed", "cleaned_text"),
        ("A2_cleaned_text", "cleaned_text"),
        ("A3_relevance_filtered_text", "relevant_text"),
        ("A4_relevance_with_section_context", "relevant_text"),
        ("A5_relevance_with_topic_representation", "relevant_text"),
    ]
    results: list[dict[str, object]] = []
    for stage_name, text_field in stages:
        token_counts = [len(tokenize_experiment_text(str(document.get(text_field) or ""), include_ngrams=True)) for document in documents]
        results.append(
            {
                "stage": stage_name,
                "status": "PRELIMINARY_FEATURE_ACCOUNTING",
                "document_count": len(documents),
                "total_tokens": sum(token_counts),
                "mean_tokens_per_document": round(safe_divide(sum(token_counts), len(token_counts)), 6),
                "formal_performance_status": FORMAL_METRICS_PENDING,
            }
        )
    return results


def error_analysis_from_predictions(rows: list[dict[str, object]], predictions: list[int], *, limit_per_type: int = 5) -> dict[str, object]:
    buckets: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row, prediction in zip(rows, predictions):
        truth = int(row.get("relevant_label", 0))
        text = str(row.get("text") or "")
        if truth == prediction:
            continue
        if prediction == 1:
            bucket = "weak_false_positive"
        else:
            bucket = "weak_false_negative"
        if len(text) < 30:
            bucket += "_short_fragment"
        elif re.search(r"\d+(?:\.\d+)?%?", text):
            bucket += "_numeric_sentence"
        elif not keyword_hits_by_topic(text):
            bucket += "_keyword_free"
        buckets[bucket].append(
            {
                "sample_id": row.get("sample_id"),
                "ticker": row.get("ticker"),
                "document_id": row.get("document_id"),
                "period": row.get("period"),
                "text": text[:500],
                "weak_label": truth,
                "prediction": prediction,
            }
        )
    return {
        "status": "PRELIMINARY_WEAK_SUPERVISION",
        "human_ground_truth_status": FORMAL_METRICS_PENDING,
        "categories": {name: items[:limit_per_type] for name, items in sorted(buckets.items())},
    }


def model_selection_rows(relevance_results: list[dict[str, object]], topic_result: dict[str, object]) -> list[dict[str, object]]:
    topic_macro_f1 = topic_result.get("macro_f1", FORMAL_METRICS_PENDING)
    rows: list[dict[str, object]] = []
    for result in relevance_results:
        rows.append(
            {
                "Model": result.get("model"),
                "Relevance F1": result.get("f1", FORMAL_METRICS_PENDING),
                "Topic Macro-F1": topic_macro_f1 if result.get("model") == "keyword_rule_baseline" else FORMAL_METRICS_PENDING,
                "Latency": "LOW_LOCAL",
                "Artifact Size": "NONE_OR_SMALL" if str(result.get("model", "")).startswith("keyword") else "SMALL_TFIDF_ARTIFACT",
                "External API Required": "NO",
                "Production Complexity": "LOW" if str(result.get("model", "")).startswith("keyword") else "MEDIUM_AFTER_VALIDATION",
                "Notes": result.get("status"),
            }
        )
    rows.append(
        {
            "Model": "multilingual_embedding_or_transformer_candidate",
            "Relevance F1": FORMAL_METRICS_PENDING,
            "Topic Macro-F1": FORMAL_METRICS_PENDING,
            "Latency": "UNKNOWN",
            "Artifact Size": "NOT_TRAINED",
            "External API Required": "CONFIG_DEPENDENT",
            "Production Complexity": "PENDING_EVALUATION",
            "Notes": "Ready for evaluation after human labels and embedding/provider decision.",
        }
    )
    return rows


def experiment_manifest(
    *,
    experiment_id: str,
    git_commit: str,
    dataset_manifest: dict[str, object],
    split_manifest: dict[str, object],
    random_seed: int,
) -> dict[str, object]:
    return {
        "schema_version": "phase14-experiment-manifest-v1.0",
        "experiment_id": experiment_id,
        "timestamp": utc_now_iso(),
        "git_commit": git_commit,
        "dataset_version": dataset_manifest.get("dataset_version"),
        "dataset_hash": dataset_manifest.get("dataset_hash"),
        "annotation_version": "PENDING_HUMAN_ANNOTATION",
        "split_manifest": split_manifest,
        "random_seed": random_seed,
        "metric_version": EXPERIMENT_METRIC_VERSION,
        "formal_metrics_status": FORMAL_METRICS_PENDING,
        "external_api_calls": [],
    }


class SklearnTextClassifier:
    """Optional training-only baseline; production does not import sklearn unless used."""

    model_name = "tfidf_logistic_regression"
    model_version = "0.1.0"

    def __init__(self, *, model_kind: str = "logistic_regression") -> None:
        self.model_kind = model_kind
        self.pipeline = None

    def fit(self, rows: Iterable[tuple[str, int]]) -> None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.svm import LinearSVC
        except Exception as exc:  # pragma: no cover - optional dependency boundary
            raise RuntimeError("scikit-learn is an optional training dependency; install requirements-ml-training.txt.") from exc

        items = list(rows)
        texts = [text for text, _label in items]
        labels = [label for _text, label in items]
        estimator = LinearSVC() if self.model_kind == "linear_svm" else LogisticRegression(max_iter=1000)
        self.pipeline = Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2))), ("model", estimator)])
        self.pipeline.fit(texts, labels)

    def predict(self, texts: list[str]) -> list[int]:
        if self.pipeline is None:
            raise RuntimeError("Model has not been fitted.")
        return [int(value) for value in self.pipeline.predict(texts)]


def rank_active_learning_candidates(
    rows: list[dict[str, object]],
    probabilities: list[dict[str, float]],
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    ranked = []
    for row, proba in zip(rows, probabilities):
        positive = float(proba.get("1", proba.get("relevant", 0.0)))
        confidence = max(positive, 1 - positive)
        ranked.append(
            {
                "sample_id": row.get("sample_id"),
                "text": row.get("text") or row.get("original_text"),
                "predicted_label": 1 if positive >= 0.5 else 0,
                "confidence": round(confidence, 6),
                "uncertainty": round(1 - confidence, 6),
                "source": row.get("source_url") or row.get("source_name"),
                "period": row.get("period"),
            }
        )
    return sorted(ranked, key=lambda item: float(item["uncertainty"]), reverse=True)[:limit]


def summarize_annotation_quality(rows: list[dict[str, str]]) -> dict[str, object]:
    by_sample: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_sample.setdefault(row.get("sample_id", ""), []).append(row)
    paired = [items for items in by_sample.values() if len(items) >= 2]
    if not paired:
        validation = validate_annotation_rows(rows)
        return {
            "sample_count": len(by_sample),
            "paired_sample_count": 0,
            "cohens_kappa_relevance": None,
            "validation": validation,
            "note": "At least two annotations per sample are required for Cohen's Kappa.",
        }
    first = [items[0].get("relevant_label", "") for items in paired]
    second = [items[1].get("relevant_label", "") for items in paired]
    return {
        "sample_count": len(by_sample),
        "paired_sample_count": len(paired),
        "cohens_kappa_relevance": cohens_kappa(first, second),
        "validation": validate_annotation_rows(rows),
    }
