from __future__ import annotations

from datetime import datetime
from typing import Any

from app.financial_analysis_models import FinancialStatementAnalysisReport
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import FinancialFact
from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.pipeline_models import AnalysisRunSummary, FrontendAnalysisSnapshot, PersistenceCounts
from app.services.analysis_repository import (
    document_id,
    financial_fact_from_row,
    historical_fact_rows,
    latest_fact_rows,
    metric_rows,
    rule_rows,
)
from app.services.official_event_sources import investor_conference_identity, material_event_identity


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
                    document_id(
                        fact["ticker"],
                        fact["analysis_type"],
                        fact["period"],
                        fact["metric_code"],
                    )
                ),
                {**fact, "retrieved_at": completed_at},
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

    def save_official_events(
        self,
        *,
        ticker: str,
        investor_conferences: list[InvestorConferenceRecord],
        material_events: list[MaterialEventRecord],
        refreshed_at: datetime,
    ) -> dict[str, int]:
        batch = self.client.batch()
        for record in investor_conferences:
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
        for record in material_events:
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
        batch.commit()
        return {"investor_conferences": len(investor_conferences), "material_events": len(material_events)}

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
        return [InvestorConferenceRecord.model_validate(row.get("payload") or {}) for row in rows[:limit]]

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
        return [MaterialEventRecord.model_validate(row.get("payload") or {}) for row in rows[:limit]]

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
        rows = [document.to_dict() or {} for document in documents]
        if not rows:
            return None
        rows.sort(
            key=lambda row: (
                0 if row.get("analysis_type") == "historical" else 1,
                str(row.get("retrieved_at") or ""),
            )
        )
        return financial_fact_from_row(rows[0])
