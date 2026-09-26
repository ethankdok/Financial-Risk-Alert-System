"""Claim verification over stored official evidence.

Pipeline: deterministic extraction (optional bounded Gemini fill-in) →
bounded retrieval → deterministic comparison → deterministic aggregation →
template summary. The model never produces evidence, numbers, or the verdict.

Decisive evidence: an item whose claim-relevant value/label pair is
source-confirmed (verified filing data, or a PDF table cell / chart value
mapped from the PDF text layer) and whose period and metric match the claim.
needs_review, Gemini-only, and OCR-only items are context only.
"""

from __future__ import annotations

from typing import Any

from app.claim_verification_models import (
    LEGACY_VERDICT_MAP,
    ClaimEvidenceItem,
    ClaimVerifyRequest,
    ClaimVerifyResponse,
    EvidenceComparison,
    StructuredClaim,
    VerificationDetail,
)
from app.models import ClaimDirection, ComparisonKind, ExtractedFinancialClaim
from app.services.claim_evidence_adapter import Candidate, ClaimEvidenceAdapter
from app.services.claim_parser import classify_claim, extract_claim
from app.services.verifier import verify_claim

MAX_EVIDENCE = 8
PERCENT_UNITS = {"%", "百分點"}
VERDICT_LABELS = {"supported": "官方資料支持", "conflicting": "與官方資料不一致", "insufficient_evidence": "證據不足"}
DECISIVE_STATUSES = {"verified", "partially_verified"}


def _decimals(text: str | None) -> int:
    cleaned = (text or "").replace(",", "").strip().rstrip("%")
    return len(cleaned.split(".")[1]) if "." in cleaned else 0


def compare_numeric(
    *,
    official: float,
    official_decimals: int | None,
    claimed: float,
    claimed_text: str | None,
    unit: str | None,
    tolerance_percentage_points: float,
    comparator: str | None = None,
) -> tuple[str, EvidenceComparison]:
    """Deterministic numeric relation: supports | conflicts | context (ambiguous).

    Supported: within the rounding precision implied by the printed numbers
    (59.5 → ±0.05). Conflicting: beyond the configured tolerance (absolute
    points for percentages, relative percent for amounts). In between: context.
    """
    exact = 0.5 * 10 ** -_decimals(claimed_text)
    if official_decimals is not None:
        exact = max(exact, 0.5 * 10 ** -official_decimals)
    exact += 1e-9
    conflict = (
        tolerance_percentage_points if unit in PERCENT_UNITS
        else abs(official) * tolerance_percentage_points / 100.0
    )
    conflict = max(conflict, exact)
    difference = abs(official - claimed)
    if comparator in {"lt", "gt"}:
        holds = official < claimed + exact if comparator == "lt" else official > claimed - exact
        relation = "supports" if holds else ("conflicts" if difference > exact else "context")
        formula = f"官方值 {official:g} {'<' if comparator == 'lt' else '>'} 主張 {claimed:g}？{'是' if holds else '否'}"
    else:
        relation = "supports" if difference <= exact else "conflicts" if difference > conflict else "context"
        formula = f"|{official:g} - {claimed:g}| = {difference:.4g}"
    return relation, EvidenceComparison(
        claimed_value=claimed,
        official_value=official,
        difference=round(difference, 6),
        tolerance=round(exact if relation == "supports" else conflict, 6),
        formula=formula,
    )


