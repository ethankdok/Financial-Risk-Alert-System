from __future__ import annotations

from datetime import datetime
from typing import Any

from app.financial_analysis_models import FinancialStatementAnalysisReport
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import FinancialFact
from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.pipeline_models import AnalysisRunSummary, FrontendAnalysisSnapshot, PersistenceCounts
from app.text_intelligence_models import NarrativeShiftResponse, TextMiningAnalysisResponse
from app.services.analysis_repository import (
    deduplicate_financial_fact_rows,
    document_id,
    fact_document_id,
    financial_fact_from_row,
    historical_fact_rows,
    latest_fact_rows,
    metric_rows,
    preferred_financial_fact_row,
    rule_rows,
    statement_type_for_metric,
)
from app.services.official_event_sources import (
    investor_conference_identity,
    is_persistable_investor_conference,
    is_persistable_material_event,
    material_event_identity,
)


class FirestoreAnalysisRepository:
    backend_name = "firestore"

    def __init__(self, project_id: str | None = None) -> None:
        from google.cloud import firestore

        self.client = firestore.Client(project=project_id or None)

    def save_pipeline_result(
        self,
        *,
        run_id: str,
        trigger: str,
        started_at: datetime,
        completed_at: datetime,
        latest_report: FinancialStatementAnalysisReport,
        historical_report: HistoricalFinancialAnalysisReport,
        snapshot: FrontendAnalysisSnapshot,
    ) -> PersistenceCounts:
        facts = latest_fact_rows(latest_report) + historical_fact_rows(historical_report)
        metrics = metric_rows(run_id, latest_report, historical_report)
        rules = rule_rows(run_id, latest_report, historical_report)
        batch = self.client.batch()

        batch.set(
            self.client.collection("analysis_runs").document(run_id),
            {
                "run_id": run_id,
                "ticker": historical_report.ticker,
                "company_name": historical_report.company_name,
                "subindustry": historical_report.subindustry,
                "analysis_type": "combined",
                "trigger": trigger,
                "status": "completed",
                "started_at": started_at,
                "completed_at": completed_at,
                "rule_version": historical_report.rule_version,
                "overall_severity": snapshot.overall_severity.value,
                "summary": snapshot.summary,
                "error_message": None,
            },
        )

        for period in historical_report.periods:
            batch.set(
                self.client.collection("financial_filings").document(
                    document_id(historical_report.ticker, period.period)
                ),
                {
                    "ticker": historical_report.ticker,
                    "period": period.period,
                    "company_name": historical_report.company_name,
                    "subindustry": historical_report.subindustry,
                    "fiscal_year": period.fiscal_year,
                    "quarter": period.quarter,
                    "source_name": period.source_name,
                    "source_url": period.source_url,
                    "status": period.status,
                    "concept_matches": period.concept_matches,
                    "warnings": period.warnings,
                    "retrieved_at": completed_at,
                },
                merge=True,
            )

        for fact in facts:
            batch.set(
                self.client.collection("normalized_financial_facts").document(
                    fact_document_id(fact)
                ),
                {**fact, "fact_key_version": "financial-fact-v2", "retrieved_at": completed_at},
                merge=True,
            )

        for metric in metrics:
            batch.set(
                self.client.collection("calculated_metrics").document(
                    document_id(
                        run_id,
                        metric["analysis_type"],
                        metric["period"],
                        metric["metric_code"],
                    )
                ),
                {**metric, "created_at": completed_at},
            )

        for rule in rules:
            batch.set(
                self.client.collection("rule_results").document(
                    document_id(run_id, rule["analysis_type"], rule["rule_id"])
                ),
                {**rule, "created_at": completed_at},
            )

        batch.set(
            self.client.collection("latest_analysis_snapshots").document(snapshot.ticker),
            {**snapshot.model_dump(mode="python"), "updated_at": completed_at},
        )
        batch.set(
            self.client.collection("analysis_snapshots").document(run_id),
            {
                "run_id": run_id,
                "ticker": snapshot.ticker,
                "snapshot": snapshot.model_dump(mode="python"),
                "created_at": completed_at,
            },
            merge=True,
        )
        batch.commit()

        return PersistenceCounts(
            filings=len(historical_report.periods),
            facts=len(facts),
            metrics=len(metrics),
            rule_results=len(rules),
            snapshots=1,
        )

    def get_latest_snapshot(self, ticker: str) -> FrontendAnalysisSnapshot | None:
        document = self.client.collection("latest_analysis_snapshots").document(ticker).get()
        if not document.exists:
            return None
        payload = document.to_dict() or {}
        payload.pop("updated_at", None)
        return FrontendAnalysisSnapshot.model_validate(payload)

    def ingest_facts(self, facts: list[FinancialFact]) -> int:
        """Canonical direct-fact write path shared with the analysis pipeline."""
        from app.services.fact_repository import fact_to_firestore_row

        for start in range(0, len(facts), 200):
            batch = self.client.batch()
            for fact in facts[start : start + 200]:
                row = fact_to_firestore_row(fact)
                batch.set(
                    self.client.collection("normalized_financial_facts").document(
                        fact_document_id(row)
                    ),
                    row,
                    merge=True,
                )
            batch.commit()
        return len(facts)

    def save_official_events(
        self,
        *,
        ticker: str,
        investor_conferences: list[InvestorConferenceRecord],
        material_events: list[MaterialEventRecord],
        refreshed_at: datetime,
    ) -> dict[str, int]:
        batch = self.client.batch()
        conference_count = 0
        material_count = 0
        for record in investor_conferences:
            if not is_persistable_investor_conference(record):
                continue
            event_id = investor_conference_identity(record)
            payload = record.model_copy(update={"event_id": event_id, "retrieved_at": record.retrieved_at or refreshed_at})
            batch.set(
                self.client.collection("official_events").document(f"investor_conference:{event_id}"),
                {
                    "event_type": "investor_conference",
                    "event_id": event_id,
                    "ticker": ticker,
                    "company_name": payload.company_name,
                    "event_date": payload.conference_date,
                    "event_time": None,
                    "title": payload.title,
                    "source_url": payload.source_url,
                    "detail_url": payload.document_url,
                    "status": payload.status,
                    "payload": payload.model_dump(mode="python"),
                    "retrieved_at": refreshed_at,
                },
                merge=True,
            )
            conference_count += 1
        for record in material_events:
            if not is_persistable_material_event(record):
                continue
            event_id = material_event_identity(record)
            payload = record.model_copy(update={"event_id": event_id, "retrieved_at": record.retrieved_at or refreshed_at})
            batch.set(
                self.client.collection("official_events").document(f"material_event:{event_id}"),
                {
                    "event_type": "material_event",
                    "event_id": event_id,
                    "ticker": ticker,
                    "company_name": payload.company_name,
                    "event_date": payload.event_date,
                    "event_time": payload.event_time,
                    "title": payload.title,
                    "source_url": payload.source_url,
                    "detail_url": payload.detail_url,
                    "status": payload.status,
                    "payload": payload.model_dump(mode="python"),
                    "retrieved_at": refreshed_at,
                },
                merge=True,
            )
            material_count += 1
        if conference_count or material_count:
            batch.commit()
        return {"investor_conferences": conference_count, "material_events": material_count}

    def list_investor_conferences(self, ticker: str, limit: int = 20) -> list[InvestorConferenceRecord]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        documents = (
            self.client.collection("official_events")
            .where(filter=FieldFilter("ticker", "==", ticker))
            .where(filter=FieldFilter("event_type", "==", "investor_conference"))
            .stream()
        )
        rows = [document.to_dict() or {} for document in documents]
        rows.sort(key=lambda row: (str(row.get("event_date") or ""), str(row.get("retrieved_at") or "")), reverse=True)
        records = [InvestorConferenceRecord.model_validate(row.get("payload") or {}) for row in rows]
        return [record for record in records if is_persistable_investor_conference(record)][:limit]

    def list_material_events(self, ticker: str, limit: int = 50) -> list[MaterialEventRecord]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        documents = (
            self.client.collection("official_events")
            .where(filter=FieldFilter("ticker", "==", ticker))
            .where(filter=FieldFilter("event_type", "==", "material_event"))
            .stream()
        )
        rows = [document.to_dict() or {} for document in documents]
        rows.sort(
            key=lambda row: (
                str(row.get("event_date") or ""),
                str(row.get("event_time") or ""),
                str(row.get("retrieved_at") or ""),
            ),
            reverse=True,
        )
        records = [MaterialEventRecord.model_validate(row.get("payload") or {}) for row in rows]
        return [record for record in records if is_persistable_material_event(record)][:limit]

    def list_metrics(
        self,
        ticker: str,
        limit: int = 200,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection("calculated_metrics").where(
            filter=FieldFilter("ticker", "==", ticker)
        )
        if run_id:
            query = query.where(filter=FieldFilter("run_id", "==", run_id))
        documents = query.stream()
        rows = [document.to_dict() or {} for document in documents]
        rows.sort(
            key=lambda row: (
                str(row.get("created_at") or ""),
                str(row.get("analysis_type") or ""),
                str(row.get("period") or ""),
                str(row.get("metric_code") or ""),
            ),
            reverse=not bool(run_id),
        )
        return rows[:limit]

    def list_facts(
        self,
        ticker: str,
        limit: int = 500,
        run_id: str | None = None,
        period: str | None = None,
        statement_type: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection("normalized_financial_facts").where(
            filter=FieldFilter("ticker", "==", ticker)
        )
        if period:
            query = query.where(filter=FieldFilter("period", "==", period))
        source_rows = []
        for document in query.stream():
            row = document.to_dict() or {}
            row["_document_id"] = document.id
            source_rows.append(row)
        rows = deduplicate_financial_fact_rows(source_rows)
        for row in rows:
            row.pop("_document_id", None)
        for row in rows:
            row["statement_type"] = statement_type_for_metric(str(row.get("metric_code") or ""))
            row["label"] = row.get("metric_code")
            row["run_id"] = run_id
        if statement_type:
            rows = [row for row in rows if row.get("statement_type") == statement_type]
        if search:
            needle = search.casefold()
            rows = [
                row for row in rows
                if needle in str(row.get("metric_code") or "").casefold()
                or needle in str(row.get("taxonomy_concept") or "").casefold()
            ]
        rows.sort(key=lambda row: (str(row.get("retrieved_at") or ""), str(row.get("period") or ""), str(row.get("metric_code") or "")), reverse=True)
        return rows[:limit]

    def list_rule_results(
        self,
        ticker: str,
        limit: int = 500,
        run_id: str | None = None,
        triggered: bool | None = None,
    ) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection("rule_results").where(filter=FieldFilter("ticker", "==", ticker))
        if run_id:
            query = query.where(filter=FieldFilter("run_id", "==", run_id))
        rows = [document.to_dict() or {} for document in query.stream()]
        if triggered is not None:
            rows = [row for row in rows if bool(row.get("triggered")) is triggered]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows[:limit]

    def list_runs(self, ticker: str, limit: int = 20) -> list[AnalysisRunSummary]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        documents = self.client.collection("analysis_runs").where(
            filter=FieldFilter("ticker", "==", ticker)
        ).stream()
        rows = [document.to_dict() or {} for document in documents]
        rows.sort(key=lambda row: str(row.get("started_at") or ""), reverse=True)
        return [AnalysisRunSummary.model_validate(row) for row in rows[:limit]]

    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        from google.cloud.firestore_v1.base_query import FieldFilter

        documents = (
            self.client.collection("normalized_financial_facts")
            .where(filter=FieldFilter("ticker", "==", ticker))
            .where(filter=FieldFilter("metric_code", "==", metric))
            .where(filter=FieldFilter("period", "==", period))
            .stream()
        )
        source_rows = []
        for document in documents:
            item = document.to_dict() or {}
            item["_document_id"] = document.id
            source_rows.append(item)
        row = preferred_financial_fact_row(source_rows)
        if row is None:
            return None
        row.pop("_document_id", None)
        return financial_fact_from_row(row)

    def save_text_intelligence_result(
        self,
        *,
        ticker: str,
        run_id: str,
        analysis: TextMiningAnalysisResponse,
        narrative_shift: NarrativeShiftResponse | None = None,
    ) -> dict[str, int]:
        batch = self.client.batch()
        created_at = analysis.generated_at
        batch.set(
            self.client.collection("text_model_runs").document(run_id),
            {
                "run_id": run_id,
                "ticker": ticker,
                "model_summary": analysis.model_summary,
                "semantic_analysis": analysis.semantic_analysis,
                "narrative_shift": narrative_shift.model_dump(mode="python") if narrative_shift else None,
                "created_at": created_at,
            },
            merge=True,
        )
        sentences = [sentence for document in analysis.documents for sentence in document.sentences]
        for sentence in sentences:
            batch.set(
                self.client.collection("text_evidence").document(sentence.evidence_id),
                {
                    "run_id": run_id,
                    "ticker": ticker,
                    "document_id": sentence.document_id,
                    "sentence_id": sentence.sentence_id,
                    "source_type": sentence.source_type,
                    "source_url": sentence.source_url,
                    "payload": sentence.model_dump(mode="python"),
                    "created_at": created_at,
                },
                merge=True,
            )
        batch.commit()
        return {"text_model_runs": 1, "text_evidence": len(sentences), "narrative_shift_results": 1 if narrative_shift else 0}

    def get_latest_text_intelligence_result(self, ticker: str) -> dict[str, Any] | None:
        from google.cloud.firestore_v1.base_query import FieldFilter

        runs = [
            document.to_dict() or {}
            for document in self.client.collection("text_model_runs")
            .where(filter=FieldFilter("ticker", "==", ticker))
            .stream()
        ]
        if not runs:
            return None
        runs.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        run = runs[0]
        run_id = str(run.get("run_id") or "")
        documents = (
            self.client.collection("text_evidence")
            .where(filter=FieldFilter("ticker", "==", ticker))
            .where(filter=FieldFilter("run_id", "==", run_id))
            .stream()
        )
        evidence = [document.to_dict() or {} for document in documents]
        evidence.sort(key=lambda row: str(row.get("sentence_id") or ""))
        return {
            "run_id": run_id,
            "ticker": ticker,
            "model_summary": run.get("model_summary") or {},
            "semantic_analysis": run.get("semantic_analysis") or {},
            "narrative_shift": run.get("narrative_shift"),
            "text_evidence": [row.get("payload") or {} for row in evidence],
            "created_at": run.get("created_at"),
        }
