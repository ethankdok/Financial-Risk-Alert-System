"""Read-only staging preflight for the historical research layer (Phase 5). Never writes to any cloud resource.

    python -m scripts.research_cloud_preflight [--out report.json]

Checks (all local, no credentials used, secret values never printed):
1. cloud sync is disabled by default and the production target is refused without separate approval;
2. which configuration variables are set (names and set/unset only; secret values are never read into output);
3. approved research dataset presence and read-only access (DB digest unchanged across the preflight);
4. container recipes ship the research code and the Flask proxy, and do not bake research data or secrets;
5. a dry-run plan of exporting persisted research runs to an in-memory MOCK Firestore (counts, collisions, batches);
6. research API readiness probe and auth posture (persist requires the ingestion token in production).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from app.services.financial_research.result_store import FirestoreResearchResultStore, SqliteResearchResultStore
from app.services.financial_research.result_sync import ResearchResultSync
from app.services.financial_research.service import ResearchConfig, ResearchService
from app.services.historical_audit.cloud_config import CloudSafetyError, CloudSyncDisabledError, HistoricalCloudConfig
from scripts.research_baseline import database_digest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SECRET_NAMES = ("SECRET_KEY", "INGESTION_API_TOKEN", "FINTRUST_INGESTION_TOKEN", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                "HISTORICAL_CLOUD_PRODUCTION_APPROVAL")
CONFIG_NAMES = ("APP_ENV", "DATASTORE_BACKEND", "GOOGLE_CLOUD_PROJECT", "CORS_ALLOW_ORIGINS", "HISTORICAL_CLOUD_SYNC_ENABLED",
                "HISTORICAL_CLOUD_ENVIRONMENT", "HISTORICAL_CLOUD_PROJECT", "HISTORICAL_CLOUD_BUCKET",
                "HISTORICAL_RESEARCH_DATABASE_PATH", "RESEARCH_RESULTS_DATABASE_PATH", "FIRESTORE_EMULATOR_HOST",
                "FINTRUST_API_BASE_URL")


class _InMemoryFirestore:  # minimal create-only MOCK used for the dry-run plan only
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict]] = {}

    def collection(self, name):
        store = self

        class Document:
            def __init__(self, document_id):
                self.id = document_id

            def get(self):
                data = store.data.get(name, {}).get(self.id)
                return type("Snapshot", (), {"exists": data is not None, "to_dict": lambda _self: data})()

        return type("Collection", (), {"document": lambda _self, document_id: Document(document_id)})()


def check(results: list, name: str, ok: bool, detail: object) -> None:
    results.append({"check": name, "ok": bool(ok), "detail": detail})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    results: list[dict] = []

    try:
        HistoricalCloudConfig.from_env({})
        check(results, "cloud_sync_disabled_by_default", False, "configuration accepted without opt-in")
    except CloudSyncDisabledError as exc:
        check(results, "cloud_sync_disabled_by_default", True, str(exc))
    try:
        HistoricalCloudConfig.from_env({"HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "production",
                                        "HISTORICAL_CLOUD_PROJECT": "fintrust-alert-ccu", "HISTORICAL_CLOUD_BUCKET": "any-bucket"})
        check(results, "production_target_refused", False, "production accepted")
    except CloudSafetyError as exc:
        check(results, "production_target_refused", True, str(exc))
    check(results, "environment_variables", True, {
        "config": {name: ("set" if os.getenv(name) else "unset") for name in CONFIG_NAMES},
        "secrets": {name: ("set" if os.getenv(name) else "unset") for name in SECRET_NAMES},
        "note": "values are never printed"})
    check(results, "current_process_not_targeting_cloud",
          os.getenv("HISTORICAL_CLOUD_SYNC_ENABLED", "").lower() not in {"1", "true", "yes", "on"}
          and os.getenv("DATASTORE_BACKEND", "sqlite") == "sqlite",
          "local sqlite backends; historical cloud sync off")

    config = ResearchConfig.from_env()
    database = Path(config.database)
    if database.is_file():
        before = database_digest(database)
        service = ResearchService(config)
        health = service.health()
        overview = service.case_overview("1785")["coverage"]
        check(results, "research_dataset_read_only", database_digest(database) == before,
              {"health": health, "coverage": overview})
    else:
        check(results, "research_dataset_read_only", True, "dataset absent here: research API answers 503 (expected in images)")

    fastapi_docker = (REPO / "Dockerfile.fastapi").read_text(encoding="utf-8")
    flask_docker = (REPO / "Dockerfile.flask").read_text(encoding="utf-8")
    check(results, "fastapi_image_ships_research_code", "COPY fintrust_backend/app ./app" in fastapi_docker,
          "app/ (includes financial_research and the research router)")
    check(results, "images_do_not_bake_research_data_or_secrets",
          not any(token in fastapi_docker + flask_docker for token in ("data/historical_audit", ".sqlite3", "ENV SECRET",
                                                                      "GEMINI_API_KEY=", "INGESTION_API_TOKEN=")),
          "research data must be mounted/provisioned separately; secrets come from Secret Manager")
    check(results, "flask_image_ships_research_proxy_and_page",
          "research_routes.py" in flask_docker and "COPY *.html *.js *.css ./" in flask_docker, "research_routes.py + page assets")

    results_db = Path(os.getenv("RESEARCH_RESULTS_DATABASE_PATH", BACKEND / "data/historical_audit/research_results.sqlite3"))
    if results_db.is_file():
        with tempfile.TemporaryDirectory() as directory:
            sync = ResearchResultSync(SqliteResearchResultStore(results_db),
                                      FirestoreResearchResultStore(_InMemoryFirestore()),
                                      journal=Path(directory) / "journal.jsonl", lock=Path(directory) / "lock")
            plan = sync.plan("1785").as_dict()
        check(results, "result_export_dry_run_plan_mock", not plan["planned"]["collision"],
              {"counts": plan["counts"], "batch_limit": sync.batch_limit, "target": "in-memory MOCK (no cloud)"})
    else:
        check(results, "result_export_dry_run_plan_mock", True, "no persisted runs yet")

    from app.routers import historical_research
    check(results, "persist_requires_ingestion_token_in_production",
          "require_ingestion_token(x_ingestion_token)" in Path(historical_research.__file__).read_text(encoding="utf-8"),
          "POST compute persist=true → require_ingestion_token (503 in production without INGESTION_API_TOKEN)")

    report = {"preflight": "historical_research_phase5", "writes_performed": "none", "ok": all(r["ok"] for r in results),
              "checks": results}
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
