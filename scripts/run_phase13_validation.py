from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask_data_repository import SqliteFlaskDataRepository
from member_services import MemberAuthService, NotificationService
FINANCIAL_DB = ROOT / "fintrust_backend" / "data" / "phase13-validation.sqlite3"
MEMBER_DB = ROOT / "fintrust_backend" / "data" / "phase13-member.sqlite3"
REPORT_PATH = ROOT / "reports" / "phase13-validation-report.json"


def init_financial_schema() -> None:
    from sys import path

    backend_root = ROOT / "fintrust_backend"
    if str(backend_root) not in path:
        path.insert(0, str(backend_root))
    from app.services.analysis_repository import SqliteAnalysisRepository

    SqliteAnalysisRepository(str(FINANCIAL_DB))


def seed_financial_run_history() -> list[dict[str, str]]:
    init_financial_schema()
    runs = [
        ("phase13-2454-001", "2454", "聯發科", "high", "2026-09-14T01:00:00Z"),
        ("phase13-2454-002", "2454", "聯發科", "attention", "2026-09-14T01:05:00Z"),
        ("phase13-2330-001", "2330", "台積電", "normal", "2026-09-14T01:10:00Z"),
        ("phase13-2303-001", "2303", "聯電", "attention", "2026-09-14T01:15:00Z"),
        ("phase13-3711-001", "3711", "日月光投控", "normal", "2026-09-14T01:20:00Z"),
    ]
    with sqlite3.connect(FINANCIAL_DB) as connection:
        for index, (run_id, ticker, company, severity, started_at) in enumerate(runs, start=1):
            completed_at = started_at.replace(":00Z", ":30Z")
            connection.execute(
                """INSERT OR REPLACE INTO analysis_runs
                (run_id,ticker,company_name,subindustry,analysis_type,trigger,status,started_at,completed_at,rule_version,overall_severity,summary,error_message)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, ticker, company, "IC 設計", "combined", "phase13_validation", "completed", started_at, completed_at, "phase13-local", severity, f"{company} controlled validation run {index}", None),
            )
            connection.execute(
                """INSERT OR REPLACE INTO normalized_financial_facts
                (fact_id,ticker,company_name,subindustry,analysis_type,period,metric_code,value,unit,source_kind,source_url,taxonomy_concept,retrieved_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"phase13:{run_id}:revenue", ticker, company, "IC 設計", "historical", "2026Q2", "revenue", 1000 + index, "百萬元", "phase13_local_fixture", "https://example.test/official", "Revenue", completed_at),
            )
            connection.execute(
                """INSERT OR REPLACE INTO calculated_metrics
                (run_id,ticker,analysis_type,period,metric_code,label,category,value,unit,formula,source_fields_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, ticker, "historical", "2026Q2", "revenue_growth_yoy", "營收年增率", "growth", 5 + index, "%", "fixture", "[\"revenue\"]"),
            )
            connection.execute(
                """INSERT OR REPLACE INTO rule_results
                (run_id,ticker,analysis_type,rule_id,name,category,severity,triggered,threshold_description,explanation,evidence_periods_json,evidence_metrics_json,rule_scope,logic_expression,actual_values_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, ticker, "historical", f"phase13-rule-{index}", "Controlled validation rule", "validation", severity, 1 if severity in {"high", "attention"} else 0, "local validation threshold", "Phase 13 local validation rule result.", "[\"2026Q2\"]", "[\"revenue_growth_yoy\"]", "phase13_validation", None, "{\"revenue_growth_yoy\":5}"),
            )
    return [{"run_id": run_id, "ticker": ticker, "status": "completed", "severity": severity} for run_id, ticker, _company, severity, _started_at in runs]


def validate_member_notifications() -> dict[str, object]:
    repo = SqliteFlaskDataRepository(MEMBER_DB)
    repo.initialize()
    auth = MemberAuthService(repo, app_env="development")
    existing = repo.get_member_by_email("phase13-member@example.com")
    member = existing or auth.register_local(
        email="phase13-member@example.com",
        password="phase13pass",
        display_name="Phase 13 Member",
    )
    repo.upsert_watchlist_item(member["uid"], {
        "ticker": "2454",
        "company_name": "聯發科",
        "alert_enabled": 1,
        "created_at": "2026-09-14T01:00:00Z",
        "updated_at": "2026-09-14T01:00:00Z",
    })
    evidence = {"run_id": "phase13-2454-001"}
    service = NotificationService(
        repo,
        evidence_provider=lambda ticker: {"ticker": ticker, "company_name": "聯發科", "overall_severity": "high", "run_id": evidence["run_id"]},
    )
    first = service.process_member(member["uid"])
    second = service.process_member(member["uid"])
    evidence["run_id"] = "phase13-2454-002"
    third = service.process_member(member["uid"])
    return {
        "member_uid": member["uid"],
        "watchlist": repo.list_watchlist(member["uid"]),
        "first_status": first[0]["status"] if first else "none",
        "second_status": second[0]["status"] if second else "none",
        "third_status": third[0]["status"] if third else "none",
        "history_count": len(repo.list_notification_history(member["uid"])),
    }


def main() -> None:
    FINANCIAL_DB.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    for path in (FINANCIAL_DB, MEMBER_DB):
        if path.exists():
            path.unlink()
    runs = seed_financial_run_history()
    notification = validate_member_notifications()
    report = {
        "mode": "local_test_only",
        "production_firestore_mutated": False,
        "financial_database": str(FINANCIAL_DB),
        "member_database": str(MEMBER_DB),
        "run_history": runs,
        "notification_validation": notification,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
