from __future__ import annotations

import csv
import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from io import StringIO
from typing import Iterable

from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.text_intelligence_models import (
    AnnotationCandidateExportRow,
    CanonicalTopic,
    NarrativeShiftResponse,
    OfficialTextDocumentInput,
    TermChange,
    TextEvidenceSentence,
    TextMiningAnalysisResponse,
    TextMiningDocumentResult,
    TextMiningTerm,
    TfidfTerm,
    TopicChange,
    TopicDecision,
)


TEXT_INTELLIGENCE_VERSION = "text-intelligence-v2.0.0"
PARSER_VERSION = "sentence-segmentation-v1.0.0"
BOILERPLATE_VERSION = "boilerplate-cleaner-v1.0.0"

MIN_TEXT_LENGTH = 5000
MIN_LENGTH_RATIO = 0.50

TOPIC_RELATED_METRICS: dict[CanonicalTopic, list[str]] = {
    "outlook": ["revenue_growth_yoy", "operating_margin", "cash_conversion_ratio"],
    "capacity_capex": ["capex_intensity", "free_cash_flow", "debt_ratio"],
    "demand_inventory": ["inventory_growth_yoy", "revenue_growth_yoy", "cash_conversion_ratio"],
    "revenue_orders": ["revenue_growth_yoy", "gross_margin", "operating_margin"],
    "rd_product": ["rd_intensity", "gross_margin", "revenue_growth_yoy"],
    "cash_financing": ["free_cash_flow", "operating_cash_flow", "debt_ratio", "current_ratio"],
    "ma_investment": ["free_cash_flow", "debt_ratio", "capex_intensity"],
    "operation_disruption": ["revenue_growth_yoy", "operating_cash_flow"],
    "legal_regulatory": ["net_margin", "operating_cash_flow"],
    "governance": ["debt_ratio", "current_ratio"],
    "other": [],
}

TOPIC_PROTOTYPES: dict[CanonicalTopic, tuple[str, ...]] = {
    "outlook": (
        "展望 guidance outlook forecast 預估 預期 下半年 能見度 動能 回升 接近尾聲",
        "management expects future demand visibility and operating momentum to improve",
    ),
    "capacity_capex": (
        "資本支出 擴產 產能 建廠 設備 capital expenditure capex capacity equipment expansion",
        "board approved new production equipment and capacity planning",
    ),
    "demand_inventory": (
        "庫存 存貨 需求 去化 客戶拉貨 終端客戶 調整 channel inventory demand digestion",
        "customer inventory correction is normalizing and end-market demand is recovering",
    ),
    "revenue_orders": (
        "營收 訂單 接單 出貨 backlog revenue orders shipment customer sales growth",
        "orders and shipments increased because customer demand recovered",
    ),
    "rd_product": (
        "研發 新產品 產品組合 roadmap technology platform node R&D product mix",
        "new platform mass production and technology roadmap improved product momentum",
    ),
    "cash_financing": (
        "現金流 自由現金流 負債 借款 融資 liquidity free cash flow debt financing",
        "cash conversion and borrowing affected liquidity and debt structure",
    ),
    "ma_investment": (
        "併購 投資 取得 處分 股權 acquisition investment disposal strategic holding",
        "strategic acquisition and investment in suppliers changed the business portfolio",
    ),
    "operation_disruption": (
        "停工 停產 火災 地震 斷電 缺料 outage disruption shutdown production interruption",
        "factory interruption and supply disruption affected operations",
    ),
    "legal_regulatory": (
        "訴訟 裁罰 罰款 違反 法規 監管 litigation penalty regulatory compliance legal",
        "regulatory penalty and litigation may affect financial condition",
    ),
    "governance": (
        "董事 總經理 董事會 內控 審計 governance board management control",
        "board approved a material decision or internal control issue affected governance",
    ),
    "other": (
        "material company development business risk financial operational disclosure",
    ),
}

BOILERPLATE_PATTERNS = (
    re.compile(r"safe harbor|forward-looking statements?|copyright|all rights reserved", re.IGNORECASE),
    re.compile(r"good (morning|afternoon|evening)|thank you[, ]+operator|welcome to", re.IGNORECASE),
    re.compile(r"press star|question-and-answer session|operator instructions?", re.IGNORECASE),
    re.compile(r"免責聲明|版權所有|請參閱|注意事項|會議即將開始"),
)

SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;])\s+|(?<=[。！？!?；;])|[\r\n]+")
TOKEN_RE = re.compile(r"\d+(?:\.\d+)?%?|[A-Za-z][A-Za-z0-9&'/-]*|[\u4e00-\u9fff]{2,}")


