"""Fail-closed configuration for the optional historical-research cloud backend.

Cloud synchronization is **disabled by default**. It is enabled only when
``HISTORICAL_CLOUD_SYNC_ENABLED=true`` and an explicit environment is named:

- ``emulator``: Firestore emulator (``FIRESTORE_EMULATOR_HOST`` must be set) and a
  test bucket;
- ``isolated-test``: a non-production project/bucket that must differ from the
  production ``GOOGLE_CLOUD_PROJECT`` / conference archive bucket;
- ``production``: refused unless ``HISTORICAL_CLOUD_PRODUCTION_APPROVAL`` carries
  a change reference *and* ``--allow-production`` is passed. Phase 1C never
  sets either.

Credentials come only from Application Default Credentials; no key file or
key material is read from the repository or the environment by this module.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping


ENVIRONMENTS = ("emulator", "isolated-test", "production")
DEFAULT_COLLECTION_PREFIX = "historical_research"
NAMESPACES = {
    "financial_filings": "historical-financial-filings",
    "regulatory_disclosures": "historical-regulatory-disclosures",
    "official_summaries": "historical-official-summaries",
    "conference_pdfs": "conference-pdf-archive",  # existing conference archive prefix; referenced, not re-uploaded
    "research_packages": "historical-research-packages",
}
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")


class CloudSyncDisabledError(RuntimeError):
    pass


class CloudSafetyError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HistoricalCloudConfig:
    environment: str
    project: str
    bucket: str
    collection_prefix: str = DEFAULT_COLLECTION_PREFIX
    object_prefix: str = ""
    emulator_host: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, *, allow_production: bool = False) -> "HistoricalCloudConfig":
        env = os.environ if environ is None else environ
        if not _truthy(env.get("HISTORICAL_CLOUD_SYNC_ENABLED")):
            raise CloudSyncDisabledError("Historical cloud sync is disabled (set HISTORICAL_CLOUD_SYNC_ENABLED=true).")
        environment = str(env.get("HISTORICAL_CLOUD_ENVIRONMENT", "")).strip()
        if environment not in ENVIRONMENTS:
            raise CloudSafetyError(f"HISTORICAL_CLOUD_ENVIRONMENT must be one of {ENVIRONMENTS}.")
        project = str(env.get("HISTORICAL_CLOUD_PROJECT", "")).strip()
        bucket = str(env.get("HISTORICAL_CLOUD_BUCKET", "")).strip()
        prefix = str(env.get("HISTORICAL_CLOUD_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX)).strip()
        if not project or not bucket:
            raise CloudSafetyError("HISTORICAL_CLOUD_PROJECT and HISTORICAL_CLOUD_BUCKET are required.")
        if not _SAFE_NAME.fullmatch(bucket) or not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", prefix):
            raise CloudSafetyError("Unsafe bucket name or collection prefix.")
        if not prefix.startswith("historical_research"):
            raise CloudSafetyError("Collection prefix must start with 'historical_research' (no production collections).")
        production_project = str(env.get("GOOGLE_CLOUD_PROJECT", "")).strip()
        production_buckets = {str(env.get(name, "")).strip() for name in (
            "CONFERENCE_PDF_ARCHIVE_GCS_BUCKET", "OFFICIAL_IR_PDF_GCS_BUCKET")} - {""}
        emulator_host = str(env.get("FIRESTORE_EMULATOR_HOST", "")).strip() or None
        if environment == "emulator":
            if not emulator_host:
                raise CloudSafetyError("emulator environment requires FIRESTORE_EMULATOR_HOST.")
        elif environment == "isolated-test":
            if project == production_project or bucket in production_buckets:
                raise CloudSafetyError("isolated-test must not use the production project or production buckets.")
            marker = re.compile(r"(test|dev|sandbox|staging)")
            if not (marker.search(project) and marker.search(bucket)):
                raise CloudSafetyError("isolated-test project and bucket names must each identify a non-production environment.")
        else:  # production
            approval = str(env.get("HISTORICAL_CLOUD_PRODUCTION_APPROVAL", "")).strip()
            if not (allow_production and approval):
                raise CloudSafetyError("Production historical cloud writes are blocked (separate authorization required).")
        return cls(environment=environment, project=project, bucket=bucket, collection_prefix=prefix,
                   object_prefix=str(env.get("HISTORICAL_CLOUD_OBJECT_PREFIX", "")).strip().strip("/"),
                   emulator_host=emulator_host)


def build_clients(config: HistoricalCloudConfig):
    """GCS and Firestore clients via Application Default Credentials (or the emulator)."""
    try:
        from google.auth.exceptions import DefaultCredentialsError
        from google.cloud import firestore, storage
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise CloudSafetyError("google-cloud-storage / google-cloud-firestore are not installed.") from exc
    try:
        storage_client = storage.Client(project=config.project)
        firestore_client = firestore.Client(project=config.project)
    except DefaultCredentialsError as exc:
        raise CloudSafetyError("No Application Default Credentials available for the historical cloud backend.") from exc
    return storage_client, firestore_client