class ClaimVerificationService:
    def __init__(self, adapter: ClaimEvidenceAdapter, llm: Any | None = None) -> None:
        self.adapter = adapter
        self.llm = llm

    # --- extraction --------------------------------------------------------------------

    def structure(self, request: ClaimVerifyRequest) -> tuple[StructuredClaim, ExtractedFinancialClaim, list[str]]:
        limitations: list[str] = []
        parsed = extract_claim(
            request.claim,
            ticker_hint=request.company_code,
            period_hint=request.period,
            comparison_period_hint=request.comparison_period,
        )
        typing = classify_claim(request.claim, parsed)
        method = "deterministic"
        material_missing = [f for f in parsed.missing_fields if f in {"metric", "period", "claim_value_or_direction"}]
        if (material_missing and self.llm is not None and getattr(self.llm, "configured", False)
                and typing["claim_type"] not in {"unsupported", "company_statement"}):
            filled = self.llm.extract(request.claim)
            if filled is None:
                limitations.append("語意輔助解析暫時無法使用，僅採用規則式解析。")
            elif filled:
                updates: dict[str, Any] = {}
                if not parsed.metric and filled.get("metric"):
                    updates["metric"] = filled["metric"]
                if not parsed.period and filled.get("period"):
                    updates["period"] = filled["period"]
                if parsed.claimed_value is None and filled.get("value") is not None and parsed.claimed_change_percent is None:
                    updates.update(claimed_value=filled["value"], claimed_value_text=filled["value_text"],
                                   unit=filled.get("unit") or parsed.unit)
                if parsed.direction == ClaimDirection.UNSPECIFIED and filled.get("direction"):
                    updates["direction"] = ClaimDirection(filled["direction"])
                if updates:
                    method = "deterministic+gemini"
                    missing = [f for f in parsed.missing_fields
                               if not ({"metric": "metric", "period": "period"}.get(f) in updates
                                       or (f == "claim_value_or_direction"
                                           and ("claimed_value" in updates or "direction" in updates)))]
                    parsed = parsed.model_copy(update={**updates, "missing_fields": missing})
                    typing = classify_claim(request.claim, parsed)
        value = parsed.claimed_value
        if value is None:
            value = parsed.claimed_change_percent if parsed.claimed_change_percent is not None else parsed.claimed_percentage_points
        structured = StructuredClaim(
            raw_claim=request.claim,
            company_code=parsed.ticker or request.company_code,
            company_name=parsed.company_name,
            claim_type=typing["claim_type"],
            metric_or_topic=typing["metric_or_topic"],
            period=parsed.period,
            comparison_period=parsed.comparison_period,
            value=value,
            value_text=parsed.claimed_value_text,
            unit=parsed.unit,
            direction=parsed.direction.value if parsed.direction else None,
            comparator=typing["comparator"],
            keywords=list(typing["keywords"]),
            extraction_method=method,
            extraction_confidence=parsed.extraction_confidence,
            missing_fields=list(parsed.missing_fields),
            requires_review=method != "deterministic",
        )
        return structured, parsed, limitations

    # --- verification ------------------------------------------------------------------

    def verify(self, request: ClaimVerifyRequest) -> ClaimVerifyResponse:
        structured, parsed, limitations = self.structure(request)
        detail = VerificationDetail()
        candidates: list[Candidate] = []
        claim_type = structured.claim_type

        early = self._early_exit(structured)
        if early is None:
            if claim_type in {"numeric_metric", "trend", "operational_metric"} and parsed.metric:
                candidates += self._fact_candidates(parsed, request, detail)
            if claim_type in {"numeric_metric", "operational_metric", "percentage_mix"}:
                candidates += self._numeric_conference(structured, request)
            if claim_type == "trend":
                candidates += self._trend_conference(structured)
            if claim_type == "company_statement":
                candidates += self._statement_candidates(structured, detail)
        detail.llm_calls = getattr(self.llm, "calls", 0) if self.llm is not None else 0

        selected = self._select(candidates)
        verdict, reason = early or self._aggregate(selected, structured)
        detail.decisive_supporting = sum(1 for c in selected if c.item.decisive and c.item.relation == "supports")
        detail.decisive_conflicting = sum(1 for c in selected if c.item.decisive and c.item.relation == "conflicts")
        requires_review = structured.requires_review or any(
            c.extra.get("llm_relation") for c in selected if c.item.decisive
        ) or (verdict == "insufficient_evidence" and bool(selected))
        limitations += self._limitations(selected, verdict, reason, structured)
        return ClaimVerifyResponse(
            request={"company_code": request.company_code, "claim": request.claim},
            structured_claim=structured,
            verdict=verdict,
            reason_code=reason,
            summary=self._summary(structured, verdict, reason, selected),
            evidence=[c.item for c in selected],
            verification_detail=detail,
            limitations=list(dict.fromkeys(limitations)),
            requires_review=requires_review,
        )

    @staticmethod
    def _early_exit(claim: StructuredClaim) -> tuple[str, str] | None:
        if claim.claim_type == "unsupported":
            return "insufficient_evidence", "unsupported_claim_type"
        if not claim.company_code:
            return "insufficient_evidence", "missing_company"
        if claim.claim_type != "company_statement" and not claim.period:
            return "insufficient_evidence", "missing_period"
        if claim.claim_type in {"numeric_metric", "operational_metric", "percentage_mix"} and claim.value is None:
            return "insufficient_evidence", "missing_claim_value"
        return None

    # financial facts / calculated metrics (existing verifier)
    def _fact_candidates(self, parsed: ExtractedFinancialClaim, request: ClaimVerifyRequest,
                         detail: VerificationDetail) -> list[Candidate]:
        repository = self.adapter.fact_repository
        if repository is None:
            return []
        try:
            legacy = verify_claim(parsed, repository=repository,
                                  tolerance_percentage_points=request.tolerance_percentage_points)
        except Exception:
            return []
        detail.legacy_verdict = legacy.verdict.value
        detail.difference = legacy.difference
        if legacy.evidence is None:
            return []
        evidence = legacy.evidence
        detail.tolerance = evidence.tolerance_percentage_points
        detail.calculation = evidence.formula
        current = self.adapter.fact(parsed.ticker, parsed.metric, parsed.period)
        if current is None:
            return []
        canonical = LEGACY_VERDICT_MAP.get(legacy.verdict.value, "insufficient_evidence")
        relation = {"supported": "supports", "conflicting": "conflicts"}.get(canonical, "context")
        comparison = EvidenceComparison(
            claimed_value=parsed.claimed_value, official_value=evidence.calculated_value,
            difference=legacy.difference, tolerance=evidence.tolerance_percentage_points, formula=evidence.formula,
        )
        exact_value = parsed.comparison_kind == ComparisonKind.VALUE and parsed.claimed_value is not None
        if exact_value and evidence.calculated_value is not None and parsed.unit in {None, current.unit} | (
                {"%"} if current.unit == "%" else set()):
            relation, comparison = compare_numeric(
                official=current.value, official_decimals=None, claimed=parsed.claimed_value,
                claimed_text=parsed.claimed_value_text, unit=current.unit,
                tolerance_percentage_points=request.tolerance_percentage_points,
            )
        elif exact_value and relation != "context":
            comparison.formula = (evidence.formula or "") + "（金額單位換算後比較）"
        candidates = []
        item = self.adapter.fact_item(current, relation=relation, comparison=comparison)
        verified = item.verification_status == "verified"
        item.decisive = verified and relation in {"supports", "conflicts"}
        candidates.append(Candidate(item=item, source_confirmed=verified, score=10.0))
        if parsed.comparison_period:
            prior = self.adapter.fact(parsed.ticker, parsed.metric, parsed.comparison_period)
            if prior is not None:
                candidates.append(Candidate(item=self.adapter.fact_item(prior), source_confirmed=False, score=5.0))
        return candidates

    def _numeric_conference(self, claim: StructuredClaim, request: ClaimVerifyRequest) -> list[Candidate]:
        out = []
        for candidate in self.adapter.conference_candidates(claim):
            item = candidate.item
            same_period = item.period == claim.period
            candidate.score = (4 if same_period else 0) + (2 if candidate.source_confirmed else 0)
            if not same_period:
                item.note = item.note or ("無法確認此資料所屬期間，不作為判定依據。" if item.period is None
                                          else "期間與主張不同，不作為判定依據。")
            comparable = (
                same_period and candidate.kind == "actual" and candidate.numeric_value is not None
                and claim.value is not None and self._units_comparable(claim.unit, item.unit)
            )
            if comparable:
                relation, comparison = compare_numeric(
                    official=candidate.numeric_value, official_decimals=candidate.decimals,
                    claimed=claim.value, claimed_text=claim.value_text, unit=item.unit or claim.unit,
                    tolerance_percentage_points=request.tolerance_percentage_points, comparator=claim.comparator,
                )
                item.relation, item.comparison = relation, comparison
                item.decisive = (candidate.source_confirmed and item.verification_status in DECISIVE_STATUSES
                                 and relation in {"supports", "conflicts"})
                candidate.score += 3
            elif same_period and candidate.kind == "actual" and candidate.numeric_value is not None:
                item.note = item.note or "主張單位與官方數值單位無法直接比較。"
            out.append(candidate)
        return out

    @staticmethod
    def _units_comparable(claimed: str | None, official: str | None) -> bool:
        if claimed in PERCENT_UNITS or official in PERCENT_UNITS:
            return claimed in PERCENT_UNITS and official in PERCENT_UNITS
        return claimed is None and official is None

    def _trend_conference(self, claim: StructuredClaim) -> list[Candidate]:
        """Recompute a direction from two actual, source-confirmed cells of the same table row."""
        if claim.direction not in {"increase", "decrease"} or not claim.comparison_period:
            return []
        found = self.adapter.conference_candidates(claim)
        rows: dict[str, dict[str, Candidate]] = {}
        for candidate in found:
            if candidate.kind == "actual" and candidate.group:
                rows.setdefault(candidate.group, {})[candidate.item.period or ""] = candidate
        out = []
        for row in rows.values():
            current, prior = row.get(claim.period or ""), row.get(claim.comparison_period)
            if not current or not prior or current.numeric_value is None or prior.numeric_value is None:
                continue
            delta = current.numeric_value - prior.numeric_value
            holds = delta > 0 if claim.direction == "increase" else delta < 0
            relation = "supports" if holds else "conflicts" if delta != 0 else "context"
            comparison = EvidenceComparison(
                official_value=round(delta, 6),
                formula=f"{current.item.value} − {prior.item.value}（{claim.period} 對 {claim.comparison_period}）",
            )
            for candidate in (current, prior):
                candidate.item.relation, candidate.item.comparison = relation, comparison
                candidate.item.decisive = (
                    candidate is current and current.source_confirmed and prior.source_confirmed
                    and relation != "context"
                )
                candidate.score = 6
                out.append(candidate)
        return out

    def _statement_candidates(self, claim: StructuredClaim, detail: VerificationDetail) -> list[Candidate]:
        candidates = self.adapter.event_candidates(claim) + self.adapter.conference_candidates(claim)
        candidates.sort(key=lambda c: c.score, reverse=True)
        candidates = candidates[:5]
        if candidates and self.llm is not None and getattr(self.llm, "configured", False):
            relations = self.llm.relate(
                {"claim": claim.raw_claim, "company_code": claim.company_code},
                [{"evidence_id": c.item.evidence_id, "source_type": c.item.source_type,
                  "text": c.item.source_text or ""} for c in candidates],
            )
            for candidate in candidates:
                relation, reason = (relations or {}).get(candidate.item.evidence_id, ("unclear", None))
                if relation in {"supports", "conflicts"}:
                    candidate.item.relation = relation
                    candidate.item.note = f"語意比對（需人工複核）：{reason}" if reason else "語意比對結果，需人工複核。"
                    candidate.extra["llm_relation"] = True
                    # A model relation never upgrades weak evidence: only verified official text counts.
                    candidate.item.decisive = candidate.source_confirmed and candidate.item.verification_status == "verified"
        return candidates

    # --- selection / aggregation / summary ------------------------------------------------

    @staticmethod
    def _select(candidates: list[Candidate]) -> list[Candidate]:
        order = {"verified": 2, "partially_verified": 1}
        seen, ranked = set(), []
        for candidate in sorted(
            candidates,
            key=lambda c: (c.item.decisive, c.score, order.get(c.item.verification_status, 0)),
            reverse=True,
        ):
            if candidate.item.evidence_id in seen:
                continue
            seen.add(candidate.item.evidence_id)
            ranked.append(candidate)
        return ranked[:MAX_EVIDENCE]

    @staticmethod
    def _aggregate(selected: list[Candidate], claim: StructuredClaim) -> tuple[str, str]:
        supporting = [c for c in selected if c.item.decisive and c.item.relation == "supports"]
        conflicting = [c for c in selected if c.item.decisive and c.item.relation == "conflicts"]
        if supporting and conflicting:
            return "insufficient_evidence", "conflicting_official_sources"
        if supporting:
            return "supported", {"trend": "trend_confirmed", "company_statement": "statement_supported"}.get(
                claim.claim_type, "value_match")
        if conflicting:
            return "conflicting", {"trend": "trend_contradicted", "company_statement": "statement_contradicted"}.get(
                claim.claim_type, "value_mismatch")
        if not selected:
            return "insufficient_evidence", "no_official_evidence"
        if any(c.item.relation in {"supports", "conflicts"} and c.item.verification_status == "needs_review"
               for c in selected):
            return "insufficient_evidence", "only_needs_review_evidence"
        if any(c.item.relation in {"supports", "conflicts"} for c in selected):
            return "insufficient_evidence", "evidence_not_source_confirmed"
        if claim.period and all(c.item.period and c.item.period != claim.period for c in selected):
            return "insufficient_evidence", "period_not_aligned"
        if any(c.item.comparison is not None for c in selected):
            return "insufficient_evidence", "value_within_ambiguity_band"
        return "insufficient_evidence", "no_decisive_evidence"

    @staticmethod
    def _limitations(selected: list[Candidate], verdict: str, reason: str, claim: StructuredClaim) -> list[str]:
        notes = []
        if reason == "unsupported_claim_type":
            notes.append("此類說法（投資建議、保證獲利、冒名或網站真偽等）不在官方財務證據可查證範圍內。")
        if reason == "missing_period":
            notes.append("說法未指明年度或季度；系統不會自行推測「今年」「最近」等期間。")
        if any(c.item.provenance.source_kind == "mops_conference_pdf" for c in selected):
            notes.append("法說會簡報證據來自本機 PDF 解析結果；表格數值由 PDF 文字層對應，非會計師查核數字。")
        if any(c.extra.get("llm_relation") for c in selected):
            notes.append("文字說法的關聯判斷使用語意模型輔助，結果需人工複核。")
        if any(c.item.provenance.is_demo for c in selected):
            notes.append("部分資料為示範資料，不可作為正式查證依據。")
        if verdict == "insufficient_evidence" and reason in {"no_official_evidence", "no_decisive_evidence"}:
            notes.append("目前已收錄的官方資料（財報、法說會簡報、重大訊息標題）未涵蓋此說法。")
        return notes

    @staticmethod
    def _summary(claim: StructuredClaim, verdict: str, reason: str, selected: list[Candidate]) -> str:
        decisive = [c.item for c in selected if c.item.decisive and c.item.relation in {"supports", "conflicts"}]
        head = f"查證結果：{VERDICT_LABELS[verdict]}。"
        if decisive:
            first = decisive[0]
            where = "、".join(filter(None, [
                first.source_title, f"第 {first.page} 頁" if first.page else None,
                f"期間 {first.period}" if first.period else None,
            ]))
            value = f"「{first.label or first.metric}」為 {first.value}{'' if (first.value or '').endswith('%') else (' ' + first.unit if first.unit else '')}"
            relation = "與說法一致" if first.relation == "supports" else "與說法不一致"
            extra = f"（另有 {len(decisive) - 1} 筆官方證據）" if len(decisive) > 1 else ""
            return f"{head}官方資料（{where}）顯示{value}，{relation}{extra}。"
        reasons = {
            "unsupported_claim_type": "此說法類型無法以官方財務或公告資料查證。",
            "missing_company": "無法確認說法所指的公司，請提供公司代號。",
            "missing_period": "說法未指明可對應的財報期間。",
            "missing_claim_value": "說法未包含可比對的數值。",
            "no_official_evidence": "目前收錄的官方資料中找不到可對應此說法的證據。",
            "only_needs_review_evidence": "找到的相關資料尚待人工複核，不足以作出判定。",
            "evidence_not_source_confirmed": "相關數值未能由官方文件文字層確認其對應關係，不足以作出判定。",
            "period_not_aligned": "找到的官方資料屬於其他期間，不能直接比較。",
            "value_within_ambiguity_band": "官方數值與說法接近但超出四捨五入範圍，無法明確判定。",
            "conflicting_official_sources": "不同官方來源的結果互相矛盾，需人工確認。",
        }
        return head + reasons.get(reason, "現有證據不足以作出判定。")