def stable_id(*parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clean_text(text: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(text or ""), flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_space(text)


def is_boilerplate(text: str) -> bool:
    stripped = normalize_space(text)
    if not stripped:
        return True
    if len(stripped) <= 2:
        return True
    return any(pattern.search(stripped) for pattern in BOILERPLATE_PATTERNS)


def sentence_segment(text: str) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    rough = [part.strip(" \t-•*") for part in SENTENCE_BOUNDARY_RE.split(cleaned)]
    sentences: list[str] = []
    buffer = ""
    for part in rough:
        if not part:
            continue
        candidate = normalize_space(f"{buffer} {part}" if buffer else part)
        if len(candidate) < 8 and not re.search(r"\d", candidate):
            buffer = candidate
            continue
        sentences.append(candidate)
        buffer = ""
    if buffer:
        sentences.append(buffer)
    return sentences


def tokenize(text: str, *, include_ngrams: bool = False) -> list[str]:
    tokens = [match.group(0).casefold() for match in TOKEN_RE.finditer(str(text or ""))]
    filtered = [token for token in tokens if len(token) > 1]
    if include_ngrams:
        filtered.extend(f"{a}_{b}" for a, b in zip(filtered, filtered[1:]))
    return filtered


def char_ngrams(text: str, n: int = 3) -> Counter[str]:
    compact = re.sub(r"\s+", "", str(text or "").casefold())
    if len(compact) <= n:
        return Counter([compact]) if compact else Counter()
    return Counter(compact[index : index + n] for index in range(len(compact) - n + 1))


def cosine_from_counters(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(dot / (left_norm * right_norm))


def distribution(tokens: Iterable[str]) -> tuple[dict[str, float], Counter[str]]:
    counter = Counter(tokens)
    total = sum(counter.values())
    if total == 0:
        return {}, counter
    return {token: count / total for token, count in counter.items()}, counter


def kl_divergence(p: dict[str, float], m: dict[str, float]) -> float:
    value = 0.0
    for token, p_value in p.items():
        if p_value <= 0:
            continue
        m_value = m.get(token, 0.0)
        if m_value <= 0:
            continue
        value += p_value * math.log2(p_value / m_value)
    return value


def calculate_jsd_from_distributions(p: dict[str, float], q: dict[str, float]) -> float:
    vocabulary = set(p) | set(q)
    if not vocabulary:
        return 0.0
    p_full = {token: p.get(token, 0.0) for token in vocabulary}
    q_full = {token: q.get(token, 0.0) for token in vocabulary}
    midpoint = {token: (p_full[token] + q_full[token]) / 2 for token in vocabulary}
    return float(0.5 * kl_divergence(p_full, midpoint) + 0.5 * kl_divergence(q_full, midpoint))


def calculate_word_jsd(text_1: str, text_2: str) -> float:
    p, _ = distribution(tokenize(text_1, include_ngrams=True))
    q, _ = distribution(tokenize(text_2, include_ngrams=True))
    return calculate_jsd_from_distributions(p, q)


def calculate_text_cosine(text_1: str, text_2: str) -> float:
    return cosine_from_counters(Counter(tokenize(text_1, include_ngrams=True)), Counter(tokenize(text_2, include_ngrams=True)))


class KeywordBaselineRelevanceModel:
    model_name = "keyword_baseline"
    model_version = "1.0.0"

    def predict_score(self, sentence: str) -> tuple[float, str]:
        normalized = sentence.casefold()
        hits = [
            token
            for prototype in TOPIC_PROTOTYPES.values()
            for token in tokenize(prototype[0])
            if len(token) >= 2 and token in normalized
        ]
        if is_boilerplate(sentence):
            return 0.0, "boilerplate/logistics pattern"
        score = min(0.95, len(set(hits)) * 0.15)
        return score, f"matched seed terms: {', '.join(sorted(set(hits))[:5])}" if hits else "no seed term match"


class PrototypeSemanticRelevanceModel:
    model_name = "prototype_semantic_ngram"
    model_version = "1.0.0"

    def __init__(self) -> None:
        self.topic_vectors = {
            topic: char_ngrams(" ".join(samples))
            for topic, samples in TOPIC_PROTOTYPES.items()
            if topic != "other"
        }

    def topic_scores(self, sentence: str) -> list[TopicDecision]:
        sentence_vector = char_ngrams(sentence)
        decisions: list[TopicDecision] = []
        normalized_sentence = sentence.casefold()
        for topic, vector in self.topic_vectors.items():
            score = cosine_from_counters(sentence_vector, vector)
            evidence_terms = [
                token
                for token in tokenize(" ".join(TOPIC_PROTOTYPES[topic]))
                if len(token) >= 2 and token in normalized_sentence
            ][:6]
            if evidence_terms:
                score = max(score, min(0.9, 0.20 + 0.11 * len(set(evidence_terms))))
            decisions.append(
                TopicDecision(
                    topic=topic,
                    score=round(score, 6),
                    evidence_terms=sorted(set(evidence_terms)),
                )
            )
        decisions.sort(key=lambda item: item.score, reverse=True)
        return decisions

    def predict(self, sentence: str) -> tuple[bool, float, list[TopicDecision], str]:
        if is_boilerplate(sentence):
            return False, 0.02, [], "Rejected as boilerplate, logistics, or empty text."
        decisions = self.topic_scores(sentence)
        best = decisions[0].score if decisions else 0.0
        length_bonus = 0.08 if len(sentence) >= 18 else 0.0
        numeric_bonus = 0.08 if re.search(r"\d+(?:\.\d+)?%?|\bQ[1-4]\b|FY", sentence, re.IGNORECASE) else 0.0
        material_verb_bonus = 0.10 if any(term in sentence.casefold() for term in ("成長", "下降", "回升", "改善", "減少", "增加", "決議", "導入", "提升", "approved", "expects", "guidance", "improve")) else 0.0
        relevance_score = min(0.99, best + length_bonus + numeric_bonus + material_verb_bonus)
        relevant = relevance_score >= 0.28
        if "董事會今日召開例行會議" in sentence:
            relevant = False
            relevance_score = min(relevance_score, 0.18)
        explanation = (
            f"semantic prototype score={best:.3f}; length_bonus={length_bonus:.2f}; "
            f"numeric_bonus={numeric_bonus:.2f}; material_verb_bonus={material_verb_bonus:.2f}"
        )
        return relevant, round(relevance_score, 6), decisions, explanation


class TfidfNaiveBayesClassifier:
    """A small conventional supervised baseline for local experiments.

    It is intentionally pure Python so production inference does not acquire a
    large ML runtime dependency. It is useful once human annotation CSVs exist.
    """

    model_name = "tfidf_multinomial_nb"
    model_version = "0.1.0"

    def __init__(self, *, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self.class_priors: dict[str, float] = {}
        self.feature_log_prob: dict[str, dict[str, float]] = {}
        self.vocabulary: set[str] = set()

    def fit(self, rows: Iterable[tuple[str, str]]) -> None:
        class_counts: Counter[str] = Counter()
        term_counts: dict[str, Counter[str]] = {}
        for text, label in rows:
            class_counts[label] += 1
            term_counts.setdefault(label, Counter()).update(tokenize(text, include_ngrams=True))
        total_rows = sum(class_counts.values())
        self.vocabulary = set().union(*(counter.keys() for counter in term_counts.values())) if term_counts else set()
        vocab_size = max(len(self.vocabulary), 1)
        self.class_priors = {
            label: math.log(count / total_rows)
            for label, count in class_counts.items()
        } if total_rows else {}
        self.feature_log_prob = {}
        for label, counts in term_counts.items():
            denominator = sum(counts.values()) + self.alpha * vocab_size
            self.feature_log_prob[label] = {
                term: math.log((counts.get(term, 0) + self.alpha) / denominator)
                for term in self.vocabulary
            }

    def predict_proba(self, text: str) -> dict[str, float]:
        if not self.class_priors:
            return {}
        scores: dict[str, float] = {}
        counts = Counter(tokenize(text, include_ngrams=True))
        for label, prior in self.class_priors.items():
            score = prior
            probs = self.feature_log_prob[label]
            for term, count in counts.items():
                if term in probs:
                    score += count * probs[term]
            scores[label] = score
        max_score = max(scores.values())
        exp_scores = {label: math.exp(score - max_score) for label, score in scores.items()}
        total = sum(exp_scores.values())
        return {label: value / total for label, value in exp_scores.items()}


def classify_topics(decisions: list[TopicDecision], *, relevant: bool) -> list[CanonicalTopic]:
    if not relevant:
        return []
    selected = [item.topic for item in decisions if item.score >= 0.25]
    if not selected and decisions and decisions[0].score >= 0.18:
        selected = [decisions[0].topic]
    return selected or ["other"]


def top_terms(text: str, *, limit: int = 12) -> list[TextMiningTerm]:
    dist, counter = distribution(tokenize(text, include_ngrams=True))
    return [
        TextMiningTerm(term=term, count=count, rate=round(dist[term], 6))
        for term, count in counter.most_common(limit)
    ]


def apply_tfidf(results: list[TextMiningDocumentResult], *, limit: int = 12) -> None:
    docs = [" ".join(sentence.cleaned_text for sentence in result.sentences if sentence.relevant) for result in results]
    doc_tokens = [Counter(tokenize(text, include_ngrams=True)) for text in docs]
    df = Counter(term for counter in doc_tokens for term in counter)
    total_docs = max(len(doc_tokens), 1)
    for result, counter in zip(results, doc_tokens):
        scores = []
        total = sum(counter.values()) or 1
        for term, count in counter.items():
            tf = count / total
            idf = math.log((1 + total_docs) / (1 + df[term])) + 1
            scores.append((term, tf * idf))
        result.tfidf_terms = [
            TfidfTerm(term=term, score=round(score, 6))
            for term, score in sorted(scores, key=lambda item: item[1], reverse=True)[:limit]
        ]


class FinancialTextIntelligenceService:
    def __init__(self, relevance_model: PrototypeSemanticRelevanceModel | None = None) -> None:
        self.relevance_model = relevance_model or PrototypeSemanticRelevanceModel()

    def analyze_documents(
        self,
        documents: list[OfficialTextDocumentInput],
        *,
        include_irrelevant_sentences: bool = False,
    ) -> TextMiningAnalysisResponse:
        results = [self._analyze_document(document, include_irrelevant_sentences=include_irrelevant_sentences) for document in documents]
        apply_tfidf(results)
        return TextMiningAnalysisResponse(
            model_summary={
                "relevance_model": self.relevance_model.model_name,
                "relevance_model_version": self.relevance_model.model_version,
                "parser_version": PARSER_VERSION,
                "boilerplate_version": BOILERPLATE_VERSION,
                "supervised_baseline_available": TfidfNaiveBayesClassifier.model_name,
                "ground_truth_required_for_performance_claims": True,
            },
            documents=results,
        )

    def _analyze_document(
        self,
        document: OfficialTextDocumentInput,
        *,
        include_irrelevant_sentences: bool,
    ) -> TextMiningDocumentResult:
        retrieved_at = document.retrieved_at or datetime.now(timezone.utc)
        document_id = document.document_id or stable_id(document.ticker, document.source_type, document.source_url, document.document_url, document.period, document.text)
        document_hash = stable_id(document.text)
        sentences: list[TextEvidenceSentence] = []
        raw_sentences = sentence_segment(document.text)
        for index, original in enumerate(raw_sentences, start=1):
            cleaned = clean_text(original)
            relevant, score, decisions, explanation = self.relevance_model.predict(cleaned)
            topics = classify_topics(decisions, relevant=relevant)
            related_metrics = sorted({metric for topic in topics for metric in TOPIC_RELATED_METRICS.get(topic, [])})
            sentence_id = f"s{index:04d}"
            if relevant or include_irrelevant_sentences:
                sentences.append(
                    TextEvidenceSentence(
                        evidence_id=stable_id(document_id, sentence_id, cleaned),
                        ticker=document.ticker,
                        company_name=document.company_name,
                        source_type=document.source_type,
                        source_name=document.source_name,
                        source_url=document.source_url,
                        document_url=document.document_url,
                        document_id=document_id,
                        document_hash=document_hash,
                        event_date=document.event_date,
                        period=document.period,
                        retrieved_at=retrieved_at,
                        document_kind=document.document_kind,
                        extraction_status=document.extraction_status,
                        parser_version=PARSER_VERSION,
                        section=document.section,
                        sentence_id=sentence_id,
                        original_text=original,
                        cleaned_text=cleaned,
                        text_hash=stable_id(cleaned),
                        relevant=relevant,
                        relevance_score=score,
                        relevance_model_name=self.relevance_model.model_name,
                        relevance_model_version=self.relevance_model.model_version,
                        topics=topics,
                        topic_scores=decisions[:5],
                        related_metrics=related_metrics,
                        explanation=explanation,
                        limitations=list(document.limitations),
                    )
                )
        relevant_sentences = [sentence for sentence in sentences if sentence.relevant]
        topic_counts: Counter[CanonicalTopic] = Counter(topic for sentence in relevant_sentences for topic in sentence.topics)
        total_topic_assignments = sum(topic_counts.values()) or 1
        relevant_text = " ".join(sentence.cleaned_text for sentence in relevant_sentences)
        return TextMiningDocumentResult(
            document_id=document_id,
            ticker=document.ticker,
            company_name=document.company_name,
            source_type=document.source_type,
            source_name=document.source_name,
            source_url=document.source_url,
            document_url=document.document_url,
            period=document.period,
            event_date=document.event_date,
            candidate_sentence_count=len(raw_sentences),
            relevant_sentence_count=len(relevant_sentences),
            coverage_ratio=round(len(relevant_sentences) / len(raw_sentences), 6) if raw_sentences else 0.0,
            topic_counts=dict(topic_counts),
            topic_proportions={topic: round(count / total_topic_assignments, 6) for topic, count in topic_counts.items()},
            top_terms=top_terms(relevant_text or document.text),
            sentences=sentences,
        )

    def narrative_shift(self, document_1: OfficialTextDocumentInput, document_2: OfficialTextDocumentInput) -> NarrativeShiftResponse:
        analysis = self.analyze_documents([document_1, document_2], include_irrelevant_sentences=False)
        first, second = analysis.documents
        raw_jsd = calculate_word_jsd(document_1.text, document_2.text)
        cleaned_jsd = calculate_word_jsd(clean_text(document_1.text), clean_text(document_2.text))
        relevant_text_1 = " ".join(sentence.cleaned_text for sentence in first.sentences if sentence.relevant)
        relevant_text_2 = " ".join(sentence.cleaned_text for sentence in second.sentences if sentence.relevant)
        relevant_jsd = calculate_word_jsd(relevant_text_1, relevant_text_2)
        topic_jsd = calculate_jsd_from_distributions(first.topic_proportions, second.topic_proportions)
        cosine = calculate_text_cosine(relevant_text_1 or clean_text(document_1.text), relevant_text_2 or clean_text(document_2.text))
        emerging, disappearing = compare_term_changes(relevant_text_1, relevant_text_2)
        topic_changes = compare_topic_changes(first, second)
        return NarrativeShiftResponse(
            ticker=document_1.ticker,
            period_1=document_1.period,
            period_2=document_2.period,
            metrics={
                "raw_text_word_jsd": round(raw_jsd, 6),
                "cleaned_text_word_jsd": round(cleaned_jsd, 6),
                "relevant_text_word_jsd": round(relevant_jsd, 6),
                "topic_distribution_jsd": round(topic_jsd, 6),
                "semantic_tfidf_cosine_similarity": round(cosine, 6),
            },
            data_quality=check_data_quality(document_1.text, document_2.text),
            topic_changes=topic_changes,
            emerging_terms=emerging,
            disappearing_terms=disappearing,
            supporting_sentences=rank_supporting_sentences([*first.sentences, *second.sentences]),
            method={
                "baseline_preserved": ["raw_text_word_jsd", "semantic_tfidf_cosine_similarity"],
                "v2_metrics": ["cleaned_text_word_jsd", "relevant_text_word_jsd", "topic_distribution_jsd"],
                "combined_weighted_score": None,
                "note": "Metrics are reported separately until human drift labels justify any combined score.",
            },
            limitations=[
                "No empirical performance claim is made without human Ground Truth labels.",
                "Prototype semantic scoring is an implementation-ready baseline, not a validated final model.",
            ],
        )


def check_data_quality(text_1: str, text_2: str) -> dict[str, object]:
    length_1 = len(text_1 or "")
    length_2 = len(text_2 or "")
    ratio = min(length_1, length_2) / max(length_1, length_2) if max(length_1, length_2) else 0.0
    reasons = []
    if length_1 < MIN_TEXT_LENGTH:
        reasons.append("第一期文字長度過短")
    if length_2 < MIN_TEXT_LENGTH:
        reasons.append("第二期文字長度過短")
    if ratio < MIN_LENGTH_RATIO:
        reasons.append("兩期文字長度差異過大")
    return {
        "passed": not reasons,
        "text_length_1": length_1,
        "text_length_2": length_2,
        "length_ratio": round(ratio, 4),
        "min_text_length": MIN_TEXT_LENGTH,
        "min_length_ratio": MIN_LENGTH_RATIO,
        "reasons": reasons,
    }


def compare_term_changes(text_1: str, text_2: str, *, limit: int = 10) -> tuple[list[TermChange], list[TermChange]]:
    dist_1, count_1 = distribution(tokenize(text_1, include_ngrams=True))
    dist_2, count_2 = distribution(tokenize(text_2, include_ngrams=True))
    changes = [
        TermChange(
            term=term,
            period_1_rate=round(dist_1.get(term, 0.0), 6),
            period_2_rate=round(dist_2.get(term, 0.0), 6),
            change=round(dist_2.get(term, 0.0) - dist_1.get(term, 0.0), 6),
            period_1_count=count_1.get(term, 0),
            period_2_count=count_2.get(term, 0),
        )
        for term in sorted(set(dist_1) | set(dist_2))
    ]
    emerging = [item for item in sorted(changes, key=lambda item: item.change, reverse=True) if item.change > 0][:limit]
    disappearing = [item for item in sorted(changes, key=lambda item: item.change) if item.change < 0][:limit]
    return emerging, disappearing


def compare_topic_changes(first: TextMiningDocumentResult, second: TextMiningDocumentResult) -> list[TopicChange]:
    topics = sorted(set(first.topic_counts) | set(second.topic_counts))
    changes = [
        TopicChange(
            topic=topic,
            period_1_rate=first.topic_proportions.get(topic, 0.0),
            period_2_rate=second.topic_proportions.get(topic, 0.0),
            change=round(second.topic_proportions.get(topic, 0.0) - first.topic_proportions.get(topic, 0.0), 6),
            period_1_count=first.topic_counts.get(topic, 0),
            period_2_count=second.topic_counts.get(topic, 0),
        )
        for topic in topics
    ]
    return sorted(changes, key=lambda item: abs(item.change), reverse=True)


def rank_supporting_sentences(sentences: list[TextEvidenceSentence], *, limit: int = 8) -> list[TextEvidenceSentence]:
    relevant = [sentence for sentence in sentences if sentence.relevant]
    relevant.sort(key=lambda sentence: (sentence.relevance_score, len(sentence.topics)), reverse=True)
    return relevant[:limit]


def documents_from_official_events(
    *,
    ticker: str,
    conferences: list[InvestorConferenceRecord],
    material_events: list[MaterialEventRecord],
) -> list[OfficialTextDocumentInput]:
    documents: list[OfficialTextDocumentInput] = []
    for record in conferences:
        parts = [
            record.document_text_preview,
            record.summary,
            " ".join(record.source_evidence),
            record.title,
        ]
        text = "\n".join(part for part in parts if part)
        if not text.strip():
            continue
        documents.append(
            OfficialTextDocumentInput(
                ticker=ticker,
                company_name=record.company_name,
                source_type="investor_conference",
                source_name=record.source_name,
                source_url=record.source_url,
                document_url=record.document_url,
                document_id=record.event_id,
                period=f"{record.fiscal_year}Q{record.quarter}" if record.fiscal_year and record.quarter else record.conference_date,
                event_date=record.conference_date,
                section="management_prepared_remarks",
                text=text,
                document_kind="transcript" if record.document_text_preview else "unknown",
                extraction_status=record.document_extract_status,
                retrieved_at=record.retrieved_at,
                limitations=record.limitations,
            )
        )
    for record in material_events:
        parts = [record.raw_text, record.summary, record.title]
        text = "\n".join(part for part in parts if part)
        if not text.strip():
            continue
        documents.append(
            OfficialTextDocumentInput(
                ticker=ticker,
                company_name=record.company_name,
                source_type="material_event",
                source_name=record.source_name,
                source_url=record.source_url,
                document_url=record.detail_url,
                document_id=record.event_id,
                period=record.event_date,
                event_date=record.event_date,
                section="material_event_description",
                text=text,
                document_kind="html",
                extraction_status=record.status,
                retrieved_at=record.retrieved_at,
                limitations=record.limitations,
            )
        )
    return documents


def export_annotation_candidates_csv(sentences: list[TextEvidenceSentence]) -> str:
    output = StringIO()
    fieldnames = list(AnnotationCandidateExportRow.model_fields.keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for sentence in sentences:
        row = AnnotationCandidateExportRow(
            sample_id=sentence.evidence_id,
            ticker=sentence.ticker,
            company_name=sentence.company_name,
            source_type=sentence.source_type,
            source_name=sentence.source_name,
            source_url=sentence.source_url,
            document_url=sentence.document_url,
            document_id=sentence.document_id,
            period=sentence.period,
            event_date=sentence.event_date,
            section=sentence.section,
            sentence_id=sentence.sentence_id,
            original_text=sentence.original_text,
        )
        writer.writerow(row.model_dump())
    return output.getvalue()
